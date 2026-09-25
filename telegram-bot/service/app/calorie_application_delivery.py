"""Approved one-off calculator link; reuses the existing notification dispatcher."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentItem, Sequence, SequenceStep, SequenceVersion


SEQUENCE_CODE = "calories_service_delivery"
STEP_KEY = "calories_metabolism_link"
CONTENT_CODE = "tpl_postpurchase_metabolism_app_link"
APP_URL = "https://edabalans.ru/metabolism"
APPROVED_TEXT = (
    'Ваш калькулятор метаболизма: <a href="https://edabalans.ru/metabolism">'
    'https://edabalans.ru/metabolism</a>. '
    'Закрепите это сообщение, чтобы ссылка была под рукой'
)


def seed_calorie_application_delivery(session: Session) -> None:
    item = session.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE))
    if item is None:
        item = ContentItem(
            code=CONTENT_CODE, title="Калькулятор метаболизма — ссылка",
            body_source=APPROVED_TEXT, source_format="telegram_html",
            status="published", editorial_status="approved", origin_system="template",
            labels=["Калорийный курс", "ссылка на приложение"],
            purpose="Сохранить у участника ссылку на калькулятор после материала о расходе калорий.",
            writer_brief="Текст дословно утверждён владельцем 25.09.2026. Не дописывать и не менять самостоятельно.",
        )
        session.add(item)
        session.flush()
    sequence = session.scalar(select(Sequence).where(Sequence.code == SEQUENCE_CODE))
    if sequence is not None:
        return  # Never overwrite a later graph or an editorial change on startup.
    sequence = Sequence(
        code=SEQUENCE_CODE, name="Калорийный курс — выдача калькулятора",
        description="Одна служебная отправка по событию чтения материала, без массового запуска.",
        status="active",
    )
    session.add(sequence)
    session.flush()
    version = SequenceVersion(sequence_id=sequence.id, version_no=1, status="published")
    session.add(version)
    session.flush()
    session.add_all([
        SequenceStep(
            sequence_version_id=version.id, step_key=STEP_KEY, position=1,
            kind="MESSAGE", label=item.title, content_item_id=item.id,
            configuration={
                "trigger": "app_revealed_metabolism", "state": "service_delivery",
                "condition": "ACCESS_CALORIES active AND exact messenger linked AND material completed",
                "buttons": [{"text": "Открыть калькулятор", "url": APP_URL}],
                "editorial_help": {
                    "trigger": "app_revealed_metabolism",
                    "condition": "Материал о расходе завершён; доступ к Калорийным действует; мессенджер подключён",
                    "recipient": "Тот же участник, выбранный основной мессенджер",
                    "purpose": item.purpose,
                },
            },
        ),
        SequenceStep(
            sequence_version_id=version.id, step_key="calories_link_finish", position=2,
            kind="STOP", label="Ссылка отправлена", configuration={"reason": "service_delivery_complete"},
        ),
    ])
