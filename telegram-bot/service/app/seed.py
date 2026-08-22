from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import BotInstance, BotRoute, ContentItem, Sequence, SequenceEdge, SequenceStep, SequenceVersion


START_ENTRY_CODE = "start_attribution_entry"
WELCOME_CODE = "welcome_intensive"
PREPURCHASE_CODE = "prepurchase_nurture"
LEGACY_PREPURCHASE_CODE = "prepurchase_masterclass"
POSTPURCHASE_CODE = "postpurchase_masterclass"
WELCOME_CIRCLE_MEDIA_PATH = "/app/media/welcome-intro-circle.mp4"


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
            false_sequence = config.get("false_sequence")
            false_step = config.get("false_step") or following
            session.add(SequenceEdge(sequence_version_id=version.id, from_step_key=step.step_key, to_step_key=true_step or (None if true_sequence else following), target_sequence_code=true_sequence, branch_key="true", label="Да"))
            session.add(SequenceEdge(sequence_version_id=version.id, from_step_key=step.step_key, to_step_key=None if false_sequence else false_step, target_sequence_code=false_sequence, branch_key="false", label="Нет", condition={"allow_cycle": True} if config.get("allow_false_cycle") else {}))
        else:
            target_sequence = config.get("target_sequence") if step.kind == "GOTO" else None
            target = config.get("step_key") if step.kind == "GOTO" else following
            if target or target_sequence:
                session.add(SequenceEdge(
                    sequence_version_id=version.id,
                    from_step_key=step.step_key,
                    to_step_key=None if target_sequence else target,
                    target_sequence_code=target_sequence,
                    branch_key="default",
                    label="Перейти в следующий модуль" if target_sequence else "Далее",
                ))
            if step.kind == "WAIT_BUTTON" and config.get("timeout_step"):
                session.add(SequenceEdge(
                    sequence_version_id=version.id,
                    from_step_key=step.step_key,
                    to_step_key=config["timeout_step"],
                    branch_key="timeout",
                    label="Не нажал за 5 минут — продолжить без подписки",
                ))


def _ensure_routes(session: Session) -> None:
    route = session.scalar(select(BotRoute).where(BotRoute.code == "main_start"))
    if not route:
        session.add(BotRoute(
            code="main_start",
            name="Главный вход в бота",
            trigger_kind="telegram_command",
            trigger_value="/start",
            source_component="telegram.start",
            target_sequence_code=WELCOME_CODE,
            configuration={"pipeline": ["crm.identity.resolve", "attribution.resolve"]},
            priority=10,
            enabled=True,
        ))
    elif route.target_sequence_code in {LEGACY_PREPURCHASE_CODE, START_ENTRY_CODE}:
        route.target_sequence_code = WELCOME_CODE
        route.configuration = {"pipeline": ["crm.identity.resolve", "attribution.resolve"]}


def _messages() -> list[dict]:
    rows = [
        ("entry_circle", "Видеокружок: знакомство", "", "video_note", ["вход", "медиа"]),
        ("entry_welcome", "Приветствие и что внутри", "<b>Привет!</b> Здесь будет четырёхдневный интенсив и полезные материалы о питании. Нажмите кнопку, когда будете готовы начать 👇", None, ["вход", "приветствие"]),
        ("day1", "Интенсив — день 1", "#интенсив_день_1\n\n<b>День 1 интенсива</b>\n\n[Добавьте основной материал первого дня]", None, ["интенсив", "день-1"]),
        ("day1_mid", "Полезный пост между днями 1 и 2", "[Полезный материал в тему первого дня]", None, ["польза", "промежуточный"]),
        ("day2", "Интенсив — день 2", "#интенсив_день_2\n\n<b>День 2 интенсива</b>\n\n[Добавьте основной материал второго дня]", None, ["интенсив", "день-2"]),
        ("day2_mid", "Полезный пост между днями 2 и 3", "[Полезный материал или мягкий переход в Telegram-канал]", None, ["польза", "промежуточный", "подписка-опционально"]),
        ("day3", "Интенсив — день 3", "#интенсив_день_3\n\n<b>День 3 интенсива</b>\n\n[Добавьте основной материал третьего дня]", None, ["интенсив", "день-3"]),
        ("day3_mid", "Полезный пост между днями 3 и 4", "[Полезный материал в тему третьего дня]", None, ["польза", "промежуточный"]),
        ("day4", "Интенсив — день 4", "#интенсив_день_4\n\n<b>День 4 интенсива</b>\n\n[Добавьте финальный материал интенсива и представление мастер-класса]", None, ["интенсив", "день-4"]),
        ("day4_mid", "Оглавление четырёхдневного интенсива", "<b>Оглавление четырёхдневного интенсива</b>\n\nНажмите на нужный хэштег — Telegram покажет сообщения этого дня:\n\n1️⃣ #интенсив_день_1\n2️⃣ #интенсив_день_2\n3️⃣ #интенсив_день_3\n4️⃣ #интенсив_день_4", None, ["интенсив", "оглавление"]),
        ("hard_sale_1", "Мотивационная продажа 1", "[Сильный мотивационный пост с предложением мастер-класса]", None, ["продажа", "жёсткая"]),
        ("hard_sale_2", "Мотивационная продажа 2", "[Второй продающий пост: возражения и следующий шаг]", None, ["продажа", "жёсткая"]),
    ]
    for n in range(13, 31):
        kind = "польза" if n % 2 else "мягкая продажа"
        rows.append((f"nurture_{n:02d}", f"Пост {n}: {kind}", f"[Пост {n}. Добавьте материал: {kind}]", None, [kind, "дожим"] ))
    return [{"code": r[0], "title": r[1], "body": r[2], "media": r[3], "labels": r[4]} for r in rows]


def _start_system_messages() -> list[dict]:
    rows = [
        (
            "start_navigation_pin",
            "Первый Start — навигационный закреп",
            "📌 <b>Навигация!</b>\n\n"
            "1️⃣ Для связи по любым вопросам — @FitnessSergey\n\n"
            "2️⃣ Начните с <a href=\"https://telegram.me/Fitness_Talks_bot?start=527c52b9-6c37-4fd8-95f5-eb213cd4dd14\">бесплатного интенсива «Последнее похудение»</a>\n\n"
            "3️⃣ Если понравится мой подход — присоединяйтесь к Мастер-классу по изменению питания и пищевых привычек: похудение-это-есть.рф\n\n"
            "4️⃣ Не забудьте подписаться на <a href=\"https://telegram.me/Fitness_Talks\">основной Telegram-канал</a> 👇",
            None,
            ["система", "start", "первый вход", "навигация", "закреп"],
        ),
        (
            "start_welcome_offer",
            "Первый Start — приветствие и начало интенсива",
            "<b>Сделайте похудение проще</b> 💅\n\n"
            "✅ Вместо ограничений — баланс\n"
            "✅ Вместо ПП-рецептов — пищевые привычки\n"
            "✅ Вместо уменьшения еды — увеличение насыщения\n"
            "✅ Вместо калорий — дневник питания по фото\n"
            "✅ Вместо погони за цифрами на весах — изменение образа жизни\n\n"
            "<b>Часть #1</b> — План успешного похудения и главные ошибки в самом его начале. Почему похудение начинается не с голода и что изменить в питании, чтобы лучше насыщаться?!\n\n"
            "<b>Часть #2</b> — Как и зачем вести дневник питания БЕЗ калорий, что такое здоровое и нездоровое пищевое поведение, примеры реальных дневников и задания.\n\n"
            "<b>Часть #3</b> — Что такое «Вредная еда» на самом деле? Почему вам не стоит бояться «вредностей» из магазина и что реально вредит вашему здоровью.\n\n"
            "<b>Часть #4</b> — Почему почти все пользуются учётом калорий не так, как надо, а потом жалуются, что без подсчёта набирают всё обратно? Насколько нужны тренировки для похудения и как их посчитать!\n\n"
            "<b>У вас появится чёткое понимание:</b>\n\n"
            "✍️ На какие важные вещи вы раньше не обращали внимания и каким должен быть план похудения сейчас.\n\n"
            "✍️ Каких навыков вам не хватает, чтобы сделать похудение проще и какие первые шаги вы можете сделать уже сегодня!\n\n"
            "Нажмите кнопку «Начать интенсив» — и я пришлю первый день прямо сюда.",
            None,
            ["система", "start", "первый вход", "приветствие", "интенсив"],
        ),
        (
            "start_has_masterclass",
            "Повторный Start — мастер-класс уже куплен",
            "Привет! У вас уже есть мой Мастер-класс по организации питания и здоровых отношений с едой.\n\n"
            "Интенсив вам больше не нужен, потому что в Мастер-классе все эти темы разбираются более подробно и в деталях.\n\n"
            "Если приобрели Мастер-класс недавно, то не отвлекайтесь, двигайтесь по программе Мастер-класса и Калорийного курса после него и да прибудет с вами похудение.\n\n"
            "Если вам нужна консультация после Мастер-класса и по любым другим вопросам пишите мне в личные сообщения → @FitnessSergey",
            None,
            ["система", "start", "мастер-класс", "покупатель"],
        ),
        (
            "start_intensive_waiting",
            "Повторный Start — интенсив ещё идёт",
            "Интенсив уже идёт 👍\n\n"
            "Следующий материал придёт {{next_message_at}} — осталось примерно {{wait_interval}}.\n"
            "А пока можете почитать мой Telegram-канал: {{channel_link}}.",
            None,
            ["система", "start", "интенсив", "ожидание", "шаблон"],
        ),
        (
            "start_intensive_complete",
            "Повторный Start — интенсив завершён",
            "💥 <b>Похудение состоит не из силы воли, а из десятков маленьких навыков.</b>\n\n"
            "Освойте как можно больше навыков, чтобы вам понадобилось как можно меньше силы воли!\n\n"
            "Читайте <a href=\"https://похудение-это-есть.рф/intensiv\">бесплатный интенсив «Последнее похудение»</a>. Теперь все материалы собраны на одной странице на моём сайте!\n\n"
            "А если вам близок мой подход к похудению и вы готовы перейти от теории к практике — читайте программу моего <a href=\"https://похудение-это-есть.рф\">Мастер-класса по изменению питания и пищевых привычек</a>.\n\n"
            "Любые вопросы — просто напишите мне в личные сообщения @FitnessSergey",
            None,
            ["система", "start", "интенсив", "навигация", "продажа"],
        ),
        (
            "start_subscription_reminder",
            "Welcome — подписка не найдена",
            "Пока не вижу подписку на канал. Подпишитесь, пожалуйста: "
            "<a href=\"https://t.me/Fitness_Talks\">Похудение — это есть!</a>\n\n"
            "После подписки нажмите кнопку «Проверить ещё раз». Если подписка "
            "не подтвердится, через пять минут первый день всё равно придёт.",
            None,
            ["система", "welcome", "подписка", "не найдена"],
        ),
    ]
    return [{"code": r[0], "title": r[1], "body": r[2], "media": r[3], "labels": r[4]} for r in rows]


def _postpurchase_messages() -> list[dict]:
    """Editable editorial slots for the disabled post-purchase module.

    The module deliberately stays disabled until CRM events and the production bot
    adapter are connected.  The owner can already prepare every message and media
    asset in the admin without changing code.
    """
    rows = [
        (
            "postpurchase_identity",
            "01 · После привязки — данные клиента",
            "<b>Проверьте ваши данные</b>\n\n"
            "Почта: {{email}}\n"
            "Telegram: @{{telegram_username}}\n"
            "Тариф: {{masterclass_tariff}}\n"
            "Дата покупки: {{purchase_date}}\n\n"
            "Всё верно? Если нет — выберите «Поменять почту». Новую почту нужно будет подтвердить кодом из письма.",
            None,
            ["после покупки", "онбординг", "данные клиента"],
        ),
        (
            "postpurchase_questionnaire",
            "02 · После привязки — анкета для пересылки",
            "<b>Ваша анкета</b>\n\n"
            "{{questionnaire_formatted}}\n\n"
            "Перешлите это сообщение Сергею: @FitnessSergey. Даже если у вас самостоятельный тариф — пожалуйста, отправьте анкету, чтобы начать личный диалог.",
            None,
            ["после покупки", "онбординг", "анкета"],
        ),
        (
            "postpurchase_dqs_support",
            "03 · Через 6 часов после открытия DQS — поддержка",
            "[Добавьте короткое сообщение поддержки после знакомства с DQS. Можно прикрепить видеокружок.]",
            "video_note",
            ["после покупки", "DQS", "поддержка", "медиа"],
        ),
        (
            "postpurchase_recipes_missing",
            "04А · Через 60 минут после рецептов — доступа нет",
            "Вы уже дошли до блока с рецептами. Если хотите продолжить без паузы, откройте актуальные варианты: {{offers_url}}\n\n"
            "Система сама покажет только то, чего у вас ещё нет, и действующую до {{offer_expires_at}} цену.",
            None,
            ["после покупки", "рецепты", "допродажа", "нет доступа"],
        ),
        (
            "postpurchase_recipes_owned",
            "04Б · Через 60 минут после рецептов — доступ есть",
            "[Добавьте короткое сообщение после открытия рецептов и, если остались подходящие продукты, ссылку {{offers_url}}. Рецепты повторно не предлагать.]",
            None,
            ["после покупки", "рецепты", "допродажа", "доступ есть"],
        ),
        (
            "postpurchase_tempo_late",
            "05А · Контроль темпа — отстал больше чем на 2 дня",
            "[Добавьте бережное напоминание вернуться к мастер-классу. Без давления и без повторного запуска уже пройденных этапов.]",
            None,
            ["после покупки", "темп", "напоминание"],
        ),
        (
            "postpurchase_tempo_ok",
            "05Б · Контроль темпа — идёт по графику",
            "[Добавьте похвалу или короткий видеокружок для участника, который движется по графику.]",
            "video_note",
            ["после покупки", "темп", "поддержка", "медиа"],
        ),
        (
            "postpurchase_recipes_second",
            "06 · Вторая часть рецептов — напоминание об оффере",
            "[Добавьте сообщение о второй точке рецептов. Перед отправкой повторно проверить покупки; показать только актуальную ссылку {{offers_url}} или ничего не отправлять.]",
            None,
            ["после покупки", "рецепты", "вторая часть", "допродажа"],
        ),
        (
            "postpurchase_review_consultation",
            "07А · Саморевью — консультация куплена",
            "Вы дошли до итогового саморевью. Заполните его в личном кабинете и нажмите «Отправить Сергею», когда будете готовы к разбору.\n\n"
            "Сначала Сергей разберёт дневник, затем вы обсудите выводы звонком или голосовыми — как вам удобнее.",
            None,
            ["после покупки", "саморевью", "консультация куплена"],
        ),
        (
            "postpurchase_review_no_consultation",
            "07Б · Саморевью — консультации нет",
            "Итоговое саморевью поможет собрать выводы по мастер-классу, даже если вы делаете его только для себя.\n\n"
            "Если захотите персональный разбор дневника и обсуждение выводов — актуальный вариант будет на странице {{offers_url}} до {{offer_expires_at}}.",
            None,
            ["после покупки", "саморевью", "консультация", "допродажа"],
        ),
        (
            "postpurchase_final_offer",
            "08 · Финальная неделя — последнее предложение",
            "[Добавьте финальное сообщение: один комплект недостающих самостоятельных продуктов и не более двух отдельных продуктов. После срока автоматический дожим прекращается.]",
            None,
            ["после покупки", "финальное предложение", "допродажа"],
        ),
    ]
    return [{"code": r[0], "title": r[1], "body": r[2], "media": r[3], "labels": r[4]} for r in rows]


def seed_defaults(session: Session, username: str) -> dict[str, int]:
    bot = session.scalar(select(BotInstance).where(BotInstance.code == "test"))
    if not bot:
        bot = BotInstance(code="test", username=username or "TetrisgfgfgfBot", display_name="Тестовый бот", token_env_name="TELEGRAM_TEST_BOT_TOKEN", is_active=True)
        session.add(bot)

    items: dict[str, ContentItem] = {}
    for row in [*_messages(), *_start_system_messages(), *_postpurchase_messages()]:
        code = f"tpl_{row['code']}"
        item = session.scalar(select(ContentItem).where(ContentItem.code == code))
        if not item:
            item = ContentItem(code=code, title=row["title"], body_source=row["body"], media_kind=row["media"], labels=row["labels"], status="draft", origin_system="template")
            session.add(item)
            session.flush()
        elif row["code"] == "start_welcome_offer" and "похудение-это-есть.рф/intensiv" in (item.body_source or ""):
            # Upgrade only the known seeded preview; later owner edits remain untouched.
            item.body_source = row["body"]
        if row["code"] == "entry_circle" and not item.media_path:
            item.media_kind = "video_note"
            item.media_path = WELCOME_CIRCLE_MEDIA_PATH
        items[row["code"]] = item
    for obsolete_code in ("tpl_subscription_passed", "tpl_subscription_fail_open"):
        obsolete = session.scalar(select(ContentItem).where(ContentItem.code == obsolete_code))
        if obsolete:
            obsolete.status = "archived"

    legacy = session.scalar(select(Sequence).where(Sequence.code == LEGACY_PREPURCHASE_CODE))
    if legacy:
        legacy.status = "archived"

    start_entry = session.scalar(select(Sequence).where(Sequence.code == START_ENTRY_CODE))
    if start_entry:
        start_entry.status = "archived"

    welcome = session.scalar(select(Sequence).where(Sequence.code == WELCOME_CODE))
    if not welcome:
        welcome = Sequence(
            code=WELCOME_CODE,
            name="2. Welcome — запуск и первые четыре дня",
            description="Навигация, кружок, CTA, мягкая подписка, четыре дня интенсива и три промежуточных поста. Продажа — в следующем модуле.",
            status="published",
        )
        session.add(welcome); session.flush()
    else:
        welcome.name = "2. Welcome — запуск и первые четыре дня"
        welcome.description = "Навигация, кружок, CTA, мягкая подписка, четыре дня интенсива и три промежуточных поста. Продажа — в следующем модуле."
        welcome.status = "published"
    current_welcome_version = session.scalar(
        select(SequenceVersion)
        .where(SequenceVersion.sequence_id == welcome.id, SequenceVersion.status == "published")
        .order_by(SequenceVersion.version_no.desc())
    )
    current_welcome_has_layout = bool(current_welcome_version and session.scalar(
        select(SequenceStep.id).where(
            SequenceStep.sequence_version_id == current_welcome_version.id,
            SequenceStep.step_key == "welcome_subscription_retry_wait",
        )
    ))
    if not current_welcome_has_layout:
        last_version = session.scalar(
            select(SequenceVersion.version_no)
            .where(SequenceVersion.sequence_id == welcome.id)
            .order_by(SequenceVersion.version_no.desc())
            .limit(1)
        ) or 0
        version = SequenceVersion(sequence_id=welcome.id, version_no=last_version + 1, status="published", published_at=datetime.now(UTC))
        session.add(version); session.flush()
        specs = [
            ("welcome_navigation", "MESSAGE", "start_navigation_pin", None, {"pin_after_send": True, "buttons": [{"text": "Перейти в канал", "url": "https://t.me/Fitness_Talks"}]}, None),
            ("welcome_circle", "VIDEO_NOTE", "entry_circle", None, {}, None),
            ("welcome_offer", "MESSAGE", "start_welcome_offer", None, {"buttons": [{"text": "Начать интенсив", "callback_data": "start_intensive"}]}, None),
            ("welcome_wait_button", "WAIT_BUTTON", None, None, {"callback_data": "start_intensive"}, None),
            ("welcome_subscription", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "before_day1", "true_step": "welcome_day1", "false_step": "welcome_subscription_failed"}, None),
            ("welcome_subscription_failed", "MESSAGE", "start_subscription_reminder", None, {"buttons": [{"text": "Проверить ещё раз", "callback_data": "check_subscription"}]}, None),
            ("welcome_subscription_retry_wait", "WAIT_BUTTON", None, None, {"callback_data": "check_subscription", "timeout_seconds": 300, "timeout_step": "welcome_day1"}, None),
            ("welcome_subscription_recheck", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_prompt", "true_step": "welcome_day1", "false_step": "welcome_subscription_failed", "allow_false_cycle": True}, None),
            ("welcome_day1", "MESSAGE", "day1", None, {}, None),
            ("welcome_subscription_after_day1", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_day1"}, None),
            ("welcome_delay_mid1", "DELAY", None, 39600, {}, None),
            ("welcome_mid1", "MESSAGE", "day1_mid", None, {}, None),
            ("welcome_subscription_after_mid1", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_mid1"}, None),
            ("welcome_delay_day2", "DELAY", None, 43200, {}, None),
            ("welcome_day2", "MESSAGE", "day2", None, {}, None),
            ("welcome_subscription_after_day2", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_day2"}, None),
            ("welcome_delay_mid2", "DELAY", None, 43200, {}, None),
            ("welcome_mid2", "MESSAGE", "day2_mid", None, {}, None),
            ("welcome_subscription_after_mid2", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_mid2"}, None),
            ("welcome_delay_day3", "DELAY", None, 43200, {}, None),
            ("welcome_day3", "MESSAGE", "day3", None, {}, None),
            ("welcome_subscription_after_day3", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_day3"}, None),
            ("welcome_delay_mid3", "DELAY", None, 43200, {}, None),
            ("welcome_mid3", "MESSAGE", "day3_mid", None, {}, None),
            ("welcome_subscription_after_mid3", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_mid3"}, None),
            ("welcome_delay_day4", "DELAY", None, 43200, {}, None),
            ("welcome_day4", "MESSAGE", "day4", None, {}, None),
            ("welcome_subscription_after_day4", "CONDITION", None, None, {"condition": "subscription_check", "enabled": False, "stage": "after_day4"}, None),
            ("welcome_delay_exit", "DELAY", None, 43200, {}, None),
            ("welcome_to_nurture", "GOTO", None, None, {"target_sequence": PREPURCHASE_CODE}, None),
        ]
        for position, (key, kind, content_code, delay, config, next_key) in enumerate(specs, 1):
            session.add(SequenceStep(sequence_version_id=version.id, step_key=key, position=position, kind=kind, label=items[content_code].title if content_code else key, content_item_id=items[content_code].id if content_code else None, delay_seconds=delay, configuration=config, next_step_key=next_key))

    sequence = session.scalar(select(Sequence).where(Sequence.code == PREPURCHASE_CODE))
    if not sequence:
        sequence = Sequence(
            code=PREPURCHASE_CODE,
            name="3. Основная рассылка до покупки",
            description="Полезные и продающие сообщения после Welcome. Останавливается после покупки мастер-класса.",
            status="published",
        )
        session.add(sequence); session.flush()
    else:
        sequence.name = "3. Основная рассылка до покупки"
        sequence.description = "Полезные и продающие сообщения после Welcome. Останавливается после покупки мастер-класса."
        sequence.status = "published"
    current_nurture_version = session.scalar(
        select(SequenceVersion)
        .where(SequenceVersion.sequence_id == sequence.id, SequenceVersion.status == "published")
        .order_by(SequenceVersion.version_no.desc())
    )
    current_first_delay_step = session.scalar(
        select(SequenceStep).where(
            SequenceStep.sequence_version_id == current_nurture_version.id,
            SequenceStep.step_key == "nurture_delay_hard_sale_1",
        )
    ) if current_nurture_version else None
    current_first_sale = session.scalar(
        select(SequenceStep.id).where(
            SequenceStep.sequence_version_id == current_nurture_version.id,
            SequenceStep.step_key == "nurture_hard_sale_1",
        )
    ) if current_nurture_version else None
    current_nurture_has_layout = bool(current_nurture_version and current_first_sale and not current_first_delay_step)
    if not current_nurture_has_layout:
        last_version = session.scalar(
            select(SequenceVersion.version_no)
            .where(SequenceVersion.sequence_id == sequence.id)
            .order_by(SequenceVersion.version_no.desc())
            .limit(1)
        ) or 0
        version = SequenceVersion(sequence_id=sequence.id, version_no=last_version + 1, status="published", published_at=datetime.now(UTC))
        session.add(version); session.flush()
        nurture_posts = [("hard_sale_1", None), ("hard_sale_2", 86400)]
        nurture_posts += [(f"nurture_{n:02d}", 86400 if n <= 20 else 302400) for n in range(13, 31)]
        specs = []
        for content_code, delay in nurture_posts:
            if delay is not None:
                specs.append((f"nurture_delay_{content_code}", "DELAY", None, delay, {}))
            specs.append((f"nurture_paid_check_{content_code}", "CONDITION", None, None, {"condition": "has_product", "product_code": "masterclass", "product_codes": ["MASTERCLASS_BASIC", "MASTERCLASS_RECIPES", "MASTERCLASS_CONSULT"], "true_sequence": POSTPURCHASE_CODE}))
            specs.append((f"nurture_{content_code}", "MESSAGE", content_code, None, {}))
        specs.append(("nurture_finish", "STOP", None, None, {}))
        for position, (key, kind, content_code, delay, config) in enumerate(specs, 1):
            session.add(SequenceStep(sequence_version_id=version.id, step_key=key, position=position, kind=kind, label=items[content_code].title if content_code else key, content_item_id=items[content_code].id if content_code else None, delay_seconds=delay, configuration=config))

    post = session.scalar(select(Sequence).where(Sequence.code == POSTPURCHASE_CODE))
    if not post:
        post = Sequence(code=POSTPURCHASE_CODE, name="После покупки мастер-класса", description="Редактируемые сообщения онбординга, DQS, рецептов, темпа и саморевью. Отправка отключена до подключения CRM-событий.", status="disabled")
        session.add(post); session.flush()
        version = SequenceVersion(sequence_id=post.id, version_no=1, status="draft")
        session.add(version); session.flush()
        session.add(SequenceStep(sequence_version_id=version.id, step_key="placeholder", position=1, kind="STOP", label="Наполнение будет добавлено позже", configuration={"upsells":["recipes","calories","consultation"]}, enabled=False))
    else:
        post.description = "Редактируемые сообщения онбординга, DQS, рецептов, темпа и саморевью. Отправка отключена до подключения CRM-событий."
        post.status = "disabled"

    existing_postpurchase = session.scalar(
        select(SequenceStep.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id)
        .where(SequenceVersion.sequence_id == post.id, SequenceStep.step_key == "pp_identity")
        .limit(1)
    )
    if not existing_postpurchase:
        last_version = session.scalar(
            select(SequenceVersion.version_no)
            .where(SequenceVersion.sequence_id == post.id)
            .order_by(SequenceVersion.version_no.desc())
            .limit(1)
        ) or 0
        version = SequenceVersion(sequence_id=post.id, version_no=last_version + 1, status="draft")
        session.add(version); session.flush()
        specs = [
            ("pp_identity", "MESSAGE", "postpurchase_identity", None, {"trigger": "messenger_link_confirmed", "state": "editorial_slot"}),
            ("pp_questionnaire", "MESSAGE", "postpurchase_questionnaire", None, {"trigger": "messenger_link_confirmed", "state": "editorial_slot"}),
            ("pp_wait_dqs", "DELAY", None, 21600, {"starts_after": "dqs_opened", "note": "Срок не переносится повторным открытием"}),
            ("pp_dqs_support", "VIDEO_NOTE", "postpurchase_dqs_support", None, {"trigger": "dqs_opened+6h", "state": "editorial_slot"}),
            ("pp_wait_recipes", "DELAY", None, 3600, {"starts_after": "recipes_part_1_opened", "note": "Перед отправкой повторно проверить покупки"}),
            ("pp_recipes_missing", "MESSAGE", "postpurchase_recipes_missing", None, {"trigger": "recipes_part_1_opened+60m", "condition": "recipes_access=false", "state": "editorial_slot"}),
            ("pp_recipes_owned", "MESSAGE", "postpurchase_recipes_owned", None, {"trigger": "recipes_part_1_opened+60m", "condition": "recipes_access=true AND has_missing_products", "state": "editorial_slot"}),
            ("pp_tempo_late", "MESSAGE", "postpurchase_tempo_late", None, {"trigger": "progress_checkpoint", "condition": "delay_days>2", "state": "editorial_slot"}),
            ("pp_tempo_ok", "VIDEO_NOTE", "postpurchase_tempo_ok", None, {"trigger": "progress_checkpoint", "condition": "delay_days<=2", "state": "editorial_slot"}),
            ("pp_recipes_second", "MESSAGE", "postpurchase_recipes_second", None, {"trigger": "recipes_part_2_opened", "condition": "has_missing_products", "state": "editorial_slot"}),
            ("pp_review_consultation", "MESSAGE", "postpurchase_review_consultation", None, {"trigger": "closing_review_opened", "condition": "consultation_access=true", "state": "editorial_slot"}),
            ("pp_review_no_consultation", "MESSAGE", "postpurchase_review_no_consultation", None, {"trigger": "closing_review_opened", "condition": "consultation_access=false", "state": "editorial_slot"}),
            ("pp_final_offer", "MESSAGE", "postpurchase_final_offer", None, {"trigger": "closing_offer_expired", "condition": "has_missing_products", "state": "editorial_slot"}),
            ("pp_finish", "STOP", None, None, {"reason": "postpurchase_automatic_messages_complete"}),
        ]
        for position, (key, kind, content_code, delay, config) in enumerate(specs, 1):
            session.add(SequenceStep(
                sequence_version_id=version.id,
                step_key=key,
                position=position,
                kind=kind,
                label=items[content_code].title if content_code else key,
                content_item_id=items[content_code].id if content_code else None,
                delay_seconds=delay,
                configuration=config,
            ))
    session.flush()
    for version in session.scalars(select(SequenceVersion)):
        _ensure_edges(session, version)
    _ensure_routes(session)
    session.commit()
    return {"messages": len(_messages()), "sequences": 3}
