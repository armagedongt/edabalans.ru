from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserLegalAcceptance


LEGAL_DOCUMENTS = (
    {
        "code": "educational_disclaimer",
        "version": "draft-2026-08-24",
        "title": "Информационно-образовательный дисклеймер",
        "url": "/legal/disclaimer.html",
        "summary": (
            "Материалы личного кабинета носят информационно-образовательный "
            "характер, не являются медицинской услугой, диагностикой или "
            "назначением лечения. При заболеваниях, симптомах и назначениях "
            "врача решения о здоровье нужно согласовывать с медицинским специалистом."
        ),
    },
    {
        "code": "personal_data_policy",
        "version": "draft-2026-08-24",
        "title": "Политика обработки персональных данных",
        "url": "/legal/privacy.html",
        "summary": (
            "В личном кабинете могут сохраняться данные аккаунта и покупки, "
            "прогресс, ответы анкет, дневники и сведения, которые вы сами "
            "вносите для работы с программами. Состав, цели, сроки хранения "
            "и используемые сервисы описываются в полной редакции политики."
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
