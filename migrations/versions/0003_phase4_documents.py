"""Phase 4: `documents` schema (extraction_runs, extracted_facts, fact_candidates,
document_checksums) and `verification` schema (verification_runs, verification_checks,
contradictions, external_response_snapshots) -- master instruction §10.1's exact table list for
document intelligence and cross-source verification (docs/adr/0012).

`fact_candidates` and `document_checksums` are schema-only in Phase 4, same pattern as Phase 1B's
`consent_records`: the deterministic regex extractor never produces competing candidates or needs
cross-application duplicate detection, so there is no writer yet -- the table exists ahead of the
phase that adds one, per docs/adr/0009 decision on "code with no caller."

Revision ID: 0003_phase4_documents
Revises: 0002_phase3_workflow_and_review
Create Date: 2026-08-31

Revision IDs must stay at or under 32 characters: Alembic's default `alembic_version.version_num`
column is `VARCHAR(32)`, and the first draft of this migration (`0003_phase4_documents_and_
verification`, 38 chars) failed `alembic upgrade head` with a real `StringDataRightTruncationError`
-- caught by this project's own integration test suite, not by review. `0002_phase3_workflow_and_
review` (32 chars exactly) was already at the limit; this one stays comfortably under it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase4_documents"
down_revision: str | None = "0002_phase3_workflow_and_review"
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
    op.execute("CREATE SCHEMA IF NOT EXISTS documents")
    op.execute("CREATE SCHEMA IF NOT EXISTS verification")

    op.create_table(
        "extraction_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("applications.documents.document_id"),
            nullable=False,
        ),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        schema="documents",
    )
    op.create_index(
        "ix_extraction_runs_tenant_id", "extraction_runs", ["tenant_id"], schema="documents"
    )
    op.create_index(
        "ix_extraction_runs_application_id",
        "extraction_runs",
        ["application_id"],
        schema="documents",
    )

    op.create_table(
        "extracted_facts",
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column(
            "run_id", sa.Text(), sa.ForeignKey("documents.extraction_runs.run_id"), nullable=False
        ),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("applications.documents.document_id"),
            nullable=False,
        ),
        sa.Column("fact_type", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("extraction_method", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("source_checksum", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="extracted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_fact_confidence"),
        sa.CheckConstraint(
            "status IN ('extracted', 'verified', 'contradicted', 'superseded', 'human_confirmed')",
            name="ck_fact_status_valid",
        ),
        schema="documents",
    )
    op.create_index(
        "ix_extracted_facts_tenant_id", "extracted_facts", ["tenant_id"], schema="documents"
    )
    op.create_index(
        "ix_extracted_facts_application_id",
        "extracted_facts",
        ["application_id"],
        schema="documents",
    )

    # Schema-only for Phase 4 (see module docstring).
    op.create_table(
        "fact_candidates",
        sa.Column("candidate_id", sa.Text(), primary_key=True),
        sa.Column(
            "fact_id", sa.Text(), sa.ForeignKey("documents.extracted_facts.fact_id"), nullable=False
        ),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extraction_method", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="documents",
    )

    # Schema-only for Phase 4 (see module docstring).
    op.create_table(
        "document_checksums",
        sa.Column("checksum_sha256", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("applications.documents.document_id"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        schema="documents",
    )

    op.create_table(
        "verification_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column("check_count", sa.Integer(), nullable=False),
        sa.Column("contradiction_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        schema="verification",
    )
    op.create_index(
        "ix_verification_runs_tenant_id", "verification_runs", ["tenant_id"], schema="verification"
    )
    op.create_index(
        "ix_verification_runs_application_id",
        "verification_runs",
        ["application_id"],
        schema="verification",
    )

    op.create_table(
        "verification_checks",
        sa.Column("check_id", sa.Text(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Text(),
            sa.ForeignKey("verification.verification_runs.run_id"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("checked_fact_type", sa.Text(), nullable=False),
        sa.Column("declared_value", sa.Text(), nullable=True),
        sa.Column("external_value", sa.Text(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "verdict IN ('MATCHED', 'CONTRADICTED', 'INSUFFICIENT_EVIDENCE')",
            name="ck_verification_verdict_valid",
        ),
        schema="verification",
    )
    op.create_index(
        "ix_verification_checks_tenant_id",
        "verification_checks",
        ["tenant_id"],
        schema="verification",
    )
    op.create_index(
        "ix_verification_checks_application_id",
        "verification_checks",
        ["application_id"],
        schema="verification",
    )

    op.create_table(
        "contradictions",
        sa.Column("contradiction_id", sa.Text(), primary_key=True),
        sa.Column(
            "check_id",
            sa.Text(),
            sa.ForeignKey("verification.verification_checks.check_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("checked_fact_type", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="verification",
    )
    op.create_index(
        "ix_contradictions_application_id",
        "contradictions",
        ["application_id"],
        schema="verification",
    )

    op.create_table(
        "external_response_snapshots",
        sa.Column("snapshot_id", sa.Text(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Text(),
            sa.ForeignKey("verification.verification_runs.run_id"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id", sa.Text(), sa.ForeignKey("identity.tenants.tenant_id"), nullable=False
        ),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.applications.application_id"),
            nullable=False,
        ),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        schema="verification",
    )
    op.create_index(
        "ix_external_response_snapshots_application_id",
        "external_response_snapshots",
        ["application_id"],
        schema="verification",
    )

    for schema, table in (
        ("documents", "extraction_runs"),
        ("documents", "extracted_facts"),
        ("documents", "fact_candidates"),
        ("documents", "document_checksums"),
        ("verification", "verification_runs"),
        ("verification", "verification_checks"),
        ("verification", "contradictions"),
        ("verification", "external_response_snapshots"),
    ):
        _enable_rls(schema, table)

    op.execute(f"GRANT USAGE ON SCHEMA documents, verification TO {_APP_ROLE}")
    for schema, table in (
        ("documents", "extraction_runs"),
        ("documents", "extracted_facts"),
        ("documents", "fact_candidates"),
        ("documents", "document_checksums"),
        ("verification", "verification_runs"),
        ("verification", "verification_checks"),
        ("verification", "contradictions"),
        ("verification", "external_response_snapshots"),
    ):
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.{table} TO {_APP_ROLE}"
        )


def downgrade() -> None:
    op.drop_table("external_response_snapshots", schema="verification")
    op.drop_table("contradictions", schema="verification")
    op.drop_table("verification_checks", schema="verification")
    op.drop_table("verification_runs", schema="verification")
    op.drop_table("document_checksums", schema="documents")
    op.drop_table("fact_candidates", schema="documents")
    op.drop_table("extracted_facts", schema="documents")
    op.drop_table("extraction_runs", schema="documents")
    op.execute("DROP SCHEMA IF EXISTS verification")
    op.execute("DROP SCHEMA IF EXISTS documents")
