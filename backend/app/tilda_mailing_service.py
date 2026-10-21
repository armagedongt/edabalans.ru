"""Private, paused drafts for the approved Tilda cohort in the existing mail queue."""
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select
from app.access_service import review_blocks_access
from app.account_onboarding_service import _encrypt_bundle, _decrypt_bundle, direct_credential_email_configuration_error, has_account_login
from app.account_security import decrypt_password
from app.course_access_service import active_resource_codes, course_entry_unlocked
from app.legacy_upgrade_service import eligible, PRICE_CODES
from app.models import AccountCredential, AccountOnboarding, AdminAppEdit, ManagedDocumentVersion, Resource, User, UserCoursePolicy, UserEmail
from app.pricing_service import active_pricing_version, pricing_entry_map
from app.product_catalog_service import product_public, DOCUMENT_TYPE, DOCUMENT_KEY
from app.service_email_templates import render_section

MODE = "tilda_transfer"
BATCH = "tilda-transfer-20261010"


def access_text(db, user):
    if review_blocks_access(user):
        return render_section("tilda-transfer", "unconfirmed")
    owned = active_resource_codes(db, user.id)
    policies = {code: p for code, p in db.execute(select(Resource.code, UserCoursePolicy)
                .join(UserCoursePolicy, UserCoursePolicy.resource_id == Resource.id)
                .where(UserCoursePolicy.user_id == user.id))}
    lines = []
    for product, code in (("masterclass", "ACCESS_MASTERCLASS"), ("calories", "ACCESS_CALORIES"),
                          ("recipes", "ACCESS_RECIPES"), ("training", "ACCESS_STRENGTH")):
        resource = code if code in owned else code + "_LEGACY" if code + "_LEGACY" in owned else None
        if not resource:
            continue
        policy = policies.get(resource)
        if not course_entry_unlocked(db, user.id, code):
            opening = "начало пока закрыто — напишите мне" if policy and policy.start_mode == "blocked" else "начало откроется по условиям программы"
        elif policy and policy.unlock_mode == "fully_unlocked":
            opening = "материалы открыты сразу"
        else:
            opening = "можно начать сразу; материалы открываются последовательно"
        edition = "необновляемый доступ" if resource.endswith("_LEGACY") else "обновляемый доступ"
        lines.append(f"— {product_public(db, product)['name']} — {edition}; {opening}.")
    apps = [("dqs", "DQS — оценка качества питания"), ("metabolism", "Калькулятор метаболизма"),
            ("recipes", "Каталог и калькулятор рецептов"), ("strength", "Дневник силовых тренировок")]
    for code, name in apps:
        if code in owned:
            lines.append(f"— {name} — по условиям открытия соответствующих материалов.")
    return "В вашем личном кабинете доступны:\n\n" + "\n".join(lines) if lines else render_section("tilda-transfer", "unconfirmed")


def letter_bundle(db, user, email, credential, settings):
    return {"batch": BATCH, "email": email, "name": user.display_name or email,
            "subject": render_section("tilda-transfer", "subject"),
            "message_text": render_section("tilda-transfer", "text",
                account_url=settings.account_public_url, email=email,
                password=decrypt_password(credential.password_ciphertext, settings.app_auth_secret),
                access_text=access_text(db, user),
                upgrade_text=render_section("tilda-transfer", "upgrade") if eligible(db, user) else ""),
            "password_version": credential.password_version, "upgrade": eligible(db, user)}


def refresh_drafts(db, settings, admin):
    refreshed = 0
    for row in rows(db, lock=True):
        if row.email_status not in {"draft", "excluded"}:
            continue
        bundle = _decrypt_bundle(row.claim_bundle_encrypted, settings)
        user = db.get(User, row.user_id)
        credential = db.get(AccountCredential, row.user_id)
        linked = db.scalar(select(UserEmail.id).where(UserEmail.user_id == row.user_id, UserEmail.email_normalized == bundle["email"]))
        if not user or user.status != "active" or user.merged_into_user_id or not credential or not credential.password_ciphertext or not linked:
            raise ValueError("Не удалось подтвердить аккаунт получателя")
        row.claim_bundle_encrypted = _encrypt_bundle(letter_bundle(db, user, bundle["email"], credential, settings), settings)
        if has_account_login(db, row.user_id):
            row.email_status = "excluded"
            row.email_error = "Участник уже входил в личный кабинет"
        db.add(AdminAppEdit(admin_username=admin, target_user_id=row.user_id, app_code="crm",
                           action="refresh_tilda_letter", details={"delivery_id": str(row.id)}))
        refreshed += 1
    db.flush()
    return refreshed


def prepare_drafts(db, manifest, settings, admin):
    """Caller commits once; this creates only draft rows and never issues a password."""
    if not db.scalar(select(ManagedDocumentVersion.id).where(ManagedDocumentVersion.document_type == DOCUMENT_TYPE,
                     ManagedDocumentVersion.document_key == DOCUMENT_KEY, ManagedDocumentVersion.is_active.is_(True))):
        raise ValueError("Нужен действующий каталог продуктов")
    existing = {row.user_id for row in db.scalars(select(AccountOnboarding).where(AccountOnboarding.delivery_mode == MODE))}
    created = 0
    for member in manifest["recipients"]:
        # The owner explicitly excluded everyone who already had a server password.
        if member["account_existing"]:
            continue
        user_id = uuid.UUID(member["user_id"])
        if user_id in existing:
            continue
        user = db.get(User, user_id)
        credential = db.get(AccountCredential, user_id)
        email = member["email"]
        linked = db.scalar(select(UserEmail).where(UserEmail.user_id == user_id, UserEmail.email_normalized == email))
        if not user or user.status != "active" or user.merged_into_user_id or not credential or not credential.password_ciphertext or not linked:
            raise ValueError("Не удалось подтвердить аккаунт получателя")
        bundle = letter_bundle(db, user, email, credential, settings)
        now = datetime.now(timezone.utc)
        row = AccountOnboarding(user_id=user_id, delivery_mode=MODE, email_status="draft",
                                expires_at=now + timedelta(days=10), claim_bundle_encrypted=_encrypt_bundle(bundle, settings))
        db.add(row)
        db.add(AdminAppEdit(admin_username=admin, target_user_id=user_id, app_code="crm",
                            action="prepare_tilda_letter", details={"batch": BATCH}))
        existing.add(user_id)
        created += 1
    db.flush()
    return created


def rows(db, lock=False):
    query = select(AccountOnboarding).where(AccountOnboarding.delivery_mode == MODE).order_by(AccountOnboarding.id)
    return list(db.scalars(query.with_for_update() if lock else query))


def blockers(db, selected, settings):
    result = []
    error = direct_credential_email_configuration_error(settings)
    if error:
        result.append("Почтовая доставка не настроена")
    for row, bundle in selected:
        user = db.get(User, row.user_id)
        credential = db.get(AccountCredential, row.user_id)
        linked = db.scalar(select(UserEmail.id).where(UserEmail.user_id == row.user_id, UserEmail.email_normalized == bundle["email"]))
        if not user or user.status != "active" or user.merged_into_user_id or not linked:
            result.append("Аккаунт или почта одного из получателей изменились")
        if not credential or credential.password_version != bundle.get("password_version"):
            result.append("Пароль одного из получателей изменился после подготовки письма")
        if bundle.get("upgrade"):
            version = active_pricing_version(db)
            entries = pricing_entry_map(db, version) if version else {}
            if any(code not in entries or not entries[code].enabled for code in PRICE_CODES.values()) or not settings.robokassa_checkout_enabled:
                result.append("Предложение перехода на обновляемый пакет ещё не включено")
    return list(dict.fromkeys(result))


def listing(db, settings):
    items = []
    selected = []
    for row in rows(db):
        bundle = _decrypt_bundle(row.claim_bundle_encrypted, settings)
        seen = has_account_login(db, row.user_id)
        excluded_for_login = seen and row.email_status in {"draft", "excluded"}
        if row.email_status == "draft" and not seen:
            selected.append((row, bundle))
        items.append({"id": str(row.id), "user_id": str(row.user_id), "name": bundle["name"],
                      "email": bundle["email"], "subject": bundle["subject"], "status": "excluded" if excluded_for_login else row.email_status,
                      "error": "Участник уже входил в личный кабинет" if excluded_for_login else row.email_error, "sent_at": row.email_sent_at.isoformat() if row.email_sent_at else None})
    return {"recipients": items, "selected": len(selected), "blockers": blockers(db, selected, settings)}


def get_draft(db, delivery_id):
    row = db.scalar(select(AccountOnboarding).where(AccountOnboarding.id == delivery_id, AccountOnboarding.delivery_mode == MODE).with_for_update())
    if row is None:
        raise ValueError("Письмо не найдено")
    return row


def update_draft(db, row, settings, admin, subject, text, included):
    if row.email_status not in {"draft", "excluded"}:
        raise ValueError("Письмо уже запущено; изменить его нельзя")
    if included and has_account_login(db, row.user_id):
        raise ValueError("Участник уже входил в личный кабинет")
    if not subject.strip() or any(ord(c) < 32 or ord(c) == 127 for c in subject) or not text.strip():
        raise ValueError("Укажите тему одной строкой и текст письма")
    bundle = _decrypt_bundle(row.claim_bundle_encrypted, settings)
    bundle.update(subject=subject.strip(), message_text=text)
    row.claim_bundle_encrypted = _encrypt_bundle(bundle, settings)
    row.email_status = "draft" if included else "excluded"
    db.add(AdminAppEdit(admin_username=admin, target_user_id=row.user_id, app_code="crm",
                        action="edit_tilda_letter", details={"delivery_id": str(row.id), "included": included}))


def launch(db, settings, admin, expected_count):
    candidates = [r for r in rows(db, lock=True) if r.email_status == "draft"]
    seen = {r.user_id for r in candidates if has_account_login(db, r.user_id)}
    selected = [(r, _decrypt_bundle(r.claim_bundle_encrypted, settings)) for r in candidates if r.user_id not in seen]
    if len(selected) != expected_count or not selected:
        raise ValueError("Список получателей изменился — обновите страницу")
    errors = blockers(db, selected, settings)
    if errors:
        raise ValueError("; ".join(errors))
    now = datetime.now(timezone.utc)
    for row in candidates:
        if row.user_id in seen:
            row.email_status = "excluded"
            row.email_error = "Участник уже входил в личный кабинет"
    for row, bundle in selected:
        row.email_status = "pending"
        row.next_email_attempt_at = now
        db.add(AdminAppEdit(admin_username=admin, target_user_id=row.user_id, app_code="crm",
                            action="launch_tilda_letter", details={"delivery_id": str(row.id), "batch": BATCH}))
    db.flush()
    return len(selected)
