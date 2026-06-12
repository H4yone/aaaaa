# fin-media-network

AI destekli Türk finansal medya üretim sistemi. Global haberleri → BIST sinyallerine → YouTube / TikTok / X içeriklerine dönüştüren tam otomatik pipeline.

```
Ham Haber (RSS/API)
      │
      ▼  ResearchAgent   — Claude ile sinyal çıkarma
      ▼  AnalystAgent    — BIST derinleme analizi
      ▼  NarrativeWriter — YouTube + TikTok + X içerik üretimi
      ▼  TTSGenerator    — ElevenLabs ile seslendirme
      ▼  Publishers      — YouTube / TikTok / X otomatik yayın
      ▼  MetricsFetcher  — Görüntüleme & etkileşim toplama
      ▼  PromptOptimizer — A/B test ile prompt iyileştirme
```

---

## Hızlı Başlangıç

### 1. Kurulum

```bash
git clone <repo-url>
cd fin-media-network
bash deploy/install.sh
```

### 2. API Anahtarları

```bash
cp .env.example .env
# .env dosyasını açıp zorunlu anahtarları doldurun
```

Zorunlu değişkenler:

| Değişken | Açıklama |
|---|---|
| `ANTHROPIC_API_KEY` | Claude Haiku erişimi |
| `ELEVENLABS_API_KEY` | TTS seslendirme |
| `ELEVENLABS_VOICE_ID_DENIZ` | YouTube için dişi ses ID |
| `ELEVENLABS_VOICE_ID_MERT` | TikTok için erkek ses ID |
| `YOUTUBE_CLIENT_SECRET` | YouTube Data API OAuth2 |
| `TWITTER_BEARER_TOKEN` | X/Twitter API v2 |
| `TIKTOK_ACCESS_TOKEN` | TikTok Content Posting API |
| `TIKTOK_CLIENT_KEY` | TikTok uygulama anahtarı |

### 3. Veritabanı Başlatma

```bash
python -m src.cli init-db
```

### 4. Çalıştırma

```bash
# Tek seferlik — bugün için
python -m src.cli run

# Belirli tarih
python -m src.cli run --date 2026-06-12

# Durum raporu
python -m src.cli status

# Zamanlayıcı başlat (Ctrl+C ile durdur)
python -m src.cli scheduled
```

---

## Mimari

### Katmanlar

| # | Modül | Açıklama |
|---|---|---|
| 1 | `ingestion/` | RSS + yfinance/FRED/EVDS/CoinGecko → ham veri |
| 2 | `processing/` | Deduplication + clustering + skorlama |
| 3 | `intelligence/` | Claude ile sinyal üretimi ve BIST analizi |
| 4 | `content/` | İçerik yazımı + SPK uyum kontrolü |
| 5 | `production/` | YouTube / TikTok / X yayını + TTS |
| 6 | `feedback/` | Metrik toplama + A/B test |
| DB | `db/` | SQLite WAL, 8 tablo |

### Veritabanı Şeması

```
raw_news          → Ham haberler (RSS/API)
clusters          → Olay kümeleri (dedup + skor)
market_snapshots  → Piyasa anlık görüntüleri
signals           → Research Agent çıktıları
content           → Üretilen içerikler (tüm platformlar)
performance       → Platform metrikleri
prompt_versions   → A/B test prompt versiyonları
llm_calls         → LLM maliyet logu
```

---

## SPK Uyumu

Tüm içerik `compliance_checker.py` üzerinden geçer:

- `config/banned_phrases.yaml` — yasaklı kalıplar (yatırım tavsiyesi niteliğindeki ifadeler)
- `compliance_passed=0` olan hiçbir satır yayına gitmez
- Her içerik otomatik olarak **"Bu içerik yatırım tavsiyesi değildir."** disclaimer'ı ile sonlandırılır

---

## LLM Bütçesi

| Parametre | Değer |
|---|---|
| Model | `claude-haiku-4-5-20251001` |
| Günlük limit | 30 000 token (~$0.024) |
| Aylık limit | 900 000 token (~$0.72) |

Bütçe aşılınca LLM adımları (research/analyst/narrative) atlanır; TTS ve yayın adımları önceki içeriklerle devam eder.

---

## Deployment

### Cron (önerilen — basit)

```bash
bash deploy/setup_cron.sh
```

Oluşturulan job'lar:

```
# Sabah pipeline    06:00 TR
0 3 * * *  cd /path/to/project && venv/bin/python -m src.cli run

# Akşam pipeline    18:15 TR
15 15 * * *  cd /path/to/project && venv/bin/python -m src.cli run

# Gece durum raporu 23:00 TR
0 20 * * *  cd /path/to/project && venv/bin/python -m src.cli status
```

### Systemd (production sunucu)

```bash
sudo cp deploy/fin-media.service /etc/systemd/system/
# fin-media.service içindeki yol ve kullanıcı adını düzenleyin
sudo systemctl daemon-reload
sudo systemctl enable --now fin-media
sudo journalctl -u fin-media -f
```

---

## Testler

```bash
# Tüm testler
python -m pytest tests/ -v

# Kapsam raporu
python -m pytest tests/ --cov=src --cov-report=term-missing
```

175 test, 7 katman:

| Test Dosyası | Test Sayısı |
|---|---|
| `test_database.py` | 7 |
| `test_llm_client.py` | 8 |
| `test_research_agent.py` | 15 |
| `test_analyst_agent.py` | 13 |
| `test_compliance_checker.py` | 16 |
| `test_narrative_writer.py` | 7 |
| `test_youtube_publisher.py` | 9 |
| `test_x_publisher.py` | 12 |
| `test_tts_generator.py` | 10 |
| `test_tiktok_publisher.py` | 10 |
| `test_orchestrator.py` | 19 |
| `test_metrics_fetcher.py` | 18 |
| `test_prompt_optimizer.py` | 14 |
| `test_e2e.py` | 17 |

---

## Proje Yapısı

```
fin-media-network/
├── .env.example           # Çevre değişkenleri şablonu
├── pyproject.toml         # Bağımlılıklar (Python 3.11+)
├── config/
│   ├── settings.yaml          # Model, bütçe, ticker listesi, RSS feed'leri
│   ├── transmission_matrix.yaml   # 11 global→BIST iletim kuralı
│   ├── source_weights.yaml    # Kaynak güvenilirlik ağırlıkları
│   └── banned_phrases.yaml    # SPK yasak kalıpları + zorunlu disclaimer
├── deploy/
│   ├── install.sh         # Kurulum betiği
│   ├── setup_cron.sh      # Cron job kurulumu
│   └── fin-media.service  # Systemd servis dosyası
├── src/
│   ├── cli.py             # CLI giriş noktası
│   ├── db/                # SQLite katmanı
│   ├── ingestion/         # RSS + piyasa veri çekme
│   ├── processing/        # Dedup + cluster + skor
│   ├── intelligence/      # LLM istemcisi + ajanlar
│   ├── content/           # İçerik yazımı + uyum
│   ├── production/        # Platform yayıncıları + TTS
│   ├── pipeline/          # Orchestrator + zamanlama
│   └── feedback/          # Metrikler + A/B test
└── tests/
    └── test_*.py          # 175 test
```

---

## Geliştirme Notları

- Tüm dış API istemcileri constructor'dan enjekte edilebilir → testlerde mock
- `get_db()` singleton — testlerde `reset_db(tmp_path/"test.db")` kullan
- `yaml.safe_load()` kullan, asla `yaml.load()`
- Config hard-code etme, her zaman `settings.yaml` + `config/*.yaml` kullan
- Her yeni modül için karşılık gelen `tests/test_*.py` dosyası ekle
