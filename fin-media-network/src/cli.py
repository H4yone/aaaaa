"""
fin-media-network CLI

Kullanım:
  python -m src.cli run                     # bugün için pipeline
  python -m src.cli run --date 2026-06-12   # belirli tarih
  python -m src.cli scheduled               # zamanlayıcı başlat (Ctrl+C ile dur)
  python -m src.cli status                  # DB özet raporu
  python -m src.cli init-db                 # veritabanı tabloları oluştur
  python -m src.cli approve 135             # belirli içerik id'lerini onayla
  python -m src.cli approve --date 2026-06-14 --platform youtube  # tarihe göre onayla
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


def cmd_approve(args: argparse.Namespace) -> int:
    """İçeriği insan onayından geçirir — yalnızca SPK-uyumlu satırlar onaylanır."""
    from datetime import timezone
    from src.db.database import get_db
    db = get_db()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    cols = "id, platform, title, compliance_passed, human_approved"
    if args.ids:
        placeholders = ",".join("?" * len(args.ids))
        rows = db.fetchall(
            f"SELECT {cols} FROM content WHERE id IN ({placeholders})",
            tuple(args.ids),
        )
        for missing in set(args.ids) - {r["id"] for r in rows}:
            logger.warning("İçerik bulunamadı: #%s", missing)
    elif args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            logger.error("Geçersiz tarih formatı: %s  (YYYY-MM-DD bekleniyor)", args.date)
            return 1
        query = f"SELECT {cols} FROM content WHERE date=?"
        params: list = [args.date]
        if args.platform:
            query += " AND platform=?"
            params.append(args.platform)
        rows = db.fetchall(query, tuple(params))
    else:
        logger.error("En az bir içerik id'si ya da --date gerekli.")
        return 1

    if not rows:
        print("Onaylanacak içerik bulunamadı.")
        return 0

    approved, already, noncompliant = [], [], []
    for r in rows:
        if not r["compliance_passed"]:
            noncompliant.append(r["id"])
        elif r["human_approved"]:
            already.append(r["id"])
        else:
            db.execute(
                "UPDATE content SET human_approved=1, approved_at=? WHERE id=?",
                (now_utc, r["id"]),
            )
            approved.append(r)

    print(f"\n  Onaylandı ({len(approved)}):")
    for r in approved:
        print(f"    #{r['id']:<4} {r['platform']:<12} {str(r['title'])[:50]}")
    if not approved:
        print("    —")
    if already:
        print(f"  Zaten onaylı: {', '.join('#' + str(i) for i in already)}")
    if noncompliant:
        print(f"  SPK UYUMSUZ — onaylanmadı: {', '.join('#' + str(i) for i in noncompliant)}")
    print()
    return 0


def cmd_export_script(args: argparse.Namespace) -> int:
    """Diyalog içeriğini HeyGen web stüdyosu için sahne sahne föye aktarır."""
    import os
    from pathlib import Path
    from src.db.database import get_db
    from src.production.tts_generator import _parse_dialogue

    # Konuşmacı → (avatar, ses) önerisi — HeyGen UI'da bu isimlerle seç
    cast = {
        "SUNUCU":  ("Annie Desk Sitting (oturan, masa başı)",  "Dynamic Derya — Türkçe, kadın"),
        "ANALİST": ("Brandon Business Sitting (oturan, ofis)", "Doga — Türkçe, erkek"),
    }
    db = get_db()
    output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
    cols = "id, date, platform, title, body"

    if args.ids:
        placeholders = ",".join("?" * len(args.ids))
        rows = db.fetchall(f"SELECT {cols} FROM content WHERE id IN ({placeholders})",
                           tuple(args.ids))
    elif args.date:
        rows = db.fetchall(f"SELECT {cols} FROM content WHERE date=? AND platform=?",
                           (args.date, args.platform))
    else:
        logger.error("En az bir içerik id'si ya da --date gerekli.")
        return 1

    if not rows:
        print("İçerik bulunamadı.")
        return 0

    for r in rows:
        segments = _parse_dialogue(r["body"])
        if not segments:
            print(f"  #{r['id']} ({r['platform']}): diyalog etiketi yok, atlandı")
            continue

        date_str = r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"])
        base = output_dir / date_str
        base.mkdir(parents=True, exist_ok=True)
        foy_path = base / f"{r['platform']}_{r['id']}_heygen.txt"
        save_as = base / f"{r['platform']}_{r['id']}.mp4"

        lines = [
            f"HeyGen Çekim Föyü — içerik #{r['id']} ({r['platform']})",
            f"Başlık : {r['title']}",
            "Boyut  : 16:9, 1080p    |    Arka plan: stüdyo / haber masası",
            "",
            "Oyuncu kadrosu (HeyGen UI'da seç):",
        ]
        for speaker, (avatar, voice) in cast.items():
            lines.append(f"  {speaker:8} → Avatar: {avatar}  |  Ses: {voice}")
        lines += [
            f"Toplam sahne : {len(segments)}",
            f"Bitince indir ve şuraya kaydet → {save_as}",
            "=" * 72,
        ]
        for i, (speaker, text) in enumerate(segments, 1):
            avatar, voice = cast.get(speaker, ("?", "?"))
            lines.append(f"\nSahne {i} — {speaker}   [Avatar: {avatar} | Ses: {voice}]")
            lines.append(text)

        foy_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  #{r['id']}: {len(segments)} sahne → {foy_path}")
        print(f"        videoyu kaydet → {save_as}")

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

    # approve
    p_app = sub.add_parser("approve", help="İçeriği insan onayından geçir (human_approved=1)")
    p_app.add_argument("ids", nargs="*", type=int, metavar="ID",
                       help="Onaylanacak içerik id'leri")
    p_app.add_argument("--date", metavar="YYYY-MM-DD",
                       help="Bu tarihteki tüm uyumlu içeriği onayla")
    p_app.add_argument("--platform",
                       help="--date ile: sadece bu platform (örn. youtube)")

    # export-script
    p_exp = sub.add_parser("export-script",
                           help="İçeriği HeyGen çekim föyüne (sahne sahne) aktar")
    p_exp.add_argument("ids", nargs="*", type=int, metavar="ID",
                       help="Föye aktarılacak içerik id'leri")
    p_exp.add_argument("--date", metavar="YYYY-MM-DD",
                       help="Bu tarihteki içeriği aktar")
    p_exp.add_argument("--platform", default="youtube",
                       help="--date ile birlikte platform (varsayılan: youtube)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "run":       cmd_run,
        "scheduled": cmd_scheduled,
        "status":    cmd_status,
        "init-db":   cmd_init_db,
        "approve":   cmd_approve,
        "export-script": cmd_export_script,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
