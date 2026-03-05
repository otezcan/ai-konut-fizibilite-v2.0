"""
core/market_fetch.py — Piyasa Fiyat Çekme Modülü

Öncelik sırası:
1. Sahibinden.com scraping (cloudscraper ile — opsiyonel bağımlılık)
2. TCMB EVDS API (ücretsiz, token gerekli)
3. Statik DB (core/market_data.py — her zaman çalışır)

Kullanım:
    from core.market_fetch import fetch_market_price, FetchResult
    r = fetch_market_price("istanbul", "atasehir", "konut")
    print(r.fiyat_usd_m2, r.kaynak)
"""
from __future__ import annotations
import os
import re
import json
import time
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache (in-memory, 6 saat TTL)
# ---------------------------------------------------------------------------
_cache: Dict[str, tuple[float, float]] = {}  # key → (timestamp, value)
CACHE_TTL_HOURS = 6


def _cache_get(key: str) -> Optional[float]:
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < CACHE_TTL_HOURS * 3600:
            return val
    return None


def _cache_set(key: str, val: float) -> None:
    _cache[key] = (time.time(), val)


# ---------------------------------------------------------------------------
# Sonuç dataclass
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    il: str
    ilce: str
    tip: str                          # "konut" | "ofis" | "ticari"
    fiyat_usd_m2: Optional[float]
    fiyat_try_m2: Optional[float]
    kaynak: str                       # "sahibinden" | "tcmb_evds" | "static_db"
    guncelleme: str                   # ISO tarih
    hata: Optional[str] = None
    ham_veri: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Seçenek A: Sahibinden Scraping
# ---------------------------------------------------------------------------

# Sahibinden kategori URL haritası
_SBD_CATEGORY = {
    "konut":  "satilik-daire",
    "ofis":   "satilik-isyeri-ofis",
    "ticari": "satilik-dukkan",
}

# İlçe URL slug haritası (en çok kullanılanlar)
_ILCE_SLUG: Dict[str, str] = {
    "ataşehir": "istanbul-atasehir",
    "kadıköy":  "istanbul-kadikoy",
    "beşiktaş": "istanbul-besiktas",
    "şişli":    "istanbul-sisli",
    "üsküdar":  "istanbul-uskudar",
    "maltepe":  "istanbul-maltepe",
    "kartal":   "istanbul-kartal",
    "pendik":   "istanbul-pendik",
    "çankaya":  "ankara-cankaya",
    "keçiören": "ankara-kecioren",
    "konak":    "izmir-konak",
    "karşıyaka":"izmir-karsiyaka",
    "bornova":  "izmir-bornova",
    "konyaaltı":"antalya-konyaalti",
    "muratpaşa":"antalya-muratpasa",
    "nilüfer":  "bursa-nilufer",
}


def _normalize(s: str) -> str:
    """Türkçe karakter normalize + küçük harf."""
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosüCGIOSU")
    return s.lower().translate(tr_map).strip()


def fetch_sahibinden(il: str, ilce: str, tip: str = "konut",
                     usd_try_rate: Optional[float] = None) -> FetchResult:
    """
    Sahibinden.com'dan ilçe bazlı ortalama m² fiyatı çek.
    cloudscraper yüklü değilse veya Cloudflare engel çıkarsa hata döner.
    """
    slug_key = _normalize(ilce)
    il_n = _normalize(il)
    slug = _ILCE_SLUG.get(slug_key) or f"{il_n}-{slug_key}"
    cat  = _SBD_CATEGORY.get(tip, "satilik-daire")
    url  = f"https://www.sahibinden.com/{cat}/{slug}"

    cache_key = f"sbd:{slug}:{tip}"
    cached = _cache_get(cache_key)
    if cached:
        result_try = cached * usd_try_rate if usd_try_rate else None
        return FetchResult(il=il, ilce=ilce, tip=tip,
                           fiyat_usd_m2=cached, fiyat_try_m2=result_try,
                           kaynak="sahibinden_cache",
                           guncelleme=datetime.now().isoformat()[:10])

    try:
        import cloudscraper  # type: ignore
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        resp = scraper.get(url, timeout=15)
        if resp.status_code != 200:
            return FetchResult(il=il, ilce=ilce, tip=tip,
                               fiyat_usd_m2=None, fiyat_try_m2=None,
                               kaynak="sahibinden", guncelleme=datetime.now().isoformat()[:10],
                               hata=f"HTTP {resp.status_code}")

        html = resp.text

        # Fiyat çekme — TL/m² ortalama
        # Sahibinden yapısı: "X.XXX TL/m²" veya data JSON içinde
        prices_try = []

        # Yöntem 1: HTML'den regex
        for m in re.finditer(r'([\d\.]+)\s*TL\s*/\s*m', html):
            try:
                p = float(m.group(1).replace(".", ""))
                if 1000 < p < 500_000_000:  # makul aralık
                    prices_try.append(p)
            except Exception:
                pass

        # Yöntem 2: JSON içinden
        json_blocks = re.findall(r'"pricePerSquareMeter"\s*:\s*([\d.]+)', html)
        for jb in json_blocks:
            try:
                p = float(jb)
                if 1000 < p < 500_000_000:
                    prices_try.append(p)
            except Exception:
                pass

        if not prices_try:
            return FetchResult(il=il, ilce=ilce, tip=tip,
                               fiyat_usd_m2=None, fiyat_try_m2=None,
                               kaynak="sahibinden", guncelleme=datetime.now().isoformat()[:10],
                               hata="Fiyat verisi parse edilemedi")

        # Uç değerleri at, ortanca al
        prices_try.sort()
        trim = max(1, len(prices_try) // 5)
        trimmed = prices_try[trim:-trim] if len(prices_try) > 4 else prices_try
        avg_try = sum(trimmed) / len(trimmed)

        avg_usd = (avg_try / usd_try_rate) if usd_try_rate else None
        _cache_set(cache_key, avg_usd or avg_try)

        return FetchResult(
            il=il, ilce=ilce, tip=tip,
            fiyat_usd_m2=avg_usd,
            fiyat_try_m2=avg_try,
            kaynak="sahibinden",
            guncelleme=datetime.now().isoformat()[:10],
            ham_veri={"url": url, "ornek_sayisi": len(trimmed)},
        )

    except ImportError:
        return FetchResult(il=il, ilce=ilce, tip=tip,
                           fiyat_usd_m2=None, fiyat_try_m2=None,
                           kaynak="sahibinden", guncelleme=datetime.now().isoformat()[:10],
                           hata="cloudscraper yüklü değil. pip install cloudscraper")
    except Exception as e:
        return FetchResult(il=il, ilce=ilce, tip=tip,
                           fiyat_usd_m2=None, fiyat_try_m2=None,
                           kaynak="sahibinden", guncelleme=datetime.now().isoformat()[:10],
                           hata=str(e))


# ---------------------------------------------------------------------------
# Seçenek B: TCMB EVDS API
# ---------------------------------------------------------------------------
# Konut Fiyat Endeksi serileri (TÜİK kaynaklı, EVDS üzerinden)
_EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"

# İl bazlı EVDS seri kodları (Konut Fiyat Endeksi)
_EVDS_SERIES: Dict[str, str] = {
    "istanbul":  "TP.HKFE02.B001",
    "ankara":    "TP.HKFE02.B006",
    "izmir":     "TP.HKFE02.B035",
    "antalya":   "TP.HKFE02.B007",
    "bursa":     "TP.HKFE02.B016",
    "turkiye":   "TP.HKFE02",       # Türkiye geneli
}


def fetch_tcmb_evds(il: str, evds_api_key: Optional[str] = None,
                    usd_try_rate: Optional[float] = None) -> FetchResult:
    """
    TCMB EVDS'den konut fiyat endeksi çek.
    Mutlak fiyat değil endeks değeri döner — static DB ile kombinlenebilir.

    API Key: https://evds2.tcmb.gov.tr → Üye Ol → Profil → API Key
    Env var: EVDS_API_KEY
    """
    api_key = evds_api_key or os.environ.get("EVDS_API_KEY")
    if not api_key:
        return FetchResult(il=il, ilce="tümü", tip="konut",
                           fiyat_usd_m2=None, fiyat_try_m2=None,
                           kaynak="tcmb_evds", guncelleme=datetime.now().isoformat()[:10],
                           hata="EVDS_API_KEY bulunamadı. Env var veya parametre olarak ver.")

    il_key = _normalize(il)
    series = _EVDS_SERIES.get(il_key, _EVDS_SERIES["turkiye"])

    cache_key = f"evds:{il_key}"
    cached = _cache_get(cache_key)
    if cached:
        return FetchResult(il=il, ilce="tümü", tip="konut",
                           fiyat_usd_m2=None, fiyat_try_m2=cached,
                           kaynak="tcmb_evds_cache", guncelleme=datetime.now().isoformat()[:10],
                           ham_veri={"endeks": cached, "not": "Bu endeks değeridir, mutlak fiyat değil"})

    # Son 3 ay
    bitis = datetime.now().strftime("%d-%m-%Y")
    baslangic = (datetime.now() - timedelta(days=90)).strftime("%d-%m-%Y")
    url = (f"{_EVDS_BASE}?series={series}"
           f"&startDate={baslangic}&endDate={bitis}"
           f"&type=json&key={api_key}")
    try:
        req = Request(url, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        items = data.get("items", [])
        values = []
        for item in items:
            v = item.get(series.split(".")[-1]) or item.get(series)
            if v and v != "ND":
                try:
                    values.append(float(v))
                except Exception:
                    pass

        if not values:
            return FetchResult(il=il, ilce="tümü", tip="konut",
                               fiyat_usd_m2=None, fiyat_try_m2=None,
                               kaynak="tcmb_evds", guncelleme=datetime.now().isoformat()[:10],
                               hata="EVDS'den veri alınamadı")

        latest_endeks = values[-1]
        _cache_set(cache_key, latest_endeks)

        return FetchResult(
            il=il, ilce="tümü", tip="konut",
            fiyat_usd_m2=None,
            fiyat_try_m2=latest_endeks,   # endeks değeri
            kaynak="tcmb_evds",
            guncelleme=datetime.now().isoformat()[:10],
            ham_veri={"endeks": latest_endeks, "seri": series,
                      "not": "TÜİK konut fiyat endeksi (2017=100). Mutlak fiyat değil."},
        )

    except Exception as e:
        return FetchResult(il=il, ilce="tümü", tip="konut",
                           fiyat_usd_m2=None, fiyat_try_m2=None,
                           kaynak="tcmb_evds", guncelleme=datetime.now().isoformat()[:10],
                           hata=str(e))


# ---------------------------------------------------------------------------
# Ana akıllı fetcher — fallback zinciri
# ---------------------------------------------------------------------------

def fetch_market_price(
    il: str,
    ilce: str,
    tip: str = "konut",
    usd_try_rate: Optional[float] = None,
    evds_api_key: Optional[str] = None,
    force_source: Optional[str] = None,   # "sahibinden" | "evds" | "static"
) -> FetchResult:
    """
    Akıllı piyasa fiyatı çekici — fallback zinciri:
    Sahibinden → TCMB EVDS → Statik DB

    Args:
        force_source: Belirli bir kaynağı zorla ("sahibinden" | "evds" | "static")
    """
    # 1. Sahibinden dene
    if force_source in (None, "sahibinden"):
        result = fetch_sahibinden(il, ilce, tip, usd_try_rate)
        if result.fiyat_usd_m2 or result.fiyat_try_m2:
            return result
        logger.info(f"Sahibinden başarısız ({result.hata}), EVDS deneniyor...")

    # 2. TCMB EVDS dene
    if force_source in (None, "evds"):
        result = fetch_tcmb_evds(il, evds_api_key, usd_try_rate)
        if result.fiyat_try_m2:
            return result
        logger.info(f"EVDS başarısız ({result.hata}), statik DB kullanılıyor...")

    # 3. Statik DB fallback (her zaman çalışır)
    from core.market_data import get_fiyat
    static_price = get_fiyat(il, ilce, tip)
    return FetchResult(
        il=il, ilce=ilce, tip=tip,
        fiyat_usd_m2=static_price,
        fiyat_try_m2=(static_price * usd_try_rate) if static_price and usd_try_rate else None,
        kaynak="static_db",
        guncelleme="2025-Q4",
        hata=None if static_price else f"'{il}/{ilce}' statik DB'de yok",
        ham_veri={"not": "2025-Q4 tahmini değer"},
    )


def fetch_bulk(
    il: str,
    ilceler: List[str],
    tip: str = "konut",
    usd_try_rate: Optional[float] = None,
) -> Dict[str, FetchResult]:
    """Birden fazla ilçe için toplu fiyat çek."""
    return {
        ilce: fetch_market_price(il, ilce, tip, usd_try_rate)
        for ilce in ilceler
    }
