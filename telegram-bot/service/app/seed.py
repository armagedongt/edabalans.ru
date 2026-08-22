from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotInstance, BotRoute, ContentItem, Sequence, SequenceEdge, SequenceStep, SequenceVersion


PREPURCHASE_CODE = "prepurchase_masterclass"
POSTPURCHASE_CODE = "postpurchase_masterclass"


def _ensure_edges(session: Session, version: SequenceVersion) -> None:
    if session.scalar(select(SequenceEdge.id).where(SequenceEdge.sequence_version_id == version.id).limit(1)):
        return
    steps = list(
        session.scalars(
            select(SequenceStep)
            .where(SequenceStep.sequence_version_id == version.id, SequenceStep.enabled.is_(True))
            .order_by(SequenceStep.position)
        )
    )
    for index, step in enumerate(steps):
        config = step.configuration or {}
        following = step.next_step_key or (steps[index + 1].step_key if index + 1 < len(steps) else None)
        if step.kind == "STOP":
            continue
        if step.kind == "CONDITION":
            true_step = config.get("true_step")
            true_sequence = config.get("true_sequence")
            false_step = config.get("false_step") or following
            session.add(SequenceEdge(sequence_version_id=version.id, from_step_key=step.step_key, to_step_key=true_step or (None if true_sequence else following), target_sequence_code=true_sequence, branch_key="true", label="Да"))
            session.add(SequenceEdge(sequence_version_id=version.id, from_step_key=step.step_key, to_step_key=false_step, branch_key="false", label="Нет"))
        else:
            target = config.get("step_key") if step.kind == "GOTO" else following
            if target:
                session.add(SequenceEdge(sequence_version_id=version.id, from_step_key=step.step_key, to_step_key=target, branch_key="default", label="Далее"))


def _ensure_routes(session: Session) -> None:
    if not session.scalar(select(BotRoute).where(BotRoute.code == "main_start")):
        session.add(BotRoute(
            code="main_start",
            name="Главный вход в бота",
            trigger_kind="telegram_command",
            trigger_value="/start",
            source_component="telegram.start",
            target_sequence_code=PREPURCHASE_CODE,
            configuration={"pipeline": ["crm.identity.resolve", "attribution.resolve"]},
            priority=10,
            enabled=True,
        ))


def _messages() -> list[dict]:
    rows = [
        ("entry_circle", "Видеокружок: знакомство", "", "video_note", ["вход", "медиа"]),
        ("entry_welcome", "Приветствие и что внутри", "<b>Привет!</b> Здесь будет четырёхдневный интенсив и полезные материалы о питании. Нажмите кнопку, когда будете готовы начать 👇", None, ["вход", "приветствие"]),
        ("day1", "Интенсив — день 1", "<b>День 1 интенсива</b>\n\n[Добавьте основной материал первого дня]", None, ["интенсив", "день-1"]),
        ("day1_mid", "Полезный пост между днями 1 и 2", "[Полезный материал в тему первого дня]", None, ["польза", "промежуточный"]),
        ("day2", "Интенсив — день 2", "<b>День 2 интенсива</b>\n\n[Добавьте основной материал второго дня]", None, ["интенсив", "день-2"]),
        ("day2_mid", "Полезный пост между днями 2 и 3", "[Полезный материал или мягкий переход в Telegram-канал]", None, ["польза", "промежуточный", "подписка-опционально"]),
        ("day3", "Интенсив — день 3", "<b>День 3 интенсива</b>\n\n[Добавьте основной материал третьего дня]", None, ["интенсив", "день-3"]),
        ("day3_mid", "Полезный пост между днями 3 и 4", "[Полезный материал в тему третьего дня]", None, ["польза", "промежуточный"]),
        ("day4", "Интенсив — день 4", "<b>День 4 интенсива</b>\n\n[Добавьте финальный материал интенсива и представление мастер-класса]", None, ["интенсив", "день-4"]),
        ("day4_mid", "Материал после четвёртого дня", "[Полезный материал после интенсива]", None, ["польза", "промежуточный"]),
        ("hard_sale_1", "Мотивационная продажа 1", "[Сильный мотивационный пост с предложением мастер-класса]", None, ["продажа", "жёсткая"]),
        ("hard_sale_2", "Мотивационная продажа 2", "[Второй продающий пост: возражения и следующий шаг]", None, ["продажа", "жёсткая"]),
    ]
    for n in range(13, 31):
        kind = "польза" if n % 2 else "мягкая продажа"
        rows.append((f"nurture_{n:02d}", f"Пост {n}: {kind}", f"[Пост {n}. Добавьте материал: {kind}]", None, [kind, "дожим"] ))
    return [{"code": r[0], "title": r[1], "body": r[2], "media": r[3], "labels": r[4]} for r in rows]


def seed_defaults(session: Session, username: str) -> dict[str, int]:
    bot = session.scalar(select(BotInstance).where(BotInstance.code == "test"))
    if not bot:
        bot = BotInstance(code="test", username=username or "TetrisgfgfgfBot", display_name="Тестовый бот", token_env_name="TELEGRAM_TEST_BOT_TOKEN", is_active=True)
        session.add(bot)

    items: dict[str, ContentItem] = {}
    for row in _messages():
        code = f"tpl_{row['code']}"
        item = session.scalar(select(ContentItem).where(ContentItem.code == code))
        if not item:
            item = ContentItem(code=code, title=row["title"], body_source=row["body"], media_kind=row["media"], labels=row["labels"], status="draft", origin_system="template")
            session.add(item)
            session.flush()
        items[row["code"]] = item

    sequence = session.scalar(select(Sequence).where(Sequence.code == PREPURCHASE_CODE))
    if not sequence:
        sequence = Sequence(code=PREPURCHASE_CODE, name="До покупки мастер-класса — 30 постов", description="Вход, 4 дня интенсива, продажи и полезный дожим", status="published")
        session.add(sequence); session.flush()
        version = SequenceVersion(sequence_id=sequence.id, version_no=1, status="published", published_at=datetime.now(UTC))
        session.add(version); session.flush()
        specs: list[tuple[str, str, str | None, int | None, dict]] = []
        specs += [("m01", "VIDEO_NOTE", "entry_circle", None, {}), ("m02", "MESSAGE", "entry_welcome", None, {"buttons":[{"text":"Начать интенсив","callback_data":"start_intensive"}] }), ("wait_start", "WAIT_BUTTON", None, None, {"callback_data":"start_intensive"}), ("subscription_placeholder", "CONDITION", None, None, {"condition":"subscription_check", "enabled":False, "fail_open_seconds":600})]
        timed = [("day1",0),("day1_mid",43200),("day2",39600),("day2_mid",43200),("day3",43200),("day3_mid",43200),("day4",43200),("day4_mid",43200),("hard_sale_1",43200),("hard_sale_2",86400)]
        timed += [(f"nurture_{n:02d}", 86400 if n <= 20 else 302400) for n in range(13,31)]
        message_no = 3
        for code, delay in timed:
            specs.append((f"delay_{code}", "DELAY", None, delay, {}))
            specs.append((f"paid_check_{code}", "CONDITION", None, None, {"condition":"has_product", "product_code":"masterclass", "product_codes":["MASTERCLASS_BASIC","MASTERCLASS_RECIPES","MASTERCLASS_CONSULT"], "true_sequence":POSTPURCHASE_CODE}))
            specs.append((f"m{message_no:02d}", "MESSAGE", code, None, {})); message_no += 1
        specs.append(("finish", "STOP", None, None, {}))
        for position, (key, kind, content_code, delay, config) in enumerate(specs, 1):
            session.add(SequenceStep(sequence_version_id=version.id, step_key=key, position=position, kind=kind, label=items[content_code].title if content_code else key, content_item_id=items[content_code].id if content_code else None, delay_seconds=delay, configuration=config))

    post = session.scalar(select(Sequence).where(Sequence.code == POSTPURCHASE_CODE))
    if not post:
        post = Sequence(code=POSTPURCHASE_CODE, name="После покупки мастер-класса", description="Отключённая заготовка: рецепты, калории, консультация", status="disabled")
        session.add(post); session.flush()
        version = SequenceVersion(sequence_id=post.id, version_no=1, status="draft")
        session.add(version); session.flush()
        session.add(SequenceStep(sequence_version_id=version.id, step_key="placeholder", position=1, kind="STOP", label="Наполнение будет добавлено позже", configuration={"upsells":["recipes","calories","consultation"]}, enabled=False))
    session.flush()
    for version in session.scalars(select(SequenceVersion)):
        _ensure_edges(session, version)
    _ensure_routes(session)
    session.commit()
    return {"messages": len(_messages()), "sequences": 2}
