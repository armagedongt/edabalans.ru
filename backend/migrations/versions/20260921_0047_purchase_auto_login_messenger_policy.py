"""Add browser-bound purchase login and stable messenger/course policy.

Revision ID: 20260921_0047
Revises: 20260920_0046
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260921_0047"
down_revision = "20260920_0046"
branch_labels = None
depends_on = None


def _document_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _stable_step_assignments(payload: dict, rows: list[dict]) -> list[tuple[object, str]]:
    day_steps = {
        int(day["number"]): [str(step["id"]) for step in day.get("steps", [])]
        for day in payload.get("days", [])
    }
    seen: set[tuple[str, str]] = set()
    assignments: list[tuple[object, str]] = []
    for row in rows:
        steps = day_steps.get(int(row["day_number"]), [])
        index = int(row["step_index"])
        if index < 0 or index >= len(steps):
            raise RuntimeError(
                f"Unmapped masterclass progress row {row['id']}: day={row['day_number']} index={index}"
            )
        step_id = steps[index]
        key = (str(row["user_id"]), step_id)
        if key in seen:
            raise RuntimeError(f"Duplicate masterclass progress for user={key[0]} step={step_id}")
        seen.add(key)
        assignments.append((row["id"], step_id))
    return assignments


def _policy_v2_payload(payload: dict) -> dict:
    next_payload = deepcopy(payload)
    first_day = next(
        (day for day in next_payload.get("days", []) if int(day.get("number", 0)) == 1),
        None,
    )
    if first_day is None:
        raise RuntimeError("Day 1 is missing")
    steps = list(first_day.get("steps", []))
    messenger = next((step for step in steps if step.get("id") == "day-01-messenger-link"), None)
    if messenger is None:
        raise RuntimeError("Day 1 messenger step is missing")
    steps = [step for step in steps if step.get("id") != "day-01-messenger-link"]
    diary_index = next(
        (index for index, step in enumerate(steps) if step.get("id") == "day-01-article-02"),
        None,
    )
    if diary_index is None:
        raise RuntimeError("Day 1 diary step is missing")
    messenger.update(
        hidden=False,
        completion="server_linked",
        label="Подключить мессенджер",
        summary="Подключите Telegram или MAX для анкет, материалов и уведомлений",
    )
    steps.insert(diary_index + 1, messenger)
    first_day["steps"] = steps
    return next_payload


def _backfill_step_ids(bind) -> None:
    documents = sa.table(
        "managed_document_versions",
        sa.column("id", sa.Uuid()),
        sa.column("document_type", sa.String()),
        sa.column("document_key", sa.String()),
        sa.column("schema_version", sa.Integer()),
        sa.column("version_no", sa.Integer()),
        sa.column("payload", sa.JSON()),
        sa.column("content_hash", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    current = bind.execute(
        sa.select(documents).where(
            documents.c.document_type == "course-structure",
            documents.c.document_key == "masterclass-21",
            documents.c.is_active.is_(True),
        )
    ).mappings().one_or_none()
    if current is None:
        count = bind.execute(sa.text("SELECT count(*) FROM masterclass_step_progress")).scalar_one()
        if count:
            raise RuntimeError("Cannot backfill course progress without the active course revision")
        return
    payload = current["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    rows = bind.execute(sa.text(
        "SELECT id, user_id, day_number, step_index FROM masterclass_step_progress"
    )).mappings().all()
    for row_id, step_id in _stable_step_assignments(payload, rows):
        bind.execute(
            sa.text("UPDATE masterclass_step_progress SET step_id=:step_id WHERE id=:id"),
            {"step_id": step_id, "id": row_id},
        )

    # Publish the approved order only after every old positional row has a stable id.
    next_payload = _policy_v2_payload(payload)
    bind.execute(
        documents.update().where(documents.c.id == current["id"]).values(is_active=False)
    )
    bind.execute(
        documents.insert().values(
            document_type=current["document_type"],
            document_key=current["document_key"],
            schema_version=current["schema_version"],
            version_no=current["version_no"] + 1,
            payload=next_payload,
            content_hash=_document_hash(next_payload),
            created_by="migration-purchase-auto-login-messenger-policy",
            is_active=True,
        )
    )


def upgrade() -> None:
    op.create_table(
        "payment_browser_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payment_browser_grants_expires", "payment_browser_grants", ["expires_at"])
    op.add_column("account_sessions", sa.Column("browser_grant_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_account_sessions_browser_grant", "account_sessions", "payment_browser_grants",
        ["browser_grant_id"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_account_sessions_browser_grant", "account_sessions", ["browser_grant_id"])

    op.add_column("messenger_accounts", sa.Column("is_deliverable", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("messenger_accounts", sa.Column("is_preferred", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("messenger_link_tokens", sa.Column("intent_payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False))
    op.add_column("user_course_policies", sa.Column("course_policy_version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("masterclass_step_progress", sa.Column("step_id", sa.String(160)))
    op.add_column("masterclass_notifications", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("masterclass_notifications", sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE masterclass_notifications SET expires_at=due_at + interval '24 hours' WHERE expires_at IS NULL"
    ))
    op.alter_column("masterclass_notifications", "expires_at", nullable=False)

    bind.execute(sa.text("""
        INSERT INTO user_course_policies
          (id, user_id, resource_id, unlock_mode, source, course_policy_version, updated_at)
        SELECT gen_random_uuid(), ua.user_id, ua.resource_id, 'paced',
               'migration-existing-masterclass', 1, now()
        FROM user_accesses ua
        JOIN resources r ON r.id = ua.resource_id AND r.code = 'ACCESS_MASTERCLASS'
        LEFT JOIN user_course_policies p
          ON p.user_id = ua.user_id AND p.resource_id = ua.resource_id
        WHERE ua.revoked_at IS NULL AND p.id IS NULL
        GROUP BY ua.user_id, ua.resource_id
    """))
    _backfill_step_ids(bind)
    op.alter_column("masterclass_step_progress", "step_id", nullable=False)
    op.drop_constraint("uq_masterclass_step_progress", "masterclass_step_progress", type_="unique")
    op.create_unique_constraint(
        "uq_masterclass_step_progress_step", "masterclass_step_progress", ["user_id", "step_id"]
    )

    # Preserve a deterministic route for legacy contacts: one link keeps itself;
    # dual-linked users keep Telegram as the initial preferred channel.
    bind.execute(sa.text(
        "UPDATE messenger_accounts SET is_deliverable=false, is_preferred=false"
    ))
    bind.execute(sa.text("""
        WITH ranked AS (
          SELECT m.id, m.user_id, m.platform,
                 row_number() OVER (
                   PARTITION BY m.user_id, m.platform
                   ORDER BY m.linked_at DESC NULLS LAST, m.created_at DESC, m.id DESC
                 ) AS platform_rank
          FROM messenger_accounts m
          WHERE platform IN ('telegram', 'max') AND linked_at IS NOT NULL
            AND EXISTS (
              SELECT 1 FROM tg_contacts c
              WHERE c.user_id = m.user_id
                AND c.telegram_user_id = m.platform_user_id
                AND c.status = 'active'
            )
        )
        UPDATE messenger_accounts m
        SET is_deliverable = (ranked.platform_rank = 1)
        FROM ranked WHERE ranked.id = m.id
    """))
    bind.execute(sa.text("""
        WITH choice AS (
          SELECT DISTINCT ON (user_id) id
          FROM messenger_accounts
          WHERE is_deliverable = true AND platform IN ('telegram', 'max')
          ORDER BY user_id, CASE WHEN platform='telegram' THEN 0 ELSE 1 END,
                   linked_at DESC NULLS LAST, created_at DESC, id DESC
        )
        UPDATE messenger_accounts m SET is_preferred = true
        FROM choice WHERE choice.id = m.id
    """))
    op.create_index(
        "uq_messenger_accounts_preferred", "messenger_accounts", ["user_id"],
        unique=True, postgresql_where=sa.text("is_preferred"),
    )
    op.create_index(
        "uq_messenger_accounts_deliverable_platform", "messenger_accounts",
        ["user_id", "platform"], unique=True,
        postgresql_where=sa.text("is_deliverable"),
    )


def downgrade() -> None:
    # The versioned course document is intentionally not rolled back: doing so could
    # reinterpret participant progress. Database columns can still be removed after
    # the application is rolled back and the production backup is restored.
    op.drop_constraint("uq_masterclass_step_progress_step", "masterclass_step_progress", type_="unique")
    op.create_unique_constraint(
        "uq_masterclass_step_progress", "masterclass_step_progress", ["user_id", "day_number", "step_index"]
    )
    op.drop_column("masterclass_step_progress", "step_id")
    op.drop_column("masterclass_notifications", "attempt_count")
    op.drop_column("masterclass_notifications", "expires_at")
    op.drop_column("user_course_policies", "course_policy_version")
    op.drop_index("uq_messenger_accounts_deliverable_platform", table_name="messenger_accounts")
    op.drop_index("uq_messenger_accounts_preferred", table_name="messenger_accounts")
    op.drop_column("messenger_accounts", "is_preferred")
    op.drop_column("messenger_accounts", "is_deliverable")
    op.drop_column("messenger_link_tokens", "intent_payload")
    op.drop_constraint("uq_account_sessions_browser_grant", "account_sessions", type_="unique")
    op.drop_constraint("fk_account_sessions_browser_grant", "account_sessions", type_="foreignkey")
    op.drop_column("account_sessions", "browser_grant_id")
    op.drop_index("ix_payment_browser_grants_expires", table_name="payment_browser_grants")
    op.drop_table("payment_browser_grants")
