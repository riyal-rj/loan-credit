"""Loads each `services/mock-*/main.py` FastAPI app for contract testing.

Those directories are hyphenated (matching the master instruction's repository tree literally),
so they can't be dotted-imported (`services.mock-kyc` is not valid Python). Each is instead loaded
by file path under a unique module name via `importlib`, which sidesteps both the hyphen problem
and any risk of two services' `main` modules colliding in `sys.modules`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "services"


def load_mock_app(service_dir_name: str) -> FastAPI:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    module_alias = f"_mock_service_{service_dir_name.replace('-', '_')}"
    main_path = SERVICES_DIR / service_dir_name / "main.py"
    spec = importlib.util.spec_from_file_location(module_alias, main_path)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[module_alias] = module
    spec.loader.exec_module(module)
    app = module.app
    assert isinstance(app, FastAPI)
    return app
