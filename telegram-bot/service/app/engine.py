from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import ContentItem, Contact, Sequence, SequenceEdge, SequenceRun, SequenceStep, SequenceVersion, StepDelivery, UserVariable


class Sender(Protocol):
    def send_content(self, chat_id: str, content: Any, configuration: dict[str, Any]) -> str: ...


def utcnow() -> datetime:
    return datetime.now(UTC)


def published_version(session: Session, sequence_code: str) -> SequenceVersion | None:
    return session.scalar(
        select(SequenceVersion)
        .join(Sequence, Sequence.id == SequenceVersion.sequence_id)
        .where(Sequence.code == sequence_code, SequenceVersion.status == "published")
        .order_by(SequenceVersion.version_no.desc())
    )


def start_run(session: Session, contact_id: str, sequence_code: str, time_scale: float = 1.0) -> SequenceRun:
    existing = session.scalar(select(SequenceRun).where(SequenceRun.contact_id == contact_id, SequenceRun.status.in_(["active", "waiting"])))
    if existing:
        return existing
    version = published_version(session, sequence_code)
    if not version:
        raise ValueError(f"No published version for sequence {sequence_code}")
    first = session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id == version.id, SequenceStep.enabled.is_(True)).order_by(SequenceStep.position))
    run = SequenceRun(contact_id=contact_id, sequence_version_id=version.id, current_step_key=first.step_key if first else None, status="active", next_action_at=utcnow(), time_scale=time_scale)
    session.add(run); session.flush()
    return run


def _step(session: Session, run: SequenceRun) -> SequenceStep | None:
    if not run.current_step_key:
        return None
    return session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id == run.sequence_version_id, SequenceStep.step_key == run.current_step_key))


def _legacy_next(session: Session, run: SequenceRun, step: SequenceStep) -> SequenceStep | None:
    if step.next_step_key:
        return session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id == run.sequence_version_id, SequenceStep.step_key == step.next_step_key))
    return session.scalar(select(SequenceStep).where(SequenceStep.sequence_version_id == run.sequence_version_id, SequenceStep.position > step.position, SequenceStep.enabled.is_(True)).order_by(SequenceStep.position))


def _edge(session: Session, run: SequenceRun, step: SequenceStep, branch_key: str) -> SequenceEdge | None:
    edge = session.scalar(
        select(SequenceEdge)
        .where(
            SequenceEdge.sequence_version_id == run.sequence_version_id,
            SequenceEdge.from_step_key == step.step_key,
            SequenceEdge.branch_key == branch_key,
            SequenceEdge.enabled.is_(True),
        )
        .order_by(SequenceEdge.priority)
    )
    if not edge and branch_key != "default":
        edge = session.scalar(
            select(SequenceEdge)
            .where(
                SequenceEdge.sequence_version_id == run.sequence_version_id,
                SequenceEdge.from_step_key == step.step_key,
                SequenceEdge.branch_key == "default",
                SequenceEdge.enabled.is_(True),
            )
            .order_by(SequenceEdge.priority)
        )
    return edge


def _set_next(session: Session, run: SequenceRun, step: SequenceStep, branch_key: str = "default") -> bool:
    edge = _edge(session, run, step, branch_key)
    if edge and edge.target_sequence_code:
        target = published_version(session, edge.target_sequence_code)
        run.status = "completed" if target else "branch_pending"
        run.finished_at = utcnow() if target else None
        run.next_action_at = None
        if target:
            start_run(session, run.contact_id, edge.target_sequence_code, run.time_scale)
        else:
            run.context = {**run.context, "pending_sequence": edge.target_sequence_code}
        return True
    nxt = None
    if edge and edge.to_step_key:
        nxt = session.scalar(
            select(SequenceStep).where(
                SequenceStep.sequence_version_id == run.sequence_version_id,
                SequenceStep.step_key == edge.to_step_key,
                SequenceStep.enabled.is_(True),
            )
        )
    elif not edge:
        # Совместимость нужна только на время применения миграции, которая
        # переводит старые next_step_key/configuration в явные связи.
        nxt = _legacy_next(session, run, step)
    run.current_step_key = nxt.step_key if nxt else None
    if not nxt:
        run.status = "completed"
        run.finished_at = utcnow()
    return False


def _variable(session: Session, contact_id: str, key: str) -> Any:
    row = session.scalar(select(UserVariable).where(UserVariable.contact_id == contact_id, UserVariable.key == key))
    return row.value.get("value") if row else None


def _write_variable(session: Session, contact_id: str, key: str, value: Any) -> None:
    row = session.scalar(select(UserVariable).where(UserVariable.contact_id == contact_id, UserVariable.key == key))
    if row:
        row.value = {"value": value}
    else:
        session.add(UserVariable(contact_id=contact_id, key=key, value={"value": value}))


def has_paid_product(session: Session, contact: Contact, product_codes: list[str], variable_key: str) -> bool:
    if contact.user_id and session.bind and session.bind.dialect.name == "postgresql":
        placeholders = ",".join(f":code_{index}" for index in range(len(product_codes)))
        params = {f"code_{index}": code for index, code in enumerate(product_codes)}
        value = session.execute(
            text(f"""
                SELECT EXISTS (
                    SELECT 1 FROM payments p
                    JOIN products pr ON pr.id = p.product_id
                    WHERE p.user_id = :user_id
                      AND p.payment_status = 'paid'
                      AND pr.code IN ({placeholders})
                    UNION ALL
                    SELECT 1 FROM user_accesses ua
                    JOIN resources r ON r.id = ua.resource_id
                    WHERE ua.user_id = :user_id
                      AND ua.revoked_at IS NULL
                      AND (ua.expires_at IS NULL OR ua.expires_at > now())
                      AND r.code = 'ACCESS_MASTERCLASS'
                )
            """),
            {"user_id": contact.user_id, **params},
        ).scalar_one()
        if value:
            return True
    return bool(_variable(session, contact.id, f"has_product:{variable_key}"))


def advance_run(session: Session, run: SequenceRun, sender: Sender, max_steps: int = 100) -> SequenceRun:
    contact = session.get(Contact, run.contact_id)
    for _ in range(max_steps):
        if run.status != "active":
            break
        step = _step(session, run)
        if not step:
            run.status = "completed"; run.finished_at = utcnow(); break
        config = step.configuration or {}
        if step.kind in {"MESSAGE", "PHOTO", "VIDEO", "VIDEO_NOTE", "VOICE"}:
            key = f"{run.id}:{step.step_key}"
            delivery = session.scalar(select(StepDelivery).where(StepDelivery.idempotency_key == key))
            if delivery and delivery.status == "sent":
                _set_next(session, run, step); continue
            content = session.get(ContentItem, step.content_item_id)
            if not delivery:
                delivery = StepDelivery(run_id=run.id, step_key=step.step_key, idempotency_key=key, status="pending", scheduled_at=utcnow(), payload_snapshot={"content_code": content.code if content else None})
                session.add(delivery); session.flush()
            try:
                delivery.attempt_count += 1
                delivery.platform_message_id = sender.send_content(contact.chat_id, content, config)
                if config.get("pin_after_send") and hasattr(sender, "pin_message"):
                    try:
                        sender.pin_message(contact.chat_id, delivery.platform_message_id)
                    except Exception as pin_error:
                        delivery.payload_snapshot = {**(delivery.payload_snapshot or {}), "pin_error": str(pin_error)}
                delivery.status = "sent"; delivery.sent_at = utcnow(); delivery.error_message = None
            except Exception as exc:
                message = str(exc)
                delivery.status = "failed"; delivery.error_message = message; run.status = "error"; run.last_error = message
                if "blocked by the user" in message.lower() or "chat not found" in message.lower():
                    contact.status = "blocked"
                break
            _set_next(session, run, step)
        elif step.kind == "DELAY":
            _set_next(session, run, step)
            run.next_action_at = utcnow() + timedelta(seconds=max(0, step.delay_seconds or 0) * max(run.time_scale, 0.0001))
            break
        elif step.kind == "WAIT_BUTTON":
            run.status = "waiting"; run.next_action_at = None; run.context = {**run.context, "waiting_callback": config.get("callback_data")}; break
        elif step.kind in {"CONDITION", "DB_READ"}:
            condition = config.get("condition") or config.get("key")
            if condition == "subscription_check" and not config.get("enabled", False):
                result = True
            elif condition == "has_product":
                variable_key = config.get("product_code", "masterclass")
                product_codes = config.get("product_codes") or [variable_key]
                result = bool(run.context.get(f"has_product:{variable_key}") or has_paid_product(session, contact, product_codes, variable_key))
            else:
                result = bool(_variable(session, run.contact_id, condition))
            branch_key = "true" if result else "false"
            if _edge(session, run, step, branch_key):
                if _set_next(session, run, step, branch_key):
                    break
            elif result and config.get("true_sequence"):
                target = published_version(session, config["true_sequence"])
                if target:
                    run.status = "completed"; run.finished_at = utcnow(); start_run(session, run.contact_id, config["true_sequence"], run.time_scale); break
                run.status = "branch_pending"
                run.next_action_at = None
                run.context = {**run.context, "pending_sequence": config["true_sequence"]}
                break
            else:
                target_key = config.get("true_step" if result else "false_step")
                if target_key:
                    run.current_step_key = target_key
                else:
                    _set_next(session, run, step)
        elif step.kind == "DB_WRITE":
            _write_variable(session, run.contact_id, config["key"], config.get("value")); _set_next(session, run, step)
        elif step.kind == "GOTO":
            if not _edge(session, run, step, "default"):
                run.current_step_key = config["step_key"]
            elif _set_next(session, run, step):
                break
        elif step.kind == "STOP":
            run.status = "completed"; run.current_step_key = None; run.finished_at = utcnow(); break
        else:
            run.status = "error"; run.last_error = f"Unsupported step kind: {step.kind}"; break
    session.commit()
    return run


def resume_callback(session: Session, contact_id: str, callback_data: str) -> SequenceRun | None:
    run = session.scalar(select(SequenceRun).where(SequenceRun.contact_id == contact_id, SequenceRun.status == "waiting").order_by(SequenceRun.started_at.desc()))
    if not run or run.context.get("waiting_callback") != callback_data:
        return None
    step = _step(session, run)
    if not step:
        return None
    _set_next(session, run, step)
    run.status = "active"; run.next_action_at = utcnow(); run.context = {k:v for k,v in run.context.items() if k != "waiting_callback"}
    session.commit()
    return run


def due_runs(session: Session, limit: int = 50) -> list[SequenceRun]:
    return list(session.scalars(select(SequenceRun).where(SequenceRun.status == "active", SequenceRun.next_action_at <= utcnow()).order_by(SequenceRun.next_action_at).limit(limit)))
