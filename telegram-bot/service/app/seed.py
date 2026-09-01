from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import BotInstance, BotRoute, ContentItem, Sequence, SequenceEdge, SequenceStep, SequenceVersion
from app.masterclass_triggers import TRIGGERS, editorial_help
from app.maintenance import DEFAULT_MAINTENANCE_MESSAGE
from app.content_formatting import is_placeholder_text


START_ENTRY_CODE = "start_attribution_entry"
WELCOME_CODE = "welcome_intensive"
PREPURCHASE_CODE = "prepurchase_nurture"
LEGACY_PREPURCHASE_CODE = "prepurchase_masterclass"
POSTPURCHASE_CODE = "postpurchase_masterclass"
POSTMASTERCLASS_CODE = "postmasterclass_nurture"
WELCOME_CIRCLE_MEDIA_PATH = "/app/media/welcome-intro-circle.mp4"


POSTPURCHASE_TRIGGER_BY_CONTENT = {item["content_code"].removeprefix("tpl_"): item for item in TRIGGERS}
OWNER_APPROVED_SEED_CODES = {
    "maintenance_notice",
    "start_navigation_pin",
    "entry_circle",
    "start_welcome_offer",
    "start_subscription_reminder",
    "start_subscription_retry_reminder",
    "start_has_masterclass",
    "start_intensive_waiting",
    "start_intensive_complete",
}


def _editorial_metadata(code: str, title: str, body: str, media: str | None) -> tuple[str, str, str]:
    specialized = {
        "maintenance_notice": (
            "Сообщить внешнему посетителю, что бот временно закрыт, и сохранить его для последующего контакта.",
            "Контекст: человек нажал Start во время ремонта после фиксации первого источника.\n\n"
            "Главная задача: спокойно объяснить временную недоступность и дать рабочий контакт Сергея.\n\n"
            "Призыв: дождаться возобновления или написать @FitnessSergey.\n\n"
            "Ограничения: не обещать точную дату, если она не задана; не запускать Welcome.",
        ),
        "start_navigation_pin": (
            "Дать новому пользователю постоянную общую навигацию и закрепить её в чате.",
            "Контекст: первое посещение определено, мастер-класс не куплен, Welcome ещё не запускался.\n\n"
            "Главная задача: показать контакт Сергея, интенсив, мастер-класс и основной канал.\n\n"
            "Призыв: кнопка ведёт в канал.\n\nОграничения: сообщение должно оставаться полезным после закрепления и не заменяет превью интенсива.",
        ),
        "entry_circle": (
            "Лично познакомить нового пользователя с Сергеем перед описанием интенсива.",
            "Контекст: навигационный пост уже отправлен и закреплён.\n\n"
            "Главная задача: отправить утверждённый видеокружок без отдельного текста.\n\n"
            "Ограничения: не добавлять подпись автоматически; следующим приходит превью интенсива.",
        ),
        "start_welcome_offer": (
            "Объяснить ценность четырёхдневного интенсива и довести до кнопки его запуска.",
            "Контекст: новый пользователь получил закреп и видеокружок.\n\n"
            "Главная задача: коротко показать подход и содержание четырёх дней.\n\n"
            "Призыв: одна кнопка «Начать интенсив».\n\n"
            "Ограничения: не давать материалы дней в этом превью и не менять callback кнопки.",
        ),
        "start_subscription_reminder": (
            "Попросить подписаться на основной канал перед первым днём.",
            "Контекст: пользователь нажал кнопку начала, но проверка не увидела подписку.\n\n"
            "Главная задача: дать ссылку на канал и объяснить повторную проверку.\n\n"
            "Призыв: подписаться и нажать «Проверить ещё раз».\n\n"
            "Ограничения: не объяснять пользователю внутренний таймер, fail-open и обходные ветки.",
        ),
        "start_subscription_retry_reminder": (
            "Мягко напомнить о подписке после неуспешной повторной проверки.",
            "Контекст: пользователь уже увидел первую просьбу, нажал «Проверить ещё раз», но Telegram по-прежнему не видит подписку.\n\n"
            "Главная задача: коротко показать, что действие ещё не выполнено, дать ссылку на канал и вернуть к той же кнопке.\n\n"
            "Призыв: подписаться и нажать «Проверить ещё раз».\n\n"
            "Ограничения: не стыдить человека, не объяснять внутренний таймер, fail-open и обходные ветки.",
        ),
        "start_has_masterclass": (
            "На повторном Start направить покупателя в уже приобретённый мастер-класс вместо интенсивa.",
            "Контекст: человек знаком с ботом, а CRM подтверждает доступ к мастер-классу.\n\n"
            "Главная задача: объяснить, что интенсив ему не нужен, и напомнить путь по программе.\n\n"
            "Призыв: при вопросах написать @FitnessSergey.\n\nОграничения: не запускать Welcome и не продавать мастер-класс повторно.",
        ),
        "start_intensive_waiting": (
            "На повторном Start объяснить, что интенсив уже идёт и когда придёт следующий материал.",
            "Контекст: мастер-класс не куплен, День 4 ещё не отправлен, активный Welcome существует.\n\n"
            "Главная задача: не ускорять расписание и показать {{next_message_at}} и {{wait_interval}}.\n\n"
            "Призыв: читать уже полученные материалы или канал.\n\nОграничения: повторный Start не двигает run на следующий шаг.",
        ),
        "start_intensive_complete": (
            "Вернуть знакомого пользователя к четырём завершённым частям интенсива.",
            "Контекст: мастер-класс не куплен, все четыре дня уже отправлены.\n\n"
            "Главная задача: дать краткое оглавление и четыре устойчивые ссылки на материалы.\n\n"
            "Призыв: при готовности перейти к мастер-классу или написать Сергею.\n\n"
            "Ограничения: не перезапускать Welcome.",
        ),
    }
    if code in specialized:
        purpose, brief = specialized[code]
    elif code.startswith("day") and code[-1:].isdigit():
        day = code[-1]
        purpose = f"Выдать основной авторский материал Дня {day} четырёхдневного интенсива."
        brief = (
            f"Контекст: пользователь дошёл по расписанию до Дня {day}.\n\n"
            f"Главная задача: раскрыть утверждённую тему Дня {day} как самостоятельный полезный материал.\n\n"
            "Что обязательно раскрыть: брать факты только из утверждённого материала соответствующего дня; сохранить хэштег дня.\n\n"
            "Призыв: только тот, который предусмотрен материалом дня.\n\n"
            "Ограничения: не придумывать программу и не продавать вместо обучения."
        )
    elif code.endswith("_mid"):
        purpose = "Поддержать интерес между днями интенсива самостоятельным полезным постом."
        brief = (
            "Самостоятельный полезный пост между двумя днями интенсива. Дать одну законченную мысль, "
            "которую можно применить без покупки. Продажа не обязательна; допустим один мягкий призыв "
            "в конце. Не повторять соседние дни и не обещать досрочную отправку следующего материала."
        )
    elif code.startswith("hard_sale_"):
        purpose = "Сделать прямое предложение мастер-класса после полезной части рассылки."
        brief = (
            "Продажный пост основной рассылки. Выбрать одну потребность или возражение, связать её с "
            "фактической программой мастер-класса и дать один понятный призыв в конце. Не обещать "
            "гарантированный результат и не придумывать цену, срок или состав продукта."
        )
    elif code.startswith("nurture_"):
        number = int(code.rsplit("_", 1)[1])
        if number % 2:
            purpose = "Дать самостоятельную полезную мысль в основной рассылке до покупки."
            brief = (
                "Самостоятельный полезный пост основной рассылки. Дать одну законченную мысль, которую "
                "можно применить без покупки. Продажа не обязательна; допустим один мягкий призыв в конце. "
                "Не повторять соседние сообщения."
            )
        else:
            purpose = "Дать пользу и мягко связать её с возможностью пройти мастер-класс."
            brief = (
                "Пост основной рассылки с одной полезной мыслью и естественным переходом к мастер-классу. "
                "Один призыв в конце. Не обещать гарантированный результат и не придумывать условия продукта."
            )
    elif code in POSTPURCHASE_TRIGGER_BY_CONTENT:
        trigger = POSTPURCHASE_TRIGGER_BY_CONTENT[code]
        purpose = trigger["purpose"]
        brief = (
            f"Контекст/триггер: {trigger['trigger']}.\n\nУсловие: {trigger['condition']}.\n\n"
            f"Получатель: {trigger['recipient']}.\n\nГлавная задача: {trigger['purpose']}\n\n"
            "Что обязательно раскрыть: использовать только переданные шаблонные переменные и актуальные продуктовые факты.\n\n"
            "Ограничения: не менять условие отправки текстом и не предлагать уже купленный продукт."
        )
    else:
        purpose = f"Содержимое служебного слота «{title}» в предусмотренной точке Telegram-сценария."
        brief = (
            "Контекст и получатель определяются единственным использующим этот слот графом. "
            "Сформулировать одно сообщение, выполняющее название слота; не добавлять новые условия, "
            "сущности или переходы текстом."
        )
    media_only = media == "video_note" and not (body or "").strip()
    editorial_status = (
        "approved"
        if code in OWNER_APPROVED_SEED_CODES or (code in POSTPURCHASE_TRIGGER_BY_CONTENT and not is_placeholder_text(body))
        else ("draft" if media_only or not is_placeholder_text(body) else "placeholder")
    )
    return purpose, brief, editorial_status


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
        ("day1", "Интенсив — день 1", "#интенсив_день_1\n\n<b>День 1 интенсива</b>\n\nЗдесь будет основной авторский материал первого дня.", None, ["интенсив", "день-1"]),
        ("day1_mid", "Полезный пост между днями 1 и 2", "Небольшой полезный материал между первым и вторым днём интенсива.", None, ["польза", "промежуточный"]),
        ("day2", "Интенсив — день 2", "#интенсив_день_2\n\n<b>День 2 интенсива</b>\n\nЗдесь будет основной авторский материал второго дня.", None, ["интенсив", "день-2"]),
        ("day2_mid", "Полезный пост между днями 2 и 3", "Небольшой полезный материал и мягкий переход к следующему дню.", None, ["польза", "промежуточный", "подписка-опционально"]),
        ("day3", "Интенсив — день 3", "#интенсив_день_3\n\n<b>День 3 интенсива</b>\n\nЗдесь будет основной авторский материал третьего дня.", None, ["интенсив", "день-3"]),
        ("day3_mid", "Полезный пост между днями 3 и 4", "Небольшой полезный материал между третьим и четвёртым днём.", None, ["польза", "промежуточный"]),
        ("day4", "Интенсив — день 4", "#интенсив_день_4\n\n<b>День 4 интенсива</b>\n\nЗдесь будет финальный авторский материал интенсива.", None, ["интенсив", "день-4"]),
        ("day4_mid", "Оглавление четырёхдневного интенсива", "<b>Оглавление четырёхдневного интенсива</b>\n\nНажмите на нужный хэштег — Telegram покажет сообщения этого дня:\n\n1️⃣ #интенсив_день_1\n2️⃣ #интенсив_день_2\n3️⃣ #интенсив_день_3\n4️⃣ #интенсив_день_4", None, ["интенсив", "оглавление"]),
        ("hard_sale_1", "Мотивационная продажа 1", "Здесь будет первый авторский пост основной рассылки с предложением мастер-класса.", None, ["продажа", "жёсткая"]),
        ("hard_sale_2", "Мотивационная продажа 2", "Здесь будет второй авторский пост: работа с возражениями и следующий шаг.", None, ["продажа", "жёсткая"]),
    ]
    for n in range(13, 31):
        kind = "польза" if n % 2 else "мягкая продажа"
        rows.append((f"nurture_{n:02d}", f"Пост {n}: {kind}", f"Здесь будет авторский пост {n}: {kind}.", None, [kind, "дожим"] ))
    return [{"code": r[0], "title": r[1], "body": r[2], "media": r[3], "labels": r[4]} for r in rows]


def _add_missing_trigger_slots(rows: list[dict], triggers: list[dict] = TRIGGERS) -> list[dict]:
    """Every text-producing Telegram trigger owns an editable writer slot by default."""
    result = list(rows)
    existing = {row["code"] for row in result}
    for trigger in triggers:
        code = trigger["content_code"].removeprefix("tpl_")
        if code in existing:
            continue
        result.append({
            "code": code,
            "title": trigger["title"],
            "body": "",
            "media": None,
            "labels": ["автослот", "требуется текст", "после покупки"],
        })
        existing.add(code)
    return result


def _start_system_messages() -> list[dict]:
    rows = [
        (
            "maintenance_notice",
            "Режим ремонта — сообщение посетителю",
            DEFAULT_MAINTENANCE_MESSAGE,
            None,
            ["система", "ремонт", "лист ожидания"],
        ),
        (
            "start_navigation_pin",
            "Первый Start — навигационный закреп",
            "📌 <b>Навигация!</b>\n\n"
            "1️⃣ Для связи по любым вопросам — @FitnessSergey\n\n"
            "2️⃣ Начните с <a href=\"https://telegram.me/Fitness_Talks_bot?start=527c52b9-6c37-4fd8-95f5-eb213cd4dd14\">бесплатного интенсива «Последнее похудение»</a>\n\n"
            "3️⃣ Если понравится мой подход — присоединяйтесь к <a href=\"https://похудение-это-есть.рф\">Мастер-классу по изменению питания и пищевых привычек</a>\n\n"
            "4️⃣ Не забудьте подписаться на <a href=\"https://t.me/Fitness_Talks\">основной Telegram-канал</a> 👇",
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
            "Посты интенсива приходят вам по расписанию 👍\n\n"
            "Выше в этом чате уже находятся закреплённая навигация, видеокружок, описание интенсива и все открытые на данный момент материалы.\n\n"
            "Следующий материал придёт {{next_message_at}} — осталось примерно {{wait_interval}}.\n"
            "Пока ждёте, можете почитать мой Telegram-канал: {{channel_link}}.",
            None,
            ["система", "start", "интенсив", "ожидание", "шаблон"],
        ),
        (
            "start_intensive_complete",
            "Повторный Start — оглавление завершённого интенсива",
            "<b>Сделайте похудение проще</b> 💅\n\n"
            "Вы уже получили все четыре части интенсива. Теперь к ним можно возвращаться в удобном порядке:\n\n"
            "1️⃣ <a href=\"https://похудение-это-есть.рф/intensiv#rec2044592871\">Часть #1</a> — план успешного похудения и главные ошибки в самом начале.\n\n"
            "2️⃣ <a href=\"https://похудение-это-есть.рф/intensiv#rec2044598581\">Часть #2</a> — дневник питания без калорий и здоровое пищевое поведение.\n\n"
            "3️⃣ <a href=\"https://похудение-это-есть.рф/intensiv#rec2044741621\">Часть #3</a> — что такое «вредная еда» на самом деле.\n\n"
            "4️⃣ <a href=\"https://похудение-это-есть.рф/intensiv#rec2044744291\">Часть #4</a> — калории, тренировки и сохранение результата.\n\n"
            "А если вам близок мой подход к похудению и вы готовы перейти от теории к практике — читайте программу моего <a href=\"https://похудение-это-есть.рф\">Мастер-класса по изменению питания и пищевых привычек</a>.\n\n"
            "Любые вопросы — просто напишите мне в личные сообщения @FitnessSergey",
            None,
            ["система", "start", "интенсив", "навигация", "продажа"],
        ),
        (
            "start_subscription_reminder",
            "Welcome — подписка не найдена",
            "Чтобы вам начали приходить материалы бесплатного интенсива, пожалуйста, "
            "сначала подпишитесь на мой Telegram-канал: "
            "<a href=\"https://t.me/Fitness_Talks\">Похудение — это есть!</a>\n\n"
            "После подписки нажмите кнопку «Проверить ещё раз».",
            None,
            ["система", "welcome", "подписка", "не найдена"],
        ),
        (
            "start_subscription_retry_reminder",
            "Welcome — повторно не подписан",
            "Кажется, вы ещё не подписались.\n\n"
            "Сначала подпишитесь на <a href=\"https://t.me/Fitness_Talks\">канал</a>, "
            "и я сразу же отправлю первый день интенсива.",
            None,
            ["система", "welcome", "подписка", "повторная проверка"],
        ),
        (
            "web_login_code",
            "Код входа на сайт через Telegram",
            "Telegram подтверждён. Введите на открытой странице код: <b>{{login_code}}</b>\n\nКод действует 15 минут. Никому его не пересылайте.",
            None,
            ["система", "вход", "сайт", "Telegram"],
        ),
        ("web_login_invalid", "Ошибка входа — ссылка недействительна", "Ссылка входа недействительна или устарела. Вернитесь на сайт и создайте новую.", None, ["система", "вход", "ошибка"]),
        ("web_login_used", "Ошибка входа — ссылка использована", "Эта ссылка уже использована. Вернитесь на сайт и создайте новую.", None, ["система", "вход", "ошибка"]),
        ("web_login_identity_failed", "Ошибка входа — аккаунт не определён", "Не удалось определить Telegram-аккаунт. Вернитесь на сайт и создайте новую ссылку.", None, ["система", "вход", "ошибка"]),
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
            "01 · После привязки — данные и анкета участника",
            "👉 <b>Данные участника мастер-класса</b>\n\n"
            "<b>Почта:</b> {{email}}\n"
            "<b>Telegram:</b> @{{telegram_username}}\n"
            "<b>Тариф:</b> {{masterclass_tariff}}\n"
            "<b>Дата покупки:</b> {{purchase_date}}\n"
            "<b>Личный кабинет:</b> <a href=\"{{account_url}}\">открыть ЛК</a>\n\n"
            "👉 <b>Анкета участника</b>\n\n{{questionnaire_formatted}}",
            None,
            ["после покупки", "онбординг", "данные клиента"],
        ),
        (
            "postpurchase_questionnaire",
            "02 · После привязки — что сделать дальше",
            "Telegram привязан.\n\n"
            "Если в почте, тарифе или других данных выше есть ошибка, напишите мне — я всё поправлю.\n\n"
            "👆 Перешлите мне в личные сообщения сообщение выше с вашими данными и анкетой. Если Telegram разделил длинную анкету на несколько сообщений, перешлите все части.",
            None,
            ["после покупки", "онбординг", "анкета"],
        ),
        (
            "postpurchase_current_diet",
            "03 · День 2 — ответы по продуктовым категориям",
            "👉 <b>А какая у вас сейчас «диета»?</b>\n\n"
            "{{current_diet_formatted}}\n\n"
            "Сохраните это сообщение в своём дневнике. К нему можно будет вернуться позже и сравнить, что изменилось.",
            None,
            ["после покупки", "день-2", "опросник", "продуктовые категории"],
        ),
        (
            "postpurchase_closing_review_copy",
            "06 · Копия итогового саморевью",
            "👉 <b>Итоговое саморевью</b>\n\n"
            "{{closing_review_formatted}}\n\n"
            "Это копия вашего итогового саморевью. Можете оставить её себе. Если хотите обсудить ответы или получить консультацию, перешлите это сообщение мне в личку и напишите, как вам было бы удобнее провести разбор.\n\n"
            "<a href=\"{{consultation_description_url}}\">Как проходит консультация</a>",
            None,
            ["после покупки", "саморевью", "копия участнику", "консультация"],
        ),
        (
            "postpurchase_dqs_app_link",
            "DQS — ссылка на приложение",
            "Ваша система оценки качества питания — <a href=\"https://похудение-это-есть.рф/dqs\">открыть приложение</a>.",
            None,
            ["после покупки", "DQS", "ссылка на приложение"],
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
            "Рецепты у вас уже открыты — повторно их не предлагаем. Если хотите посмотреть остальные доступные дополнения, они собраны здесь: {{offers_url}}",
            None,
            ["после покупки", "рецепты", "допродажа", "доступ есть"],
        ),
        (
            "postpurchase_day_unopened",
            "03 · Новый день не открыт к 18:00",
            "Привет! Вам уже доступен день {{day_number}} — «{{day_title}}». Он открылся сегодня в 06:00 по вашему времени, но вы его ещё не открыли. Просто напоминаю: <a href=\"{{day_url}}\">перейти к дню</a>.",
            None,
            ["после покупки", "курс", "день", "18:00"],
        ),
        (
            "postpurchase_tempo_late",
            "04 · Контроль темпа — три дня без активности",
            "Вы давно не заходили в Мастер-класс. Сейчас у вас открыт день {{day_number}} — «{{day_title}}». День-два пропустить — нормально, но не откладывайте надолго, чтобы не выпадать из ритма. <a href=\"{{day_url}}\">Продолжить Мастер-класс</a>.",
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
            "Это последнее автоматическое напоминание о дополнениях к Мастер-классу. Страница сама покажет только то, чего у вас ещё нет: {{offers_url}}. После окончания предложения дополнительных сообщений не будет.",
            None,
            ["после покупки", "финальное предложение", "допродажа"],
        ),
        (
            "postpurchase_review_week_1",
            "09 · После саморевью — день 2",
            "Вы начали итоговое саморевью. Здесь будет первый авторский пост недели закрепления результатов.",
            None,
            ["после покупки", "саморевью", "день-2"],
        ),
        (
            "postpurchase_review_week_2",
            "10 · После саморевью — день 4",
            "Прошло несколько дней после саморевью. Здесь будет второй авторский пост недели закрепления результатов.",
            None,
            ["после покупки", "саморевью", "день-4"],
        ),
        (
            "postpurchase_review_week_3",
            "11 · После саморевью — день 7",
            "Неделя после саморевью завершена. Здесь будет итоговый авторский пост и переход к дальнейшему сопровождению.",
            None,
            ["после покупки", "саморевью", "день-7"],
        ),
    ]
    return _add_missing_trigger_slots(
        [{"code": r[0], "title": r[1], "body": r[2], "media": r[3], "labels": r[4]} for r in rows]
    )


def seed_defaults(
    session: Session,
    username: str,
    *,
    enable_subscription_checks: bool = False,
) -> dict[str, int]:
    resolved_username = (username or "TetrisgfgfgfBot").lstrip("@")
    is_main_bot = resolved_username.casefold() == "fitness_talks_bot"
    bot = session.scalar(select(BotInstance).where(BotInstance.code == "test"))
    if not bot:
        bot = BotInstance(
            code="test",
            username=resolved_username,
            display_name="Основной бот" if is_main_bot else "Тестовый бот",
            token_env_name="TELEGRAM_TEST_BOT_TOKEN",
            is_production=is_main_bot,
            is_active=True,
        )
        session.add(bot)
    elif username:
        bot.username = resolved_username
        bot.is_production = is_main_bot
        bot.display_name = "Основной бот" if bot.is_production else "Тестовый бот"

    items: dict[str, ContentItem] = {}
    postpurchase_rows = _postpurchase_messages()
    published_codes = {row["code"] for row in postpurchase_rows} | {"maintenance_notice", "web_login_code", "web_login_invalid", "web_login_used", "web_login_identity_failed"}
    for row in [*_messages(), *_start_system_messages(), *postpurchase_rows]:
        code = f"tpl_{row['code']}"
        purpose, writer_brief, editorial_status = _editorial_metadata(
            row["code"], row["title"], row["body"], row["media"]
        )
        item = session.scalar(select(ContentItem).where(ContentItem.code == code))
        authoring_before = (
            (item.body_source, item.purpose, item.writer_brief, item.source_format)
            if item else None
        )
        if not item:
            item = ContentItem(
                code=code,
                title=row["title"],
                body_source=row["body"],
                media_kind=row["media"],
                labels=row["labels"],
                status="published" if row["code"] in published_codes or editorial_status == "approved" else "draft",
                purpose=purpose,
                writer_brief=writer_brief,
                editorial_status=editorial_status,
                origin_system="template",
            )
            session.add(item)
            session.flush()
        elif row["code"] in published_codes:
            # System and test-only messages must remain sendable. Replace known
            # seed placeholders, but never overwrite text edited by the owner.
            item.status = "published"
            known_old_postpurchase = (
                row["code"] == "postpurchase_identity" and "Проверьте ваши данные" in (item.body_source or "")
            ) or (
                row["code"] == "postpurchase_questionnaire" and "Ваша анкета" in (item.body_source or "")
            ) or (
                row["code"] == "postpurchase_tempo_late" and "Вы остановились в Мастер-классе" in (item.body_source or "")
            )
            if (item.body_source or "").lstrip().startswith("[Добавьте ") or "Поменять почту" in (item.body_source or "") or known_old_postpurchase:
                item.body_source = row["body"]
        elif (item.body_source or "").lstrip().startswith((
            "[Добавьте ", "[Полезный ", "[Сильный ", "[Второй ", "[Пост ",
        )):
            # Replace only the exact families used by old seed placeholders;
            # an owner-authored post may legitimately start with an HTML link.
            item.body_source = row["body"]
        elif row["code"] == "start_welcome_offer" and "похудение-это-есть.рф/intensiv" in (item.body_source or ""):
            # Upgrade only the known seeded preview; later owner edits remain untouched.
            item.body_source = row["body"]
        elif row["code"] == "start_navigation_pin" and "Мастер-классу по изменению питания и пищевых привычек: похудение-это-есть.рф" in (item.body_source or ""):
            item.body_source = row["body"]
        elif row["code"] == "start_intensive_waiting" and (item.body_source or "").startswith("Интенсив уже идёт"):
            item.body_source = row["body"]
        elif row["code"] == "start_intensive_complete" and (item.body_source or "").startswith("💥 <b>Похудение состоит"):
            item.body_source = row["body"]
        elif row["code"] == "start_subscription_reminder" and (item.body_source or "").startswith("Пока не вижу подписку"):
            item.body_source = row["body"]
        elif row["code"] == "start_subscription_retry_reminder" and (item.body_source or "").startswith("¯\\*(ツ)*/¯"):
            item.body_source = row["body"]
        if row["code"] in {"start_navigation_pin", "start_welcome_offer", "start_intensive_waiting", "start_intensive_complete"}:
            item.title = row["title"]
        if row["code"] == "entry_circle" and not item.media_path:
            item.media_kind = "video_note"
            item.media_path = WELCOME_CIRCLE_MEDIA_PATH
        if not (item.purpose or "").strip():
            item.purpose = purpose
        if not (item.writer_brief or "").strip():
            item.writer_brief = writer_brief
        if (item.editorial_status or "") in {"", "needs_writing"}:
            item.editorial_status = editorial_status
        if item.editorial_status == "approved":
            item.status = "published"
        if authoring_before is not None and authoring_before != (
            item.body_source,
            item.purpose,
            item.writer_brief,
            item.source_format,
        ):
            item.content_version += 1
        items[row["code"]] = item
    for obsolete_code in (
        "tpl_subscription_passed",
        "tpl_subscription_fail_open",
        "tpl_postpurchase_dqs_support",
        "tpl_postpurchase_tempo_ok",
        "tpl_postpurchase_recipes_second",
        "tpl_postpurchase_review_consultation",
        "tpl_postpurchase_review_no_consultation",
        "tpl_postpurchase_review_week_1",
        "tpl_postpurchase_review_week_2",
        "tpl_postpurchase_review_week_3",
    ):
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
    current_welcome_has_layout = bool(current_welcome_version) and all(
        session.scalar(
            select(SequenceStep.id).where(
                SequenceStep.sequence_version_id == current_welcome_version.id,
                SequenceStep.step_key == step_key,
            )
        )
        for step_key in (
            "welcome_subscription_retry_wait",
            "welcome_subscription_retry_failed",
            "welcome_subscription_retry_wait_again",
        )
    )
    current_subscription_step = session.scalar(
        select(SequenceStep).where(
            SequenceStep.sequence_version_id == current_welcome_version.id,
            SequenceStep.step_key == "welcome_subscription",
        )
    ) if current_welcome_version else None
    current_welcome_has_live_subscription = bool(
        current_subscription_step
        and (current_subscription_step.configuration or {}).get("enabled")
    )
    if not current_welcome_has_layout or (
        enable_subscription_checks and not current_welcome_has_live_subscription
    ):
        last_version = session.scalar(
            select(SequenceVersion.version_no)
            .where(SequenceVersion.sequence_id == welcome.id)
            .order_by(SequenceVersion.version_no.desc())
            .limit(1)
        ) or 0
        if current_welcome_version:
            current_welcome_version.status = "archived"
        version = SequenceVersion(sequence_id=welcome.id, version_no=last_version + 1, status="published", published_at=datetime.now(UTC))
        session.add(version); session.flush()
        specs = [
            ("welcome_navigation", "MESSAGE", "start_navigation_pin", None, {"pin_after_send": True, "buttons": [{"text": "Перейти в канал", "url": "https://t.me/Fitness_Talks"}]}, None),
            ("welcome_circle", "VIDEO_NOTE", "entry_circle", None, {}, None),
            ("welcome_offer", "MESSAGE", "start_welcome_offer", None, {"buttons": [{"text": "Начать интенсив", "callback_data": "start_intensive"}]}, None),
            ("welcome_wait_button", "WAIT_BUTTON", None, None, {"callback_data": "start_intensive"}, None),
            ("welcome_subscription", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "before_day1", "true_step": "welcome_day1", "false_step": "welcome_subscription_failed"}, None),
            ("welcome_subscription_failed", "MESSAGE", "start_subscription_reminder", None, {"buttons": [{"text": "Проверить ещё раз", "callback_data": "check_subscription"}]}, None),
            ("welcome_subscription_retry_wait", "WAIT_BUTTON", None, None, {"callback_data": "check_subscription", "timeout_seconds": 300, "timeout_step": "welcome_day1"}, None),
            ("welcome_subscription_recheck", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_prompt", "true_step": "welcome_day1", "false_step": "welcome_subscription_retry_failed", "allow_false_cycle": True}, None),
            ("welcome_subscription_retry_failed", "MESSAGE", "start_subscription_retry_reminder", None, {"buttons": [{"text": "Проверить ещё раз", "callback_data": "check_subscription"}]}, None),
            ("welcome_subscription_retry_wait_again", "WAIT_BUTTON", None, None, {"callback_data": "check_subscription", "timeout_seconds": 300, "timeout_step": "welcome_day1"}, "welcome_subscription_recheck"),
            ("welcome_day1", "MESSAGE", "day1", None, {}, None),
            ("welcome_subscription_after_day1", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_day1"}, None),
            ("welcome_delay_mid1", "DELAY", None, 39600, {}, None),
            ("welcome_mid1", "MESSAGE", "day1_mid", None, {}, None),
            ("welcome_subscription_after_mid1", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_mid1"}, None),
            ("welcome_delay_day2", "DELAY", None, 43200, {}, None),
            ("welcome_day2", "MESSAGE", "day2", None, {}, None),
            ("welcome_subscription_after_day2", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_day2"}, None),
            ("welcome_delay_mid2", "DELAY", None, 43200, {}, None),
            ("welcome_mid2", "MESSAGE", "day2_mid", None, {}, None),
            ("welcome_subscription_after_mid2", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_mid2"}, None),
            ("welcome_delay_day3", "DELAY", None, 43200, {}, None),
            ("welcome_day3", "MESSAGE", "day3", None, {}, None),
            ("welcome_subscription_after_day3", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_day3"}, None),
            ("welcome_delay_mid3", "DELAY", None, 43200, {}, None),
            ("welcome_mid3", "MESSAGE", "day3_mid", None, {}, None),
            ("welcome_subscription_after_mid3", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_mid3"}, None),
            ("welcome_delay_day4", "DELAY", None, 43200, {}, None),
            ("welcome_day4", "MESSAGE", "day4", None, {}, None),
            ("welcome_subscription_after_day4", "CONDITION", None, None, {"condition": "subscription_check", "enabled": enable_subscription_checks, "stage": "after_day4"}, None),
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
    current_day25_finish = session.scalar(
        select(SequenceStep.id).where(
            SequenceStep.sequence_version_id == current_nurture_version.id,
            SequenceStep.step_key == "nurture_finish_day25",
        )
    ) if current_nurture_version else None
    current_purchase_check = session.scalar(
        select(SequenceStep.id).where(
            SequenceStep.sequence_version_id == current_nurture_version.id,
            SequenceStep.step_key.like("nurture_paid_check_%"),
        ).limit(1)
    ) if current_nurture_version else None
    current_nurture_has_layout = bool(
        current_nurture_version
        and current_day25_finish
        and not current_purchase_check
    )
    if not current_nurture_has_layout:
        last_version = session.scalar(
            select(SequenceVersion.version_no)
            .where(SequenceVersion.sequence_id == sequence.id)
            .order_by(SequenceVersion.version_no.desc())
            .limit(1)
        ) or 0
        if current_nurture_version:
            current_nurture_version.status = "archived"
        version = SequenceVersion(sequence_id=sequence.id, version_no=last_version + 1, status="published", published_at=datetime.now(UTC))
        session.add(version); session.flush()
        content_codes = ["hard_sale_1", "hard_sale_2", *[f"nurture_{n:02d}" for n in range(13, 28)]]
        days = [*range(1, 11), 12, 14, 16, 18, 20, 22, 24]
        nurture_posts = list(zip(content_codes, days, strict=True))
        specs = []
        previous_day = 1
        for index, (content_code, day) in enumerate(nurture_posts):
            delay = None if index == 0 else (day - previous_day) * 86400
            if delay:
                specs.append((f"nurture_delay_{content_code}", "DELAY", None, delay, {}))
            specs.append((f"nurture_{content_code}", "MESSAGE", content_code, None, {"campaign_day": day}))
            previous_day = day
        specs.append(("nurture_delay_finish_day25", "DELAY", None, 86400, {}))
        specs.append(("nurture_finish_day25", "STOP", None, None, {"reason": "prepurchase_day_25_complete"}))
        for position, (key, kind, content_code, delay, config) in enumerate(specs, 1):
            label = items[content_code].title if content_code else key
            if content_code and config.get("campaign_day"):
                label = f"День {config['campaign_day']} · {label}"
            session.add(SequenceStep(sequence_version_id=version.id, step_key=key, position=position, kind=kind, label=label, content_item_id=items[content_code].id if content_code else None, delay_seconds=delay, configuration=config))

    post = session.scalar(select(Sequence).where(Sequence.code == POSTPURCHASE_CODE))
    if not post:
        post = Sequence(code=POSTPURCHASE_CODE, name="После покупки мастер-класса", description="Редактируемые сообщения онбординга, возврата в курс, персональных предложений и саморевью. Отправка отключена до отдельного production-решения.", status="disabled")
        session.add(post); session.flush()
        version = SequenceVersion(sequence_id=post.id, version_no=1, status="draft")
        session.add(version); session.flush()
        session.add(SequenceStep(sequence_version_id=version.id, step_key="placeholder", position=1, kind="STOP", label="Наполнение будет добавлено позже", configuration={"upsells":["recipes","calories","consultation"]}, enabled=False))
    else:
        post.description = "Редактируемые сообщения онбординга, возврата в курс, персональных предложений и саморевью. Отправка отключена до отдельного production-решения."
        post.status = "disabled"

    current_postpurchase = session.scalar(
        select(SequenceStep.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id)
        .where(SequenceVersion.sequence_id == post.id, SequenceStep.step_key == "pp_closing_review_copy")
        .limit(1)
    )
    current_day_unopened = session.scalar(
        select(SequenceStep.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id)
        .where(SequenceVersion.sequence_id == post.id, SequenceStep.step_key == "pp_day_unopened_18h")
        .limit(1)
    )
    current_diet_questionnaire = session.scalar(
        select(SequenceStep.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id)
        .where(
            SequenceVersion.sequence_id == post.id,
            SequenceStep.step_key == "pp_current_diet_questionnaire",
        )
        .limit(1)
    )
    current_dqs_app_link = session.scalar(
        select(SequenceStep.id)
        .join(SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id)
        .where(
            SequenceVersion.sequence_id == post.id,
            SequenceStep.step_key == "pp_dqs_app_link",
        )
        .limit(1)
    )
    if not current_postpurchase or not current_day_unopened or not current_diet_questionnaire or not current_dqs_app_link:
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
            ("pp_current_diet_questionnaire", "MESSAGE", "postpurchase_current_diet", None, {"trigger": "current_diet_questionnaire_completed", "condition": "telegram_linked=true", "state": "editorial_slot"}),
            ("pp_dqs_app_link", "MESSAGE", "postpurchase_dqs_app_link", None, {"trigger": "dqs_app_link_requested", "condition": "telegram_linked=true AND masterclass_access=true", "state": "manual_request"}),
            ("pp_day_unopened_18h", "MESSAGE", "postpurchase_day_unopened", None, {"trigger": "course_day_unopened_18h", "condition": "local_time=18:00 AND day_available=true AND day_opened=false", "state": "editorial_slot"}),
            ("pp_course_stalled_72h", "MESSAGE", "postpurchase_tempo_late", None, {"trigger": "course_stalled_72h", "condition": "masterclass_access=true AND later_course_activity=false AND course_completed=false", "state": "editorial_slot"}),
            ("pp_sales_early_missing", "MESSAGE", "postpurchase_recipes_missing", None, {"trigger": "sales_last_chance_due", "condition": "stage IN (early,second) AND recipes_access=false", "state": "editorial_slot"}),
            ("pp_sales_early_owned", "MESSAGE", "postpurchase_recipes_owned", None, {"trigger": "sales_last_chance_due", "condition": "stage IN (early,second) AND recipes_access=true AND has_missing_products", "state": "editorial_slot"}),
            ("pp_closing_review_copy", "MESSAGE", "postpurchase_closing_review_copy", None, {"trigger": "closing_review_submitted", "condition": "telegram_linked=true", "state": "participant_requested"}),
            ("pp_final_offer", "MESSAGE", "postpurchase_final_offer", None, {"trigger": "sales_last_chance_due", "condition": "stage=last_week AND has_missing_products", "state": "editorial_slot"}),
            ("pp_finish", "STOP", None, None, {"reason": "postpurchase_automatic_messages_complete"}),
        ]
        for position, (key, kind, content_code, delay, config) in enumerate(specs, 1):
            config = {**config, "editorial_help": editorial_help(key)}
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
    for step in session.scalars(
        select(SequenceStep)
        .join(SequenceVersion, SequenceVersion.id == SequenceStep.sequence_version_id)
        .where(SequenceVersion.sequence_id == post.id)
    ):
        help_data = editorial_help(step.step_key)
        if help_data:
            step.configuration = {**(step.configuration or {}), "editorial_help": help_data}

    postmasterclass = session.scalar(select(Sequence).where(Sequence.code == POSTMASTERCLASS_CODE))
    if not postmasterclass:
        postmasterclass = Sequence(
            code=POSTMASTERCLASS_CODE,
            name="5. После завершения мастер-класса",
            description="Будущий отдельный модуль. Содержание и расписание ещё не утверждены; отправка отключена.",
            status="disabled",
        )
        session.add(postmasterclass); session.flush()
        empty_version = SequenceVersion(sequence_id=postmasterclass.id, version_no=1, status="draft")
        session.add(empty_version); session.flush()
        session.add(SequenceStep(
            sequence_version_id=empty_version.id,
            step_key="postmasterclass_not_configured",
            position=1,
            kind="STOP",
            label="Модуль пока не настроен и ничего не отправляет",
            configuration={"reason": "requirements_not_approved"},
            enabled=True,
        ))
    session.flush()
    for version in session.scalars(select(SequenceVersion)):
        _ensure_edges(session, version)
    _ensure_routes(session)
    session.commit()
    return {"messages": len(_messages()), "sequences": 4}
