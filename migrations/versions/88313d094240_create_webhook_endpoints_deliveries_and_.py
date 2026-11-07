"""create webhook endpoints deliveries and outbox tables

Revision ID: 88313d094240
Revises: e6d71bfc8f8a
Create Date: 2026-11-08 00:10:49.374566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88313d094240'
down_revision: Union[str, Sequence[str], None] = 'e6d71bfc8f8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("encrypted_signing_secret", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_webhook_endpoints_project_id_projects", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_endpoints"),
    )
    op.create_index("ix_webhook_endpoints_project_id", "webhook_endpoints", ["project_id"])

    op.create_table(
        "endpoint_subscriptions",
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["webhook_endpoints.id"],
            name="fk_endpoint_subscriptions_endpoint_id_webhook_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("endpoint_id", "event_type", name="pk_endpoint_subscriptions"),
    )
    op.create_index("ix_endpoint_subscriptions_event_type", "endpoint_subscriptions", ["event_type"])

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name="fk_deliveries_event_id_events", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["webhook_endpoints.id"],
            name="fk_deliveries_endpoint_id_webhook_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deliveries"),
        sa.UniqueConstraint("event_id", "endpoint_id", name="uq_deliveries_event_id_endpoint_id"),
    )
    op.create_index("ix_deliveries_status_next_retry_at", "deliveries", ["status", "next_retry_at"])
    op.create_index("ix_deliveries_endpoint_id_created_at", "deliveries", ["endpoint_id", "created_at"])

    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["delivery_id"], ["deliveries.id"], name="fk_outbox_messages_delivery_id_deliveries", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_messages"),
    )
    op.create_index("ix_outbox_messages_delivery_id", "outbox_messages", ["delivery_id"])
    op.create_index("ix_outbox_messages_status_created_at", "outbox_messages", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_status_created_at", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_delivery_id", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index("ix_deliveries_endpoint_id_created_at", table_name="deliveries")
    op.drop_index("ix_deliveries_status_next_retry_at", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("ix_endpoint_subscriptions_event_type", table_name="endpoint_subscriptions")
    op.drop_table("endpoint_subscriptions")
    op.drop_index("ix_webhook_endpoints_project_id", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")