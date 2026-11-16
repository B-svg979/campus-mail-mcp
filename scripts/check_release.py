"""Fail if tracked files include mailbox data, local paths or recognizable secret tokens."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    names = [name for name in raw.decode().split("\0") if name]
    if not names:
        raise SystemExit("No tracked release files to check")
    issues = []
    secret_patterns = [
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        rb"gh[pousr]_[A-Za-z0-9]{32,}",
        rb"github_pat_[A-Za-z0-9_]{35,}",
        rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}",
        rb"AKIA[A-Z0-9]{16}",
    ]
    for name in names:
        path = Path(name)
        if (
            (path.name.startswith(".env") and path.name != ".env.example")
            or path.suffix in {".sqlite", ".sqlite3", ".db", ".eml", ".log", ".whl", ".zip"}
            or any(part in {"data", "mail-import", ".venv", "__pycache__"}
                   or part.startswith("data-") for part in path.parts)
        ):
            issues.append(f"{name}: forbidden release file")
            continue
        data = (root / name).read_bytes()
        if any(re.search(pattern, data) for pattern in secret_patterns):
            issues.append(f"{name}: possible secret (value omitted)")
        if re.search(rb"/Users/[A-Za-z0-9_.-]+/", data):
            issues.append(f"{name}: author-specific absolute path")
    if issues:
        raise SystemExit("\n".join(issues))
    print(f"Checked {len(names)} tracked files: no forbidden files or matching secret patterns")


if __name__ == "__main__":
    main()
