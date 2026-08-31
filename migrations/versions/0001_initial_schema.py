"""Phase 1B initial schema: identity.tenants, applications.*, integration.*, audit.*, plus
row-level-security tenant isolation and a seeded demo tenant/product (docs/adr/0009,
docs/architecture/phase-0-assessment.md assumptions A1/A2).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "INTAKE_VALIDATION",
    "DOCUMENT_PROCESSING",
    "VERIFICATION",
    "POLICY_EVALUATION",
    "AFFORDABILITY_EVALUATION",
    "FRAUD_ANALYSIS",
    "RISK_SYNTHESIS",
    "AWAITING_HUMAN_REVIEW",
    "APPROVED",
    "DECLINED",
    "NEEDS_MORE_INFORMATION",
    "ESCALATED",
    "CANCELLED",
)

_DEMO_TENANT_ID = "00000000-0000-4000-8000-000000000001"
_DEMO_PRODUCT_ID = "00000000-0000-4000-8000-000000000002"

_APP_ROLE = "finassist_app"
_APP_ROLE_PASSWORD = "finassist_app"  # noqa: S105 # nosec B105 -- local-dev-only, see docs/adr/0009


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
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")
    op.execute("CREATE SCHEMA IF NOT EXISTS applications")
    op.execute("CREATE SCHEMA IF NOT EXISTS integration")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="identity",
    )

    op.create_table(
        "products",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("min_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("max_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("min_term_months", sa.Integer(), nullable=False),
        sa.Column("max_term_months", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("min_amount > 0 AND max_amount >= min_amount", name="ck_product_amount_bounds"),
        sa.CheckConstraint(
            "min_term_months >= 1 AND max_term_months >= min_term_months",
            name="ck_product_term_bounds",
        ),
        schema="applications",
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"], schema="applications")

    op.create_table(
        "applicants",
        sa.Column("applicant_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column("given_name", sa.Text(), nullable=False),
        sa.Column("family_name", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="applications",
    )
    op.create_index("ix_applicants_tenant_id", "applicants", ["tenant_id"], schema="applications")

    op.create_table(
        "applications",
        sa.Column("application_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "applicant_id",
            sa.Text(),
            sa.ForeignKey("applications.applicants.applicant_id"),
            nullable=False,
        ),
        sa.Column(
            "product_id", sa.Text(), sa.ForeignKey("applications.products.product_id"), nullable=False
        ),
        sa.Column("requested_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("requested_term_months", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("requested_amount > 0", name="ck_application_amount_positive"),
        sa.CheckConstraint("requested_term_months >= 1", name="ck_application_term_positive"),
        sa.CheckConstraint("version >= 1", name="ck_application_version_positive"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _APPLICATION_STATUSES) + ")",
            name="ck_application_status_valid",
        ),
        schema="applications",
    )
    op.create_index(
        "ix_applications_tenant_id", "applications", ["tenant_id"], schema="applications"
    )

    op.create_table(
        "application_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("requested_term_months", sa.Integer(), nullable=False),
        sa.Column("applicant_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("application_id", "version", name="uq_application_version"),
        schema="applications",
    )
    op.create_index(
        "ix_application_versions_application_id",
        "application_versions",
        ["application_id"],
        schema="applications",
    )
    op.create_index(
        "ix_application_versions_tenant_id",
        "application_versions",
        ["tenant_id"],
        schema="applications",
    )

    # Schema-only for Phase 1B: no command writes here yet (docs/adr/0009). Kept in the same
    # migration as the rest of the applications schema so the table exists per master
    # instruction §10.1 ahead of the intake consent-capture command that will populate it.
    op.create_table(
        "consent_records",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column("consent_type", sa.Text(), nullable=False),
        sa.Column("consent_version", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        schema="applications",
    )
    op.create_index(
        "ix_consent_records_tenant_id", "consent_records", ["tenant_id"], schema="applications"
    )

    op.create_table(
        "state_transitions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column("previous_status", sa.Text(), nullable=False),
        sa.Column("new_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        schema="applications",
    )
    op.create_index(
        "ix_state_transitions_application_id",
        "state_transitions",
        ["application_id"],
        schema="applications",
    )
    op.create_index(
        "ix_state_transitions_tenant_id", "state_transitions", ["tenant_id"], schema="applications"
    )

    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("causation_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="integration",
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"], schema="integration")
    op.create_index(
        "ix_outbox_events_published_at", "outbox_events", ["published_at"], schema="integration"
    )

    # Schema-only for Phase 1B: no consumer exists until Kafka lands in Phase 3 (docs/adr/0009
    # decision 3). Table created now so the outbox/inbox pattern is structurally complete.
    op.create_table(
        "inbox_messages",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("consumer_name", sa.Text(), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        schema="integration",
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("operation_name", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        schema="integration",
    )

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="audit",
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"], schema="audit")
    op.create_index(
        "ix_audit_events_aggregate_id", "audit_events", ["aggregate_id"], schema="audit"
    )

    op.create_table(
        "audit_hashes",
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("latest_event_id", sa.Text(), nullable=True),
        sa.Column("latest_hash", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="audit",
    )

    for schema, table in (
        ("applications", "products"),
        ("applications", "applicants"),
        ("applications", "applications"),
        ("applications", "application_versions"),
        ("applications", "consent_records"),
        ("applications", "state_transitions"),
        ("integration", "outbox_events"),
        ("integration", "idempotency_keys"),
        ("audit", "audit_events"),
        ("audit", "audit_hashes"),
    ):
        _enable_rls(schema, table)

    # The application must connect as a distinct, non-superuser, non-BYPASSRLS role: PostgreSQL
    # exempts superusers from row-level security even with FORCE ROW LEVEL SECURITY, so the
    # migration role (a superuser locally) can never double as the runtime role (docs/adr/0009).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                CREATE ROLE {_APP_ROLE} WITH LOGIN PASSWORD '{_APP_ROLE_PASSWORD}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA identity, applications, integration, audit TO {_APP_ROLE}")
    op.execute(f"GRANT SELECT ON identity.tenants TO {_APP_ROLE}")
    for schema in ("applications", "integration", "audit"):
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {_APP_ROLE}"
        )

    op.execute(
        sa.text(
            "INSERT INTO identity.tenants (tenant_id, name, created_at) "
            "VALUES (:tenant_id, :name, now())"
        ).bindparams(tenant_id=_DEMO_TENANT_ID, name="demo-bank")
    )
    op.execute(
        sa.text(
            "SELECT set_config('app.tenant_id', :tenant_id, false)"
        ).bindparams(tenant_id=_DEMO_TENANT_ID)
    )
    op.execute(
        sa.text(
            "INSERT INTO applications.products "
            "(product_id, tenant_id, code, name, currency, min_amount, max_amount, "
            "min_term_months, max_term_months, is_active, created_at) "
            "VALUES (:product_id, :tenant_id, :code, :name, :currency, :min_amount, "
            ":max_amount, :min_term_months, :max_term_months, true, now())"
        ).bindparams(
            product_id=_DEMO_PRODUCT_ID,
            tenant_id=_DEMO_TENANT_ID,
            code="PERSONAL_LOAN_USD",
            name="Unsecured Personal Loan (USD)",
            currency="USD",
            min_amount=1000.00,
            max_amount=25000.00,
            min_term_months=6,
            max_term_months=60,
        )
    )


def downgrade() -> None:
    op.drop_table("audit_hashes", schema="audit")
    op.drop_table("audit_events", schema="audit")
    op.drop_table("idempotency_keys", schema="integration")
    op.drop_table("inbox_messages", schema="integration")
    op.drop_table("outbox_events", schema="integration")
    op.drop_table("state_transitions", schema="applications")
    op.drop_table("consent_records", schema="applications")
    op.drop_table("application_versions", schema="applications")
    op.drop_table("applications", schema="applications")
    op.drop_table("applicants", schema="applications")
    op.drop_table("products", schema="applications")
    op.drop_table("tenants", schema="identity")
    op.execute("DROP SCHEMA IF EXISTS audit CASCADE")
    op.execute("DROP SCHEMA IF EXISTS integration CASCADE")
    op.execute("DROP SCHEMA IF EXISTS applications CASCADE")
    op.execute("DROP SCHEMA IF EXISTS identity CASCADE")
    op.execute(f"DROP ROLE IF EXISTS {_APP_ROLE}")
