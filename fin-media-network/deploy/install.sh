#!/usr/bin/env bash
# fin-media-network kurulum betiği
# Kullanım: bash deploy/install.sh [--prod]
set -euo pipefail

PROD=false
[[ "${1:-}" == "--prod" ]] && PROD=true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> fin-media-network kurulum başlıyor: $ROOT"

# ── Python sürüm kontrolü ─────────────────────────────────────────────────────
python_ver=$(python3 --version 2>&1 | awk '{print $2}')
required="3.11"
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"; then
  echo "HATA: Python $required+ gerekli (mevcut: $python_ver)"
  exit 1
fi
echo "  Python $python_ver ✓"

# ── Sanal ortam ───────────────────────────────────────────────────────────────
if [[ ! -d venv ]]; then
  python3 -m venv venv
  echo "  venv oluşturuldu ✓"
fi
source venv/bin/activate

# ── Bağımlılıklar ─────────────────────────────────────────────────────────────
pip install --quiet --upgrade pip
if $PROD; then
  pip install --quiet -e .
else
  pip install --quiet -e ".[dev]"
fi
echo "  Bağımlılıklar kuruldu ✓"

# ── Çevre değişkenleri ────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "  .env oluşturuldu — lütfen API anahtarlarını doldurun: $ROOT/.env"
else
  echo "  .env zaten mevcut ✓"
fi

# ── Çıktı dizini ─────────────────────────────────────────────────────────────
mkdir -p output
echo "  output/ dizini hazır ✓"

# ── Veritabanı başlatma ───────────────────────────────────────────────────────
python -m src.cli init-db
echo "  Veritabanı başlatıldı ✓"

# ── Test çalıştırma (prod'da atla) ────────────────────────────────────────────
if ! $PROD; then
  echo "==> Testler çalıştırılıyor…"
  python -m pytest tests/ -q --tb=short
  echo "  Tüm testler geçti ✓"
fi

echo ""
echo "==> Kurulum tamamlandı."
echo ""
echo "  Sonraki adımlar:"
echo "  1. $ROOT/.env dosyasını API anahtarlarıyla doldurun"
echo "  2. Tek seferlik çalıştırmak için:"
echo "       source venv/bin/activate && python -m src.cli run"
echo "  3. Zamanlayıcıyı başlatmak için:"
echo "       source venv/bin/activate && python -m src.cli scheduled"
echo "  4. Cron kurulumu için:"
echo "       bash deploy/setup_cron.sh"
