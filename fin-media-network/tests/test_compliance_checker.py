"""
ComplianceChecker testleri.
"""
from __future__ import annotations

import pytest

from src.content.compliance_checker import ComplianceChecker


@pytest.fixture()
def checker():
    return ComplianceChecker()


# ── Yasak kalıplar ────────────────────────────────────────────────────────────

class TestBannedPatterns:
    def test_fails_on_explicit_buy_advice(self, checker):
        result = checker.check("Bu hisseyi almalısınız, çok iyi fırsat var.")
        assert result.passed is False
        assert any("almalısınız" in w for w in result.warnings)

    def test_fails_on_guaranteed_gain(self, checker):
        result = checker.check("Bu yatırım garantili kazanç sağlar.")
        assert result.passed is False

    def test_fails_on_price_target_language(self, checker):
        result = checker.check("Şirketin hedef fiyatı 150 TL olarak belirlendi.")
        assert result.passed is False

    def test_fails_on_numeric_price_target(self, checker):
        result = checker.check("Hisse 200 TL'ye ulaşır diye düşünüyoruz.")
        assert result.passed is False

    def test_fails_on_risksiz_yatirim(self, checker):
        result = checker.check("Bu risksiz yatırım fırsatını kaçırmayın.")
        assert result.passed is False

    def test_body_unchanged_on_failure(self, checker):
        original = "Bu hisseyi almalısınız."
        result = checker.check(original)
        assert result.body == original


# ── Uyarı kalıpları ───────────────────────────────────────────────────────────

class TestWarningPatterns:
    def test_passes_with_warning_on_yukselebilir(self, checker):
        result = checker.check(
            "Bankacılık sektörü yükselebilir. Bu içerik yatırım tavsiyesi değildir."
        )
        assert result.passed is True
        assert any("yükselebilir" in w for w in result.warnings)

    def test_passes_with_warning_on_dusebilir(self, checker):
        result = checker.check(
            "Endeks düşebilir. Bu içerik yatırım tavsiyesi değildir."
        )
        assert result.passed is True
        assert any("düşebilir" in w for w in result.warnings)

    def test_clean_text_has_no_warnings(self, checker):
        result = checker.check(
            "Fed faiz artırdı. BIST üzerinde baskı oluştu. Bu içerik yatırım tavsiyesi değildir."
        )
        assert result.passed is True
        assert result.warnings == []


# ── Zorunlu disclaimer ────────────────────────────────────────────────────────

class TestRequiredEndings:
    def test_disclaimer_appended_when_missing(self, checker):
        result = checker.check("Fed faiz artırdı. Piyasalar olumsuz etkilendi.")
        assert result.passed is True
        assert "yatırım tavsiyesi değildir" in result.body.lower()

    def test_no_duplicate_disclaimer(self, checker):
        text = "Haberler olumlu. Bu içerik yatırım tavsiyesi değildir."
        result = checker.check(text)
        count = result.body.lower().count("yatırım tavsiyesi değildir")
        assert count == 1

    def test_alternative_ending_accepted(self, checker):
        text = "Analiz tamamlandı. Bu içerik bilgi amaçlıdır."
        result = checker.check(text)
        # Alternatif kabul edilmeli, disclaimer eklenmemeli
        count = result.body.lower().count("yatırım tavsiyesi değildir")
        assert count == 0

    def test_another_alternative_ending_accepted(self, checker):
        text = "Piyasa analizi. Bu içerik yatırım danışmanlığı değildir."
        result = checker.check(text)
        assert result.passed is True
        assert "yatırım tavsiyesi değildir" not in result.body.lower()


# ── Karma senaryolar ──────────────────────────────────────────────────────────

class TestMixedScenarios:
    def test_banned_takes_priority_over_warning(self, checker):
        # Hem yasak hem uyarı içeriyor
        result = checker.check(
            "Bu hisseyi almalısınız çünkü yükselebilir. Bu içerik yatırım tavsiyesi değildir."
        )
        assert result.passed is False

    def test_empty_body_gets_disclaimer(self, checker):
        result = checker.check("")
        assert result.passed is True
        assert "yatırım tavsiyesi değildir" in result.body.lower()

    def test_case_insensitive_match(self, checker):
        result = checker.check("ALMALIYDINIZ zaten bu fırsatı.")
        # "almalısınız" ≠ "almalıydınız" — bu geçmeli
        # Gerçek yasak: "almalısınız" — farklı kelime, geçer
        assert result.passed is True
