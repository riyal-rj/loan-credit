"""Synthetic data generation for the mock enterprise ecosystem (Phase 2).

Deliberately kept outside `src/finassist/`: this package generates *fake* applicants, bureau
reports, KYC results, employer verifications, transaction histories, and documents for the mock
services under `services/mock-*` and for demo/evaluation seeding. None of it is part of the real
underwriting platform's domain model -- it is the synthetic *world* that platform is tested
against (master instruction §4: "Use synthetic applicant data ... for this portfolio/PoC").

Every generator is deterministic given the same `(scenario_id, index)` pair (`rng.py`), so a
scenario replays identically across test runs, demo seeding, and evaluation datasets.
"""
