#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
# Use the project's installed Python/entrypoint. First run defaults to demo.
if [ ! -f .env ]; then
    .venv/bin/campus-mail init --mode demo
fi
exec .venv/bin/campus-mail serve
