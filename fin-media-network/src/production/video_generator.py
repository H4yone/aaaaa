"""
Video Jeneratörü — TTS MP3'lerini YouTube'a yüklenebilir MP4'e dönüştürür.

Akış:
  1. Başlık kartı (PIL) üretilir — marka + başlık + SPK uyarısı.
  2. ffmpeg ile kart (sabit görüntü) + ses → MP4 birleştirilir.

Env:
  OUTPUT_DIR  (varsayılan: "output")

Girdi  : {OUTPUT_DIR}/{YYYY-MM-DD}/youtube_{content_id}.mp3   (tts_generator üretir)
Çıktı  : {OUTPUT_DIR}/{YYYY-MM-DD}/youtube_{content_id}.mp4   (youtube_publisher yükler)

ffmpeg binary'si imageio-ffmpeg ile paketlenir — sistemde ffmpeg kurulu olması gerekmez.
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_WIDTH, _HEIGHT = 1920, 1080
_BG_COLOR = (15, 23, 42)        # koyu lacivert
_TITLE_COLOR = (241, 245, 249)  # açık gri
_BRAND_COLOR = (56, 189, 248)   # camgöbeği
_DISCLAIMER_COLOR = (148, 163, 184)
_BRAND_TEXT = "BIST GÜNDEM"
_DISCLAIMER_TEXT = "Bu içerik yatırım tavsiyesi değildir."


def _resolve_ffmpeg() -> str:
    """Paketlenmiş ffmpeg binary'sinin yolunu döner."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _load_font(size: int):
    from PIL import ImageFont
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    """Metni piksel genişliğine göre satırlara böler."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class VideoGenerator:
    """TTS MP3'lerini başlık kartlı MP4 videolara dönüştürür.

    Testlerde `ffmpeg_exe` ve `runner` enjekte edilebilir.
    """

    def __init__(self, ffmpeg_exe: str | None = None, runner=None) -> None:
        self._ffmpeg_exe = ffmpeg_exe
        self._runner = runner or subprocess.run

    def _ffmpeg(self) -> str:
        if self._ffmpeg_exe is None:
            self._ffmpeg_exe = _resolve_ffmpeg()
        return self._ffmpeg_exe

    # ── Başlık kartı ──────────────────────────────────────────────────────────

    def make_title_card(self, headline: str, output_path: Path) -> Path:
        """Başlık + marka + SPK uyarısı içeren PNG üretir."""
        from PIL import Image, ImageDraw

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (_WIDTH, _HEIGHT), _BG_COLOR)
        draw = ImageDraw.Draw(img)

        brand_font = _load_font(56)
        title_font = _load_font(84)
        disc_font = _load_font(40)

        margin = 140

        # Marka (üst)
        draw.text((margin, 110), _BRAND_TEXT, font=brand_font, fill=_BRAND_COLOR)

        # Başlık (ortada, sarılmış)
        lines = _wrap(draw, headline, title_font, _WIDTH - 2 * margin)
        line_h = title_font.size + 24
        block_h = len(lines) * line_h
        y = (_HEIGHT - block_h) // 2
        for line in lines:
            draw.text((margin, y), line, font=title_font, fill=_TITLE_COLOR)
            y += line_h

        # SPK uyarısı (alt)
        draw.text((margin, _HEIGHT - 130), _DISCLAIMER_TEXT,
                  font=disc_font, fill=_DISCLAIMER_COLOR)

        img.save(output_path)
        return output_path

    # ── MP4 birleştirme ───────────────────────────────────────────────────────

    def render(self, audio_path: Path, card_path: Path, output_path: Path) -> Path:
        """Sabit görüntü + ses → MP4 (ffmpeg)."""
        cmd = [
            self._ffmpeg(), "-y",
            "-loop", "1", "-i", str(card_path),
            "-i", str(audio_path),
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]
        result = self._runner(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg hatası ({result.returncode}): {result.stderr[-500:]}")
        return output_path

    # ── Ana döngü ─────────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[Path]:
        """
        Sesi olup videosu olmayan YouTube içerikleri için MP4 üretir.

        Returns:
            Oluşturulan MP4 dosyalarının listesi.
        """
        from src.db.database import get_db

        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
        db = get_db()

        rows = db.fetchall(
            """SELECT id, title FROM content
               WHERE date=? AND platform='youtube' AND compliance_passed=1""",
            (date_str,),
        )

        generated: list[Path] = []
        for row in rows:
            base = output_dir / date_str
            audio_path = base / f"youtube_{row['id']}.mp3"
            video_path = base / f"youtube_{row['id']}.mp4"

            if not audio_path.exists():
                logger.warning("[Video] Ses yok, atlanıyor: %s", audio_path)
                continue
            if video_path.exists():
                logger.debug("[Video] Zaten mevcut, atlanıyor: %s", video_path)
                continue

            try:
                card_path = base / f"youtube_{row['id']}_card.png"
                self.make_title_card(row["title"] or _BRAND_TEXT, card_path)
                self.render(audio_path, card_path, video_path)
                generated.append(video_path)
                logger.info("[Video] Üretildi: %s", video_path)
            except Exception as exc:
                logger.error("[Video] İçerik %d video üretim hatası: %s", row["id"], exc)

        return generated


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    paths = VideoGenerator().run()
    print(f"Üretilen videolar: {paths}")
