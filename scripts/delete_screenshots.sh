#!/usr/bin/env bash
# デスクトップのスクリーンショット画像を削除する
# 対象: macOS / Linux の一般的なスクリーンショットファイル名パターン

set -euo pipefail

DESKTOP="${HOME}/Desktop"
LOG_DIR="${HOME}/.local/share/delete-screenshots"
LOG_FILE="${LOG_DIR}/delete_screenshots.log"
DRY_RUN="${DRY_RUN:-false}"

mkdir -p "${LOG_DIR}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

if [[ ! -d "${DESKTOP}" ]]; then
  log "WARN: Desktop directory not found: ${DESKTOP} — nothing to do."
  exit 0
fi

# macOS: "Screenshot YYYY-MM-DD at HH.MM.SS.png"
# macOS (日本語): "スクリーンショット YYYY-MM-DD HH.MM.SS.png"
# GNOME: "Screenshot from YYYY-MM-DD HH-MM-SS.png"
# KDE / Spectacle: "Screenshot_YYYYMMDD_HHMMSS.png"
PATTERNS=(
  "Screenshot*.png"
  "Screenshot*.jpg"
  "スクリーンショット*.png"
  "スクリーンショット*.jpg"
  "Screenshot_*.png"
  "Screenshot_*.jpg"
)

total=0

for pattern in "${PATTERNS[@]}"; do
  while IFS= read -r -d '' file; do
    if [[ "${DRY_RUN}" == "true" ]]; then
      log "DRY-RUN: would delete: ${file}"
    else
      rm -f "${file}"
      log "Deleted: ${file}"
    fi
    ((total++)) || true
  done < <(find "${DESKTOP}" -maxdepth 1 -name "${pattern}" -print0 2>/dev/null)
done

if [[ ${total} -eq 0 ]]; then
  log "No screenshot files found on Desktop."
else
  log "Done. ${total} file(s) processed."
fi
