"""SQLAlchemy 2.0 declarative ORM models -- the only place the applications bounded context's
domain model is translated to/from relational rows.

Deliberately separate from `finassist.domain.applications.*`: the domain layer has zero
SQLAlchemy imports (enforced by the import-linter contract in `pyproject.toml`).
`SqlAlchemyApplicationRepository`/`SqlAlchemyApplicantRepository` (`repository.py`) do the
translation both ways.

Only tables with an active read/write code path in Phase 1B are ORM-mapped here. `identity.
tenants`, `applications.consent_records`, and `integration.inbox_messages` exist as real tables
(created by the Alembic migration) but have no ORM class yet -- consent capture and the inbox
consumer are Phase 3+ concerns (docs/adr/0009); mapping them now would be exactly the "code with
no caller" premature abstraction the coding standards warn against.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # Every `Mapped[datetime]` column defaults to TIMESTAMPTZ, matching what the Alembic
    # migration actually creates. Without this, SQLAlchemy's default type-annotation mapping for
    # `datetime.datetime` is a *naive* DateTime, which asyncpg then rejects tz-aware Python
    # datetimes against (a real bug this project hit and fixed during Phase 1B integration
    # testing -- see docs/architecture/phase-1b-completion.md).
    type_annotation_map = {datetime: DateTime(timezone=True)}


# `identity.tenants` has no ORM-mapped class (nothing queries it in Phase 1B -- see the module
# docstring), but it must still be registered as a `Table` on `Base.metadata` so SQLAlchemy can
# resolve the `ForeignKey("identity.tenants.tenant_id")` references below and compute a correct
# insert ordering. This is Core-level table registration, not an ORM entity.
identity_tenants_table = Table(
    "tenants",
    Base.metadata,
    Column("tenant_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema="identity",
)


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "applications"}

    product_id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("identity.tenants.tenant_id"), index=True)
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    currency: Mapped[str]
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    min_term_months: Mapped[int]
    max_term_months: Mapped[int]
    is_active: Mapped[bool]
    created_at: Mapped[datetime]


class ApplicantRow(Base):
    __tablename__ = "applicants"
    __table_args__ = {"schema": "applications"}

    applicant_id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("identity.tenants.tenant_id"), index=True)
    given_name: Mapped[str]
    family_name: Mapped[str]
    date_of_birth: Mapped[date]
    email: Mapped[str]
    created_at: Mapped[datetime]


class ApplicationRow(Base):
    __tablename__ = "applications"
    __table_args__ = {"schema": "applications"}

    application_id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("identity.tenants.tenant_id"), index=True)
    applicant_id: Mapped[str] = mapped_column(ForeignKey("applications.applicants.applicant_id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("applications.products.product_id"))
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str]
    requested_term_months: Mapped[int]
    status: Mapped[str]
    version: Mapped[int]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ApplicationVersionRow(Base):
    """One immutable row per version of an `Application`, per docs/adr/0009: a full snapshot at
    the moment of each save, so a historical version can be replayed bit-for-bit (invariant
    §5.11) independent of `state_transitions`, which records only the state-machine narrative."""

    __tablename__ = "application_versions"
    __table_args__ = (
        UniqueConstraint("application_id", "version"),
        {"schema": "applications"},
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.applications.application_id"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("identity.tenants.tenant_id"), index=True)
    version: Mapped[int]
    status: Mapped[str]
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str]
    requested_term_months: Mapped[int]
    applicant_id: Mapped[str]
    product_id: Mapped[str]
    recorded_at: Mapped[datetime]


class StateTransitionRow(Base):
    __tablename__ = "state_transitions"
    __table_args__ = {"schema": "applications"}

    id: Mapped[str] = mapped_column(primary_key=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.applications.application_id"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("identity.tenants.tenant_id"), index=True)
    previous_status: Mapped[str]
    new_status: Mapped[str]
    reason: Mapped[str]
    occurred_at: Mapped[datetime]


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "integration"}

    event_id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(index=True)
    event_type: Mapped[str]
    schema_version: Mapped[int]
    occurred_at: Mapped[datetime]
    aggregate_type: Mapped[str]
    aggregate_id: Mapped[str]
    correlation_id: Mapped[str | None]
    causation_id: Mapped[str | None]
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class IdempotencyKeyRow(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": "integration"}

    tenant_id: Mapped[str] = mapped_column(primary_key=True)
    operation_name: Mapped[str] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(primary_key=True)
    reserved_at: Mapped[datetime]


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = {"schema": "audit"}

    event_id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(index=True)
    occurred_at: Mapped[datetime]
    event_type: Mapped[str]
    aggregate_type: Mapped[str]
    aggregate_id: Mapped[str]
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    correlation_id: Mapped[str | None]
    prev_hash: Mapped[str]
    hash: Mapped[str]
    created_at: Mapped[datetime]


class AuditHashRow(Base):
    """Per-tenant checkpoint anchor for the `audit_events` hash chain (docs/adr/0009 decision 2)."""

    __tablename__ = "audit_hashes"
    __table_args__ = {"schema": "audit"}

    tenant_id: Mapped[str] = mapped_column(primary_key=True)
    latest_event_id: Mapped[str | None]
    latest_hash: Mapped[str]
    updated_at: Mapped[datetime]
