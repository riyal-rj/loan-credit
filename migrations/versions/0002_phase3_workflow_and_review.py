"""Phase 3: applications.documents, applications.status_projection, the new `review` schema
(review.review_queue_entries), and `applications.applications.active_workflow_id` -- the
persistence surface for durable-workflow orchestration, document upload, the reviewer-queue
stopgap, and the Kafka projection consumer (docs/adr/0011).

Revision ID: 0002_phase3_workflow_and_review
Revises: 0001_initial_schema
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase3_workflow_and_review"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE = "finassist_app"


def _enable_rls(schema: str, table: str) -> None:
    qualified = f"{schema}.{table}"
    op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {qualified} "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("active_workflow_id", sa.Text(), nullable=True),
        schema="applications",
    )

    op.create_table(
        "documents",
        sa.Column("document_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_document_size_positive"),
        schema="applications",
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"], schema="applications")
    op.create_index(
        "ix_documents_application_id", "documents", ["application_id"], schema="applications"
    )

    op.create_table(
        "status_projection",
        sa.Column("application_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="applications",
    )
    op.create_index(
        "ix_status_projection_tenant_id",
        "status_projection",
        ["tenant_id"],
        schema="applications",
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS review")
    op.create_table(
        "review_queue_entries",
        sa.Column("application_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column("entered_queue_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'decided')", name="ck_review_status_valid"),
        schema="review",
    )
    op.create_index(
        "ix_review_queue_entries_tenant_id",
        "review_queue_entries",
        ["tenant_id"],
        schema="review",
    )

    for schema, table in (
        ("applications", "documents"),
        ("applications", "status_projection"),
        ("review", "review_queue_entries"),
    ):
        _enable_rls(schema, table)

    # `integration.inbox_messages` was created schema-only by 0001; Phase 3's projection consumer
    # is its first real writer, so it needs the same RLS + grant treatment the other integration
    # tables already have. Not RLS'd: the consumer polls per-tenant like the outbox relay does
    # (docs/adr/0011), but a dedup key is (event_id, consumer_name), not tenant-scoped by itself --
    # RLS would need tenant_id on this table to be meaningful, which it deliberately does not carry
    # (the dedup guarantee is global per consumer, not per tenant). Grant only.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON integration.inbox_messages TO {_APP_ROLE}")

    op.execute(f"GRANT USAGE ON SCHEMA review TO {_APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON applications.documents TO {_APP_ROLE}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON applications.status_projection TO {_APP_ROLE}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON review.review_queue_entries TO {_APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_table("review_queue_entries", schema="review")
    op.execute("DROP SCHEMA IF EXISTS review")
    op.drop_table("status_projection", schema="applications")
    op.drop_table("documents", schema="applications")
    op.drop_column("applications", "active_workflow_id", schema="applications")
