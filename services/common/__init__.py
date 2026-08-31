"""Shared FastAPI plumbing for the mock enterprise services (Phase 2): scenario resolution,
deterministic fault injection, and health endpoints. Every `services/mock-*` service depends on
this instead of reimplementing the same header-parsing/fault logic five times.
"""
