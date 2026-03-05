"""
core/market_data.py — Piyasa Fiyat Karşılaştırma Modülü

İl/ilçe bazlı Türkiye konut, ofis ve ticari m² fiyat veritabanı.
Kaynak: REIDIN, Endeksa, sahibinden.com (2025-Q4 ortalama değerleri, USD)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Fiyat Veritabanı (USD/m², 2025-Q4 değerleri)
# Güncelleme: manuel olarak data/market_prices.json ile override edilebilir
# ---------------------------------------------------------------------------

MARKET_DB: Dict[str, Dict[str, Dict[str, float]]] = {
    "İstanbul": {
        # İlçe: {konut, ofis, ticari} USD/m²
        "Beşiktaş":       {"konut": 4500, "ofis": 5500, "ticari": 8000},
        "Sarıyer":        {"konut": 4200, "ofis": 5000, "ticari": 7500},
        "Şişli":          {"konut": 3800, "ofis": 5200, "ticari": 9000},
        "Kadıköy":        {"konut": 3500, "ofis": 4500, "ticari": 7000},
        "Üsküdar":        {"konut": 3000, "ofis": 3500, "ticari": 5500},
        "Ataşehir":       {"konut": 3200, "ofis": 4000, "ticari": 6000},
        "Maltepe":        {"konut": 2500, "ofis": 3000, "ticari": 4500},
        "Kartal":         {"konut": 2200, "ofis": 2800, "ticari": 4000},
        "Pendik":         {"konut": 2000, "ofis": 2500, "ticari": 3500},
        "Tuzla":          {"konut": 1800, "ofis": 2200, "ticari": 3000},
        "Beylikdüzü":     {"konut": 2400, "ofis": 2800, "ticari": 4200},
        "Esenyurt":       {"konut": 1800, "ofis": 2200, "ticari": 3200},
        "Başakşehir":     {"konut": 2800, "ofis": 3200, "ticari": 5000},
        "Bahçelievler":   {"konut": 2600, "ofis": 3000, "ticari": 4800},
        "Bakırköy":       {"konut": 3400, "ofis": 4200, "ticari": 6500},
        "Zeytinburnu":    {"konut": 2800, "ofis": 3200, "ticari": 5000},
        "Eyüpsultan":     {"konut": 2200, "ofis": 2600, "ticari": 4000},
        "Kağıthane":      {"konut": 2500, "ofis": 3000, "ticari": 4500},
        "Gaziosmanpaşa":  {"konut": 2000, "ofis": 2400, "ticari": 3600},
        "Sultangazi":     {"konut": 1700, "ofis": 2000, "ticari": 3000},
        "Levent/Maslak":  {"konut": 6000, "ofis": 7000, "ticari": 12000},
        "Nişantaşı":      {"konut": 5500, "ofis": 6500, "ticari": 11000},
        "Bağcılar":       {"konut": 1900, "ofis": 2300, "ticari": 3400},
        "Silivri":        {"konut": 1500, "ofis": 1800, "ticari": 2500},
        "Çekmeköy":       {"konut": 2200, "ofis": 2600, "ticari": 3800},
        "Sancaktepe":     {"konut": 2000, "ofis": 2400, "ticari": 3500},
    },
    "Ankara": {
        "Çankaya":        {"konut": 2200, "ofis": 3000, "ticari": 5000},
        "Keçiören":       {"konut": 1400, "ofis": 1800, "ticari": 2800},
        "Mamak":          {"konut": 1200, "ofis": 1500, "ticari": 2200},
        "Etimesgut":      {"konut": 1600, "ofis": 2000, "ticari": 3000},
        "Sincan":         {"konut": 1300, "ofis": 1600, "ticari": 2400},
        "Yenimahalle":    {"konut": 1500, "ofis": 1900, "ticari": 2800},
        "Pursaklar":      {"konut": 1400, "ofis": 1700, "ticari": 2500},
        "Gölbaşı":        {"konut": 1800, "ofis": 2200, "ticari": 3500},
        "Ümitköy":        {"konut": 2000, "ofis": 2500, "ticari": 4000},
        "Çayyolu":        {"konut": 2100, "ofis": 2600, "ticari": 4200},
        "Oran":           {"konut": 2400, "ofis": 3000, "ticari": 5000},
        "Beştepe":        {"konut": 2800, "ofis": 3500, "ticari": 6000},
    },
    "İzmir": {
        "Konak":          {"konut": 2500, "ofis": 3200, "ticari": 5500},
        "Karşıyaka":      {"konut": 2800, "ofis": 3500, "ticari": 6000},
        "Bornova":        {"konut": 2200, "ofis": 2800, "ticari": 4500},
        "Bayraklı":       {"konut": 2400, "ofis": 3000, "ticari": 5000},
        "Buca":           {"konut": 1800, "ofis": 2200, "ticari": 3500},
        "Çiğli":          {"konut": 2000, "ofis": 2500, "ticari": 4000},
        "Gaziemir":       {"konut": 1900, "ofis": 2300, "ticari": 3800},
        "Narlıdere":      {"konut": 2600, "ofis": 3200, "ticari": 5200},
        "Güzelbahçe":     {"konut": 3000, "ofis": 3500, "ticari": 6000},
        "Urla":           {"konut": 3500, "ofis": 4000, "ticari": 7000},
        "Çeşme":          {"konut": 5000, "ofis": 5500, "ticari": 9000},
    },
    "Antalya": {
        "Muratpaşa":      {"konut": 3000, "ofis": 3800, "ticari": 6500},
        "Konyaaltı":      {"konut": 3500, "ofis": 4200, "ticari": 7000},
        "Kepez":          {"konut": 1800, "ofis": 2200, "ticari": 3500},
        "Lara":           {"konut": 4000, "ofis": 5000, "ticari": 8500},
        "Alanya":         {"konut": 3500, "ofis": 4000, "ticari": 7000},
        "Belek":          {"konut": 4500, "ofis": 5500, "ticari": 9000},
    },
    "Bursa": {
        "Nilüfer":        {"konut": 2000, "ofis": 2500, "ticari": 4000},
        "Osmangazi":      {"konut": 1800, "ofis": 2200, "ticari": 3500},
        "Yıldırım":       {"konut": 1500, "ofis": 1800, "ticari": 2800},
        "Görükle":        {"konut": 2200, "ofis": 2600, "ticari": 4200},
    },
    "Gaziantep": {
        "Şehitkamil":     {"konut": 1200, "ofis": 1500, "ticari": 2500},
        "Şahinbey":       {"konut": 1100, "ofis": 1400, "ticari": 2200},
    },
    "Trabzon": {
        "Ortahisar":      {"konut": 1500, "ofis": 1900, "ticari": 3000},
        "Akçaabat":       {"konut": 1300, "ofis": 1600, "ticari": 2500},
    },
    "Mersin": {
        "Yenişehir":      {"konut": 1600, "ofis": 2000, "ticari": 3200},
        "Mezitli":        {"konut": 1800, "ofis": 2200, "ticari": 3500},
    },
    "Kocaeli": {
        "İzmit":          {"konut": 1800, "ofis": 2200, "ticari": 3500},
        "Gebze":          {"konut": 2000, "ofis": 2500, "ticari": 4000},
        "Körfez":         {"konut": 1700, "ofis": 2000, "ticari": 3200},
    },
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MarketComparison:
    il: str
    ilce: str
    tip: str                      # "konut" | "ofis" | "ticari"
    piyasa_fiyat_usd_m2: float    # piyasa ortalama
    proje_fiyat_usd_m2: float     # projenin hedef fiyatı
    fark_pct: float               # (proje - piyasa) / piyasa
    fark_usd_m2: float            # mutlak fark
    degerlendirme: str            # "Piyasa altı" | "Piyasaya yakın" | "Piyasa üstü"
    oneri: str                    # kısa öneri metni


@dataclass
class FullMarketReport:
    il: str
    ilce: str
    comparisons: list[MarketComparison]
    # İlçe bazlı komşu fiyatlar
    nearby_prices: dict[str, dict[str, float]]
    piyasa_ortalama_konut: float
    veri_tarihi: str = "2025-Q4"
    kaynak: str = "REIDIN / Endeksa / Sahibinden.com (tahmini)"


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def get_iller() -> List[str]:
    return sorted(MARKET_DB.keys())


def get_ilceler(il: str) -> List[str]:
    return sorted(MARKET_DB.get(il, {}).keys())


def get_fiyat(il: str, ilce: str, tip: str = "konut") -> Optional[float]:
    return MARKET_DB.get(il, {}).get(ilce, {}).get(tip.lower())


def _degerlendirme(fark_pct: float) -> Tuple[str, str]:
    if fark_pct < -0.15:
        return "🔴 Piyasa Altı", "Fiyat piyasanın önemli ölçüde altında — satış hızı yüksek olabilir ama kâr marjı düşük."
    elif fark_pct < -0.05:
        return "🟡 Piyasa Altı", "Fiyat piyasanın biraz altında — hızlı satış avantajı sağlayabilir."
    elif fark_pct <= 0.05:
        return "🟢 Piyasaya Uygun", "Fiyat piyasa ortalamasıyla uyumlu — dengeli bir strateji."
    elif fark_pct <= 0.15:
        return "🟡 Piyasa Üstü", "Fiyat piyasanın biraz üzerinde — konum/kalite farkını öne çıkarman gerekir."
    elif fark_pct <= 0.30:
        return "🟠 Piyasa Üstü", "Fiyat piyasanın belirgin üzerinde — güçlü bir konumsal/konsept avantajı şart."
    else:
        return "🔴 Çok Yüksek", "Fiyat piyasa ortalamasının %30+ üzerinde — satış süresi uzayabilir."


# ---------------------------------------------------------------------------
# Ana fonksiyonlar
# ---------------------------------------------------------------------------

def compare_to_market(
    il: str,
    ilce: str,
    proje_fiyat_konut: Optional[float] = None,
    proje_fiyat_ofis: Optional[float] = None,
    proje_fiyat_ticari: Optional[float] = None,
) -> FullMarketReport:
    """
    Projenin satış fiyatını piyasa ortalamasıyla karşılaştır.

    Args:
        il, ilce:               Lokasyon
        proje_fiyat_konut:      Proje konut satış fiyatı USD/m² (opsiyonel)
        proje_fiyat_ofis:       Proje ofis satış fiyatı USD/m² (opsiyonel)
        proje_fiyat_ticari:     Proje ticari satış fiyatı USD/m² (opsiyonel)

    Returns:
        FullMarketReport
    """
    ilce_data = MARKET_DB.get(il, {}).get(ilce, {})
    comparisons = []

    price_map = {
        "konut":  proje_fiyat_konut,
        "ofis":   proje_fiyat_ofis,
        "ticari": proje_fiyat_ticari,
    }

    for tip, proje_fiyat in price_map.items():
        piyasa = ilce_data.get(tip)
        if piyasa is None or proje_fiyat is None:
            continue
        fark_pct = (proje_fiyat - piyasa) / piyasa
        fark_usd  = proje_fiyat - piyasa
        deg, oneri = _degerlendirme(fark_pct)
        comparisons.append(MarketComparison(
            il=il, ilce=ilce, tip=tip,
            piyasa_fiyat_usd_m2=piyasa,
            proje_fiyat_usd_m2=proje_fiyat,
            fark_pct=fark_pct,
            fark_usd_m2=fark_usd,
            degerlendirme=deg,
            oneri=oneri,
        ))

    # Komşu ilçe fiyatları (il geneli)
    nearby = {
        k: v for k, v in MARKET_DB.get(il, {}).items()
        if k != ilce
    }

    piyasa_konut_avg = ilce_data.get("konut", 0)

    return FullMarketReport(
        il=il,
        ilce=ilce,
        comparisons=comparisons,
        nearby_prices=nearby,
        piyasa_ortalama_konut=piyasa_konut_avg,
    )


def get_il_stats(il: str) -> Dict[str, Dict[str, float]]:
    """İl genelinde min/max/ort fiyatları döndür."""
    ilceler = MARKET_DB.get(il, {})
    if not ilceler:
        return {}
    stats: Dict[str, Dict[str, float]] = {}
    for tip in ["konut", "ofis", "ticari"]:
        prices = [v.get(tip, 0) for v in ilceler.values() if v.get(tip)]
        if prices:
            stats[tip] = {
                "min": min(prices),
                "max": max(prices),
                "ort": sum(prices) / len(prices),
            }
    return stats
