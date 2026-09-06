"""Generate package data from canonical repository image contexts.

Run this before uv build. The generated destination is ignored and is never a
second maintained source of truth.
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY_ROOT / "agent-images"
DESTINATION = REPOSITORY_ROOT / "cli" / "src" / "agent_containers" / "_assets" / "agent-images"


def main() -> None:
    """Replace generated package data with a complete canonical snapshot."""
    if not SOURCE.is_dir():
        raise SystemExit(f"canonical image directory does not exist: {SOURCE}")
    staging = DESTINATION.parent / ".agent-images-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(SOURCE, staging / "agent-images", symlinks=False)
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    staging.joinpath("agent-images").replace(DESTINATION)
    staging.rmdir()


if __name__ == "__main__":
    main()
