from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserLegalAcceptance


LEGAL_DOCUMENTS = (
    {
        "code": "educational_disclaimer",
        "version": "2026-08-24-v2",
        "title": "Образовательный дисклеймер",
        "url": "/legal/disclaimer.html",
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
        "version": "2026-08-24-v1",
        "title": "Согласие на обработку персональных данных",
        "url": "/legal/consent.html",
        "summary": (
            "В личном кабинете хранятся все данные вашего аккаунта — история "
            "покупок, прогресс обучения, анкета, дневник питания и любые другие "
            "сведения, которые вы укажете самостоятельно.\n\n"
            "По умолчанию основные базы данных личного кабинета хранятся на "
            "территории РФ в соответствии с законом. Политика подробно объясняет "
            "состав данных, цели обработки, сроки хранения и ваши права."
        ),
    },
)


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
    return all((item["code"], item["version"]) in accepted for item in LEGAL_DOCUMENTS)


def legal_status_payload(db: Session, user_id: uuid.UUID) -> dict:
    accepted = accepted_legal_versions(db, user_id)
    documents = [
        {
            **item,
            "accepted": (item["code"], item["version"]) in accepted,
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
        if (code, version) not in accepted:
            db.add(
                UserLegalAcceptance(
                    user_id=user_id,
                    document_code=code,
                    document_version=version,
                    source=source,
                )
            )
