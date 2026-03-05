"""
core/cashflow.py — Nakit Akış Motoru
Proje ve özkaynak düzeyinde IRR/NPV, S-Curve maliyet dağılımı, senaryo analizi
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, List, Optional
import math

try:
    import numpy_financial as npf
    HAS_NPF = True
except ImportError:
    HAS_NPF = False

CostCurve     = Literal["slow", "normal", "fast"]
SalesVelocity = Literal["slow", "normal", "fast"]
Granularity   = Literal["quarterly", "monthly"]

# S-eğrisi maliyet ağırlıkları (8 çeyrek, normalize — diğer sürelere interpolasyon yapılır)
S_CURVE_WEIGHTS: dict[CostCurve, list[float]] = {
    "slow":   [0.04, 0.08, 0.13, 0.18, 0.22, 0.17, 0.11, 0.07],
    "normal": [0.07, 0.14, 0.22, 0.22, 0.16, 0.10, 0.06, 0.03],
    "fast":   [0.14, 0.24, 0.26, 0.18, 0.09, 0.05, 0.03, 0.01],
}

SALES_VELOCITY_PARAMS: dict[SalesVelocity, dict] = {
    "slow":   {"ramp_quarters": 4, "peak_weight": 0.20},
    "normal": {"ramp_quarters": 3, "peak_weight": 0.35},
    "fast":   {"ramp_quarters": 2, "peak_weight": 0.55},
}


@dataclass
class CashFlowScenario:
    name: str
    cost_curve: CostCurve          = "normal"
    presale_ratio: float            = 0.30         # 0.0 – 0.6
    sales_velocity: SalesVelocity  = "normal"
    equity_ratio: float             = 0.50
    loan_interest_annual: float     = 0.22
    # Tahsilat yapısı (toplam = 1.0)
    collection_kaparo: float        = 0.10
    collection_contract: float      = 0.15
    collection_installment: float   = 0.35
    collection_delivery: float      = 0.40


@dataclass
class PeriodCashFlow:
    period: str
    cost: float
    revenue: float
    loan_drawdown: float
    loan_repayment: float
    net: float            # gelir - maliyet + kredi - geri ödeme
    cumulative: float     # birikimli nakit pozisyonu


@dataclass
class CashFlowResult:
    scenario: CashFlowScenario
    periods: List[PeriodCashFlow]
    max_funding_need: float    # en dip nakit (negatif → finansman ihtiyacı)
    breakeven_period: int      # nakit pozitife geçtiği periyot (-1 = geçmedi)
    irr_project: float         # proje (unlevered) IRR — yıllık
    irr_equity: float          # özkaynak IRR — yıllık
    npv_project: float         # proje NPV (%15 iskonto, USD)
    payback_years: float       # geri ödeme süresi (yıl)
    total_cost: float
    total_revenue: float
    total_loan_interest: float


# ---------------------------------------------------------------------------
# Presetler
# ---------------------------------------------------------------------------

PRESET_PESSIMISTIC = CashFlowScenario(
    name="🐻 Kötümser",
    cost_curve="slow", presale_ratio=0.10, sales_velocity="slow",
    equity_ratio=0.30, loan_interest_annual=0.28,
)
PRESET_BASE = CashFlowScenario(
    name="🎯 Baz",
    cost_curve="normal", presale_ratio=0.30, sales_velocity="normal",
    equity_ratio=0.50, loan_interest_annual=0.22,
)
PRESET_OPTIMISTIC = CashFlowScenario(
    name="🚀 İyimser",
    cost_curve="fast", presale_ratio=0.60, sales_velocity="fast",
    equity_ratio=0.70, loan_interest_annual=0.18,
)
ALL_PRESETS = [PRESET_PESSIMISTIC, PRESET_BASE, PRESET_OPTIMISTIC]


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _interpolate_weights(base: list[float], n: int) -> list[float]:
    """n periyoda ağırlık vektörü interpolasyonu."""
    bn = len(base)
    if bn == n:
        return list(base)
    result = []
    for i in range(n):
        src = i * (bn - 1) / max(n - 1, 1)
        lo, hi = int(src), min(int(src) + 1, bn - 1)
        frac = src - lo
        result.append(base[lo] * (1 - frac) + base[hi] * frac)
    total = sum(result) or 1.0
    return [v / total for v in result]


def _safe_irr(cashflows: list[float]) -> float:
    """IRR hesapla; hata veya anlamsız sonuçta 0 döndür."""
    if not HAS_NPF:
        return 0.0
    # En az bir işaret değişimi gerekli
    signs = [1 if v >= 0 else -1 for v in cashflows]
    changes = sum(1 for i in range(len(signs) - 1) if signs[i] != signs[i + 1])
    if changes < 1:
        return 0.0
    try:
        val = float(npf.irr(cashflows))
        if math.isnan(val) or math.isinf(val) or val < -1:
            return 0.0
        return val
    except Exception:
        return 0.0


def _safe_npv(rate_annual: float, cashflows: list[float]) -> float:
    if not HAS_NPF:
        return 0.0
    try:
        rate_q = (1 + rate_annual) ** 0.25 - 1
        return float(npf.npv(rate_q, cashflows))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Ana hesaplama
# ---------------------------------------------------------------------------

def compute_cashflow(
    total_cost_usd: float,
    satilabilir_alan_m2: float,
    satis_fiyat_usd_m2: float,
    project_duration_quarters: int = 8,
    scenario: CashFlowScenario = PRESET_BASE,
    usd_try_rate: Optional[float] = None,
    granularity: Granularity = "quarterly",
    start_year: int = 2026,
    start_quarter: int = 1,
) -> CashFlowResult:
    """
    Nakit akış hesabı — proje ve özkaynak düzeyinde IRR/NPV.

    Args:
        total_cost_usd:              Toplam proje maliyeti (inşaat + arsa, USD)
        satilabilir_alan_m2:         Satılabilir alan (m²)
        satis_fiyat_usd_m2:          Satış birim fiyatı (USD/m²)
        project_duration_quarters:   Proje süresi (çeyrek, 4–16)
        scenario:                    CashFlowScenario objesi
        usd_try_rate:                USD/TRY kuru (opsiyonel, gelecek kullanım)
        granularity:                 Gösterim granülaritesi (şimdilik quarterly)
        start_year / start_quarter:  Proje başlangıcı
    """
    n = max(4, min(16, project_duration_quarters))
    total_revenue = satilabilir_alan_m2 * satis_fiyat_usd_m2

    # ── Maliyet dağılımı (S-eğrisi) ────────────────────────────────────────
    cost_w = _interpolate_weights(S_CURVE_WEIGHTS[scenario.cost_curve], n)
    costs = [total_cost_usd * w for w in cost_w]

    # ── Satış & tahsilat dağılımı ──────────────────────────────────────────
    vel = SALES_VELOCITY_PARAMS[scenario.sales_velocity]
    ramp = min(vel["ramp_quarters"], n - 1)

    # Satış oranı per quarter (hangi çeyrekte ne kadar birim satıldı)
    sales_q = [0.0] * n
    sales_q[0] = min(scenario.presale_ratio, 0.70)
    remaining = 1.0 - sales_q[0]
    cw = [0.0] * n
    for i in range(1, n):
        if i <= ramp:
            cw[i] = vel["peak_weight"] * i / ramp
        else:
            cw[i] = vel["peak_weight"] * max(0.0, (n - i) / max(n - ramp, 1))
    cw_total = sum(cw) or 1.0
    for i in range(1, n):
        sales_q[i] += remaining * cw[i] / cw_total

    # Tahsilatları dönemlere dağıt
    rev = [0.0] * (n + 2)
    for q, sr in enumerate(sales_q):
        if sr <= 0:
            continue
        ur = total_revenue * sr
        # Kaparo: satış çeyreğinde
        rev[q] += ur * scenario.collection_kaparo
        # Sözleşme: bir sonraki çeyrekte
        rev[min(q + 1, n + 1)] += ur * scenario.collection_contract
        # Taksit: kalan çeyrekler boyunca eşit
        rem_q = max(n - q - 1, 1)
        for tq in range(q + 1, n):
            rev[tq] += ur * scenario.collection_installment / rem_q
        # Teslim: son çeyrekte
        rev[n - 1] += ur * scenario.collection_delivery
    rev = rev[:n]

    # ── Kredi hesabı ───────────────────────────────────────────────────────
    loan_ratio = 1.0 - scenario.equity_ratio
    total_loan = total_cost_usd * loan_ratio
    q_rate = (1 + scenario.loan_interest_annual) ** 0.25 - 1

    draws = [0.0] * n
    drawn = 0.0
    for q in range(n // 2):
        d = min(costs[q] * loan_ratio, total_loan - drawn)
        draws[q] = max(d, 0.0)
        drawn += draws[q]

    repays = [0.0] * n
    total_interest = 0.0
    repay_start = int(n * 2 / 3)
    repay_n = n - repay_start
    outstanding = drawn
    if repay_n > 0 and drawn > 0:
        principal_q = drawn / repay_n
        for q in range(repay_start, n):
            interest = outstanding * q_rate
            repays[q] = principal_q + interest
            total_interest += interest
            outstanding = max(0.0, outstanding - principal_q)

    # ── Periyot ismi ───────────────────────────────────────────────────────
    def pname(q: int) -> str:
        yr = start_year + (start_quarter - 1 + q) // 4
        qr = ((start_quarter - 1 + q) % 4) + 1
        return f"Q{qr} {yr}"

    # ── Periyotlar ─────────────────────────────────────────────────────────
    periods: List[PeriodCashFlow] = []
    cumulative = 0.0
    # IRR için nakit akış listeleri
    project_cf: list[float] = []   # unlevered: rev - cost
    equity_cf: list[float] = []    # levered:   rev - equity_cost - repay + draw

    for q in range(n):
        net = rev[q] - costs[q] + draws[q] - repays[q]
        cumulative += net
        periods.append(PeriodCashFlow(
            period=pname(q),
            cost=costs[q],
            revenue=rev[q],
            loan_drawdown=draws[q],
            loan_repayment=repays[q],
            net=net,
            cumulative=cumulative,
        ))
        project_cf.append(rev[q] - costs[q])
        equity_cf.append(rev[q] - costs[q] * scenario.equity_ratio - repays[q])

    # ── Özet metrikler ─────────────────────────────────────────────────────
    cum_vals = [p.cumulative for p in periods]
    max_funding = min(cum_vals)
    breakeven = next((i for i, v in enumerate(cum_vals) if v >= 0), -1)

    # Proje IRR (unlevered, quarterly → yıllık)
    irr_project_q = _safe_irr(project_cf)
    irr_project = (1 + irr_project_q) ** 4 - 1 if irr_project_q != 0 else 0.0

    # Özkaynak IRR (levered)
    irr_equity_q = _safe_irr(equity_cf)
    irr_equity = (1 + irr_equity_q) ** 4 - 1 if irr_equity_q != 0 else 0.0

    npv_project = _safe_npv(0.15, project_cf)
    payback = breakeven / 4.0 if breakeven >= 0 else (n / 4.0 + 1.0)

    return CashFlowResult(
        scenario=scenario,
        periods=periods,
        max_funding_need=max_funding,
        breakeven_period=breakeven,
        irr_project=irr_project,
        irr_equity=irr_equity,
        npv_project=npv_project,
        payback_years=payback,
        total_cost=total_cost_usd,
        total_revenue=sum(rev),
        total_loan_interest=total_interest,
    )


def compare_scenarios(
    total_cost_usd: float,
    satilabilir_alan_m2: float,
    satis_fiyat_usd_m2: float,
    project_duration_quarters: int = 8,
    scenarios: Optional[List[CashFlowScenario]] = None,
    usd_try_rate: Optional[float] = None,
) -> List[CashFlowResult]:
    """Tüm preset senaryoları tek seferde hesapla ve listele."""
    if scenarios is None:
        scenarios = ALL_PRESETS
    return [
        compute_cashflow(
            total_cost_usd, satilabilir_alan_m2, satis_fiyat_usd_m2,
            project_duration_quarters, sc, usd_try_rate
        )
        for sc in scenarios
    ]
