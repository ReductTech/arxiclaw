"""Shared pytest fixtures + sys.path setup for the test suite.

Makes the `scripts/` directory importable so `import engagement`,
`import home`, `import behavior_report` work from any test file.
"""
import sys
from pathlib import Path

# Add scripts/ to sys.path (insert at front so it shadows any system
# packages of the same name).
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def pytest_configure(config):
    """Hook: log a warning if scripts/ can't be imported (e.g. missing
    requests). The test suite itself is pure-Python (engagement /
    behavior_report / home), so it should not need network libs."""
    try:
        import engagement  # noqa: F401
        import home  # noqa: F401
        import behavior_report  # noqa: F401
    except ImportError as exc:
        print(
            f"\n[conftest] WARNING: scripts/ import failed: {exc}\n"
            f"[conftest] Some tests may skip. Run: pip install -r requirements.txt\n"
        )
