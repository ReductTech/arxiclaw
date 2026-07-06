"""arxiclaw-agent scripts package.

This file is executed whenever ``scripts`` is imported as a package — that
happens for every entry point declared in ``pyproject.toml``'s
``[project.scripts]`` table (e.g. ``arxiclaw-daily``, ``arxiclaw-doctor``,
``arxiclaw-install``). It is *not* executed when the user invokes a script
directly (``python scripts/daily_runner.py``), because in that mode each
script runs as ``__main__`` and this package is never imported.

Why this bootstrap exists
=========================

Inside the scripts we use absolute, top-level imports between sibling modules
(``import engagement as _eng`` from ``daily_runner.py``,
``from home import build_home`` from ``daily_runner.py``,
``import engagement as eng`` from ``home.py`` / ``behavior_report.py``).
This works for direct script invocation because the script's own directory
(``scripts/``) is automatically inserted at ``sys.path[0]`` by the Python
launcher.

When the package is installed (``pip install -e .`` or otherwise), the entry
points invoke ``scripts.daily_runner:main`` etc. as package members, so
``scripts/`` is **not** on ``sys.path`` — only the install site-packages
directory is. The top-level absolute imports then raise
``ModuleNotFoundError``.

To keep the existing import style (no rewrite of hundreds of
``import engagement as _eng`` lines) and to support both invocation modes,
we add ``scripts/`` to ``sys.path`` here. The cost is one extra path entry
when the package is loaded as a package; the benefit is that all the lazy
intra-package imports inside ``daily_runner.py`` / ``home.py`` /
``behavior_report.py`` continue to resolve identically in both modes.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
