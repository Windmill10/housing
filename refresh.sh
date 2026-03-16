#!/bin/bash
set -e
cd "$(dirname "$0")"

uv run main.py -c config.yaml --scrolls ${1:-30}

git add report.html
git diff --staged --quiet && echo "No changes to report." && exit 0
git commit -m "refresh: $(date '+%Y-%m-%d %H:%M')"
git push
