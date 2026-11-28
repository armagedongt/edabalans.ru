"""Day discussions with separate read state and a shared account profile."""
from __future__ import annotations

from datetime import UTC
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import subprocess
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from pydantic import BaseModel, Field
from sqlalchemy import case, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL, ACCOUNT_VIEW_HEADER, native_session_actor, primary_email
from app.config import get_settings
from app.course_material_routes import component_asset
from app.course_structure_service import active_course_version
from app.database import get_db
from app.masterclass_discussion_push import PUSH_TITLES, endpoint_hash, enqueue_post, enqueue_test, permitted_endpoint, public_key, valid_keys
from app.models import MasterclassDiscussionPost as Post
from app.models import MasterclassDiscussionProfile as Profile
from app.models import MasterclassDiscussionRead as Read
from app.models import MasterclassDiscussionSubscription as Subscription
from app.models import AccountCredential, AccountSession, MessengerAccount, User, UserEmail

router = APIRouter(prefix="/api/masterclass/discussion", tags=["masterclass-discussion"])
PAGE_SIZE = 30
PHOTO_LIMIT = 8_000_000
VOICE_LIMIT = 16_000_000
VOICE_SECONDS = 900
VOICE_BITRATE = 128_000
# Lower-rate AAC encoders can pad the last frame by a fraction of a second.
VOICE_PADDING_BYTES = VOICE_BITRATE // 8 // 3
NOTICE = "Обсуждения пока доступны только автору курса. Дождитесь уведомления об открытии."
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow"}


def owner(request: Request, db: Session) -> User | None:
    if not get_settings().masterclass_discussion_pilot or request.headers.get(ACCOUNT_VIEW_HEADER):
        return None
    actor = native_session_actor(request, db)
    if actor is not None and primary_email(db, actor.id) == ACCOUNT_MANAGER_EMAIL:
        return actor
    return None


def require_owner(request: Request, db: Session) -> User:
    actor = owner(request, db)
    if actor is None:
        raise HTTPException(403, NOTICE)
    if request.method != "GET" and request.headers.get("origin") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Откройте обсуждение в кабинете.")
    return actor


def lock_owner(db: Session, user_id: UUID) -> None:
    db.execute(select(User.id).where(User.id == user_id).with_for_update()).one()


def root() -> Path:
    return Path(get_settings().masterclass_discussion_media_dir)


def day_path(day_number: int) -> str:
    return f"{router.prefix}/day-{day_number:02d}"


def require_day(db: Session, day_number: int) -> None:
    if not any(int(day["number"]) == day_number for day in active_course_version(db).payload["days"]):
        raise HTTPException(404, "День курса недоступен.")


def discussion_author(db: Session) -> UUID | None:
    user_id = db.scalar(select(UserEmail.user_id).where(UserEmail.email_normalized == ACCOUNT_MANAGER_EMAIL))
    return user_id if user_id is not None and primary_email(db, user_id) == ACCOUNT_MANAGER_EMAIL else None


def populate_registered_profiles(db: Session) -> int:
    author_id = discussion_author(db)
    is_author = User.id == author_id if author_id else literal(False)
    registered = or_(
        exists(select(AccountCredential.user_id).where(AccountCredential.user_id == User.id)),
        exists(select(AccountSession.user_id).where(AccountSession.user_id == User.id)),
        is_author,
    )
    defaults = select(
        User.id, case((is_author, "Сергей Воронцов"), else_=""), literal(""), is_author,
    ).where(User.status == "active", User.merged_into_user_id.is_(None), registered)
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(Profile).from_select(
        ["user_id", "display_name", "about", "visible"], defaults, include_defaults=False,
    ).on_conflict_do_nothing(index_elements=[Profile.user_id])
    return len(db.scalars(statement.returning(Profile.user_id)).all())


def select_day(day_number: int):
    return select(Post).where(Post.day_number == day_number)


def unread_query(user_id: UUID, day_number: int):
    read = exists(select(Read.post_id).where(Read.user_id == user_id, Read.post_id == Post.id))
    return select(Post.id).where(Post.day_number == day_number, or_(Post.author_id.is_(None), Post.author_id != user_id), ~read)


def count_unread(db: Session, user_id: UUID, day_number: int) -> int:
    return db.scalar(select(func.count()).select_from(unread_query(user_id, day_number).subquery())) or 0


def total_posts(db: Session, day_number: int) -> int:
    return db.scalar(select(func.count()).select_from(Post).where(Post.day_number == day_number)) or 0


def profile_avatar(profile: Profile | None, day_number: int) -> str | None:
    return f"{day_path(day_number)}/profile/photo/{profile.photo_key}" if profile and profile.photo_key else None


def discussion_alias(user_id: UUID) -> str:
    adjectives = (
        "Бодрый", "Весёлый", "Добрый", "Зоркий", "Ловкий", "Любопытный", "Мечтательный",
        "Отважный", "Проворный", "Пушистый", "Радостный", "Смелый", "Солнечный",
        "Спокойный", "Тёплый", "Улыбчивый", "Шустрый", "Яркий", "Дружелюбный", "Находчивый",
    )
    animals = (
        "барсук", "бобр", "волк", "енот", "заяц", "ирбис", "кот", "крот", "лев", "леопард",
        "лемур", "лисёнок", "лось", "манул", "медведь", "окапи", "пёс", "суслик", "тигр",
        "тушканчик", "хомяк", "шакал", "ящер", "сурикат",
    )
    first, second = sha256(user_id.bytes).digest()[:2]
    return f"{adjectives[first % len(adjectives)]} {animals[second % len(animals)]}"


def public_profile(profile: Profile | None, user_id: UUID, day_number: int) -> dict | None:
    if not profile or not profile.visible:
        return None
    return {
        "name": profile.display_name or discussion_alias(user_id),
        "about": profile.about,
        "avatar": profile_avatar(profile, day_number),
    }


def own_profile(profile: Profile | None, user_id: UUID, day_number: int, is_author: bool) -> dict:
    return {
        "name": profile.display_name if profile else "",
        "defaultName": "Сергей Воронцов" if is_author else discussion_alias(user_id),
        "about": profile.about if profile else "",
        "avatar": profile_avatar(profile, day_number),
    }


def participant_identities(db: Session, user_ids: set[UUID]) -> dict[UUID, dict]:
    if not user_ids:
        return {}
    email = (
        select(UserEmail.email_original)
        .where(UserEmail.user_id == User.id)
        .order_by(UserEmail.is_primary.desc(), UserEmail.created_at, UserEmail.id)
        .limit(1).correlate(User).scalar_subquery()
    )
    telegram = (
        select(MessengerAccount.id)
        .where(
            MessengerAccount.user_id == User.id,
            MessengerAccount.platform == "telegram",
            MessengerAccount.linked_at.is_not(None),
            MessengerAccount.is_deliverable.is_(True),
        )
        .order_by(MessengerAccount.is_preferred.desc(), MessengerAccount.linked_at.desc(), MessengerAccount.id.desc())
        .limit(1).correlate(User).scalar_subquery()
    )
    rows = db.execute(
        select(User.id, User.display_name, email, MessengerAccount.id, MessengerAccount.username)
        .outerjoin(MessengerAccount, MessengerAccount.id == telegram)
        .where(User.id.in_(user_ids))
    )
    return {
        user_id: {"name": name, "email": address, "telegram": username, "telegramLinked": linked_id is not None}
        for user_id, name, address, linked_id, username in rows
    }


def serialize(post: Post, user_id: UUID, author_id: UUID | None, profile: Profile | None,
              identity: dict | None) -> dict:
    is_author = post.author_id is not None and post.author_id == author_id
    card = public_profile(profile, post.author_id, post.day_number) if post.author_id else None
    if is_author:
        name = "Сергей Воронцов"
    elif post.author_id:
        name = card["name"] if card else discussion_alias(post.author_id)
    else:
        name = post.source_label or "Участник"
    base = day_path(post.day_number)
    message = {
        "id": post.id,
        "name": name,
        "isAuthor": is_author,
        "isOwn": post.author_id == user_id,
        "profile": card,
        "text": post.body,
        "archived": post.archived,
        "at": post.created_at.astimezone(UTC).isoformat() if not post.archived else None,
        "photo": f"{base}/posts/{post.id}/photo" if post.photo else None,
        "voice": f"{base}/posts/{post.id}/voice" if post.voice else None,
        "replyTo": post.reply_to_id,
        "marked": post.featured,
    }
    if identity is not None:
        message["ownerIdentity"] = identity
    return message


def payload(db: Session, request: Request, day_number: int, posts: list[Post], user_id: UUID, has_more: bool) -> dict:
    known = {post.id for post in posts}
    parent_ids = {post.reply_to_id for post in posts if post.reply_to_id and post.reply_to_id not in known}
    related = list(db.scalars(
        select_day(day_number).where(or_(Post.id.in_(parent_ids), Post.featured.is_(True) & Post.reply_to_id.in_(known)))
    ))
    authors = {post.author_id for post in [*posts, *related] if post.author_id}
    profiles = {profile.user_id: profile for profile in db.scalars(select(Profile).where(Profile.user_id.in_(authors)))}
    author_id = discussion_author(db)
    identities = (
        participant_identities(db, authors - {user_id})
        if user_id == author_id and not request.headers.get(ACCOUNT_VIEW_HEADER) else {}
    )

    def serialize_message(post: Post) -> dict:
        return serialize(post, user_id, author_id, profiles.get(post.author_id), identities.get(post.author_id))

    answers = {post.reply_to_id: post.id for post in sorted([*posts, *related], key=lambda row: row.id) if post.featured}
    first_unread = db.scalar(unread_query(user_id, day_number).order_by(Post.id).limit(1))
    return {
        "posts": [serialize_message(post) for post in posts],
        "related": [serialize_message(post) for post in related if post.id not in known],
        "answers": answers,
        "more": has_more,
        "unread": count_unread(db, user_id, day_number),
        "total": total_posts(db, day_number),
        "firstUnread": first_unread,
        "canAuthor": user_id == author_id,
    }


def read_image(raw: bytes) -> bytes:
    if not raw or len(raw) > PHOTO_LIMIT:
        raise HTTPException(413, "Фото должно быть до 8 МБ.")
    register_heif_opener()
    try:
        with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "WEBP", "HEIF"]) as source:
            if source.width * source.height > 25_000_000:
                raise HTTPException(413, "Фото слишком большое. Уменьшите его и повторите.")
            source.thumbnail((1600, 1600))
            image = ImageOps.exif_transpose(source).convert("RGB")
            result = BytesIO()
            image.save(result, format="WEBP", quality=84)
            return result.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(415, "Выберите фото JPEG, PNG, WebP или HEIC.") from None


def read_voice(raw: bytes) -> bytes:
    if not raw or len(raw) > VOICE_LIMIT:
        raise HTTPException(413, "Голосовое должно быть до 16 МБ.")
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "pipe",
             "-i", "pipe:0", "-vn", "-ac", "1", "-ar", "48000", "-b:a", str(VOICE_BITRATE),
             "-t", str(VOICE_SECONDS + 1), "-f", "mp3", "pipe:1"],
            input=raw, capture_output=True, timeout=20, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(422, "Не удалось подготовить аудио. Попробуйте записать его снова.") from None
    if not result.stdout:
        raise HTTPException(422, "В записи нет звука или она пуста.")
    if len(result.stdout) > VOICE_SECONDS * VOICE_BITRATE // 8 + VOICE_PADDING_BYTES:
        raise HTTPException(413, "Голосовое должно быть короче 15 минут.")
    return result.stdout


def limited_upload(file: UploadFile | None, limit: int) -> bytes | None:
    return file.file.read(limit + 1) if file is not None else None


@lru_cache(maxsize=1)
def voice_template() -> str:
    template = component_asset("article-audio", "player.html")
    home = Path(__file__).parent / "static" / "homepage-preview" / "release-candidate.html"
    html = home.read_text(encoding="utf-8")
    styles = html[html.index("    .voice-widget{"):html.index("    .homepage-program{")]
    start = template.index("    .voice-widget{")
    end = template.index("*{box-sizing:border-box}", start)
    template = template[:start] + styles + template[end:]
    return template.replace("<style>", '<link rel="stylesheet" href="/assets/site-typography.css"><style>', 1)


@router.get("/day-{day_number}/status")
def status(day_number: int, request: Request, db: Session = Depends(get_db)) -> dict:
    if not get_settings().masterclass_discussion_pilot:
        return {"mode": "off"}
    actor = owner(request, db)
    if actor is None:
        return {"mode": "locked", "notice": NOTICE}
    require_day(db, day_number)
    return {"mode": "owner", "unread": count_unread(db, actor.id, day_number), "total": total_posts(db, day_number)}


@router.get("/day-{day_number}/thread")
def thread(day_number: int, request: Request, response: Response, db: Session = Depends(get_db), after: int = Query(default=0, ge=0),
           around: int | None = Query(default=None, ge=1)) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    if around is not None:
        if db.scalar(select_day(day_number).where(Post.id == around)) is None:
            raise HTTPException(404, "Сообщение недоступно.")
        rows = list(db.scalars(select_day(day_number).where(Post.id < around).order_by(Post.id.desc()).limit(PAGE_SIZE // 2)))
        rows.reverse()
        rows.extend(db.scalars(select_day(day_number).where(Post.id >= around).order_by(Post.id).limit(PAGE_SIZE + 1 - len(rows))))
    else:
        rows = list(db.scalars(select_day(day_number).where(Post.id > after).order_by(Post.id).limit(PAGE_SIZE + 1)))
    response.headers.update(PRIVATE_HEADERS)
    result = payload(db, request, day_number, rows[:PAGE_SIZE], actor.id, len(rows) > PAGE_SIZE)
    if not after and around is None:
        profile = db.get(Profile, actor.id)
        result["profile"] = own_profile(profile, actor.id, day_number, result["canAuthor"])
        result["player"] = voice_template()
    return result


@router.post("/day-{day_number}/posts")
def create_post(
    day_number: int, request: Request, response: Response, db: Session = Depends(get_db), nonce: UUID = Form(),
    text: str = Form(default="", max_length=2000), reply_to: int | None = Form(default=None),
    featured: bool = Form(default=False), photo: UploadFile | None = File(default=None),
    voice: UploadFile | None = File(default=None),
) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    lock_owner(db, actor.id)
    response.headers.update(PRIVATE_HEADERS)
    client_key = sha256(f"{actor.id}:{day_number}:{nonce}".encode()).hexdigest()
    existing = db.scalar(select_day(day_number).where(
        Post.author_id == actor.id, Post.client_nonce.in_([client_key, str(nonce)])
    ))
    if existing:
        return payload(db, request, day_number, [existing], actor.id, False)
    question = db.scalar(select_day(day_number).where(Post.id == reply_to)) if reply_to is not None else None
    if reply_to is not None and question is None:
        raise HTTPException(404, "Исходное сообщение недоступно.")
    is_author = actor.id == discussion_author(db)
    if (featured or voice is not None) and not is_author:
        raise HTTPException(403, "Это действие доступно автору обсуждения.")
    if featured and (question is None or question.author_id == actor.id):
        raise HTTPException(422, "Ответ можно отметить у чужого сообщения.")
    text = text.strip()
    photo_data = limited_upload(photo, PHOTO_LIMIT)
    voice_data = limited_upload(voice, VOICE_LIMIT)
    if not text and photo_data is None and voice_data is None:
        raise HTTPException(422, "Добавьте текст или вложение.")
    image = read_image(photo_data) if photo_data is not None else None
    audio = read_voice(voice_data) if voice_data is not None else None
    if featured:
        for old in db.scalars(select_day(day_number).where(Post.reply_to_id == reply_to, Post.featured.is_(True))):
            old.featured = False
    post = Post(
        day_number=day_number, author_id=actor.id, client_nonce=client_key, body=text,
        photo=image is not None, voice=audio is not None, reply_to_id=reply_to, featured=featured,
    )
    db.add(post)
    db.flush()
    written = []
    try:
        for data, suffix in ((image, "webp"), (audio, "mp3")):
            if data is not None:
                path = root() / f"post-{post.id}.{suffix}"
                written.append(path)
                path.write_bytes(data)
        enqueue_post(db, post, question, is_author=is_author)
        db.commit()
    except Exception:
        db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise
    rows = [question, post] if question is not None else [post]
    return payload(db, request, day_number, rows, actor.id, False)


class ReadBatch(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


@router.post("/day-{day_number}/read")
def mark_read(day_number: int, batch: ReadBatch, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    lock_owner(db, actor.id)
    unread = db.scalars(unread_query(actor.id, day_number).where(Post.id.in_(batch.ids))).all()
    db.add_all(Read(user_id=actor.id, post_id=post_id) for post_id in unread)
    db.commit()
    return {"unread": count_unread(db, actor.id, day_number)}


@router.get("/day-{day_number}/posts/{post_id}/{kind}")
def media(day_number: int, post_id: int, kind: str, request: Request, db: Session = Depends(get_db)) -> FileResponse:
    require_owner(request, db)
    require_day(db, day_number)
    post = db.scalar(select_day(day_number).where(Post.id == post_id))
    if post and kind == "photo" and post.photo:
        suffix, media_type = "webp", "image/webp"
    elif post and kind == "voice" and post.voice:
        suffix, media_type = "mp3", "audio/mpeg"
    else:
        raise HTTPException(404, "Вложение недоступно.")
    path = root() / f"post-{post_id}.{suffix}"
    if not path.is_file():
        raise HTTPException(404, "Вложение недоступно.")
    return FileResponse(path, media_type=media_type, headers=PRIVATE_HEADERS)


@router.put("/day-{day_number}/profile")
def update_profile(
    day_number: int, request: Request, db: Session = Depends(get_db),
    name: str = Form(default="", max_length=80), about: str = Form(default="", max_length=500),
    visible: bool = Form(default=False), photo: UploadFile | None = File(default=None),
    remove_photo: bool = Form(default=False),
) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    lock_owner(db, actor.id)
    profile = db.get(Profile, actor.id)
    if profile is None:
        profile = Profile(user_id=actor.id)
        db.add(profile)
    profile.display_name, profile.about, profile.visible = name.strip(), about.strip(), visible
    previous = profile.photo_key
    data = limited_upload(photo, PHOTO_LIMIT)
    written = None
    if data is not None:
        image = read_image(data)
        profile.photo_key = uuid4()
        written = root() / f"profile-{profile.photo_key}.webp"
    elif remove_photo:
        profile.photo_key = None
    try:
        if written is not None:
            written.write_bytes(image)
        db.commit()
    except Exception:
        db.rollback()
        if written:
            written.unlink(missing_ok=True)
        raise
    if previous and previous != profile.photo_key:
        (root() / f"profile-{previous}.webp").unlink(missing_ok=True)
    return {"profile": public_profile(profile, actor.id, day_number), "avatar": profile_avatar(profile, day_number)}


@router.get("/day-{day_number}/profile/photo/{key}")
def profile_photo(day_number: int, key: UUID, request: Request, db: Session = Depends(get_db)) -> FileResponse:
    actor = require_owner(request, db)
    require_day(db, day_number)
    posted = exists(select(Post.id).where(Post.author_id == Profile.user_id, Post.day_number == day_number))
    profile = db.scalar(select(Profile).where(
        Profile.photo_key == key, Profile.visible.is_(True), or_(Profile.user_id == actor.id, posted)
    ).limit(1))
    path = root() / f"profile-{key}.webp"
    if profile is None or not path.is_file():
        raise HTTPException(404, "Фото недоступно.")
    return FileResponse(path, media_type="image/webp", headers=PRIVATE_HEADERS)


@router.post("/day-{day_number}/voice-preview")
def voice_preview(day_number: int, request: Request, voice: UploadFile = File(), db: Session = Depends(get_db)):
    actor = require_owner(request, db)
    require_day(db, day_number)
    if actor.id != discussion_author(db):
        raise HTTPException(403, "Запись голосовых доступна автору обсуждения.")
    return Response(read_voice(voice.file.read(VOICE_LIMIT + 1)), media_type="audio/mpeg", headers=PRIVATE_HEADERS)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    auth: str = Field(min_length=20, max_length=25, pattern=r"^[A-Za-z0-9_-]+$")


class PushEndpoint(BaseModel):
    endpoint: str = Field(max_length=1800)


class PushSettings(PushEndpoint):
    keys: PushKeys
    replies: bool
    new_posts: bool


class PushProbe(PushEndpoint):
    kind: str
    nonce: UUID
    post_id: int | None = None


@router.post("/day-{day_number}/push/key")
def push_key(day_number: int, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    lock_owner(db, actor.id)
    return {"key": public_key()}


def find_subscription(db: Session, actor: User, endpoint: str) -> Subscription | None:
    return db.scalar(select(Subscription).where(
        Subscription.user_id == actor.id, Subscription.endpoint_hash == endpoint_hash(endpoint)
    ))


@router.post("/day-{day_number}/push/preferences")
def push_preferences(day_number: int, data: PushEndpoint, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    stored = find_subscription(db, actor, data.endpoint)
    return {
        "enabled": stored is not None,
        "replies": stored.replies if stored else True,
        "new_posts": stored.new_posts if stored else True,
    }


@router.put("/day-{day_number}/push/subscription")
def push_subscription(day_number: int, data: PushSettings, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    lock_owner(db, actor.id)
    if not permitted_endpoint(data.endpoint):
        raise HTTPException(422, "Этот браузер использует неподдерживаемую службу уведомлений.")
    if not valid_keys(data.keys.p256dh, data.keys.auth):
        raise HTTPException(422, "Браузер передал недействительную подписку. Подключите уведомления снова.")
    stored = find_subscription(db, actor, data.endpoint)
    if not stored:
        stored = Subscription(user_id=actor.id, endpoint_hash=endpoint_hash(data.endpoint))
        db.add(stored)
    stored.subscription = {"endpoint": data.endpoint, "keys": data.keys.model_dump()}
    stored.replies, stored.new_posts = data.replies, data.new_posts
    db.commit()
    return {"ok": True}


@router.delete("/day-{day_number}/push/subscription")
def drop_subscription(day_number: int, data: PushEndpoint, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    stored = find_subscription(db, actor, data.endpoint)
    if stored:
        db.delete(stored)
        db.commit()
    return {"ok": True}


@router.post("/day-{day_number}/push/test")
def push_test(day_number: int, data: PushProbe, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    require_day(db, day_number)
    lock_owner(db, actor.id)
    stored = find_subscription(db, actor, data.endpoint)
    if not stored or data.kind not in PUSH_TITLES:
        raise HTTPException(404, "Подписка недоступна.")
    if (data.kind == "reply" and not stored.replies) or (data.kind == "day" and not stored.new_posts):
        raise HTTPException(409, "Сначала включите этот вид уведомлений.")
    query = select_day(day_number)
    if data.post_id is not None:
        query = query.where(Post.id == data.post_id)
    else:
        query = query.order_by(Post.id.desc())
    post = db.scalar(query.limit(1))
    if data.post_id is not None and post is None:
        raise HTTPException(404, "Сообщение недоступно.")
    enqueue_test(db, stored, data.kind, data.nonce, day_number, post.id if post else None)
    db.commit()
    return {"ok": True}
