"""finassist.infrastructure.external_systems package: httpx-based adapters for the Phase 2 mock
KYC/bureau/employer/core-banking services (Phase 4, docs/adr/0012). Every adapter uses explicit,
short timeouts and no automatic retries -- the same lesson `S3ObjectStore` already learned the hard
way in Phase 2 (docs/adr/0010 decision 7): library-default timeouts are not acceptable.
"""
