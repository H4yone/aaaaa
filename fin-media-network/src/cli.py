"""
fin-media-network CLI

Kullanım:
  python -m src.cli run                     # bugün için pipeline
  python -m src.cli run --date 2026-06-12   # belirli tarih
  python -m src.cli scheduled               # zamanlayıcı başlat (Ctrl+C ile dur)
  python -m src.cli status                  # DB özet raporu
  python -m src.cli init-db                 # veritabanı tabloları oluştur
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime

from dotenv import load_dotenv
load_dotenv()  # .env dosyasını yükle — API key'lerin ortam değişkenine alınması

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Alt komutlar ──────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    run_date: date | None = None
    if args.date:
        try:
            run_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Geçersiz tarih formatı: %s  (YYYY-MM-DD bekleniyor)", args.date)
            return 1

    from src.pipeline.orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator()
    result = orch.run(run_date)

    print(f"\n{'─'*60}")
    print(f"  Pipeline Sonucu — {result.run_date}")
    print(f"{'─'*60}")
    for step in result.steps:
        status = "✓" if step.success else "✗"
        detail = f"{step.output_count} çıktı  {step.duration_ms}ms"
        err    = f"  [{step.error}]" if step.error else ""
        print(f"  {status} {step.name:<22} {detail}{err}")
    print(f"{'─'*60}")
    print(f"  Genel: {'BAŞARILI' if result.success else 'HATA'}  "
          f"toplam={result.total_outputs}  "
          f"bütçe_aşıldı={result.budget_exceeded}")
    print(f"{'─'*60}\n")

    return 0 if result.success else 1


def cmd_scheduled(args: argparse.Namespace) -> int:
    from src.pipeline.orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator()
    try:
        orch.run_scheduled()
    except KeyboardInterrupt:
        logger.info("Zamanlayıcı durduruldu.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from src.db.database import get_db
    db = get_db()
    today = date.today().isoformat()
    month = datetime.now().strftime("%Y-%m")

    # İçerik özeti
    content_rows = db.fetchall(
        "SELECT platform, COUNT(*) as cnt, SUM(compliance_passed) as ok "
        "FROM content WHERE date=? GROUP BY platform",
        (today,),
    )

    # Yayın özeti
    published = db.fetchall(
        "SELECT platform, COUNT(*) as cnt FROM content "
        "WHERE date=? AND published_at IS NOT NULL GROUP BY platform",
        (today,),
    )

    # Performans özeti
    perf = db.fetchone(
        "SELECT COUNT(*) as cnt, AVG(engagement_rate) as avg_eng "
        "FROM performance p JOIN content c ON c.id=p.content_id WHERE c.date=?",
        (today,),
    )

    # LLM maliyet
    daily_cost  = db.get_daily_llm_cost(today)
    monthly_cost = db.get_monthly_llm_cost(month)
    llm_calls   = db.fetchone(
        "SELECT COUNT(*) as cnt, SUM(total_tokens) as tokens "
        "FROM llm_calls WHERE date(called_at)=?",
        (today,),
    )

    # Aktif prompt versiyonları
    versions = db.fetchall(
        "SELECT platform, version, performance_score FROM prompt_versions WHERE is_active=1"
    )

    print(f"\n{'═'*60}")
    print(f"  fin-media-network Durum Raporu — {today}")
    print(f"{'═'*60}")

    print(f"\n  İçerik ({today}):")
    if content_rows:
        for r in content_rows:
            print(f"    {r['platform']:<18} {r['cnt']} satır  "
                  f"(uyumlu: {r['ok'] or 0})")
    else:
        print("    Henüz içerik yok")

    print(f"\n  Yayınlar ({today}):")
    if published:
        for r in published:
            print(f"    {r['platform']:<18} {r['cnt']} yayın")
    else:
        print("    Henüz yayın yok")

    print(f"\n  Performans ({today}):")
    if perf and perf["cnt"]:
        avg = perf["avg_eng"] or 0.0
        print(f"    {perf['cnt']} kayıt  ort. etkileşim={avg:.4f}")
    else:
        print("    Henüz performans verisi yok")

    print(f"\n  LLM Maliyet:")
    tokens = llm_calls["tokens"] or 0 if llm_calls else 0
    calls  = llm_calls["cnt"]    or 0 if llm_calls else 0
    print(f"    Bugün   : {calls} çağrı  {tokens:,} token  ${daily_cost:.4f}")
    print(f"    Bu ay   : ${monthly_cost:.4f}")

    print(f"\n  Aktif Prompt Versiyonları:")
    if versions:
        for v in versions:
            score = f"{v['performance_score']:.4f}" if v["performance_score"] is not None else "—"
            print(f"    {v['platform']:<18} {v['version']}  skor={score}")
    else:
        print("    Kayıtlı versiyon yok")

    print(f"\n{'═'*60}\n")
    return 0


def cmd_init_db(args: argparse.Namespace) -> int:
    import os
    from src.db.database import reset_db
    db = reset_db(os.getenv("DB_PATH", "media_network.db"))
    db.init()
    print(f"Veritabanı hazır: {db.db_path.resolve()}")
    return 0


# ── Argparse kurulumu ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="fin-media-network pipeline CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Pipeline'ı tek seferlik çalıştır")
    p_run.add_argument("--date", metavar="YYYY-MM-DD",
                       help="Çalıştırılacak tarih (varsayılan: bugün)")

    # scheduled
    sub.add_parser("scheduled", help="Zamanlayıcıyı başlat (Ctrl+C ile durdur)")

    # status
    sub.add_parser("status", help="DB özet raporu")

    # init-db
    sub.add_parser("init-db", help="Veritabanı tablolarını oluştur")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "run":       cmd_run,
        "scheduled": cmd_scheduled,
        "status":    cmd_status,
        "init-db":   cmd_init_db,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
