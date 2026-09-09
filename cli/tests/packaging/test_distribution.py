"""Build wheel from standalone sdist and exercise a clean installed entry point.

No Docker, repository-side imports, host tool installation, or publication.
Builds use uv's local backend; the isolated installation may download dependencies.
"""

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
REPOSITORY = PROJECT.parent


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Execute from an isolated working directory without checkout imports."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True, timeout=120)


@pytest.mark.packaging
def test_standalone_sdist_to_installed_wheel(tmp_path: Path) -> None:
    """A source distribution builds and installs without its parent repository."""
    assert (PROJECT / "LICENSE").read_bytes() == (REPOSITORY / "LICENSE").read_bytes()
    checkout = tmp_path / "checkout"
    shutil.copytree(
        REPOSITORY,
        checkout,
        ignore=shutil.ignore_patterns(
            ".git",
            ".env",
            ".venv",
            ".venv*",
            "dist",
            "_assets",
            "site",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
        ),
    )
    run(sys.executable, "cli/scripts/bundle_image_assets.py", cwd=checkout)
    dist = tmp_path / "dist"
    run("uv", "build", "--offline", "--out-dir", str(dist), str(checkout / "cli"), cwd=tmp_path)
    (sdist,) = dist.glob("*.tar.gz")
    source = tmp_path / "source"
    with tarfile.open(sdist) as archive:
        archive.extractall(source, filter="data")
    (project,) = source.iterdir()
    rebuilt = tmp_path / "rebuilt"
    run(
        "uv",
        "build",
        "--offline",
        "--wheel",
        "--out-dir",
        str(rebuilt),
        str(project),
        cwd=tmp_path,
    )
    (wheel,) = rebuilt.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert "agent_containers/cli.py" in archive.namelist()
        assert "agent_containers/_assets/agent-images/claude-code/Dockerfile" in archive.namelist()
        (metadata,) = (name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        dist_info = metadata.rsplit("/", 1)[0]
        assert f"{dist_info}/licenses/LICENSE" in archive.namelist()
        metadata_text = archive.read(metadata).decode()
        assert "Requires-Python: >=3.12" in metadata_text
        assert "License-Expression: MIT" in metadata_text
        assert "License-File: LICENSE" in metadata_text

    venv = tmp_path / "venv"
    run("uv", "venv", "--offline", "--python", sys.executable, str(venv), cwd=tmp_path)
    python = venv / "bin" / "python"
    run("uv", "pip", "install", "--python", str(python), str(wheel), cwd=tmp_path)
    script = venv / "bin" / "agent-containers"
    assert run(str(script), "--version", cwd=tmp_path).stdout.startswith("agent-containers ")
    assert "apply" in run(str(python), "-m", "agent_containers", cwd=tmp_path).stdout
