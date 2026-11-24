"""A process that imports only part of the app must still know every table.

The API imports everything through its routers; a worker does not. These run in a fresh
interpreter because inside the test session everything is already imported, which hides the bug.
"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _run(code: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip()


def _tables(entry: str) -> str:
    return _run(
        f"import {entry}\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "from app.db.base import Base\n"
        "configure_mappers()\n"
        "print(','.join(sorted(Base.metadata.tables)))"
    )


def test_theWorkerAloneKnowsEveryTableTheApiKnows() -> None:
    worker = _tables("app.worker.tasks")
    assert worker == _tables("app.main")
    assert "workspaces" in worker.split(",") and "chunk_embeddings" in worker.split(",")


def test_everyModulesModelsAreRegisteredInTheOnePlace() -> None:
    on_disk = sorted(path.parent.name for path in (BACKEND / "app/modules").glob("*/models.py"))
    registered = _run(
        "import sys\n"
        "import app.db.models\n"
        "print(','.join(sorted(name.split('.')[2] for name in sys.modules\n"
        "    if name.startswith('app.modules.') and name.endswith('.models'))))"
    )
    assert registered.split(",") == on_disk, "add the new module's models to app/db/models.py"
