from datetime import date as Date
from rapidfuzz import fuzz
from src.db.database import get_db


class Deduplicator:
    def __init__(self, threshold: int = 90) -> None:
        self._threshold = threshold  # rapidfuzz benzerlik eşiği (0-100)

    def run(self, run_date: Date | None = None) -> list[int]:
        # Çalışma tarihi belirlenir
        target_date = run_date if run_date is not None else Date.today()
        date_str = target_date.isoformat()

        db = get_db()

        # Bugünün duplikat olmayan makaleleri sırayla alınır
        rows: list[tuple[int, str]] = db.fetchall(
            "SELECT id, title FROM raw_news WHERE date(fetched_at)=? AND is_duplicate=0 ORDER BY id ASC",
            (date_str,),
        )

        # Daha önce işlenmiş başlıkların listesi (greedy karşılaştırma)
        seen_titles: list[tuple[int, str]] = []
        duplicate_ids: list[int] = []

        for row_id, title in rows:
            is_dup = False
            # Her makale kendinden önce gelen tüm makalelerle karşılaştırılır
            for _, prev_title in seen_titles:
                if fuzz.ratio(title, prev_title) >= self._threshold:
                    is_dup = True
                    break

            if is_dup:
                db.execute(
                    "UPDATE raw_news SET is_duplicate=1 WHERE id=?",
                    (row_id,),
                )
                duplicate_ids.append(row_id)
            else:
                seen_titles.append((row_id, title))

        n = len(duplicate_ids)
        print(f"[Deduplicator] {date_str}: {n} duplikat tespit edildi")
        return duplicate_ids
