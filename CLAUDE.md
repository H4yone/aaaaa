# CLAUDE.md — Repo Anayasası

Bu dosya her oturumda otomatik okunur. Yeni bir oturum açtığında buradan devam et —
ne yapıldığını yeniden keşfetme, nerede kalındığını gör ve bir sonraki güne başla.

---

## Aktif Proje: fin-media-network

**Tanım:** AI destekli Türk finansal medya sistemi. Global haberleri → BIST sinyallerine →
YouTube/TikTok/X içeriğine dönüştüren tam otomatik pipeline.

**Dizin:** `fin-media-network/`
**Branch kuralı:** Her gün için `claude/financial-media-day-N-<hash>` branch'i aç.
**Dil:** Python 3.11+. Tüm yorumlar ve log mesajları Türkçe.

---

## Mimari — 7 Katman

```
ham_haber (RSS/API)
    │
    ▼
[1] ingestion/        rss_fetcher.py · market_fetcher.py
    │  feedparser + yfinance/FRED/EVDS/CoinGecko → raw_news + market_snapshots
    ▼
[2] processing/       deduplicator.py · clusterer.py · scorer.py
    │  url_hash + rapidfuzz → clusters (Tier 1 ≥70, Tier 2 40-70)
    ▼
[3] intelligence/     llm_client.py · research_agent.py · analyst_agent.py  ← ŞU AN BURADA
    │  Claude → signals (headline/what/why/bias/confidence/bist_impact)
    ▼
[4] content/          narrative_writer.py · compliance_checker.py
    │  Claude → YouTube (~1000 kelime) + TikTok (~100 kelime) + X thread
    ▼
[5] production/       youtube_publisher.py · x_publisher.py · tiktok_publisher.py
    │  YouTube Data API + Tweepy + TikTok SDK
    ▼
[6] feedback/         metrics_fetcher.py · prompt_optimizer.py
    │  Görüntüleme/etkileşim → A/B test → prompt_versions tablosu
    ▼
[DB] src/db/          database.py · schema.sql
     SQLite WAL, 8 tablo, singleton get_db()
```

---

## İlerleme Takibi

| Gün | Kapsam | Durum | Commit |
|-----|--------|-------|--------|
| 1 | DB katmanı: `schema.sql`, `database.py`, config dosyaları | ✅ Bitti | `10d4600` |
| 2 | Ingestion: `rss_fetcher.py` (feedparser + url_hash) | ⬜ Yapılmadı | — |
| 3 | Ingestion: `market_fetcher.py` (yfinance + FRED + EVDS + CoinGecko) | ⬜ Yapılmadı | — |
| 4 | Processing: `deduplicator.py` + `clusterer.py` + `scorer.py` | ⬜ Yapılmadı | — |
| 5 | Intelligence: `llm_client.py` + `research_agent.py` | ✅ Bitti | `3bf7c33` |
| 6 | Intelligence: `analyst_agent.py` (BIST derinleme analizi) | ✅ Bitti | `—` |
| 7 | Content: `narrative_writer.py` + `compliance_checker.py` | ⬜ Yapılmadı | — |
| 8 | Content: platform formatlama (YouTube/TikTok/X şablonları) | ⬜ Yapılmadı | — |
| 9 | Production: `youtube_publisher.py` + `x_publisher.py` | ⬜ Yapılmadı | — |
| 10 | Production: TikTok + ElevenLabs TTS entegrasyonu | ⬜ Yapılmadı | — |
| 11 | Pipeline: `orchestrator.py` (zamanlama + hata yönetimi) | ⬜ Yapılmadı | — |
| 12 | Feedback: `metrics_fetcher.py` + `prompt_optimizer.py` | ⬜ Yapılmadı | — |
| 13 | End-to-end test + CLI runner | ⬜ Yapılmadı | — |
| 14 | Deployment config + cron setup + README | ⬜ Yapılmadı | — |

**Bir sonraki adım → Gün 7:** `src/content/narrative_writer.py` + `src/content/compliance_checker.py`

---

## Gün 7 — Ne Yapılacak

`analyst_agent.py` → `content` tablosuna "analyst_brief" yazar.
`narrative_writer.py` ise `signals` tablosundan en yüksek sıralı sinyali alır
ve üç farklı platform için içerik üretir:

- **YouTube** (`platform="youtube"`): ~1000 kelime, başlık + gövde + kapanış disclaimer
- **TikTok** (`platform="tiktok_1"`..`tiktok_4`): ~100 kelime, dikkat çekici hook + özet
- **X thread** (`platform="x_thread"`): tweetler dizisi (her biri ≤280 karakter)

`compliance_checker.py`:
- `config/banned_phrases.yaml`'ı regex ile tarar
- `banned_patterns` eşleşirse `compliance_passed=0`, pipeline durur
- `warning_patterns` eşleşirse `compliance_warnings` dolar ama içerik geçer
- `required_endings` yoksa otomatik disclaimer ekler
- Sadece `compliance_passed=1` olan satır `content` tablosuna yazılabilir

Test: mock LLM + DB fixture + compliance senaryoları (yasak kelime, uyarı, eksik disclaimer)

---

## Kritik Kurallar (hiç değişmez)

### SPK Uyum
- `config/banned_phrases.yaml` her içerikte taranır
- `compliance_checker.py` olmadan içerik `content` tablosuna yazılamaz
- `compliance_passed=0` olan satır production'a gitmez
- Zorunlu kapanış: `"Bu içerik yatırım tavsiyesi değildir."`

### LLM Bütçesi
- Model: `claude-haiku-4-5-20251001` (settings.yaml'dan okunur, hard-code etme)
- Günlük: 30 000 token → ~$0.024
- Aylık: 900 000 token → ~$0.72
- `BudgetExceeded` fırlatıldığında pipeline durur, loglanır, ertesi güne geçilir

### DB Erişimi
- Her modül `from src.db.database import get_db` kullanır — direkt sqlite3 bağlantısı açma
- Test fixture'larında `reset_db(tmp_path/"test.db")` + `db.init()`
- `log_llm_call()` her başarılı/başarısız LLM çağrısında çağrılır

### Kod Stili
- Type hint zorunlu, docstring yasak (tek satır yorum ihtiyaç halinde)
- `yaml.safe_load()` — asla `yaml.load()`
- Config hard-code edilmez, her zaman `settings.yaml` + `config/*.yaml`'dan okunur
- Yeni dosya = karşılık gelen test dosyası (tests/test_*.py)

---

## Temel Dosya Haritası

```
fin-media-network/
├── config/
│   ├── settings.yaml              # model, bütçe, ticker listesi, RSS feed URL'leri
│   ├── transmission_matrix.yaml   # 11 global→BIST iletim kuralı
│   ├── source_weights.yaml        # kaynak güvenilirlik ağırlıkları (elite→unknown)
│   └── banned_phrases.yaml        # SPK yasak kalıpları + zorunlu disclaimer
├── src/
│   ├── db/
│   │   ├── database.py            # Singleton Database, get_db(), reset_db()
│   │   └── schema.sql             # 8 tablo: raw_news, clusters, market_snapshots,
│   │                              #   signals, content, performance, prompt_versions, llm_calls
│   ├── intelligence/
│   │   ├── llm_client.py          # LLMClient, BudgetExceeded, LLMResponse
│   │   ├── research_agent.py      # ResearchAgent.run(date) → signal_ids[]
│   │   └── analyst_agent.py       # AnalystAgent.run(date) → content_ids[] (analyst_brief)
│   ├── ingestion/                 # ⬜ rss_fetcher.py, market_fetcher.py
│   ├── processing/                # ⬜ deduplicator.py, clusterer.py, scorer.py
│   ├── content/                   # ⬜ narrative_writer.py, compliance_checker.py
│   ├── production/                # ⬜ youtube_publisher.py, x_publisher.py
│   ├── pipeline/                  # ⬜ orchestrator.py
│   └── feedback/                  # ⬜ metrics_fetcher.py, prompt_optimizer.py
└── tests/
    ├── test_database.py           # ✅ 7 test
    ├── test_llm_client.py         # ✅ 8 test
    ├── test_research_agent.py     # ✅ 15 test
    └── test_analyst_agent.py      # ✅ 13 test
```

---

## Çevre Değişkenleri (.env)

```
ANTHROPIC_API_KEY=...   # zorunlu
DB_PATH=media_network.db
FRED_API_KEY=...
EVDS_API_KEY=...
ELEVENLABS_API_KEY=...
YOUTUBE_CLIENT_SECRET=...
TWITTER_BEARER_TOKEN=...
```

---

## Günlük Oturum Açılış Prosedürü

1. Bu dosyayı oku (otomatik yapılır)
2. `İlerleme Takibi` tablosunda son `✅` satırına bak
3. `Bir sonraki adım` bölümüne geç
4. `git checkout -b claude/financial-media-day-N-<hash>` yap
5. İşi bitir, testleri çalıştır (`pytest tests/ -v`), push et
6. **Bu dosyayı güncelle:** ilgili satıra `✅ Bitti | <commit>` yaz,
   `Bir sonraki adım` bölümünü bir sonraki güne ilerlet

---

## Diğer Projeler (bu repoda)

| Dizin | Tanım | Durum |
|-------|-------|-------|
| `realm-ruin/` | React Native + Expo medieval strateji oyunu (TypeScript) | ✅ Tamamlandı |
