import json
from datetime import date as Date
from rapidfuzz import fuzz
from src.db.database import get_db


class Clusterer:
    def __init__(self, similarity_threshold: int = 75) -> None:
        self._threshold = similarity_threshold

    def run(self, run_date: Date | None = None) -> list[int]:
        # Çalışma tarihi belirlenir
        target_date = run_date if run_date is not None else Date.today()
        date_str = target_date.isoformat()

        db = get_db()

        # Bugünün kümelenmemiş, duplikat olmayan makaleleri alınır
        rows: list[tuple[int, str, str, str | None]] = db.fetchall(
            "SELECT id, title, source_name, source_url FROM raw_news "
            "WHERE date(fetched_at)=? AND is_duplicate=0 AND cluster_id IS NULL "
            "ORDER BY id ASC",
            (date_str,),
        )

        # Her küme: temsil başlığı + makale ID listesi + kaynak ağırlığı (yer tutucu)
        clusters: list[dict] = []

        for row_id, title, source_name, source_url in rows:
            matched_cluster = None
            # Mevcut kümelerle greedy benzerlik karşılaştırması
            for cluster in clusters:
                if fuzz.ratio(title, cluster["representative_title"]) >= self._threshold:
                    matched_cluster = cluster
                    break

            if matched_cluster is not None:
                matched_cluster["article_ids"].append(row_id)
            else:
                # Yeni küme oluşturulur
                clusters.append({
                    "representative_title": title,
                    "article_ids": [row_id],
                    "source_weight": 0.0,  # Scorer tarafından doldurulacak
                })

        created_ids: list[int] = []

        for cluster in clusters:
            # Küme veritabanına kaydedilir
            cluster_id: int = db.execute(
                "INSERT INTO clusters "
                "(date, representative_title, news_count, source_weight, "
                "market_relevance, volatility_impact, score, keywords, tickers_mentioned) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    date_str,
                    cluster["representative_title"],
                    len(cluster["article_ids"]),
                    0.0,  # source_weight — Scorer dolduracak
                    0.0,  # market_relevance
                    0.0,  # volatility_impact
                    0.0,  # score
                    json.dumps([]),  # keywords
                    json.dumps([]),  # tickers_mentioned
                ),
            ).lastrowid

            # Kümedeki her makale güncellenir
            for article_id in cluster["article_ids"]:
                db.execute(
                    "UPDATE raw_news SET cluster_id=? WHERE id=?",
                    (cluster_id, article_id),
                )

            created_ids.append(cluster_id)

        k = len(created_ids)
        n = len(rows)
        print(f"[Clusterer] {date_str}: {n} makale → {k} küme")
        return created_ids
