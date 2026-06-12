from datetime import date as Date
from pathlib import Path
from urllib.parse import urlparse

import yaml

from src.db.database import get_db


_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
_WEIGHTS_PATH = Path(__file__).parent.parent.parent / "config" / "source_weights.yaml"
_MATRIX_PATH = Path(__file__).parent.parent.parent / "config" / "transmission_matrix.yaml"

# Volatilite kategorisi → (anahtar kelimeler, etki ağırlığı)
_VOL_KEYWORDS: dict[str, tuple[list[str], float]] = {
    "faiz_kararı":   (["faiz", "rate", "tcmb", "fed", "hike", "cut"], 1.0),
    "kap_bildirimi": (["kap", "özel durum"], 0.9),
    "earnings":      (["earnings", "eps", "revenue", "kazanç"], 0.9),
    "jeopolitik":    (["war", "savaş", "sanctions", "yaptırım", "conflict"], 0.8),
    "makro_veri":    (["cpi", "gdp", "inflation", "unemployment", "nfp", "enflasyon"], 0.8),
    "merger_acq":    (["acquisition", "merger", "satın alma", "birleşme"], 0.7),
}


class Scorer:
    def __init__(
        self,
        config_path: Path | None = None,
        source_weights_path: Path | None = None,
        matrix_path: Path | None = None,
    ) -> None:
        # Yapılandırma dosyaları yüklenir
        cfg_path = config_path or _CONFIG_PATH
        wts_path = source_weights_path or _WEIGHTS_PATH
        mtx_path = matrix_path or _MATRIX_PATH

        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        scoring = cfg.get("scoring", {})
        self._tier1_threshold: float = float(scoring.get("tier1_threshold", 70))
        self._tier2_min: float = float(scoring.get("tier2_min", 40))

        with open(wts_path, encoding="utf-8") as f:
            weights_cfg = yaml.safe_load(f)

        # Domain → ağırlık eşlem tablosu oluşturulur
        self._domain_weights: dict[str, float] = {}
        for tier_key, tier_data in weights_cfg.items():
            if not isinstance(tier_data, dict):
                continue
            weight = tier_data.get("weight")
            sources = tier_data.get("sources", [])
            if weight is None or not isinstance(sources, list):
                continue
            for domain in sources:
                self._domain_weights[domain.lower()] = float(weight)

        with open(mtx_path, encoding="utf-8") as f:
            matrix_cfg = yaml.safe_load(f)

        # Tüm transmission matrix anahtar kelimeleri tek sette birleştirilir
        self._matrix_keywords: set[str] = set()
        for rule in matrix_cfg.get("rules", []):
            for kw in rule.get("keywords", []):
                self._matrix_keywords.add(kw.lower())

    def _source_weight_for_cluster(self, db, cluster_id: int) -> float:
        # Kümedeki tüm makalelerin kaynak URL'leri sorgulanır
        rows: list[tuple[str | None]] = db.fetchall(
            "SELECT rn.source_url FROM raw_news rn WHERE rn.cluster_id=?",
            (cluster_id,),
        )

        best_weight = 0.4  # Bilinmeyen kaynak varsayılanı
        for (source_url,) in rows:
            if not source_url:
                continue
            try:
                domain = urlparse(source_url).netloc.lower()
                # "www." öneki varsa kaldırılır
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                continue

            # Alan adı eşleşmesi — tam veya son ek bazlı
            for known_domain, weight in self._domain_weights.items():
                if domain == known_domain or domain.endswith("." + known_domain):
                    if weight > best_weight:
                        best_weight = weight
                    break

        return best_weight

    def _market_relevance(self, title: str) -> float:
        # Başlıkta transmission matrix anahtar kelimelerinin kaç tanesi geçiyor
        title_lower = title.lower()
        matched_count = sum(1 for kw in self._matrix_keywords if kw in title_lower)
        # 2 veya daha fazla eşleşme tam ilgililik sayılır
        return min(matched_count / 2, 1.0)

    def _volatility_impact(self, title: str) -> float:
        # Başlık volatilite kategorisi anahtar kelimeleriyle karşılaştırılır
        title_lower = title.lower()
        best_impact = 0.2  # genel_haber varsayılan etkisi

        for _category, (keywords, impact) in _VOL_KEYWORDS.items():
            for kw in keywords:
                if kw in title_lower:
                    if impact > best_impact:
                        best_impact = impact
                    break  # Bu kategori için yeter, sonrakine geç

        return best_impact

    def run(self, run_date: Date | None = None) -> list[int]:
        # Çalışma tarihi belirlenir
        target_date = run_date if run_date is not None else Date.today()
        date_str = target_date.isoformat()

        db = get_db()

        # Bugünün henüz puanlanmamış kümeleri alınır
        rows: list[tuple[int, str, int]] = db.fetchall(
            "SELECT id, representative_title, news_count FROM clusters WHERE date=? AND score=0.0",
            (date_str,),
        )

        tiered_ids: list[int] = []

        for cluster_id, representative_title, news_count in rows:
            # Bileşen skorları hesaplanır
            source_w = self._source_weight_for_cluster(db, cluster_id)
            market_rel = self._market_relevance(representative_title)
            vol_imp = self._volatility_impact(representative_title)

            # Haber sayısına göre küçük artış faktörü (max %30 bonus)
            count_factor = min(1.0 + (news_count - 1) * 0.05, 1.3)

            # Ağırlıklı bileşik skor (0-100)
            raw_score = (
                0.40 * source_w + 0.35 * market_rel + 0.25 * vol_imp
            ) * count_factor * 100
            score = round(min(raw_score, 100.0), 2)

            # Tier belirlenir
            if score >= self._tier1_threshold:
                tier: int | None = 1
            elif score >= self._tier2_min:
                tier = 2
            else:
                tier = None

            # Küme güncellenir
            db.execute(
                "UPDATE clusters SET source_weight=?, market_relevance=?, "
                "volatility_impact=?, score=?, tier=? WHERE id=?",
                (source_w, market_rel, vol_imp, score, tier, cluster_id),
            )

            if tier is not None:
                tiered_ids.append(cluster_id)

        n = len(rows)
        t = len(tiered_ids)
        print(f"[Scorer] {date_str}: {n} küme puanlandı, {t} tier (1+2)")
        return tiered_ids
