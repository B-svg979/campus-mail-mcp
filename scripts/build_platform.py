"""Build both wheels from source without downloading or embedding credentials."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tomllib
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
    for project in [root, root / "platform"]:
        if project.name == "platform":
            name = f"campus_mail_mcp-{core['version']}-py3-none-any.whl"
            wheel = dist / name
            package = project / "src/campus_mail_platform"
            shutil.copy2(wheel, package / name)
            (package / "wheel.sha256").write_text(
                hashlib.sha256(wheel.read_bytes()).hexdigest() + "\n", encoding="ascii"
            )
        subprocess.run([
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "--no-index", "--wheel-dir", str(dist), str(project),
        ], check=True)
    print(f"Built core and standalone platform wheels in {dist}")


if __name__ == "__main__":
    main()
