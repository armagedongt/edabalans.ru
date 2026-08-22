from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotRoute, ContentItem, Sequence, SequenceEdge, SequenceStep, SequenceVersion


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
        "description": "Разбирает токен ссылки и сохраняет первое и последнее касание.",
        "source_ref": "telegram-bot/service/app/main.py:process_update",
    },
    "subscription.check": {
        "name": "Проверить подписку",
        "description": "Системная операция проверки текущего статуса подписки.",
        "source_ref": "telegram-bot/service/app/engine.py:advance_run",
    },
    "purchase.check": {
        "name": "Проверить покупку",
        "description": "Проверяет подтверждённую покупку в центральной CRM.",
        "source_ref": "telegram-bot/service/app/engine.py:_has_paid_product",
    },
}


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
        nodes.append({
            "id": step.step_key,
            "kind": step.kind.lower(),
            "label": step.label,
            "subtitle": content.title if content else (component.get("name") or step.kind),
            "position": step.position,
            "sequence_code": sequence.code,
            "details": {
                "Хранение": f"tg_sequence_steps · {step.step_key}",
                "Версия": str(version.version_no),
                "Исполнение": component.get("source_ref", "telegram-bot/service/app/engine.py:advance_run"),
                "Контент": content.code if content else "—",
                "Настройки": step.configuration or {},
            },
        })
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
