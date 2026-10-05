"""Temporary workspaces and rollback-safe directory replacement."""

import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

TEMP_ROOT = Path(__file__).resolve().parents[2] / "tmp"


@contextmanager
def publish_workspace(target, prefix):
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=prefix, dir=TEMP_ROOT))
    try:
        yield work
    finally:
        if (work / "backup").exists() and not target.exists():
            # A second filesystem failure must not delete the only good copy.
            print(f"回滚未完成，保留原目录：{work / 'backup'}", file=sys.stderr)
        else:
            shutil.rmtree(work)


def replace_directory(staged, target, backup):
    """Restore the previous directory if publishing raises an exception."""
    existed = target.exists()
    if existed:
        target.replace(backup)
    try:
        staged.replace(target)
    except BaseException:
        if existed:
            backup.replace(target)
        raise


