"""
ElevenLabs TTS Jeneratörü — içerik metinlerini MP3'e dönüştürür.

Env:
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID_DENIZ  (dişi ses — YouTube)
  ELEVENLABS_VOICE_ID_MERT   (erkek ses — TikTok)
  OUTPUT_DIR                 (varsayılan: "output")

Çıktı dosyası konvansiyonu:
  {OUTPUT_DIR}/{YYYY-MM-DD}/{platform}_{content_id}.mp3
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL_ID = "eleven_multilingual_v2"
_OUTPUT_FORMAT = "mp3_44100_128"


class TTSGenerator:
    """
    ElevenLabs text-to-speech wrapper.

    Testlerde `client` parametresine mock geçilir.
    """

    def __init__(self, client=None) -> None:
        self._client = client

    def _get_client(self):
        if self._client is None:
            from elevenlabs.client import ElevenLabs
            self._client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY", ""))
        return self._client

    # ── Ses üretimi ───────────────────────────────────────────────────────────

    def generate(
        self,
        text: str,
        output_path: Path,
        voice_id: str | None = None,
    ) -> Path:
        """
        Metni sese dönüştürür ve MP3 olarak kaydeder.

        Args:
            text:        Seslendirilecek metin
            output_path: Kaydedilecek dosya yolu (.mp3)
            voice_id:    None → ELEVENLABS_VOICE_ID_DENIZ env'den okunur

        Returns:
            Kaydedilen dosyanın yolu
        """
        if voice_id is None:
            voice_id = os.getenv("ELEVENLABS_VOICE_ID_DENIZ", "")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        audio_stream = self._get_client().text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=_MODEL_ID,
            output_format=_OUTPUT_FORMAT,
        )

        with output_path.open("wb") as f:
            for chunk in audio_stream:
                f.write(chunk)

        logger.info("[TTS] %d karakter → %s", len(text), output_path)
        return output_path

    # ── Toplu üretim ──────────────────────────────────────────────────────────

    def run(self, run_date=None) -> list[Path]:
        """
        Belirtilen tarih için sesi olmayan TikTok ve YouTube içeriklerini seslendirir.

        Returns:
            Oluşturulan MP3 dosyalarının listesi.
        """
        from datetime import date
        from src.db.database import get_db

        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
        db = get_db()

        # YouTube → Deniz sesi, TikTok → Mert sesi
        voice_map = {
            "youtube":  os.getenv("ELEVENLABS_VOICE_ID_DENIZ", ""),
            "tiktok_1": os.getenv("ELEVENLABS_VOICE_ID_MERT", ""),
            "tiktok_2": os.getenv("ELEVENLABS_VOICE_ID_MERT", ""),
            "tiktok_3": os.getenv("ELEVENLABS_VOICE_ID_MERT", ""),
            "tiktok_4": os.getenv("ELEVENLABS_VOICE_ID_MERT", ""),
        }

        rows = db.fetchall(
            """SELECT id, platform, body FROM content
               WHERE date=? AND compliance_passed=1
                 AND platform IN ('youtube','tiktok_1','tiktok_2','tiktok_3','tiktok_4')""",
            (date_str,),
        )

        generated: list[Path] = []
        for row in rows:
            mp3_path = output_dir / date_str / f"{row['platform']}_{row['id']}.mp3"
            if mp3_path.exists():
                logger.debug("[TTS] Zaten mevcut, atlanıyor: %s", mp3_path)
                continue

            voice_id = voice_map.get(row["platform"], "")
            if not voice_id:
                logger.warning("[TTS] Ses ID bulunamadı, platform: %s", row["platform"])
                continue

            try:
                path = self.generate(text=row["body"], output_path=mp3_path, voice_id=voice_id)
                generated.append(path)
            except Exception as exc:
                logger.error("[TTS] İçerik %d ses üretim hatası: %s", row["id"], exc)

        return generated
