#!/usr/bin/env bash
# Cron job'larını kurar.
# Kullanım: bash deploy/setup_cron.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/venv/bin/python"
LOG_DIR="$ROOT/logs"

mkdir -p "$LOG_DIR"

# Türkiye saati (UTC+3) → UTC'ye dönüştürülmüş saatler:
#   Sabah çalışması  06:00 TR  → 03:00 UTC
#   Akşam çalışması  18:15 TR  → 15:15 UTC
#   Gece metrikler   23:00 TR  → 20:00 UTC

CRON_ENTRIES="
# fin-media-network — sabah pipeline (06:00 TR / 03:00 UTC)
0 3 * * * cd $ROOT && $PYTHON -m src.cli run >> $LOG_DIR/pipeline.log 2>&1

# fin-media-network — akşam pipeline (18:15 TR / 15:15 UTC)
15 15 * * * cd $ROOT && $PYTHON -m src.cli run >> $LOG_DIR/pipeline.log 2>&1

# fin-media-network — gece durum raporu (23:00 TR / 20:00 UTC)
0 20 * * * cd $ROOT && $PYTHON -m src.cli status >> $LOG_DIR/status.log 2>&1
"

# Mevcut crontab'a ekleme yap (çift eklemeyi önle)
TMPFILE=$(mktemp)
crontab -l 2>/dev/null > "$TMPFILE" || true

if grep -q "fin-media-network" "$TMPFILE"; then
  echo "Uyarı: crontab'da zaten fin-media-network girişi var. Atlanıyor."
  rm "$TMPFILE"
  exit 0
fi

echo "$CRON_ENTRIES" >> "$TMPFILE"
crontab "$TMPFILE"
rm "$TMPFILE"

echo "Cron job'lar kuruldu:"
crontab -l | grep "fin-media"
echo ""
echo "Loglar: $LOG_DIR/"
