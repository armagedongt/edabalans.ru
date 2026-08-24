from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotRoute, ContentItem, Sequence, SequenceEdge, SequenceStep, SequenceVersion
from app.masterclass_triggers import TRIGGERS


SYSTEM_COMPONENTS: dict[str, dict[str, str]] = {
    "telegram.start": {
        "name": "Вход пользователя в Telegram",
        "description": "Принимает /start или специальную ссылку и запускает настроенный маршрут.",
        "source_ref": "telegram-bot/service/app/main.py:process_update",
    },
    "crm.identity.resolve": {
        "name": "Связать Telegram с клиентом CRM",
        "description": "Находит или создаёт клиента и связывает Telegram ID с единым user_id.",
        "source_ref": "telegram-bot/service/app/main.py:_upsert_contact",
    },
    "attribution.resolve": {
        "name": "Определить источник",
        "description": "Разбирает токен ссылки и при первом посещении сохраняет источник и назначает связанные теги. Повторный /start источник не перезаписывает.",
        "source_ref": "telegram-bot/service/app/main.py:process_update",
    },
    "maintenance.gate": {
        "name": "Ограничить работу на время ремонта",
        "description": "Разрешает полную логику только двум аккаунтам владельца; остальных сохраняет в лист ожидания и останавливает до запуска цепочек.",
        "source_ref": "telegram-bot/service/app/maintenance.py",
    },
    "subscription.check": {
        "name": "Проверить подписку",
        "description": "Системная операция проверки текущего статуса подписки.",
        "source_ref": "telegram-bot/service/app/engine.py:advance_run",
    },
    "purchase.lifecycle": {
        "name": "Событие владения мастер-классом",
        "description": "Привязка покупателя или активный ACCESS_MASTERCLASS один раз останавливают все сообщения до покупки.",
        "source_ref": "telegram-bot/service/app/customer_lifecycle.py",
    },
}

GLOBAL_MODULES: tuple[dict[str, str], ...] = (
    {"code": "start_attribution", "name": "Старт и атрибуция", "status": "Исполняемый модуль · временно включён режим ремонта"},
    {"code": "welcome_intensive", "name": "Welcome: запуск и первые четыре дня", "status": "Исполняемая редактируемая цепочка"},
    {"code": "prepurchase_nurture", "name": "Основная рассылка до покупки", "status": "Исполняемый каркас · контент частичный"},
    {"code": "postpurchase_masterclass", "name": "После покупки мастер-класса", "status": "Требования частичные"},
    {"code": "postmasterclass_nurture", "name": "После завершения мастер-класса", "status": "Отключённый пустой каркас"},
    {"code": "broadcasts", "name": "Разовые рассылки", "status": "Draft → preview → test → send/schedule → retry"},
    {"code": "inbox", "name": "Входящие сообщения и ответы", "status": "Единая Telegram-лента в карточке пользователя"},
    {"code": "lottery", "name": "Лотерея", "status": "Запланировано"},
    {"code": "quiz", "name": "Тесты и опросы", "status": "Запланировано"},
)

# Исполнитель start_router проходит правила строго сверху вниз. Текстовая проекция
# админки обязана показывать те же условия и выходы; тесты проверяют соответствие.
START_ROUTER_RULES: tuple[tuple[str, bool, str], ...] = (
    ("has_masterclass", True, "masterclass_owned"),
    ("is_first_visit", True, "launch_welcome"),
    ("day_four_sent", True, "intensive_complete"),
    ("has_active_welcome_run", True, "intensive_waiting"),
    ("welcome_ever_started", False, "launch_welcome"),
    ("__default__", True, "welcome_state_error"),
)


def module_overview_graph(_: Session) -> dict[str, Any]:
    nodes = [{
        "id": f"module:{module['code']}", "kind": "module", "label": module["name"],
        "subtitle": module["status"], "module_code": module["code"],
        "details": {"Код": module["code"], "Статус": module["status"], "Канон": "docs/knowledge-base/modules/telegram/MODULE_REGISTRY.md"},
    } for module in GLOBAL_MODULES]
    nodes.append({
        "id": "event:masterclass_owned", "kind": "event", "label": "Покупатель определён",
        "subtitle": "M-link или ACCESS_MASTERCLASS", "module_code": "postpurchase_masterclass",
        "details": {"Действие": "Единоразово остановить presale-run и поставить post-purchase события"},
    })
    edges = [
        {"id": "modules:start-welcome", "source": "module:start_attribution", "target": "module:welcome_intensive", "label": "Запустить Welcome", "branch": "default"},
        {"id": "modules:welcome-prepurchase", "source": "module:welcome_intensive", "target": "module:prepurchase_nurture", "label": "Завершён без покупки", "branch": "false"},
        {"id": "modules:event-stop-welcome", "source": "event:masterclass_owned", "target": "module:welcome_intensive", "label": "Остановить активный run", "branch": "stop"},
        {"id": "modules:event-stop-prepurchase", "source": "event:masterclass_owned", "target": "module:prepurchase_nurture", "label": "Остановить активный run", "branch": "stop"},
        {"id": "modules:event-postpurchase", "source": "event:masterclass_owned", "target": "module:postpurchase_masterclass", "label": "Поставить нужные сообщения", "branch": "event"},
        {"id": "modules:postpurchase-postmasterclass", "source": "module:postpurchase_masterclass", "target": "module:postmasterclass_nurture", "label": "После 7-го дня; пока отключено", "branch": "default"},
    ]
    return {"level": "overview", "title": "Глобальные модули Telegram-бота", "description": "Каждый модуль раскрывается в автоматически построенную текстовую последовательность входов, условий и выходов.", "nodes": nodes, "edges": edges, "issues": []}


def start_attribution_graph(session: Session) -> dict[str, Any]:
    def node(node_id: str, kind: str, label: str, subtitle: str, position: int, content_code: str | None = None, **details: Any) -> dict[str, Any]:
        result = {"id": node_id, "kind": kind, "label": label, "subtitle": subtitle, "position": position, "details": details}
        if content_code:
            item = session.scalar(select(ContentItem).where(ContentItem.code == content_code))
            if item:
                result["content"] = {
                    "id": item.id,
                    "code": item.code,
                    "title": item.title,
                    "body_source": item.body_source,
                    "media_kind": item.media_kind,
                    "media_path": item.media_path,
                    "labels": item.labels,
                }
        return result

    nodes = [
        node("entry_rule", "entry", "Создать/импортировать правило", "Админка ссылок", 1, Канон="LEAD_ENTRY_OWNER_REQUIREMENTS.md"),
        node("entry_link", "entry", "Открыта bot/go/legacy/invite ссылка", "Обычный вход", 2, Источники="t.me, go., LeadTeh UUID, channel invite"),
        node("entry_buyer", "entry", "Специальная ссылка покупателя", "Одноразовый CRM token", 3, Статус="M-link реализован; test-only"),
        node("telegram_start", "entry", "Нажата кнопка Start", "Telegram /start", 4, Исполнение="app/main.py:process_update"),
        node("identity", "technical", "Найти contact и CRM user", "Идентификация", 5, Хранение="tg_contacts / messenger_accounts"),
        node("maintenance_gate", "condition", "Разрешён полный доступ во время ремонта?", "Только два Telegram ID владельца", 6, Исполнение="app/maintenance.py"),
        node("maintenance_notice", "message", "Сообщить о ремонте и сохранить в лист ожидания", "Нажмите, чтобы изменить текст", 7, "tpl_maintenance_notice", Хранение="tg_contacts.status / tg_tracking_events"),
        node("exit_maintenance", "module_exit", "Стоп до окончания ремонта", "Ни одна цепочка и отправка не запускается", 8, Результат="maintenance_waitlist"),
        node("attribution", "technical", "Распознать источник и first-touch", "Не перезаписывать повторным Start", 9, Хранение="tg_tracking_* / attribution_events / user_tags"),
        node("has_masterclass", "condition", "Куплен именно мастер-класс?", "Платёж или активное право ACCESS_MASTERCLASS", 10, Исполнение="app/start_router.py"),
        node("send_buyer", "message", "Отправить пост: мастер-класс куплен", "Нажмите, чтобы изменить текст", 11, "tpl_start_has_masterclass", Контент="tg_content_items"),
        node("exit_buyer", "module_exit", "Стоп", "Остановить Welcome/pre-purchase; нового не запускать", 12, Результат="Существующие post-purchase процессы не меняются"),
        node("first_visit", "condition", "Первое посещение бота?", "main_scenario_seen_at", 13, Хранение="messenger_accounts"),
        node("day_four_sent", "condition", "Четвёртый материал отправлен?", "Успешная доставка обязательного шага", 14, Хранение="tg_step_deliveries"),
        node("send_complete", "message", "Отправить навигацию по интенсиву", "Нажмите, чтобы изменить текст", 15, "tpl_start_intensive_complete", Контент="tg_content_items"),
        node("exit_complete", "module_exit", "Стоп", "Интенсив не перезапускать", 16, Результат="Текущие другие цепочки не меняются"),
        node("welcome_run_active", "condition", "Есть active/waiting Welcome run?", "Только welcome_intensive", 17, Хранение="tg_sequence_runs"),
        node("send_waiting", "message", "Сообщить время следующего материала", "Нажмите, чтобы изменить текст", 18, "tpl_start_intensive_waiting", Источник_времени="tg_sequence_runs.next_action_at"),
        node("exit_waiting", "module_exit", "Стоп", "Welcome run продолжает расписание", 19, Запрещено="Не менять current_step_key и next_action_at"),
        node("welcome_ever_started", "condition", "Новый Welcome когда-либо запускался?", "Run текущей версии; старый LeadTeh не считается", 20, Хранение="tg_sequence_runs / tg_sequence_versions"),
        node("exit_welcome", "module_exit", "Перейти в Welcome", "Навигация, кружок, кнопка, подписка и первые четыре дня", 21, Следующий_модуль="welcome_intensive"),
        node("exit_error", "error", "Ошибка: Welcome потерял состояние", "Ручная проверка; пользователю ничего не отправлять", 22, Причина="Welcome был, но run нет и День 4 не отправлен"),
    ]
    edges = [
        {"id": "e01", "source": "entry_rule", "target": "entry_link", "label": "Опубликовать", "branch": "default"},
        {"id": "e02", "source": "entry_link", "target": "telegram_start", "label": "Открыть бот", "branch": "default"},
        {"id": "e03", "source": "telegram_start", "target": "identity", "label": "Update", "branch": "default"},
        {"id": "e04", "source": "entry_buyer", "target": "identity", "label": "Связать с CRM", "branch": "default"},
        {"id": "e05", "source": "identity", "target": "maintenance_gate", "label": "Далее", "branch": "default"},
        {"id": "e05a", "source": "maintenance_gate", "target": "attribution", "label": "Да", "branch": "true"},
        {"id": "e05b", "source": "maintenance_gate", "target": "maintenance_notice", "label": "Нет", "branch": "false"},
        {"id": "e05c", "source": "maintenance_notice", "target": "exit_maintenance", "label": "Сохранено и отправлено", "branch": "default"},
        {"id": "e06", "source": "attribution", "target": "has_masterclass", "label": "Далее", "branch": "default"},
        {"id": "e07", "source": "has_masterclass", "target": "send_buyer", "label": "Да", "branch": "true"},
        {"id": "e08", "source": "send_buyer", "target": "exit_buyer", "label": "Отправлено", "branch": "default"},
        {"id": "e09", "source": "has_masterclass", "target": "first_visit", "label": "Нет", "branch": "false"},
        {"id": "e10", "source": "first_visit", "target": "exit_welcome", "label": "Да", "branch": "true"},
        {"id": "e11", "source": "first_visit", "target": "day_four_sent", "label": "Нет", "branch": "false"},
        {"id": "e12", "source": "day_four_sent", "target": "send_complete", "label": "Да", "branch": "true"},
        {"id": "e13", "source": "send_complete", "target": "exit_complete", "label": "Отправлено", "branch": "default"},
        {"id": "e14", "source": "day_four_sent", "target": "welcome_run_active", "label": "Нет", "branch": "false"},
        {"id": "e15", "source": "welcome_run_active", "target": "send_waiting", "label": "Да", "branch": "true"},
        {"id": "e16", "source": "send_waiting", "target": "exit_waiting", "label": "Отправлено", "branch": "default"},
        {"id": "e17", "source": "welcome_run_active", "target": "welcome_ever_started", "label": "Нет", "branch": "false"},
        {"id": "e18", "source": "welcome_ever_started", "target": "exit_welcome", "label": "Нет", "branch": "false"},
        {"id": "e19", "source": "welcome_ever_started", "target": "exit_error", "label": "Да", "branch": "true"},
    ]
    return {"level": "module", "module_code": "start_attribution", "title": "1. Старт и атрибуция", "status": "Основной бот · временный режим ремонта", "description": "Сначала действует глобальный предохранитель ремонта. Полная атрибуция и сценарии доступны только двум аккаунтам владельца; остальные сохраняются в лист ожидания.", "nodes": nodes, "edges": edges, "issues": []}


def postpurchase_graph(session: Session) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for index, trigger in enumerate(TRIGGERS, 1):
        event_id = f"event:{trigger['step_key']}"
        condition_id = f"condition:{trigger['step_key']}"
        message_id = trigger["step_key"]
        item = session.scalar(select(ContentItem).where(ContentItem.code == trigger["content_code"]))
        nodes.extend((
            {"id": event_id, "kind": "event", "label": trigger["trigger"], "subtitle": "Доменное событие или due-сигнал", "position": index * 3 - 2, "details": {"Источник": "backend/app/masterclass_routes.py", "Очередь": "masterclass_notifications", "Триггер": trigger["trigger"]}},
            {"id": condition_id, "kind": "condition", "label": "Проверить перед отправкой", "subtitle": trigger["condition"], "position": index * 3 - 1, "details": {"Точный факт": trigger["condition"], "Права": "user_accesses + resources", "Исполнение": "telegram-bot/service/app/masterclass_dispatch.py"}},
        ))
        message = {"id": message_id, "kind": "message", "label": trigger["title"], "subtitle": trigger["purpose"], "position": index * 3, "details": {"Получатель": trigger["recipient"], "Контент": trigger["content_code"], "Хранение": "tg_content_items", "Доставка": "masterclass_notifications → tg_manual_messages"}}
        if item:
            message["content"] = {"id": item.id, "code": item.code, "title": item.title, "body_source": item.body_source, "media_kind": item.media_kind, "media_path": item.media_path, "labels": item.labels}
        nodes.append(message)
        edges.extend((
            {"id": f"{message_id}:event", "source": event_id, "target": condition_id, "label": "Наступил срок", "branch": "event"},
            {"id": f"{message_id}:yes", "source": condition_id, "target": message_id, "label": "Да", "branch": "true"},
        ))
    nodes.append({"id": "postpurchase_exit", "kind": "module_exit", "label": "7 дней после саморевью завершены", "subtitle": "Следующий модуль пока отключён", "position": len(TRIGGERS) * 3 + 1, "details": {"Следующий модуль": "postmasterclass_nurture", "Статус": "disabled"}})
    edges.append({"id": "postpurchase:exit", "source": "pp_review_week_day7", "target": "postpurchase_exit", "label": "Отправлено", "branch": "default"})
    return {"level": "module", "module_code": "postpurchase_masterclass", "title": "4. После покупки мастер-класса", "status": "Событийный модуль · test-only", "description": "Каждая строка читается слева направо: событие → точная проверка → редактируемое сообщение. Ветка «нет» означает безопасный пропуск без отправки.", "nodes": nodes, "edges": edges, "issues": []}


def service_module_graph(module_code: str) -> dict[str, Any]:
    if module_code == "inbox":
        nodes = [
            {"id": "message", "kind": "entry", "label": "Получено обычное сообщение", "subtitle": "Telegram update", "details": {"Исполнение": "main.py:process_update"}},
            {"id": "store", "kind": "technical", "label": "Сохранить incoming", "subtitle": "Текст, caption или тип вложения", "details": {"Хранение": "tg_manual_messages"}},
            {"id": "timeline", "kind": "module_exit", "label": "Показать в ленте человека", "subtitle": "Вместе с автоматическими и ручными исходящими", "details": {"API": "/contacts/{id}/timeline"}},
            {"id": "reply", "kind": "entry", "label": "Ответ владельца", "subtitle": "Из карточки пользователя", "details": {"Доставка": "Telegram Bot API"}},
            {"id": "log_reply", "kind": "module_exit", "label": "Сохранить outgoing", "subtitle": "Статус и Telegram message ID", "details": {"Хранение": "tg_manual_messages"}},
        ]
        edges = [
            {"id": "inbox:1", "source": "message", "target": "store", "label": "Не Start", "branch": "default"},
            {"id": "inbox:2", "source": "store", "target": "timeline", "label": "Сохранено", "branch": "default"},
            {"id": "inbox:3", "source": "reply", "target": "log_reply", "label": "Отправлено/ошибка", "branch": "default"},
        ]
    else:
        nodes = [
            {"id": "draft", "kind": "entry", "label": "Создать draft", "subtitle": "Текст, медиа, кнопки и сегмент", "details": {"Хранение": "tg_broadcasts / tg_content_items"}},
            {"id": "preview", "kind": "technical", "label": "Посчитать аудиторию", "subtitle": "Точное число и sample", "details": {"Предохранитель": "maintenance allowlist"}},
            {"id": "confirm", "kind": "condition", "label": "Число получателей подтверждено?", "subtitle": "При изменении аудитории запуск отклоняется", "details": {"API": "launch / schedule"}},
            {"id": "deliver", "kind": "technical", "label": "Зафиксировать recipients и отправить", "subtitle": "Идемпотентно по broadcast + contact", "details": {"Хранение": "tg_broadcast_recipients"}},
            {"id": "result", "kind": "module_exit", "label": "Результаты и retry failed", "subtitle": "Sent/failed по каждому человеку", "details": {"Повтор": "только failed"}},
        ]
        edges = [
            {"id": "broadcast:1", "source": "draft", "target": "preview", "label": "Предпросмотр", "branch": "default"},
            {"id": "broadcast:2", "source": "preview", "target": "confirm", "label": "Показано владельцу", "branch": "default"},
            {"id": "broadcast:3", "source": "confirm", "target": "deliver", "label": "Да", "branch": "true"},
            {"id": "broadcast:4", "source": "confirm", "target": "preview", "label": "Нет/изменилось", "branch": "false"},
            {"id": "broadcast:5", "source": "deliver", "target": "result", "label": "Завершено", "branch": "default"},
        ]
    module = next(item for item in GLOBAL_MODULES if item["code"] == module_code)
    return {"level": "module", "module_code": module_code, "title": module["name"], "status": module["status"], "description": "Автоматическая текстовая проекция исполняемой служебной логики.", "nodes": nodes, "edges": edges, "issues": []}


def module_graph(session: Session, module_code: str) -> dict[str, Any]:
    if module_code == "start_attribution":
        return start_attribution_graph(session)
    if module_code == "postpurchase_masterclass":
        return postpurchase_graph(session)
    if module_code in {"inbox", "broadcasts"}:
        return service_module_graph(module_code)
    if module_code in {"welcome_intensive", "prepurchase_nurture", "postmasterclass_nurture"}:
        return sequence_graph(session, module_code, "")
    module = next((item for item in GLOBAL_MODULES if item["code"] == module_code), None)
    if not module:
        raise LookupError(module_code)
    return {"level": "module", "module_code": module_code, "title": module["name"], "status": module["status"], "description": "Подробная последовательность появится после фиксации и утверждения требований.", "nodes": [{"id": "module_draft", "kind": "module", "label": module["name"], "subtitle": module["status"], "details": {"Статус": module["status"], "Канон": "MODULE_REGISTRY.md"}}], "edges": [], "issues": [{"severity": "warning", "code": "module_not_designed", "message": "Подробная логика этого модуля ещё не утверждена."}]}


def component_for_step(step: SequenceStep) -> str | None:
    config = step.configuration or {}
    condition = config.get("condition") or config.get("key")
    if condition == "subscription_check":
        return "subscription.check"
    if condition == "has_product":
        return "purchase.check"
    return None


def version_for_sequence(session: Session, sequence: Sequence, status: str = "published") -> SequenceVersion | None:
    query = select(SequenceVersion).where(SequenceVersion.sequence_id == sequence.id)
    if status:
        preferred = session.scalar(query.where(SequenceVersion.status == status).order_by(SequenceVersion.version_no.desc()))
        if preferred:
            return preferred
    return session.scalar(query.order_by(SequenceVersion.version_no.desc()))


def graph_issues(session: Session, version: SequenceVersion) -> list[dict[str, str]]:
    steps = list(session.scalars(select(SequenceStep).where(SequenceStep.sequence_version_id == version.id, SequenceStep.enabled.is_(True))))
    edges = list(session.scalars(select(SequenceEdge).where(SequenceEdge.sequence_version_id == version.id, SequenceEdge.enabled.is_(True))))
    issues: list[dict[str, str]] = []
    if not steps:
        return [{"severity": "error", "code": "empty_sequence", "message": "В цепочке нет активных блоков."}]

    by_key = {step.step_key: step for step in steps}
    outgoing: dict[str, list[SequenceEdge]] = defaultdict(list)
    incoming: dict[str, int] = defaultdict(int)
    for edge in edges:
        if edge.from_step_key not in by_key:
            issues.append({"severity": "error", "code": "missing_source", "message": f"Связь начинается из отсутствующего блока {edge.from_step_key}."})
            continue
        if not edge.to_step_key and not edge.target_sequence_code:
            issues.append({"severity": "error", "code": "empty_target", "message": f"У связи из {edge.from_step_key} не задано продолжение."})
        if edge.to_step_key and edge.to_step_key not in by_key:
            issues.append({"severity": "error", "code": "missing_target", "message": f"Блок {edge.from_step_key} ведёт в отсутствующий блок {edge.to_step_key}."})
        if edge.target_sequence_code and not session.scalar(select(Sequence.id).where(Sequence.code == edge.target_sequence_code)):
            issues.append({"severity": "error", "code": "missing_sequence", "message": f"Блок {edge.from_step_key} ведёт в отсутствующую цепочку {edge.target_sequence_code}."})
        outgoing[edge.from_step_key].append(edge)
        if edge.to_step_key in by_key:
            incoming[edge.to_step_key] += 1

    for step in steps:
        if step.kind in {"MESSAGE", "PHOTO", "VIDEO", "VIDEO_NOTE", "VOICE"} and not step.content_item_id:
            issues.append({"severity": "error", "code": "missing_content", "message": f"В блоке «{step.label}» не выбрано сообщение."})
        if step.kind == "DELAY" and step.delay_seconds is None:
            issues.append({"severity": "error", "code": "missing_delay", "message": f"В блоке «{step.label}» не указана задержка."})
        if step.kind == "CONDITION":
            branches = {edge.branch_key for edge in outgoing[step.step_key]}
            if "true" not in branches:
                issues.append({"severity": "error", "code": "missing_true_branch", "message": f"У условия «{step.label}» нет ветки «да»."})
            if "false" not in branches:
                issues.append({"severity": "error", "code": "missing_false_branch", "message": f"У условия «{step.label}» нет ветки «нет»."})
        elif step.kind != "STOP" and not outgoing[step.step_key]:
            issues.append({"severity": "error", "code": "dead_end", "message": f"После блока «{step.label}» не задано продолжение."})

    first = min(steps, key=lambda item: item.position)
    reached: set[str] = set()
    queue = deque([first.step_key])
    while queue:
        key = queue.popleft()
        if key in reached:
            continue
        reached.add(key)
        queue.extend(edge.to_step_key for edge in outgoing[key] if edge.to_step_key in by_key)
    for step in steps:
        if step.step_key not in reached:
            issues.append({"severity": "error", "code": "unreachable", "message": f"До блока «{step.label}» невозможно дойти от начала цепочки."})

    visiting: set[str] = set()
    visited: set[str] = set()

    def has_unapproved_cycle(key: str) -> bool:
        if key in visiting:
            return True
        if key in visited:
            return False
        visiting.add(key)
        for edge in outgoing[key]:
            if edge.to_step_key and not (edge.condition or {}).get("allow_cycle") and has_unapproved_cycle(edge.to_step_key):
                return True
        visiting.remove(key)
        visited.add(key)
        return False

    if has_unapproved_cycle(first.step_key):
        issues.append({"severity": "error", "code": "cycle", "message": "Обнаружен цикл, который явно не разрешён в настройках связи."})
    return issues


def sequence_graph(session: Session, sequence_code: str, status: str = "published") -> dict[str, Any]:
    sequence = session.scalar(select(Sequence).where(Sequence.code == sequence_code))
    if not sequence:
        raise LookupError(sequence_code)
    version = version_for_sequence(session, sequence, status)
    if not version:
        return {"level": "sequence", "title": sequence.name, "nodes": [], "edges": [], "issues": []}
    rows = session.execute(
        select(SequenceStep, ContentItem)
        .outerjoin(ContentItem, ContentItem.id == SequenceStep.content_item_id)
        .where(SequenceStep.sequence_version_id == version.id, SequenceStep.enabled.is_(True))
        .order_by(SequenceStep.position)
    ).all()
    edges = list(session.scalars(select(SequenceEdge).where(SequenceEdge.sequence_version_id == version.id, SequenceEdge.enabled.is_(True)).order_by(SequenceEdge.priority)))
    nodes = []
    for step, content in rows:
        component_code = component_for_step(step)
        component = SYSTEM_COMPONENTS.get(component_code or "", {})
        graph_node = {
            "id": step.step_key,
            "step_id": step.id,
            "kind": step.kind.lower(),
            "label": step.label,
            "subtitle": content.title if content else (component.get("name") or step.kind),
            "position": step.position,
            "sequence_code": sequence.code,
            "configuration": step.configuration or {},
            "details": {
                "Хранение": f"tg_sequence_steps · {step.step_key}",
                "Версия": str(version.version_no),
                "Исполнение": component.get("source_ref", "telegram-bot/service/app/engine.py:advance_run"),
                "Контент": content.code if content else "—",
                "Настройки": step.configuration or {},
            },
        }
        if content:
            graph_node["content"] = {
                "id": content.id,
                "code": content.code,
                "title": content.title,
                "body_source": content.body_source,
                "media_kind": content.media_kind,
                "media_path": content.media_path,
                "labels": content.labels,
            }
        nodes.append(graph_node)
    graph_edges = [{
        "id": edge.id,
        "source": edge.from_step_key,
        "target": edge.to_step_key or f"sequence:{edge.target_sequence_code}",
        "label": edge.label or {"true": "Да", "false": "Нет", "default": "Далее"}.get(edge.branch_key, edge.branch_key),
        "branch": edge.branch_key,
        "external": bool(edge.target_sequence_code),
    } for edge in edges]
    target_codes = sorted({edge.target_sequence_code for edge in edges if edge.target_sequence_code})
    for code in target_codes:
        target = session.scalar(select(Sequence).where(Sequence.code == code))
        nodes.append({"id": f"sequence:{code}", "kind": "sequence", "label": target.name if target else code, "subtitle": "Переход в другую цепочку", "sequence_code": code, "details": {"Хранение": "tg_sequences", "Код": code}})
    return {
        "level": "sequence",
        "title": sequence.name,
        "sequence_code": sequence.code,
        "version": version.version_no,
        "version_status": version.status,
        "nodes": nodes,
        "edges": graph_edges,
        "issues": graph_issues(session, version),
    }


def overview_graph(session: Session, status: str = "published") -> dict[str, Any]:
    sequences = list(session.scalars(select(Sequence).order_by(Sequence.name)))
    routes = list(session.scalars(select(BotRoute).where(BotRoute.enabled.is_(True)).order_by(BotRoute.priority, BotRoute.name)))
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    used_components = {route.source_component for route in routes}
    for route in routes:
        used_components.update((route.configuration or {}).get("pipeline", []))
    for code in sorted(used_components):
        component = SYSTEM_COMPONENTS.get(code, {"name": code, "description": "Зарегистрированный системный компонент", "source_ref": "—"})
        nodes.append({"id": f"component:{code}", "kind": "system", "label": component["name"], "subtitle": "Системный блок", "details": {"Исполнение": component["source_ref"], "Описание": component["description"]}})
    for route in routes:
        route_id = f"route:{route.code}"
        nodes.append({"id": route_id, "kind": "entry", "label": route.name, "subtitle": f"{route.trigger_kind}: {route.trigger_value}", "details": {"Хранение": "tg_bot_routes", "Триггер": f"{route.trigger_kind}: {route.trigger_value}", "Настройки": route.configuration}})
        pipeline = [route.source_component, *(route.configuration or {}).get("pipeline", [])]
        previous = route_id
        for index, component_code in enumerate(pipeline):
            target = f"component:{component_code}"
            edges.append({"id": f"{route_id}:component:{index}", "source": previous, "target": target, "label": "Вход" if index == 0 else "Далее", "branch": "default"})
            previous = target
        edges.append({"id": f"{route_id}:target", "source": previous, "target": f"sequence:{route.target_sequence_code}", "label": "Запустить", "branch": "default"})
    issues: list[dict[str, str]] = []
    for sequence in sequences:
        version = version_for_sequence(session, sequence, status)
        sequence_issues = graph_issues(session, version) if version else [{"severity": "warning", "code": "no_version", "message": "Нет версии для отображения."}]
        errors = sum(issue["severity"] == "error" for issue in sequence_issues)
        nodes.append({
            "id": f"sequence:{sequence.code}",
            "kind": "sequence",
            "label": sequence.name,
            "subtitle": f"Версия {version.version_no if version else '—'} · {sequence.status}",
            "sequence_code": sequence.code,
            "details": {"Хранение": "tg_sequences / tg_sequence_versions", "Код": sequence.code, "Ошибок проверки": errors, "Описание": sequence.description or "—"},
        })
        if version:
            for edge in session.scalars(select(SequenceEdge).where(SequenceEdge.sequence_version_id == version.id, SequenceEdge.target_sequence_code.is_not(None), SequenceEdge.enabled.is_(True))):
                edges.append({"id": f"overview:{edge.id}", "source": f"sequence:{sequence.code}", "target": f"sequence:{edge.target_sequence_code}", "label": edge.label or edge.branch_key, "branch": edge.branch_key})
        issues.extend({**issue, "sequence_code": sequence.code, "sequence_name": sequence.name} for issue in sequence_issues)
    return {"level": "overview", "title": "Карта всей логики бота", "nodes": nodes, "edges": edges, "issues": issues}
