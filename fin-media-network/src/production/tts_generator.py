"""
ElevenLabs TTS Jeneratörü — diyalog formatındaki içerikleri MP3'e dönüştürür.

Env:
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID_DENIZ  (Sunucu sesi)
  ELEVENLABS_VOICE_ID_MERT   (Analist sesi)
  OUTPUT_DIR                 (varsayılan: "output")

Diyalog formatı:
  [SUNUCU] metin → Sunucu sesiyle üretilir
  [ANALİST] metin → Analist sesiyle üretilir
  Tüm segmentler birleştirilerek tek MP3 çıkar.

Çıktı dosyası konvansiyonu:
  {OUTPUT_DIR}/{YYYY-MM-DD}/{platform}_{content_id}.mp3
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL_ID = "eleven_multilingual_v2"
_OUTPUT_FORMAT = "mp3_44100_128"
_TTS_BASE_URL = "https://api.elevenlabs.io/v1/text-to-speech"


class _ElevenLabsHTTPClient:
    """ElevenLabs TTS için hafif HTTP istemcisi.

    Resmi `elevenlabs` SDK'sı Windows'ta uzun-dosya-yolu sınırı nedeniyle
    kurulamadığından doğrudan REST API kullanılır. Arayüz SDK ile aynıdır:
    `client.text_to_speech.convert(...)` → ses byte'larını yield eden iteratör.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self.text_to_speech = self  # SDK'daki client.text_to_speech.convert ile aynı erişim

    def convert(self, *, voice_id: str, text: str, model_id: str, output_format: str):
        import httpx
        with httpx.stream(
            "POST",
            f"{_TTS_BASE_URL}/{voice_id}",
            params={"output_format": output_format},
            headers={"xi-api-key": self._api_key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": model_id},
            timeout=120.0,
        ) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes():
                if chunk:
                    yield chunk


def _parse_dialogue(text: str) -> list[tuple[str, str]]:
    """[SUNUCU] ve [ANALİST] etiketlerini parse eder, (konuşmacı, metin) listesi döner."""
    parts = re.split(r"\[(SUNUCU|ANAL[İI]ST)\]", text)
    segments: list[tuple[str, str]] = []
    i = 1
    while i < len(parts) - 1:
        speaker = parts[i].strip()
        if re.match(r"ANAL[İI]ST", speaker):
            speaker = "ANALİST"
        content = parts[i + 1].strip()
        if content:
            segments.append((speaker, content))
        i += 2
    return segments


class TTSGenerator:
    """
    ElevenLabs text-to-speech wrapper — diyalog desteğiyle.

    Testlerde `client` parametresine mock geçilir.
    """

    def __init__(self, client=None) -> None:
        self._client = client

    def _get_client(self):
        if self._client is None:
            self._client = _ElevenLabsHTTPClient(api_key=os.getenv("ELEVENLABS_API_KEY", ""))
        return self._client

    def _voice_for(self, speaker: str) -> str:
        """Konuşmacıya göre ses ID döner."""
        if speaker == "ANALİST":
            return os.getenv("ELEVENLABS_VOICE_ID_MERT", "")
        return os.getenv("ELEVENLABS_VOICE_ID_DENIZ", "")

    # ── Tekli ses üretimi ─────────────────────────────────────────────────────

    def generate(
        self,
        text: str,
        output_path: Path,
        voice_id: str | None = None,
    ) -> Path:
        """
        Metni tek sesle MP3'e dönüştürür.

        voice_id None ise ELEVENLABS_VOICE_ID_DENIZ kullanılır.
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

    # ── Diyalog ses üretimi ───────────────────────────────────────────────────

    def generate_dialogue(self, text: str, output_path: Path) -> Path:
        """
        [SUNUCU]/[ANALİST] etiketli metni iki sesle üretip tek MP3'te birleştirir.

        Etiket yoksa tek sesle (Sunucu) üretilir.
        """
        segments = _parse_dialogue(text)

        if not segments:
            return self.generate(text, output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        all_audio = b""
        for speaker, content in segments:
            voice_id = self._voice_for(speaker)
            if not voice_id:
                logger.warning("[TTS] %s için ses ID tanımlı değil, atlanıyor", speaker)
                continue
            audio_stream = self._get_client().text_to_speech.convert(
                voice_id=voice_id,
                text=content,
                model_id=_MODEL_ID,
                output_format=_OUTPUT_FORMAT,
            )
            for chunk in audio_stream:
                all_audio += chunk

        with output_path.open("wb") as f:
            f.write(all_audio)

        logger.info("[TTS] Diyalog %d segment → %s", len(segments), output_path)
        return output_path

    # ── Toplu üretim ──────────────────────────────────────────────────────────

    def run(self, run_date=None) -> list[Path]:
        """
        Belirtilen tarih için sesi olmayan YouTube ve TikTok içeriklerini seslendirir.

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

            try:
                path = self.generate_dialogue(text=row["body"], output_path=mp3_path)
                generated.append(path)
            except Exception as exc:
                logger.error("[TTS] İçerik %d ses üretim hatası: %s", row["id"], exc)

        return generated
