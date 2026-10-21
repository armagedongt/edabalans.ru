from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserLegalAcceptance


LEGAL_DOCUMENTS = (
    {
        "code": "educational_disclaimer",
        "version": "2026-08-24-v2",
        "title": "Образовательный дисклеймер",
        "url": "/legal/disclaimer",
        "summary": (
            "Все материалы личного кабинета и мои консультации носят "
            "информационно-образовательный характер. Они не являются медицинской "
            "услугой, диагностикой или назначением лечения.\n\n"
            "При любых заболеваниях и патологиях рекомендации врача имеют "
            "приоритет над любой информацией, полученной от меня."
        ),
    },
    {
        "code": "personal_data_consent",
        "version": "2026-10-21-v2",
        "title": "Согласие на обработку персональных данных",
        "url": "/legal/consent",
        "summary": (
            "В личном кабинете хранятся данные вашего аккаунта — история "
            "покупок, прогресс обучения, анкета, дневник питания и любые другие "
            "сведения, которые вы укажете самостоятельно.\n\n"
            "Данные проекта хранятся на территории РФ в соответствии "
            "с законом. Политика подробно объясняет "
            "состав данных, цели обработки, сроки хранения и ваши права."
        ),
    },
)

OFFER_VERSION = "2026-10-21-v2"


def checkout_legal_snapshot(source: str) -> dict:
    return {
        "source": source,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "personal_data_consent": current_legal_versions()["personal_data_consent"],
        "offer": OFFER_VERSION,
    }


def record_data_consent(db: Session, user_id: uuid.UUID, snapshot: dict) -> None:
    version = snapshot.get("personal_data_consent")
    if not version or not snapshot.get("accepted_at") or not snapshot.get("source"):
        return
    if ("personal_data_consent", version) in accepted_legal_versions(db, user_id):
        return
    db.add(UserLegalAcceptance(
        user_id=user_id,
        document_code="personal_data_consent",
        document_version=version,
        source=snapshot["source"],
        accepted_at=datetime.fromisoformat(snapshot["accepted_at"]),
    ))


def document_accepted(accepted: set[tuple[str, str]], code: str, version: str) -> bool:
    if (code, version) in accepted:
        return True
    return code == "personal_data_consent" and (code, "2026-08-24-v1") in accepted


def data_consent_complete(db: Session, user_id: uuid.UUID) -> bool:
    return document_accepted(accepted_legal_versions(db, user_id), "personal_data_consent",
                             current_legal_versions()["personal_data_consent"])


def current_legal_versions() -> dict[str, str]:
    return {item["code"]: item["version"] for item in LEGAL_DOCUMENTS}


def accepted_legal_versions(db: Session, user_id: uuid.UUID) -> set[tuple[str, str]]:
    return set(
        db.execute(
            select(
                UserLegalAcceptance.document_code,
                UserLegalAcceptance.document_version,
            ).where(UserLegalAcceptance.user_id == user_id)
        ).all()
    )


def legal_acceptances_complete(db: Session, user_id: uuid.UUID) -> bool:
    accepted = accepted_legal_versions(db, user_id)
    return all(document_accepted(accepted, item["code"], item["version"]) for item in LEGAL_DOCUMENTS)


def legal_status_payload(db: Session, user_id: uuid.UUID) -> dict:
    accepted = accepted_legal_versions(db, user_id)
    documents = [
        {
            **item,
            "accepted": document_accepted(accepted, item["code"], item["version"]),
        }
        for item in LEGAL_DOCUMENTS
    ]
    return {
        "required": not all(item["accepted"] for item in documents),
        "documents": documents,
    }


def accept_current_legal_documents(
    db: Session,
    user_id: uuid.UUID,
    document_codes: list[str],
    *,
    source: str,
) -> None:
    requested = set(document_codes)
    expected = set(current_legal_versions())
    if requested != expected:
        raise ValueError("all current legal documents must be accepted together")
    accepted = accepted_legal_versions(db, user_id)
    for code, version in current_legal_versions().items():
        if not document_accepted(accepted, code, version):
            db.add(
                UserLegalAcceptance(
                    user_id=user_id,
                    document_code=code,
                    document_version=version,
                    source=source,
                )
            )
