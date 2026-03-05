"""
core/mixed_use.py — Karma Kullanım (Mixed-Use) Fizibilite Motoru

Konut, Ofis ve Ticari kullanım tiplerini ayrı ayrı hesaplar,
ağırlıklı ortalama metrikler üretir.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import math

# ---------------------------------------------------------------------------
# Varsayılan birim maliyetler ve satış fiyatları (USD/m²)
# ---------------------------------------------------------------------------
DEFAULTS_BY_TYPE = {
    "Konut": {
        "insaat_maliyet_usd_m2": 900,
        "satis_fiyat_usd_m2":    2500,
        "kdv_orani":             0.08,   # %8 KDV (konut ≤150m²)
        "satilabilir_katsayi":   1.25,
        "otopark_katsayi":       {"ACIK": 1.20, "KAPALI": 1.60},
        "renk":                  "#3B82F6",
        "emoji":                 "🏠",
    },
    "Ofis": {
        "insaat_maliyet_usd_m2": 1000,
        "satis_fiyat_usd_m2":    3000,
        "kdv_orani":             0.20,   # %20 KDV
        "satilabilir_katsayi":   1.10,   # ofiste koridor vs. düşük
        "otopark_katsayi":       {"ACIK": 1.15, "KAPALI": 1.40},
        "renk":                  "#8B5CF6",
        "emoji":                 "🏢",
    },
    "Ticari": {
        "insaat_maliyet_usd_m2": 1100,
        "satis_fiyat_usd_m2":    4000,
        "kdv_orani":             0.20,   # %20 KDV
        "satilabilir_katsayi":   1.05,
        "otopark_katsayi":       {"ACIK": 1.10, "KAPALI": 1.30},
        "renk":                  "#F59E0B",
        "emoji":                 "🏪",
    },
}

USAGE_TYPES = list(DEFAULTS_BY_TYPE.keys())


@dataclass
class UsageType:
    """Tek bir kullanım tipi tanımı."""
    name: str                          # "Konut" | "Ofis" | "Ticari"
    alan_orani: float                  # toplam emsalin kaçta kaçı (0.0–1.0, toplam=1.0)
    insaat_maliyet_usd_m2: float       # inşaat birim maliyeti
    satis_fiyat_usd_m2: float          # satış birim fiyatı
    kdv_orani: float                   # KDV oranı (örn. 0.08)
    satilabilir_katsayi: float = 1.25  # satılabilir alan katsayısı

    @classmethod
    def from_defaults(cls, name: str, alan_orani: float, **overrides) -> "UsageType":
        """Varsayılan değerlerden oluştur, override edilebilir."""
        d = dict(DEFAULTS_BY_TYPE[name])
        d.pop("otopark_katsayi")
        d.pop("renk")
        d.pop("emoji")
        d.update(overrides)
        return cls(name=name, alan_orani=alan_orani, **d)


@dataclass
class UsageTypeResult:
    """Tek kullanım tipi hesap sonucu."""
    name: str
    alan_orani: float

    # Alan (m²)
    emsal_insaat_alani_m2: float
    satilabilir_alan_m2: float
    toplam_insaat_alani_m2: float

    # Maliyet
    insaat_maliyeti_usd: float
    arsa_payi_usd: float          # arsa maliyetinin bu tipe düşen payı
    toplam_maliyet_usd: float

    # Gelir
    satis_hasilati_usd: float     # kdv hariç
    kdv_usd: float                 # tahsil edilecek KDV
    net_hasilat_usd: float         # kdv dahil toplam tahsilat

    # Karlılık
    kar_usd: float
    brut_karlilik: float           # (hasilat - maliyet) / maliyet
    breakeven_usd_m2: float        # başabaş satış fiyatı
    target_30_usd_m2: float        # %30 kâr hedef fiyatı


@dataclass
class MixedUseResult:
    """Tüm karma kullanım analizi sonucu."""
    # Girdi özeti
    arsa_alani_m2: float
    emsal: float
    otopark_tipi: str
    arsa_degeri_usd: float

    # Tip bazlı sonuçlar
    types: List[UsageTypeResult]

    # Toplam metrikler
    toplam_emsal_insaat_m2: float
    toplam_satilabilir_m2: float
    toplam_insaat_alani_m2: float
    toplam_insaat_maliyeti_usd: float
    toplam_maliyet_usd: float       # inşaat + arsa
    toplam_hasilat_usd: float       # kdv hariç
    toplam_kdv_usd: float
    toplam_net_hasilat_usd: float   # kdv dahil
    toplam_kar_usd: float
    brut_karlilik: float
    agirlikli_breakeven_usd_m2: float

    # TRY karşılıkları (opsiyonel)
    usd_try_rate: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arsa_alani_m2": self.arsa_alani_m2,
            "emsal": self.emsal,
            "toplam_satilabilir_m2": self.toplam_satilabilir_m2,
            "toplam_maliyet_usd": self.toplam_maliyet_usd,
            "toplam_hasilat_usd": self.toplam_hasilat_usd,
            "toplam_kar_usd": self.toplam_kar_usd,
            "brut_karlilik": self.brut_karlilik,
            "agirlikli_breakeven_usd_m2": self.agirlikli_breakeven_usd_m2,
            "types": [
                {
                    "name": t.name,
                    "satilabilir_alan_m2": t.satilabilir_alan_m2,
                    "toplam_maliyet_usd": t.toplam_maliyet_usd,
                    "satis_hasilati_usd": t.satis_hasilati_usd,
                    "kar_usd": t.kar_usd,
                    "brut_karlilik": t.brut_karlilik,
                    "breakeven_usd_m2": t.breakeven_usd_m2,
                }
                for t in self.types
            ],
        }


# ---------------------------------------------------------------------------
# Ana hesaplama
# ---------------------------------------------------------------------------

def compute_mixed_use(
    arsa_alani_m2: float,
    emsal: float,
    otopark_tipi: str,                    # "ACIK" | "KAPALI"
    arsa_degeri_usd: float,
    usage_types: List[UsageType],
    usd_try_rate: Optional[float] = None,
) -> MixedUseResult:
    """
    Karma kullanım fizibilite hesabı.

    Args:
        arsa_alani_m2:    Arsa alanı (m²)
        emsal:            Yapılaşma emsali
        otopark_tipi:     "ACIK" veya "KAPALI"
        arsa_degeri_usd:  Toplam arsa değeri (USD)
        usage_types:      Kullanım tipi listesi (alan_orani toplamı = 1.0)
        usd_try_rate:     USD/TRY kuru (opsiyonel)

    Returns:
        MixedUseResult
    """
    # Oran doğrulama
    total_ratio = sum(u.alan_orani for u in usage_types)
    if abs(total_ratio - 1.0) > 0.01:
        # Normalize et
        for u in usage_types:
            u.alan_orani = u.alan_orani / total_ratio

    toplam_emsal_insaat = arsa_alani_m2 * emsal
    type_results: List[UsageTypeResult] = []

    toplam_insaat_maliyeti = 0.0
    toplam_hasilat         = 0.0
    toplam_kdv             = 0.0
    toplam_net_hasilat     = 0.0
    toplam_satilabilir     = 0.0
    toplam_insaat_alani    = 0.0

    for u in usage_types:
        if u.alan_orani <= 0:
            continue

        # Alan hesabı
        emsal_insaat = toplam_emsal_insaat * u.alan_orani
        satilabilir  = emsal_insaat * u.satilabilir_katsayi

        # Otopark katsayısı: default değerden al
        otopark_k = DEFAULTS_BY_TYPE.get(u.name, {}).get(
            "otopark_katsayi", {"ACIK": 1.20, "KAPALI": 1.60}
        )[otopark_tipi]
        insaat_alani = satilabilir * otopark_k

        # Maliyet
        insaat_maliyeti = insaat_alani * u.insaat_maliyet_usd_m2
        arsa_payi       = arsa_degeri_usd * u.alan_orani
        toplam_maliyet  = insaat_maliyeti + arsa_payi

        # Gelir
        hasilat_kdv_hariç = satilabilir * u.satis_fiyat_usd_m2
        kdv                = hasilat_kdv_hariç * u.kdv_orani
        net_hasilat        = hasilat_kdv_hariç + kdv

        # Karlılık
        kar             = hasilat_kdv_hariç - toplam_maliyet
        brut_karlilik   = (kar / toplam_maliyet) if toplam_maliyet > 0 else 0.0
        breakeven       = (toplam_maliyet / satilabilir) if satilabilir > 0 else 0.0
        target_30       = breakeven * 1.30

        type_results.append(UsageTypeResult(
            name=u.name,
            alan_orani=u.alan_orani,
            emsal_insaat_alani_m2=emsal_insaat,
            satilabilir_alan_m2=satilabilir,
            toplam_insaat_alani_m2=insaat_alani,
            insaat_maliyeti_usd=insaat_maliyeti,
            arsa_payi_usd=arsa_payi,
            toplam_maliyet_usd=toplam_maliyet,
            satis_hasilati_usd=hasilat_kdv_hariç,
            kdv_usd=kdv,
            net_hasilat_usd=net_hasilat,
            kar_usd=kar,
            brut_karlilik=brut_karlilik,
            breakeven_usd_m2=breakeven,
            target_30_usd_m2=target_30,
        ))

        toplam_insaat_maliyeti += insaat_maliyeti
        toplam_hasilat         += hasilat_kdv_hariç
        toplam_kdv             += kdv
        toplam_net_hasilat     += net_hasilat
        toplam_satilabilir     += satilabilir
        toplam_insaat_alani    += insaat_alani

    toplam_maliyet_genel = toplam_insaat_maliyeti + arsa_degeri_usd
    toplam_kar           = toplam_hasilat - toplam_maliyet_genel
    brut_karlilik_genel  = (toplam_kar / toplam_maliyet_genel) if toplam_maliyet_genel > 0 else 0.0
    agirlikli_breakeven  = (toplam_maliyet_genel / toplam_satilabilir) if toplam_satilabilir > 0 else 0.0

    return MixedUseResult(
        arsa_alani_m2=arsa_alani_m2,
        emsal=emsal,
        otopark_tipi=otopark_tipi,
        arsa_degeri_usd=arsa_degeri_usd,
        types=type_results,
        toplam_emsal_insaat_m2=toplam_emsal_insaat,
        toplam_satilabilir_m2=toplam_satilabilir,
        toplam_insaat_alani_m2=toplam_insaat_alani,
        toplam_insaat_maliyeti_usd=toplam_insaat_maliyeti,
        toplam_maliyet_usd=toplam_maliyet_genel,
        toplam_hasilat_usd=toplam_hasilat,
        toplam_kdv_usd=toplam_kdv,
        toplam_net_hasilat_usd=toplam_net_hasilat,
        toplam_kar_usd=toplam_kar,
        brut_karlilik=brut_karlilik_genel,
        agirlikli_breakeven_usd_m2=agirlikli_breakeven,
        usd_try_rate=usd_try_rate,
    )


def quick_mix(
    arsa_alani_m2: float,
    emsal: float,
    otopark_tipi: str,
    arsa_degeri_usd: float,
    konut_pct: float = 70,
    ofis_pct: float  = 20,
    ticari_pct: float = 10,
    usd_try_rate: Optional[float] = None,
) -> MixedUseResult:
    """Hızlı karma kullanım: yüzde girilerek varsayılan değerlerle hesapla."""
    types = []
    if konut_pct > 0:
        types.append(UsageType.from_defaults("Konut",  konut_pct  / 100))
    if ofis_pct > 0:
        types.append(UsageType.from_defaults("Ofis",   ofis_pct   / 100))
    if ticari_pct > 0:
        types.append(UsageType.from_defaults("Ticari", ticari_pct / 100))
    return compute_mixed_use(arsa_alani_m2, emsal, otopark_tipi, arsa_degeri_usd, types, usd_try_rate)
