"""Private, owner-only day-four pilot. Course progress and product access remain independent."""
from __future__ import annotations

from datetime import UTC
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import subprocess
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.account_auth_routes import ACCOUNT_MANAGER_EMAIL, ACCOUNT_VIEW_HEADER, native_session_actor, primary_email
from app.config import get_settings
from app.course_material_routes import component_asset
from app.database import get_db
from app.masterclass_discussion_push import PUSH_TITLES, endpoint_hash, enqueue_test, permitted_endpoint, public_key, valid_keys
from app.models import MasterclassDiscussionPost as Post
from app.models import MasterclassDiscussionProfile as Profile
from app.models import MasterclassDiscussionRead as Read
from app.models import MasterclassDiscussionSubscription as Subscription
from app.models import User

router = APIRouter(prefix="/api/masterclass/discussion/day-04", tags=["masterclass-discussion"])
DAY = 4
PAGE_SIZE = 30
PHOTO_LIMIT = 8_000_000
VOICE_LIMIT = 12_000_000
VOICE_SECONDS = 900
NOTICE = "Обсуждение работает в тестовом режиме. У вас пока нет доступа. Ожидайте уведомления."
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


def select_day():
    return select(Post).where(Post.day_number == DAY)


def unread_query(user_id: UUID):
    read = exists(select(Read.post_id).where(Read.user_id == user_id, Read.post_id == Post.id))
    return select(Post.id).where(Post.day_number == DAY, or_(Post.author_id.is_(None), Post.author_id != user_id), ~read)


def count_unread(db: Session, user_id: UUID) -> int:
    return db.scalar(select(func.count()).select_from(unread_query(user_id).subquery())) or 0


def public_profile(profile: Profile | None, user_id: UUID) -> dict | None:
    if not profile or not profile.visible:
        return None
    return {
        "name": profile.display_name or "Сергей",
        "about": profile.about,
        "avatar": f"{router.prefix}/profile/photo/{profile.photo_key}" if profile.photo_key else None,
    }


def serialize(post: Post, user_id: UUID, profile: Profile | None) -> dict:
    own = post.author_id == user_id
    card = public_profile(profile, user_id) if own else None
    return {
        "id": post.id,
        "name": (card["name"] if card else "Сергей") if own else post.source_label or "Участник",
        "isAuthor": own,
        "profile": card,
        "text": post.body,
        "archived": post.archived,
        "at": post.created_at.astimezone(UTC).isoformat() if not post.archived else None,
        "photo": f"{router.prefix}/posts/{post.id}/photo" if post.photo else None,
        "voice": f"{router.prefix}/posts/{post.id}/voice" if post.voice else None,
        "replyTo": post.reply_to_id,
        "marked": post.featured,
    }


def payload(db: Session, posts: list[Post], user_id: UUID, has_more: bool) -> dict:
    profile = db.get(Profile, user_id)
    known = {post.id for post in posts}
    parent_ids = {post.reply_to_id for post in posts if post.reply_to_id and post.reply_to_id not in known}
    related = list(db.scalars(
        select_day().where(or_(Post.id.in_(parent_ids), Post.featured.is_(True) & Post.reply_to_id.in_(known)))
    ))
    answers = {post.reply_to_id: post.id for post in sorted([*posts, *related], key=lambda row: row.id) if post.featured}
    first_unread = db.scalar(unread_query(user_id).order_by(Post.id).limit(1))
    return {
        "posts": [serialize(post, user_id, profile) for post in posts],
        "related": [serialize(post, user_id, profile) for post in related if post.id not in known],
        "answers": answers,
        "more": has_more,
        "unread": count_unread(db, user_id),
        "firstUnread": first_unread,
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
        raise HTTPException(413, "Голосовое должно быть до 12 МБ.")
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "pipe",
             "-i", "pipe:0", "-vn", "-ac", "1", "-b:a", "48k", "-t", str(VOICE_SECONDS + 1), "-f", "mp3", "pipe:1"],
            input=raw, capture_output=True, timeout=20, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(422, "Не удалось подготовить аудио. Попробуйте записать его снова.") from None
    if not result.stdout:
        raise HTTPException(422, "В записи нет звука или она пуста.")
    if len(result.stdout) > VOICE_SECONDS * 6000 + 1024:
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


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)) -> dict:
    if not get_settings().masterclass_discussion_pilot:
        return {"mode": "off"}
    actor = owner(request, db)
    if actor is None:
        return {"mode": "locked", "notice": NOTICE}
    return {"mode": "owner", "unread": count_unread(db, actor.id)}


@router.get("/thread")
def thread(request: Request, db: Session = Depends(get_db), after: int = Query(default=0, ge=0),
           around: int | None = Query(default=None, ge=1)) -> dict:
    actor = require_owner(request, db)
    if around is not None:
        if db.scalar(select_day().where(Post.id == around)) is None:
            raise HTTPException(404, "Сообщение недоступно.")
        rows = list(db.scalars(select_day().where(Post.id < around).order_by(Post.id.desc()).limit(PAGE_SIZE // 2)))
        rows.reverse()
        rows.extend(db.scalars(select_day().where(Post.id >= around).order_by(Post.id).limit(PAGE_SIZE + 1 - len(rows))))
    else:
        rows = list(db.scalars(select_day().where(Post.id > after).order_by(Post.id).limit(PAGE_SIZE + 1)))
    result = payload(db, rows[:PAGE_SIZE], actor.id, len(rows) > PAGE_SIZE)
    if not after and around is None:
        profile = db.get(Profile, actor.id)
        result["profile"] = {"name": profile.display_name, "about": profile.about, "visible": profile.visible} if profile else {"name": "", "about": "", "visible": False}
        result["player"] = voice_template()
    return result


@router.post("/posts")
def create_post(
    request: Request, db: Session = Depends(get_db), nonce: UUID = Form(),
    text: str = Form(default="", max_length=2000), reply_to: int | None = Form(default=None),
    featured: bool = Form(default=False), photo: UploadFile | None = File(default=None),
    voice: UploadFile | None = File(default=None),
) -> dict:
    actor = require_owner(request, db)
    lock_owner(db, actor.id)
    existing = db.scalar(select_day().where(Post.author_id == actor.id, Post.client_nonce == str(nonce)))
    if existing:
        return payload(db, [existing], actor.id, False)
    question = db.scalar(select_day().where(Post.id == reply_to)) if reply_to is not None else None
    if reply_to is not None and question is None:
        raise HTTPException(404, "Исходное сообщение недоступно.")
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
        for old in db.scalars(select_day().where(Post.reply_to_id == reply_to, Post.featured.is_(True))):
            old.featured = False
    post = Post(
        day_number=DAY, author_id=actor.id, client_nonce=str(nonce), body=text,
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
        db.commit()
    except Exception:
        db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise
    rows = [question, post] if question is not None else [post]
    return payload(db, rows, actor.id, False)


class ReadBatch(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


@router.post("/read")
def mark_read(batch: ReadBatch, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    lock_owner(db, actor.id)
    unread = db.scalars(unread_query(actor.id).where(Post.id.in_(batch.ids))).all()
    db.add_all(Read(user_id=actor.id, post_id=post_id) for post_id in unread)
    db.commit()
    return {"unread": count_unread(db, actor.id)}


@router.get("/posts/{post_id}/{kind}")
def media(post_id: int, kind: str, request: Request, db: Session = Depends(get_db)) -> FileResponse:
    require_owner(request, db)
    post = db.scalar(select_day().where(Post.id == post_id))
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


@router.put("/profile")
def update_profile(
    request: Request, db: Session = Depends(get_db),
    name: str = Form(default="", max_length=80), about: str = Form(default="", max_length=500),
    visible: bool = Form(default=False), photo: UploadFile | None = File(default=None),
    remove_photo: bool = Form(default=False),
) -> dict:
    actor = require_owner(request, db)
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
    return {"profile": public_profile(profile, actor.id)}


@router.get("/profile/photo/{key}")
def profile_photo(key: UUID, request: Request, db: Session = Depends(get_db)) -> FileResponse:
    actor = require_owner(request, db)
    profile = db.get(Profile, actor.id)
    path = root() / f"profile-{key}.webp"
    if not profile or profile.photo_key != key or not profile.visible or not path.is_file():
        raise HTTPException(404, "Фото недоступно.")
    return FileResponse(path, media_type="image/webp", headers=PRIVATE_HEADERS)


@router.post("/voice-preview")
def voice_preview(request: Request, voice: UploadFile = File(), db: Session = Depends(get_db)):
    from fastapi.responses import Response

    require_owner(request, db)
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


@router.post("/push/key")
def push_key(request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    lock_owner(db, actor.id)
    return {"key": public_key()}


def find_subscription(db: Session, actor: User, endpoint: str) -> Subscription | None:
    return db.scalar(select(Subscription).where(
        Subscription.user_id == actor.id, Subscription.endpoint_hash == endpoint_hash(endpoint)
    ))


@router.post("/push/preferences")
def push_preferences(data: PushEndpoint, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    stored = find_subscription(db, actor, data.endpoint)
    return {"replies": stored.replies if stored else True, "new_posts": stored.new_posts if stored else False}


@router.put("/push/subscription")
def push_subscription(data: PushSettings, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
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


@router.delete("/push/subscription")
def drop_subscription(data: PushEndpoint, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    stored = find_subscription(db, actor, data.endpoint)
    if stored:
        db.delete(stored)
        db.commit()
    return {"ok": True}


@router.post("/push/test")
def push_test(data: PushProbe, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = require_owner(request, db)
    lock_owner(db, actor.id)
    stored = find_subscription(db, actor, data.endpoint)
    if not stored or data.kind not in PUSH_TITLES:
        raise HTTPException(404, "Подписка недоступна.")
    if (data.kind == "reply" and not stored.replies) or (data.kind == "day" and not stored.new_posts):
        raise HTTPException(409, "Сначала включите этот вид уведомлений.")
    query = select_day()
    if data.post_id is not None:
        query = query.where(Post.id == data.post_id)
    else:
        query = query.order_by(Post.id.desc())
    post = db.scalar(query.limit(1))
    enqueue_test(db, stored, data.kind, data.nonce, post.id if post else None)
    db.commit()
    return {"ok": True}
