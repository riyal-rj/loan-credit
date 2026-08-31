"""Domain exceptions for the applications bounded context.

API-layer mapping to RFC 9457 problem details happens in `finassist.api.error_handling`, not
here -- these carry no HTTP concerns.
"""

from __future__ import annotations

from finassist.domain.applications.status import ApplicationStatus


class IllegalStateTransitionError(RuntimeError):
    """Raised when code attempts a transition not present in `status.ALLOWED_TRANSITIONS`."""

    def __init__(self, source: ApplicationStatus, target: ApplicationStatus) -> None:
        super().__init__(f"cannot transition application from {source.value} to {target.value}")
        self.source = source
        self.target = target


class ConcurrencyConflictError(RuntimeError):
    """Raised when a repository save is attempted against a stale aggregate version.

    Maps to HTTP 409 at the API boundary (§11: "Return 409 for state/version conflicts").
    """

    def __init__(self, application_id: str, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"application {application_id} version conflict: expected {expected_version}, "
            f"found {actual_version}"
        )
        self.application_id = application_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class InvalidApplicationDataError(ValueError):
    """Raised when application creation data violates a domain invariant (e.g. non-positive
    requested amount, unknown product)."""


class ApplicationNotFoundError(LookupError):
    """Raised when a command/query references an `application_id` that does not exist for the
    requesting tenant (including one that exists for a *different* tenant -- RLS makes that
    indistinguishable from not existing, which is the point)."""

    def __init__(self, application_id: str) -> None:
        super().__init__(f"application {application_id} does not exist")
        self.application_id = application_id


class ProductNotFoundError(LookupError):
    """Raised when a command references a `product_id` that does not exist in the catalog."""

    def __init__(self, product_id: str) -> None:
        super().__init__(f"product {product_id} does not exist")
        self.product_id = product_id


class ProductRejectedRequestError(ValueError):
    """Raised when the requested amount/term falls outside the product's catalog bounds.

    Not a policy decision (Phase 5 owns those) -- this is the coarse intake-level check described
    in `finassist.domain.applications.product.Product.accepts`.
    """

    def __init__(self, product_id: str, amount: str, term_months: int) -> None:
        super().__init__(
            f"product {product_id} does not accept amount={amount} term_months={term_months}"
        )
        self.product_id = product_id


class DuplicateRequestError(RuntimeError):
    """Raised when a command's idempotency key has already been reserved.

    Signals the caller made the same request twice (client retry, network duplicate); the correct
    caller response is to look up the prior outcome rather than treat this as a new failure.
    """

    def __init__(self, operation_name: str, idempotency_key: str) -> None:
        super().__init__(
            f"operation {operation_name!r} already processed for idempotency key "
            f"{idempotency_key!r}"
        )
        self.operation_name = operation_name
        self.idempotency_key = idempotency_key
