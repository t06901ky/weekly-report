#!/usr/bin/env bash
# delete_screenshots.sh を毎晩 23:00 (JST) に実行する cron ジョブを登録する
# 実行時刻: 23:00 JST = 14:00 UTC

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${SCRIPT_DIR}/delete_screenshots.sh"

if [[ ! -x "${TARGET}" ]]; then
  chmod +x "${TARGET}"
fi

CRON_ENTRY="0 14 * * * ${TARGET} >> \${HOME}/.local/share/delete-screenshots/delete_screenshots.log 2>&1"

# 既存の同一エントリがあれば追加しない
if crontab -l 2>/dev/null | grep -qF "${TARGET}"; then
  echo "Cron job already registered: ${TARGET}"
else
  (crontab -l 2>/dev/null; echo "${CRON_ENTRY}") | crontab -
  echo "Cron job registered: ${CRON_ENTRY}"
fi

echo ""
echo "Current crontab:"
crontab -l
