"""Build both wheels from source without downloading or embedding credentials."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    core = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    platform = tomllib.loads(
        (root / "platform/pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    if core["version"] != platform["version"]:
        raise SystemExit("Core and platform versions must match")
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    name = f"campus_mail_mcp-{core['version']}-py3-none-any.whl"
    # Fresh staging excludes previous wheel versions and setuptools' cached build/lib.
    with tempfile.TemporaryDirectory(prefix="campus-mail-build-") as temporary:
        for label, project in [("core", root), ("platform", root / "platform")]:
            staged = Path(temporary) / label
            staged.mkdir()
            for metadata in ["pyproject.toml", "README.md", "LICENSE"]:
                if (project / metadata).is_file():
                    shutil.copy2(project / metadata, staged / metadata)
            shutil.copytree(
                project / "src", staged / "src",
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "*.egg-info", "*.whl", "wheel.sha256"
                ),
            )
            if label == "platform":
                wheel = dist / name
                package = staged / "src/campus_mail_platform"
                shutil.copy2(wheel, package / name)
                (package / "wheel.sha256").write_text(
                    hashlib.sha256(wheel.read_bytes()).hexdigest() + "\n", encoding="ascii"
                )
            subprocess.run([
                sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                "--no-index", "--wheel-dir", str(dist), str(staged),
            ], check=True)
    output = dist / f"campus_mail_platform-{platform['version']}-py3-none-any.whl"
    with zipfile.ZipFile(output) as bundle:
        embedded = [item for item in bundle.namelist() if item.endswith(".whl")]
        if embedded != [f"campus_mail_platform/{name}"]:
            raise SystemExit("Unexpected embedded core wheel; do not publish")
        if hashlib.sha256(bundle.read(embedded[0])).hexdigest() != bundle.read(
            "campus_mail_platform/wheel.sha256"
        ).decode().strip():
            raise SystemExit("Embedded core checksum mismatch; do not publish")
    print(f"Built core and standalone platform wheels in {dist}")


if __name__ == "__main__":
    main()
