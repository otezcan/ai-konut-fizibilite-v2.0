import streamlit as st
from openai import OpenAI
from datetime import datetime, date
import hashlib
from typing import Dict, Any, Optional
import xml.etree.ElementTree as ET
from urllib.request import urlopen
import json
import pandas as pd
import time

from feasibility import compute_outputs, sensitivity, DEFAULTS, DAIRE_TIPLERI
from pdf_report import build_pdf
from excel_export import create_excel_report, create_comparison_excel
from formatters import fmt_int, fmt_usd, fmt_try, fmt_pct, fmt_m2

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================
APP_TITLE = "AI Konut Fizibilite Asistani"
APP_SUBTITLE = "Hizli, Akilli, Profesyonel Analiz"
DEFAULT_DAILY_LIMIT = 100  # Updated: 100 hesaplama/kullanıcı/gün
TCMB_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"

# Modern color scheme
PRIMARY_COLOR = "#1E3A8A"
ACCENT_COLOR = "#3B82F6"
SUCCESS_COLOR = "#10B981"
WARNING_COLOR = "#F59E0B"
DANGER_COLOR = "#EF4444"

# Example scenarios for quick start
EXAMPLE_SCENARIOS = {
    "Küçük Proje (5.000 m²)": {
        "arsa_alani_m2": 5000,
        "emsal": 1.8,
        "otopark_tipi": "ACIK",
        "konut_sinifi": "ORTA",
        "arsa_toplam_degeri_usd": 2500000,
        "ortalama_konut_m2": 100,
    },
    "Orta Proje (8.500 m²)": {
        "arsa_alani_m2": 8500,
        "emsal": 2.0,
        "otopark_tipi": "KAPALI",
        "konut_sinifi": "YUKSEK",
        "arsa_toplam_degeri_usd": 5500000,
        "ortalama_konut_m2": 135,
    },
    "Büyük Proje (15.000 m²)": {
        "arsa_alani_m2": 15000,
        "emsal": 2.2,
        "otopark_tipi": "KAPALI",
        "konut_sinifi": "YUKSEK",
        "arsa_toplam_degeri_usd": 10000000,
        "ortalama_konut_m2": 150,
    },
}

# ============================================================================
# HELPER FUNCTIONS (Formatting now in formatters.py)
# ============================================================================

def get_client() -> OpenAI:
    api_key = st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        st.error("🔑 OPENAI_API_KEY eksik. Streamlit Secrets'e eklemelisin.")
        st.stop()
    return OpenAI(api_key=api_key)

def stable_user_key() -> str:
    try:
        xf = st.context.headers.get("X-Forwarded-For", "")
        ua = st.context.headers.get("User-Agent", "")
    except Exception:
        xf, ua = "", ""
    base = (xf or "") + "|" + (ua or "") + "|" + st.session_state.get("session_fallback", "fallback")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]

@st.cache_resource
def usage_store():
    return {"day": date.today().isoformat(), "counts": {}}

def check_and_increment_quota() -> tuple[bool, int, int]:
    """
    Returns (success, remaining, total)
    
    IMPORTANT: This is ONLY called when "Hesapla" button is pressed,
    NOT during chat interactions. Chat is unlimited!
    """
    store = usage_store()
    today = date.today().isoformat()
    if store["day"] != today:
        store["day"] = today
        store["counts"] = {}
    key = stable_user_key()
    limit = int(st.secrets.get("DAILY_LIMIT", DEFAULT_DAILY_LIMIT))
    
    # If limit is very high (>1000), treat as unlimited
    if limit >= 1000:
        return True, 999999, 999999
    
    count = store["counts"].get(key, 0)
    remaining = max(0, limit - count)
    if count >= limit:
        return False, 0, limit
    store["counts"][key] = count + 1
    return True, remaining - 1, limit

def ensure_defaults(inputs: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(inputs)
    out.setdefault("satilabilir_katsayi", DEFAULTS["satilabilir_katsayi"])
    out.setdefault("ortalama_konut_m2", DEFAULTS["ortalama_konut_m2"])
    if out.get("otopark_tipi") in ["ACIK", "KAPALI"] and "otopark_katsayi" not in out:
        out["otopark_katsayi"] = DEFAULTS["otopark_katsayi"][out["otopark_tipi"]]
    if out.get("konut_sinifi") in ["ALT", "ORTA", "YUKSEK"] and "insaat_maliyet_usd_m2" not in out:
        out["insaat_maliyet_usd_m2"] = DEFAULTS["insaat_maliyet_usd_m2"][out["konut_sinifi"]]
    return out

@st.cache_data(ttl=60 * 30)
def fetch_usd_try_from_tcmb() -> Dict[str, Optional[str]]:
    try:
        with urlopen(TCMB_URL, timeout=10) as r:
            xml_bytes = r.read()
        root = ET.fromstring(xml_bytes)
        tarih = root.attrib.get("Tarih", None)

        usd_node = None
        for cur in root.findall("Currency"):
            code = cur.attrib.get("CurrencyCode", "")
            if code == "USD":
                usd_node = cur
                break

        if usd_node is None:
            return {"rate": None, "date": tarih, "source": "TCMB today.xml"}

        selling = usd_node.findtext("ForexSelling")
        buying = usd_node.findtext("ForexBuying")
        val = selling or buying
        if val is None:
            return {"rate": None, "date": tarih, "source": "TCMB today.xml"}

        rate = float(val.strip())
        return {"rate": rate, "date": tarih, "source": "TCMB today.xml"}
    except Exception:
        return {"rate": None, "date": None, "source": "TCMB today.xml"}

# ============================================================================
# LLM INTEGRATION
# ============================================================================
PARSE_TOOL = {
    "type": "function",
    "function": {
        "name": "patch_inputs",
        "description": "Kullanici mesajindan fizibilite girdilerini cikart ve mevcut inputs uzerine uygulanacak patch uret.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": "Sadece bulunan alanlari ekle. Bulamadiklari ekleme.",
                    "properties": {
                        "arsa_alani_m2": {"type": "number"},
                        "emsal": {"type": "number"},
                        "satilabilir_katsayi": {"type": "number"},
                        "otopark_tipi": {"type": "string", "enum": ["ACIK", "KAPALI"]},
                        "otopark_katsayi": {"type": "number"},
                        "satis_birim_fiyat_usd_m2": {"type": "number"},
                        "konut_sinifi": {"type": "string", "enum": ["ALT", "ORTA", "YUKSEK"]},
                        "insaat_maliyet_usd_m2": {"type": "number"},
                        "arsa_toplam_degeri_usd": {"type": "number"},
                        "ortalama_konut_m2": {"type": "number"},
                    },
                    "additionalProperties": False
                },
                "explanations": {"type": "array", "items": {"type": "string"}},
                "next_questions": {"type": "array", "items": {"type": "string"}},
                "confirmations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["patch", "next_questions", "confirmations", "explanations"],
            "additionalProperties": False
        }
    }
}

AGENT_SYSTEM = """
Sen bir "Konut Fizibilite Asistani"sin. Amac: kullanicidan girdileri pratik sekilde toplayip, kabulleri netlestirip, sonuclari kisa ve anlasilir sunmak.

Kritik akis:
1) Ilk mesajinda kullanicidan asagidaki sablonu tek seferde doldurmasini iste:
   - Arsa alani (m²)
   - Emsal
   - Otopark (Acik/Kapali)
   - Konut sinifi (Alt/Orta/Yuksek)
   - Arsa degeri ($)
   - (Opsiyonel) Ortalama konut m² (default 120)
2) Satis fiyatini ilk turda isteme.
   Once: basabas satis fiyati + %10/%30/%50 hedef satis fiyatlarini goster.
   Sonra: "Hangi satis fiyatiyla calisalim?" diye sor.
3) Kullanici anlamsiz deger girerse nazikce teyit iste (emsal>5, arsa alani cok kucuk, vb.)

Kurallar:
- Matematiksel hesap yapma. Arayuz sonuc paneli hesaplayacak.
- patch_inputs tool'u ile sadece patch uret.
Dil: Turkce, net, premium ton (kisa, maddeli).
"""

def llm_extract_patch(client: OpenAI, user_text: str, current_inputs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model=st.secrets.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": AGENT_SYSTEM},
                {"role": "user", "content": f"Mevcut inputs: {current_inputs}\n\nKullanici mesaji: {user_text}"}
            ],
            tools=[PARSE_TOOL],
            tool_choice="required",
            temperature=0.2
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"patch": {}, "explanations": [], "next_questions": ["Tekrar dener misin?"], "confirmations": []}
        
        tool_call = msg.tool_calls[0]
        data = json.loads(tool_call.function.arguments)
        return data
    except Exception as e:
        st.error(f"LLM hatasi: {str(e)}")
        return {"patch": {}, "explanations": [], "next_questions": [], "confirmations": []}

def merge_patch(inputs: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(inputs)
    for k, v in patch.items():
        merged[k] = v
    return ensure_defaults(merged)

def compute_if_possible(inputs: Dict[str, Any], usd_try_rate: Optional[float]):
    must = ["arsa_alani_m2", "emsal", "otopark_tipi", "konut_sinifi", "arsa_toplam_degeri_usd"]
    if not all(k in inputs and inputs[k] not in [None, ""] for k in must):
        return None
    outputs, warnings = compute_outputs(inputs, usd_try_rate=usd_try_rate)
    return {"outputs": outputs, "warnings": warnings}

# ============================================================================
# MODERN UI COMPONENTS
# ============================================================================
def render_metric_card(label: str, value: str, delta: Optional[str] = None, icon: str = "📊"):
    """Render a beautiful metric card"""
    delta_html = f"<div style='font-size: 0.8em; color: #64748B; margin-top: 4px;'>{delta}</div>" if delta else ""
    
    st.markdown(f"""
    <div style='
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        color: white;
    '>
        <div style='font-size: 2em; margin-bottom: 8px;'>{icon}</div>
        <div style='font-size: 0.9em; opacity: 0.9; text-transform: uppercase; letter-spacing: 1px;'>{label}</div>
        <div style='font-size: 1.8em; font-weight: bold; margin-top: 8px;'>{value}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)

def render_progress_bar(percentage: float, label: str):
    """Render a colorful progress bar"""
    color = SUCCESS_COLOR if percentage > 30 else WARNING_COLOR if percentage > 10 else DANGER_COLOR
    st.markdown(f"""
    <div style='margin: 10px 0;'>
        <div style='display: flex; justify-content: space-between; margin-bottom: 4px;'>
            <span style='font-size: 0.9em; color: #64748B;'>{label}</span>
            <span style='font-size: 0.9em; font-weight: bold; color: {color};'>{percentage:.1f}%</span>
        </div>
        <div style='background: #E5E7EB; border-radius: 8px; height: 8px; overflow: hidden;'>
            <div style='background: {color}; width: {percentage}%; height: 100%; transition: width 0.3s;'></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_kpi_grid(outputs: Dict[str, Any]):
    """Render KPI grid with beautiful cards"""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        render_metric_card(
            "Satilabilir Alan",
            fmt_int(outputs.get('satilabilir_alan_m2')) + " m²",
            icon="🏗️"
        )
    
    with col2:
        render_metric_card(
            "Konut Adedi",
            str(int(outputs.get('yaklasik_konut_adedi', 0))),
            f"~{fmt_int(outputs.get('kalan_satilabilir_alan_m2'))} m² kalan",
            icon="🏘️"
        )
    
    with col3:
        render_metric_card(
            "Toplam Maliyet",
            fmt_usd(outputs.get('toplam_proje_maliyeti_usd')),
            fmt_try(outputs.get('toplam_proje_maliyeti_try')),
            icon="💰"
        )
    
    with col4:
        kar = outputs.get('proje_kari_usd')
        karlilik = outputs.get('brut_karlilik_orani', 0)
        if kar and kar > 0:
            render_metric_card(
                "Proje Kari",
                fmt_usd(kar),
                f"Karlilik: {fmt_pct(karlilik)}",
                icon="💎"
            )
        else:
            render_metric_card(
                "Basabas Fiyat",
                fmt_int(outputs.get('breakeven_usd_m2')) + " $/m²",
                fmt_int(outputs.get('breakeven_try_m2')) + " ₺/m²",
                icon="⚖️"
            )

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================
st.set_page_config(
    page_title="AI Konut Fizibilite",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Modern CSS
st.markdown("""
<style>
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Modern font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Compact header */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    
    /* Better buttons */
    .stButton > button {
        width: 100%;
        border-radius: 8px;
        font-weight: 600;
        padding: 0.5rem 1rem;
        transition: all 0.2s;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    /* Chat messages */
    .stChatMessage {
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.75rem 1.5rem;
    }
    
    /* Info boxes */
    .stAlert {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE INIT
# ============================================================================
if "session_fallback" not in st.session_state:
    st.session_state.session_fallback = hashlib.sha256(str(datetime.now()).encode()).hexdigest()

if "inputs" not in st.session_state:
    st.session_state.inputs = ensure_defaults({})
if "messages" not in st.session_state:
    st.session_state.messages = []
if "initialized" not in st.session_state:
    st.session_state.initialized = False
if "scenarios" not in st.session_state:
    st.session_state.scenarios = []  # For comparison mode

# ============================================================================
# HEADER
# ============================================================================
st.markdown(f"""
<div style='text-align: center; padding: 1rem 0 2rem 0;'>
    <h1 style='
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.5em;
        font-weight: 700;
        margin: 0;
    '>{APP_TITLE}</h1>
    <p style='color: #64748B; font-size: 1.1em; margin-top: 0.5rem;'>{APP_SUBTITLE}</p>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# SIDEBAR - CURRENCY & QUOTA
# ============================================================================
with st.sidebar:
    st.markdown("### ⚙️ Ayarlar")
    
    # Currency
    tcmb = fetch_usd_try_from_tcmb()
    auto_rate = tcmb.get("rate", None)
    rate_date = tcmb.get("date", None)
    
    if auto_rate:
        st.success(f"💱 **USD/TRY:** {auto_rate:.4f} TL")
        if rate_date:
            st.caption(f"📅 {rate_date}")
    else:
        st.warning("Kur alinamadi")
    
    override = st.checkbox("Manuel kur kullan", value=False)
    if override:
        manual_rate = st.number_input("USD/TRY", value=float(auto_rate or 33.0), step=0.10, format="%.2f")
        usd_try_rate = manual_rate
    else:
        usd_try_rate = auto_rate
    
    st.divider()
    
    # Quota (only show if limited)
    _, remaining, total = check_and_increment_quota()
    if total < 1000:  # If total < 1000, show quota. Otherwise unlimited
        quota_pct = (remaining / total * 100) if total > 0 else 0
        
        st.markdown("### 📊 Kullanim")
        render_progress_bar(quota_pct, f"{remaining}/{total} hesaplama kaldi")
        
        st.divider()
    
    # Quick actions
    st.markdown("### 🚀 Hizli Islemler")
    if st.button("🔄 Yeni Hesaplama", use_container_width=True):
        st.session_state.inputs = ensure_defaults({})
        st.session_state.messages = []
        st.session_state.initialized = False
        st.rerun()
    
    st.divider()
    
    # Example scenarios
    st.markdown("### 🎯 Ornek Senaryolar")
    st.caption("Hizli test icin hazir sablonlar")
    
    scenario_name = st.selectbox(
        "Senaryo sec",
        [""] + list(EXAMPLE_SCENARIOS.keys()),
        label_visibility="collapsed"
    )
    
    if scenario_name and scenario_name in EXAMPLE_SCENARIOS:
        if st.button("📥 Yukle", use_container_width=True, key="load_scenario"):
            st.session_state.inputs = ensure_defaults(EXAMPLE_SCENARIOS[scenario_name])
            st.success(f"✅ {scenario_name} yuklendi!")
            time.sleep(0.5)
            st.rerun()
    
    if st.button("📄 Son Raporu İndir", use_container_width=True, disabled=True):
        st.info("Henuz rapor olusturulmadi")

# ============================================================================
# MAIN CONTENT - TABS
# ============================================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["💬 AI Asistan", "📊 Hızlı Hesap", "📈 Sonuçlar", "💰 Nakit Akış", "🏗️ Karma Kullanım", "📍 Piyasa Karşılaştırma"])

client = get_client()

# TAB 1: AI Chat Assistant
with tab1:
    st.markdown("### AI Destekli Analiz")
    st.caption("Bilgilerinizi dogal dille yazin, AI size yardimci olsun")
    
    if not st.session_state.initialized:
        st.session_state.initialized = True
        intro = (
            "👋 Merhaba! Konut projesi icin hizli fizibilite cikaralim.\n\n"
            "**Lütfen su bilgileri tek mesajda yaz:**\n"
            "- Arsa alani (m²)\n"
            "- Emsal\n"
            "- Otopark (Acik/Kapali)\n"
            "- Konut sinifi (Alt/Orta/Yuksek)\n"
            "- Arsa degeri ($)\n\n"
            "Satis fiyatini en sonda isteyecegim; once basabas ve hedef fiyatlari gosterecegim."
        )
        st.session_state.messages.append({"role": "assistant", "content": intro})

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    user_text = st.chat_input("Bilgileri yaz veya bir degeri guncelle...")
    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})

        data = llm_extract_patch(client, user_text, st.session_state.inputs)
        patch = data.get("patch", {})
        explanations = data.get("explanations", [])
        confirmations = data.get("confirmations", [])
        next_qs = data.get("next_questions", [])

        st.session_state.inputs = merge_patch(st.session_state.inputs, patch)

        result = compute_if_possible(st.session_state.inputs, usd_try_rate)

        if result:
            outs = result["outputs"]
            warns = result["warnings"]

            lines = []
            if explanations:
                lines.append("**Anladiklarim**")
                lines += [f"- {e}" for e in explanations]
            if confirmations:
                lines.append("\n**Kabuller**")
                lines += [f"- {c}" for c in confirmations]

            lines.append("\n**Hizli Ozet**")
            lines.append(f"- Satilabilir alan: **{fmt_int(outs.get('satilabilir_alan_m2'))} m²**")
            lines.append(f"- Toplam proje maliyeti: **{fmt_usd(outs.get('toplam_proje_maliyeti_usd'))}** / **{fmt_try(outs.get('toplam_proje_maliyeti_try'))}**")
            lines.append(f"- Basabas satis: **{fmt_int(outs.get('breakeven_usd_m2'))} $/m²** / **{fmt_int(outs.get('breakeven_try_m2'))} ₺/m²**")

            lines.append("\n**Hedef Satis Fiyatlari (Brut karlilik)**")
            lines.append(f"- %10: **{fmt_int(outs.get('target_10_usd_m2'))} $/m²** / **{fmt_int(outs.get('target_10_try_m2'))} ₺/m²**")
            lines.append(f"- %30: **{fmt_int(outs.get('target_30_usd_m2'))} $/m²** / **{fmt_int(outs.get('target_30_try_m2'))} ₺/m²**")
            lines.append(f"- %50: **{fmt_int(outs.get('target_50_usd_m2'))} $/m²** / **{fmt_int(outs.get('target_50_try_m2'))} ₺/m²**")

            if not outs.get("satis_birim_fiyat_usd_m2"):
                lines.append("\nSimdi hangi **satis fiyatiyla** calisalim? (örn: **2200 $/m²** veya **95.000 ₺/m²**)")

            if warns:
                lines.append("\n**Notlar/Uyarilar**")
                lines += [f"- {w}" for w in warns]

            st.session_state.messages.append({"role": "assistant", "content": "\n".join(lines)})
        else:
            ask = []
            if explanations:
                ask.append("**Anladiklarim**\n" + "\n".join([f"- {e}" for e in explanations]))
            if next_qs:
                ask.append("**Devam**\n" + "\n".join([f"- {q}" for q in next_qs]))
            else:
                ask.append("Devam edelim: Arsa alani (m²), emsal, otopark tipi, konut sinifi ve arsa degerini yazar misin?")
            st.session_state.messages.append({"role": "assistant", "content": "\n\n".join(ask)})

        st.rerun()

# TAB 2: Quick Calculator
with tab2:
    st.markdown("### Hizli Hesaplama")
    st.caption("Formdan dogrudan giris yap")
    
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("#### Arsa Bilgileri")
        arsa = st.number_input(
            "Arsa Alani (m²)", 
            value=float(st.session_state.inputs.get("arsa_alani_m2", 0.0) or 0.0), 
            step=100.0, 
            key="quick_arsa",
            help="📏 Toplam arsa buyuklugu. Ornek: 8.500 m²"
        )
        emsal = st.number_input(
            "Emsal", 
            value=float(st.session_state.inputs.get("emsal", 0.0) or 0.0), 
            step=0.05, 
            format="%.2f", 
            key="quick_emsal",
            help="🏗️ Emsal = Toplam Insaat Alani / Arsa Alani. Tipik: 1.5-2.5"
        )
        arsa_degeri = st.number_input(
            "Arsa Degeri ($)", 
            value=float(st.session_state.inputs.get("arsa_toplam_degeri_usd", 0.0) or 0.0), 
            step=100000.0, 
            key="quick_arsa_degeri",
            help="💰 Arsanin toplam aliş degeri (USD)"
        )
        
        st.markdown("#### Proje Detaylari")
        konut_sinifi = st.selectbox(
            "Konut Sinifi", 
            ["ALT", "ORTA", "YUKSEK"], 
            index=["ALT","ORTA","YUKSEK"].index(st.session_state.inputs.get("konut_sinifi","ORTA")),
            key="quick_sinif",
            help="🏠 Alt: Ekonomik, Orta: Standart, Yuksek: Premium"
        )
        otopark_tipi = st.selectbox(
            "Otopark Tipi", 
            ["ACIK", "KAPALI"], 
            index=0 if st.session_state.inputs.get("otopark_tipi","ACIK")=="ACIK" else 1,
            key="quick_otopark",
            help="🚗 Acik: Acik otopark, Kapali: Kapali otopark"
        )
    
    with col_right:
        st.markdown("#### Gelismis Ayarlar")
        sat_kats = st.number_input(
            "Satilabilir Alan Katsayisi", 
            value=float(st.session_state.inputs.get("satilabilir_katsayi", 1.25)), 
            step=0.01, 
            format="%.2f", 
            key="quick_sat",
            help="📊 Emsal insaat × bu katsayi = satilabilir alan. Tipik: 1.20-1.35"
        )
        ot_kats = st.number_input(
            "Otopark Katsayisi", 
            value=float(st.session_state.inputs.get("otopark_katsayi", DEFAULTS["otopark_katsayi"][otopark_tipi])), 
            step=0.05, 
            format="%.2f", 
            key="quick_ot",
            help="🅿️ Satilabilir alan × bu katsayi = toplam insaat. Acik: ~1.20, Kapali: ~1.60"
        )
        cost = st.number_input(
            "Insaat Maliyeti ($/m²)", 
            value=float(st.session_state.inputs.get("insaat_maliyet_usd_m2", DEFAULTS["insaat_maliyet_usd_m2"][konut_sinifi])), 
            step=25.0, 
            key="quick_cost",
            help="🔨 m² basina insaat maliyeti. Alt: ~700, Orta: ~900, Yuksek: ~1100 $/m²"
        )
        ort_konut = st.number_input(
            "Ortalama Konut (m²)", 
            value=float(st.session_state.inputs.get("ortalama_konut_m2", 120.0)), 
            step=5.0, 
            key="quick_konut",
            help="🏡 Ortalama daire buyuklugu. Tipik: 100-150 m²"
        )
        satis = st.number_input(
            "Satis Fiyati ($/m²)", 
            value=float(st.session_state.inputs.get("satis_birim_fiyat_usd_m2", 0.0) or 0.0), 
            step=50.0, 
            key="quick_satis",
            help="💵 Hedef satis fiyati. Bosveya 0 ise basabas/hedef fiyatlar gosterilir"
        )

    
    if st.button("🧮 HESAPLA", use_container_width=True, type="primary"):
        with st.spinner("⏳ Hesaplaniyor..."):
            st.session_state.inputs = ensure_defaults({
                "arsa_alani_m2": arsa,
                "emsal": emsal,
                "satilabilir_katsayi": sat_kats,
                "otopark_tipi": otopark_tipi,
                "otopark_katsayi": ot_kats,
                "konut_sinifi": konut_sinifi,
                "insaat_maliyet_usd_m2": cost,
                "arsa_toplam_degeri_usd": arsa_degeri,
                "ortalama_konut_m2": ort_konut,
                "satis_birim_fiyat_usd_m2": (satis if satis > 0 else None),
            })
            
            # Quota check - ONLY here, NOT in chat!
            success, remaining, total = check_and_increment_quota()
            time.sleep(0.3)  # Visual feedback
        
        if not success:
            st.error(f"❌ Gunluk limit doldu ({total} hesaplama/gun)")
            st.info("💡 Yarin tekrar dene veya AI Asistan ile sinirsiz sohbet et!")
        else:
            st.success(f"✅ Hesaplama tamamlandi! ({remaining} hesaplama kaldi)")
            time.sleep(0.3)
            st.rerun()

# TAB 3: Results Dashboard
with tab3:
    result = compute_if_possible(st.session_state.inputs, usd_try_rate)
    
    if result:
        outs = result["outputs"]
        warns = result["warnings"]
        
        st.markdown("### 📊 Proje Dashboard")
        
        # Action buttons row
        col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
        
        with col_btn1:
            if st.button("💾 Senaryoyu Kaydet", use_container_width=True):
                scenario_name = f"Senaryo {len(st.session_state.scenarios) + 1}"
                st.session_state.scenarios.append({
                    "name": scenario_name,
                    "inputs": dict(st.session_state.inputs),
                    "outputs": dict(outs),
                    "timestamp": datetime.now().isoformat()
                })
                st.success(f"✅ {scenario_name} kaydedildi!")
                st.rerun()
        
        with col_btn2:
            if len(st.session_state.scenarios) > 0:
                if st.button(f"🔄 Senaryolari Temizle ({len(st.session_state.scenarios)})", use_container_width=True):
                    st.session_state.scenarios = []
                    st.rerun()
        
        with col_btn3:
            if st.button("📄 PDF Rapor", use_container_width=True, type="primary"):
                with st.spinner("PDF hazirlaniyor..."):
                    pdf_path = "konut_fizibilite_raporu.pdf"
                    build_pdf(
                        path=pdf_path,
                        project_title="Konut Projesi Fizibilite",
                        inputs=st.session_state.inputs,
                        outputs=outs,
                        warnings=warns,
                        usd_try_rate=usd_try_rate,
                        rate_source="TCMB today.xml" if usd_try_rate else None,
                    )
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "⬇️ PDF'i indir",
                            data=f,
                            file_name="konut_fizibilite_raporu.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key="pdf_download"
                        )
        
        with col_btn4:
            if st.button("📊 Excel Rapor", use_container_width=True, type="primary"):
                with st.spinner("Excel hazirlaniyor..."):
                    excel_path = "konut_fizibilite_raporu.xlsx"
                    create_excel_report(
                        filepath=excel_path,
                        project_title="Konut Projesi Fizibilite",
                        inputs=st.session_state.inputs,
                        outputs=outs,
                        warnings=warns,
                        usd_try_rate=usd_try_rate,
                        rate_source="TCMB today.xml" if usd_try_rate else None,
                    )
                    with open(excel_path, "rb") as f:
                        st.download_button(
                            "⬇️ Excel'i indir",
                            data=f,
                            file_name="konut_fizibilite_raporu.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="excel_download"
                        )
        
        st.divider()
        
        # KPI Grid
        render_kpi_grid(outs)
        
        st.divider()
        
        # Charts Section
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.markdown("#### 💰 Maliyet Dagilimi")
            
            # Pie Chart data
            import pandas as pd
            
            chart_data = pd.DataFrame({
                "Kategori": ['Arsa Degeri', 'Insaat Maliyeti'],
                "Tutar": [
                    outs.get('arsa_degeri_usd', 0),
                    outs.get('insaat_maliyeti_usd', 0)
                ]
            })
            
            # Display as metrics instead of chart (simpler)
            total = outs.get('toplam_proje_maliyeti_usd', 1)
            arsa_pct = (outs.get('arsa_degeri_usd', 0) / total * 100) if total > 0 else 0
            insaat_pct = (outs.get('insaat_maliyeti_usd', 0) / total * 100) if total > 0 else 0
            
            st.metric("Arsa Degeri", fmt_usd(outs.get('arsa_degeri_usd')), f"{arsa_pct:.1f}%")
            st.metric("Insaat Maliyeti", fmt_usd(outs.get('insaat_maliyeti_usd')), f"{insaat_pct:.1f}%")
            
            render_progress_bar(arsa_pct, "Arsa Payi")
            render_progress_bar(insaat_pct, "Insaat Payi")
        
        with col_chart2:
            st.markdown("#### 📈 Fiyat Karsilastirmasi")
            
            # Bar chart data
            import pandas as pd
            
            categories = ['Basabas', '%10 Kar', '%30 Kar', '%50 Kar']
            usd_prices = [
                outs.get('breakeven_usd_m2', 0),
                outs.get('target_10_usd_m2', 0),
                outs.get('target_30_usd_m2', 0),
                outs.get('target_50_usd_m2', 0),
            ]
            
            chart_df = pd.DataFrame({
                "Hedef": categories,
                "Fiyat": usd_prices
            })
            
            st.bar_chart(chart_df.set_index("Hedef"), height=300)
            
            # Current price indicator if exists
            current_price = outs.get('satis_birim_fiyat_usd_m2', None)
            if current_price:
                st.info(f"🎯 Secilen fiyat: **${current_price:,.0f}/m²**")
        
        st.divider()
        
        # Pricing Strategy Table
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("### 🎯 Satis Fiyat Stratejisi")
            
            pricing_data = {
                "Hedef": ["Basabas", "%10 Kar", "%30 Kar", "%50 Kar"],
                "USD/m²": [
                    fmt_int(outs.get('breakeven_usd_m2')),
                    fmt_int(outs.get('target_10_usd_m2')),
                    fmt_int(outs.get('target_30_usd_m2')),
                    fmt_int(outs.get('target_50_usd_m2')),
                ],
                "TL/m²": [
                    fmt_int(outs.get('breakeven_try_m2')),
                    fmt_int(outs.get('target_10_try_m2')),
                    fmt_int(outs.get('target_30_try_m2')),
                    fmt_int(outs.get('target_50_try_m2')),
                ],
            }
            st.dataframe(pricing_data, use_container_width=True, hide_index=True)
        
        with col2:
            st.markdown("### 🏘️ Konut Bilgileri")
            st.metric("Toplam Konut", f"{int(outs.get('yaklasik_konut_adedi') or 0)} adet")
            st.metric("Ortalama Buyukluk", f"{fmt_int(st.session_state.inputs.get('ortalama_konut_m2', 120))} m²")
            st.metric("Kalan Alan", f"{fmt_int(outs.get('kalan_satilabilir_alan_m2'))} m²")
        
        # Revenue section (if sales price exists)
        if outs.get("satis_birim_fiyat_usd_m2"):
            st.divider()
            st.markdown("### 💰 Gelir & Karlilik")
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Satis Fiyati", f"{fmt_int(outs.get('satis_birim_fiyat_usd_m2'))} $/m²")
            col2.metric("Hasilat (USD)", fmt_usd(outs.get("proje_hasilati_usd")))
            col3.metric("Kar (USD)", fmt_usd(outs.get("proje_kari_usd")))
            col4.metric("Brut Karlilik", fmt_pct(outs.get("brut_karlilik_orani")))
            
            # Profitability gauge
            profit_margin = outs.get("brut_karlilik_orani", 0) * 100
            render_progress_bar(profit_margin, "Karlilik Orani")
            
            # Revenue breakdown visual
            st.markdown("#### 💵 Gelir Analizi")
            
            col_r1, col_r2, col_r3 = st.columns(3)
            
            hasilat = outs.get("proje_hasilati_usd", 0)
            maliyet = outs.get("toplam_proje_maliyeti_usd", 0)
            kar = outs.get("proje_kari_usd", 0)
            
            col_r1.metric("1️⃣ Hasilat", fmt_usd(hasilat))
            col_r2.metric("2️⃣ Maliyet", fmt_usd(maliyet), delta=f"-{fmt_usd(maliyet)}", delta_color="inverse")
            col_r3.metric("3️⃣ Net Kar", fmt_usd(kar), delta=f"+{fmt_pct(outs.get('brut_karlilik_orani', 0))}")
            
            # Simple flow visualization
            st.markdown(f"""
            <div style='text-align: center; padding: 20px; background: linear-gradient(90deg, #10B981 0%, #3B82F6 50%, #F59E0B 100%); border-radius: 8px; color: white; font-weight: bold;'>
                Hasilat: {fmt_usd(hasilat)} → Maliyet: {fmt_usd(maliyet)} → Kar: {fmt_usd(kar)}
            </div>
            """, unsafe_allow_html=True)
        # Apartment Type Pricing Table
        if outs.get("daire_fiyatlari"):
            st.divider()
            st.markdown("### 🏠 Daire Tiplerine Gore Satis Fiyatlari")
            
            st.caption(f"Birim fiyat: {fmt_usd(outs.get('satis_birim_fiyat_usd_m2'))} / {fmt_try(outs.get('satis_birim_fiyat_try_m2'))}")
            
            # Create dataframe
            daire_data = []
            for tip in ["1+1", "2+1", "3+1", "4+1"]:
                if tip in outs["daire_fiyatlari"]:
                    bilgi = outs["daire_fiyatlari"][tip]
                    daire_data.append({
                        "Daire Tipi": tip,
                        "Brut Alan": fmt_m2(bilgi['m2']),
                        "Satis Fiyati (USD)": fmt_usd(bilgi['fiyat_usd']),
                        "Satis Fiyati (TL)": fmt_try(bilgi['fiyat_try']) if bilgi['fiyat_try'] else "-",
                    })
            
            df = pd.DataFrame(daire_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Bar chart
            st.markdown("#### 📊 Fiyat Karsilastirmasi")
            
            chart_df = pd.DataFrame({
                "Tip": [d["Daire Tipi"] for d in daire_data],
                "Fiyat (USD)": [outs["daire_fiyatlari"][tip]["fiyat_usd"] for tip in ["1+1", "2+1", "3+1", "4+1"] if tip in outs["daire_fiyatlari"]]
            })
            
            st.bar_chart(chart_df.set_index("Tip"), height=300)
            
            # Info message
            st.info("💡 Fiyatlar birim fiyat × brut alan olarak hesaplanmistir. Net alandan %15-20 fazladir.")

# Break-even Analysis
        if outs.get("breakeven_konut_adedi"):
            st.divider()
            st.markdown("### 🎯 Break-Even Analizi")
            st.caption("Maliyeti karsilamak icin kac konut satilmali?")
            
            col1, col2, col3 = st.columns(3)
            
            breakeven_konut = int(outs.get("breakeven_konut_adedi", 0))
            breakeven_oran = outs.get("breakeven_konut_orani", 0)
            toplam_konut = int(outs.get("yaklasik_konut_adedi", 0))
            
            col1.metric(
                "Break-Even Konut",
                f"{breakeven_konut} adet",
                help="Maliyeti karsilamak icin satilmasi gereken konut sayisi"
            )
            
            col2.metric(
                "Break-Even Orani",
                fmt_pct(breakeven_oran),
                help="Toplam konutun yuzde kaci"
            )
            
            col3.metric(
                "Toplam Konut",
                f"{toplam_konut} adet"
            )
            
            # Progress bar
            if toplam_konut > 0:
                st.progress(
                    min(breakeven_oran, 1.0),
                    text=f"{breakeven_konut}/{toplam_konut} konut satilmali (%{breakeven_oran*100:.1f})"
                )
                
                # Color-coded message
                if breakeven_oran < 0.7:
                    st.success(f"✅ Dusuk risk: Konutlarin %{breakeven_oran*100:.0f}'ini satarak maliyeti karsilayabilirsiniz.")
                elif breakeven_oran < 0.9:
                    st.warning(f"⚠️ Orta risk: Konutlarin %{breakeven_oran*100:.0f}'ini satmaniz gerekiyor.")
                else:
                    st.error(f"🚩 Yuksek risk: Neredeyse tum konutlari satmaniz gerekiyor (%{breakeven_oran*100:.0f}).")
        # Warnings
        if warns:
            st.divider()
            st.markdown("### ⚠️ Uyarilar")
            for w in warns:
                st.warning(w)
        
        # Scenario Comparison Section
        if len(st.session_state.scenarios) > 0:
            st.divider()
            st.markdown("### 🔄 Senaryo Karsilastirmasi")
            st.caption(f"{len(st.session_state.scenarios)} senaryo kaydedildi")
            
            # Show comparison table
            comparison_data = {
                "Senaryo": [],
                "Arsa (m²)": [],
                "Emsal": [],
                "Maliyet ($)": [],
                "Kar ($)": [],
                "Karlilik": [],
            }
            
            for scenario in st.session_state.scenarios:
                comparison_data["Senaryo"].append(scenario["name"])
                comparison_data["Arsa (m²)"].append(fmt_int(scenario["inputs"].get("arsa_alani_m2", 0)))
                comparison_data["Emsal"].append(scenario["inputs"].get("emsal", 0))
                comparison_data["Maliyet ($)"].append(fmt_usd(scenario["outputs"].get("toplam_proje_maliyeti_usd", 0)))
                comparison_data["Kar ($)"].append(fmt_usd(scenario["outputs"].get("proje_kari_usd", 0)))
                comparison_data["Karlilik"].append(fmt_pct(scenario["outputs"].get("brut_karlilik_orani", 0)))
            
            st.dataframe(comparison_data, use_container_width=True, hide_index=True)
            
            # Comparison chart with native bar chart
            import pandas as pd
            
            profits = [s["outputs"].get("proje_kari_usd", 0) for s in st.session_state.scenarios]
            names = [s["name"] for s in st.session_state.scenarios]
            
            chart_df = pd.DataFrame({
                "Senaryo": names,
                "Kar (USD)": profits
            })
            
            st.markdown("#### 📊 Kar Karsilastirmasi")
            st.bar_chart(chart_df.set_index("Senaryo"), height=400)
            
            # Export comparison to Excel
            if st.button("📊 Karsilastirma Excel'i Indir", use_container_width=True):
                with st.spinner("Karsilastirma hazirlaniyor..."):
                    comp_excel_path = "senaryo_karsilastirmasi.xlsx"
                    create_comparison_excel(
                        filepath=comp_excel_path,
                        scenarios=st.session_state.scenarios
                    )
                    with open(comp_excel_path, "rb") as f:
                        st.download_button(
                            "⬇️ Karsilastirma Excel'i indir",
                            data=f,
                            file_name="senaryo_karsilastirmasi.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="comparison_excel_download"
                        )
    else:
        st.info("👈 Lutfen AI Asistan veya Hizli Hesap sekmesinden bilgileri girin")


# ============================================================================
# TAB 4: NAKİT AKIŞ ANALİZİ
# ============================================================================
with tab4:
    st.markdown("## 💰 Nakit Akış & Yatırım Analizi")
    st.markdown("*Proje bazlı IRR, NPV ve dönemsel nakit akış senaryoları*")

    try:
        from core.cashflow import (
            compute_cashflow, compare_scenarios,
            PRESET_PESSIMISTIC, PRESET_BASE, PRESET_OPTIMISTIC,
            CashFlowScenario,
        )
        cashflow_ok = True
    except ImportError:
        st.error("⚠️ core/cashflow.py bulunamadı. `pip install numpy-financial` gerekebilir.")
        cashflow_ok = False

    if cashflow_ok:
        outputs = st.session_state.get("outputs", None)

        if not outputs or not outputs.get("toplam_proje_maliyeti_usd"):
            st.info("👈 Önce **Hızlı Hesap** veya **AI Asistan** sekmesinden fizibilite hesabı yap.")
        else:
            total_cost   = outputs["toplam_proje_maliyeti_usd"]
            satilabilir  = outputs.get("satilabilir_alan_m2", 0)
            satis_fiyat  = outputs.get("satis_birim_fiyat_usd_m2") or outputs.get("target_30_usd_m2", 2000)

            st.markdown(f"""
            <div style='background:linear-gradient(135deg,#1E3A8A,#3B82F6);
                        padding:1rem 1.5rem;border-radius:12px;color:white;margin-bottom:1rem;'>
              <b>📌 Temel Girdi Özeti</b><br>
              Toplam Maliyet: <b>${total_cost/1e6:.1f}M</b> &nbsp;|&nbsp;
              Satılabilir Alan: <b>{satilabilir:,.0f} m²</b> &nbsp;|&nbsp;
              Satış Fiyatı: <b>${satis_fiyat:,.0f}/m²</b>
            </div>
            """, unsafe_allow_html=True)

            col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 2, 2])
            with col_ctrl1:
                duration_q = st.slider("⏱ Proje Süresi (Çeyrek)", min_value=4, max_value=16, value=8, step=1, help="4 çeyrek = 1 yıl")
                st.caption(f"≈ {duration_q/4:.1f} yıl")
            with col_ctrl2:
                mode = st.radio("📊 Görünüm", ["Senaryo Karşılaştırma", "Tek Senaryo Detay"], horizontal=True)
            with col_ctrl3:
                custom_price = st.number_input("💲 Satış Fiyatı Override (USD/m²)", min_value=500, max_value=10000, value=int(satis_fiyat), step=100)

            import pandas as pd

            if mode == "Senaryo Karşılaştırma":
                with st.spinner("Senaryolar hesaplanıyor..."):
                    results = compare_scenarios(
                        total_cost_usd=total_cost,
                        satilabilir_alan_m2=satilabilir,
                        satis_fiyat_usd_m2=float(custom_price),
                        project_duration_quarters=duration_q,
                    )

                st.markdown("### 📊 Senaryo Özeti")
                cols = st.columns(3)
                colors = ["#EF4444", "#3B82F6", "#10B981"]
                for i, (r, col) in enumerate(zip(results, cols)):
                    irr_color = "#10B981" if r.irr_project > 0.20 else "#F59E0B" if r.irr_project > 0.10 else "#EF4444"
                    with col:
                        st.markdown(f"""
                        <div style='background:linear-gradient(135deg,{colors[i]}22,{colors[i]}11);
                                    border:2px solid {colors[i]}44;border-radius:12px;
                                    padding:1.2rem;text-align:center;'>
                            <div style='font-size:1.3em;font-weight:bold;'>{r.scenario.name}</div>
                            <hr style='border-color:{colors[i]}44;'>
                            <div style='font-size:1.8em;font-weight:bold;color:{irr_color};'>{r.irr_project:.1%}</div>
                            <div style='font-size:0.8em;color:#6B7280;'>Proje IRR (yıllık)</div>
                            <br>
                            <div><b>${r.npv_project/1e6:.1f}M</b> NPV</div>
                            <div><b>{r.payback_years:.1f} yıl</b> geri ödeme</div>
                            <div style='color:#EF4444;'><b>${abs(r.max_funding_need)/1e6:.1f}M</b> max finansman</div>
                        </div>
                        """, unsafe_allow_html=True)

                st.markdown("### 📋 Dönemsel Nakit Akış")
                tab_data = {"Dönem": [p.period for p in results[1].periods]}
                for r in results:
                    tab_data[f"{r.scenario.name} Gelir"] = [f"${p.revenue/1e6:.1f}M" for p in r.periods]
                    tab_data[f"{r.scenario.name} Birikimli"] = [
                        f"{'🔴' if p.cumulative < 0 else '🟢'} ${p.cumulative/1e6:.1f}M" for p in r.periods
                    ]
                st.dataframe(pd.DataFrame(tab_data), use_container_width=True, hide_index=True)

                st.markdown("### 📈 Birikimli Nakit Akış Grafiği")
                chart_df = pd.DataFrame(
                    {r.scenario.name: [p.cumulative/1e6 for p in r.periods] for r in results},
                    index=[p.period for p in results[0].periods]
                )
                st.line_chart(chart_df, height=350)
                st.caption("Negatif bölge = finansman ihtiyacı | Sıfır geçiş = geri ödeme noktası")

                st.markdown("### 📊 Baz Senaryo — Dönemsel Maliyet vs Gelir")
                base_r = results[1]
                bar_df = pd.DataFrame({
                    "Maliyet ($M)": [-p.cost/1e6 for p in base_r.periods],
                    "Gelir ($M)":   [p.revenue/1e6 for p in base_r.periods],
                }, index=[p.period for p in base_r.periods])
                st.bar_chart(bar_df, height=300)

            else:
                preset_map = {
                    "🐻 Kötümser": PRESET_PESSIMISTIC,
                    "🎯 Baz": PRESET_BASE,
                    "🚀 İyimser": PRESET_OPTIMISTIC,
                    "⚙️ Özel": None,
                }
                sel = st.selectbox("Senaryo Seç", list(preset_map.keys()))

                if preset_map[sel] is None:
                    st.markdown("#### ⚙️ Özel Senaryo Parametreleri")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        presale    = st.slider("Ön Satış Oranı (%)", 0, 70, 30, 5) / 100
                        equity     = st.slider("Özkaynak Oranı (%)", 20, 100, 50, 5) / 100
                    with c2:
                        cost_curve = st.selectbox("Maliyet Eğrisi", ["normal","slow","fast"])
                        sales_vel  = st.selectbox("Satış Hızı", ["normal","slow","fast"])
                    with c3:
                        interest   = st.slider("Yıllık Faiz (%)", 10, 40, 22, 1) / 100
                    scenario = CashFlowScenario(
                        name="⚙️ Özel", cost_curve=cost_curve,
                        presale_ratio=presale, sales_velocity=sales_vel,
                        equity_ratio=equity, loan_interest_annual=interest,
                    )
                else:
                    scenario = preset_map[sel]

                with st.spinner("Hesaplanıyor..."):
                    r = compute_cashflow(
                        total_cost_usd=total_cost,
                        satilabilir_alan_m2=satilabilir,
                        satis_fiyat_usd_m2=float(custom_price),
                        project_duration_quarters=duration_q,
                        scenario=scenario,
                    )

                k1, k2, k3, k4 = st.columns(4)
                k1.metric("📈 Proje IRR", f"{r.irr_project:.1%}")
                k2.metric("💵 NPV (%15)", f"${r.npv_project/1e6:.1f}M")
                k3.metric("⏱ Geri Ödeme", f"{r.payback_years:.1f} yıl")
                k4.metric("🏦 Max Finansman", f"${abs(r.max_funding_need)/1e6:.1f}M")

                st.markdown("#### 📋 Dönemsel Nakit Akış Tablosu")
                detail_df = pd.DataFrame({
                    "Dönem":        [p.period for p in r.periods],
                    "Maliyet ($M)": [f"${p.cost/1e6:.2f}M" for p in r.periods],
                    "Gelir ($M)":   [f"${p.revenue/1e6:.2f}M" for p in r.periods],
                    "Kredi Çekimi": [f"${p.loan_drawdown/1e6:.2f}M" for p in r.periods],
                    "Geri Ödeme":   [f"${p.loan_repayment/1e6:.2f}M" for p in r.periods],
                    "Net ($M)":     [f"{'↑' if p.net>=0 else '↓'} ${p.net/1e6:.2f}M" for p in r.periods],
                    "Birikimli":    [f"{'🟢' if p.cumulative>=0 else '🔴'} ${p.cumulative/1e6:.2f}M" for p in r.periods],
                })
                st.dataframe(detail_df, use_container_width=True, hide_index=True)

                chart_df = pd.DataFrame({
                    "Birikimli ($M)": [p.cumulative/1e6 for p in r.periods],
                    "Net ($M)":       [p.net/1e6 for p in r.periods],
                }, index=[p.period for p in r.periods])
                st.line_chart(chart_df, height=300)

                if r.total_loan_interest > 0:
                    st.warning(f"💳 Toplam faiz maliyeti: **${r.total_loan_interest/1e6:.2f}M** "
                               f"(maliyetin %{r.total_loan_interest/total_cost*100:.1f}\'i)")



# ============================================================================
# TAB 5: KARMA KULLANIM (MIXED-USE)
# ============================================================================
with tab5:
    st.markdown("## 🏗️ Karma Kullanım Analizi")
    st.markdown("*Konut + Ofis + Ticari karışık projeler için ayrı tip bazlı fizibilite*")

    try:
        from core.mixed_use import (
            compute_mixed_use, quick_mix, UsageType,
            DEFAULTS_BY_TYPE, USAGE_TYPES
        )
        mu_ok = True
    except ImportError:
        st.error("⚠️ core/mixed_use.py bulunamadı.")
        mu_ok = False

    if mu_ok:
        import pandas as pd

        st.markdown("### ⚙️ Proje Parametreleri")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            mu_arsa = st.number_input("Arsa Alanı (m²)", min_value=500, max_value=100000, value=8500, step=500, key="mu_arsa")
        with c2:
            mu_emsal = st.number_input("Emsal", min_value=0.5, max_value=6.0, value=2.0, step=0.1, key="mu_emsal")
        with c3:
            mu_otopark = st.selectbox("Otopark", ["KAPALI", "ACIK"], key="mu_otopark")
        with c4:
            mu_arsa_deger = st.number_input("Arsa Değeri ($M)", min_value=0.1, max_value=500.0, value=5.5, step=0.1, key="mu_arsa_deger") * 1_000_000

        st.markdown("### 📐 Kullanım Tipi Dağılımı")
        st.caption("Yüzdelerin toplamı 100 olmalı — otomatik normalize edilir.")

        col_k, col_o, col_t = st.columns(3)
        with col_k:
            st.markdown("🏠 **Konut**")
            konut_pct = st.slider("Oran (%)", 0, 100, 60, 5, key="mu_konut_pct")
            konut_cost = st.number_input("İnşaat Maliyeti ($/m²)", 500, 3000,
                DEFAULTS_BY_TYPE["Konut"]["insaat_maliyet_usd_m2"], 50, key="mu_konut_cost")
            konut_price = st.number_input("Satış Fiyatı ($/m²)", 500, 15000,
                DEFAULTS_BY_TYPE["Konut"]["satis_fiyat_usd_m2"], 100, key="mu_konut_price")
            konut_kdv = st.selectbox("KDV", ["8%", "1%", "20%"], key="mu_konut_kdv")

        with col_o:
            st.markdown("🏢 **Ofis**")
            ofis_pct = st.slider("Oran (%)", 0, 100, 25, 5, key="mu_ofis_pct")
            ofis_cost = st.number_input("İnşaat Maliyeti ($/m²)", 500, 3000,
                DEFAULTS_BY_TYPE["Ofis"]["insaat_maliyet_usd_m2"], 50, key="mu_ofis_cost")
            ofis_price = st.number_input("Satış Fiyatı ($/m²)", 500, 15000,
                DEFAULTS_BY_TYPE["Ofis"]["satis_fiyat_usd_m2"], 100, key="mu_ofis_price")

        with col_t:
            st.markdown("🏪 **Ticari**")
            ticari_pct = st.slider("Oran (%)", 0, 100, 15, 5, key="mu_ticari_pct")
            ticari_cost = st.number_input("İnşaat Maliyeti ($/m²)", 500, 3000,
                DEFAULTS_BY_TYPE["Ticari"]["insaat_maliyet_usd_m2"], 50, key="mu_ticari_cost")
            ticari_price = st.number_input("Satış Fiyatı ($/m²)", 500, 15000,
                DEFAULTS_BY_TYPE["Ticari"]["satis_fiyat_usd_m2"], 100, key="mu_ticari_price")

        kdv_map = {"8%": 0.08, "1%": 0.01, "20%": 0.20}

        if st.button("🧮 Karma Kullanım Hesapla", use_container_width=True, type="primary", key="mu_calc"):
            total_pct = konut_pct + ofis_pct + ticari_pct
            if total_pct == 0:
                st.error("En az bir kullanım tipi seçilmeli.")
            else:
                usage_types = []
                if konut_pct > 0:
                    usage_types.append(UsageType(
                        name="Konut", alan_orani=konut_pct/total_pct,
                        insaat_maliyet_usd_m2=konut_cost, satis_fiyat_usd_m2=konut_price,
                        kdv_orani=kdv_map[konut_kdv], satilabilir_katsayi=1.25,
                    ))
                if ofis_pct > 0:
                    usage_types.append(UsageType(
                        name="Ofis", alan_orani=ofis_pct/total_pct,
                        insaat_maliyet_usd_m2=ofis_cost, satis_fiyat_usd_m2=ofis_price,
                        kdv_orani=0.20, satilabilir_katsayi=1.10,
                    ))
                if ticari_pct > 0:
                    usage_types.append(UsageType(
                        name="Ticari", alan_orani=ticari_pct/total_pct,
                        insaat_maliyet_usd_m2=ticari_cost, satis_fiyat_usd_m2=ticari_price,
                        kdv_orani=0.20, satilabilir_katsayi=1.05,
                    ))

                r = compute_mixed_use(mu_arsa, mu_emsal, mu_otopark, mu_arsa_deger, usage_types)

                # ── Özet KPI'lar ──
                st.markdown("### 📊 Özet Sonuçlar")
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Satılabilir Alan", f"{r.toplam_satilabilir_m2:,.0f} m²")
                m2.metric("Toplam Maliyet", f"${r.toplam_maliyet_usd/1e6:.1f}M")
                m3.metric("Toplam Hasılat", f"${r.toplam_hasilat_usd/1e6:.1f}M")
                kar_color = "normal" if r.toplam_kar_usd >= 0 else "inverse"
                m4.metric("Toplam Kâr", f"${r.toplam_kar_usd/1e6:.1f}M",
                          delta=f"{r.brut_karlilik:.1%} kârlılık")
                m5.metric("Ağırlıklı Başabaş", f"${r.agirlikli_breakeven_usd_m2:,.0f}/m²")

                if r.toplam_kdv_usd > 0:
                    st.info(f"🧾 Toplam KDV tahsilatı: **${r.toplam_kdv_usd/1e6:.2f}M** "
                            f"(alıcıdan tahsil edilir, devlete ödenir)")

                # ── Tip bazlı karşılaştırma tablosu ──
                st.markdown("### 📋 Kullanım Tipi Karşılaştırması")
                rows = []
                emojis = {"Konut": "🏠", "Ofis": "🏢", "Ticari": "🏪"}
                for t in r.types:
                    rows.append({
                        "Tip": f"{emojis.get(t.name,'')} {t.name}",
                        "Oran": f"%{t.alan_orani*100:.0f}",
                        "Satılabilir (m²)": f"{t.satilabilir_alan_m2:,.0f}",
                        "Maliyet": f"${t.toplam_maliyet_usd/1e6:.2f}M",
                        "Hasılat (KDV hariç)": f"${t.satis_hasilati_usd/1e6:.2f}M",
                        "KDV": f"${t.kdv_usd/1e6:.2f}M",
                        "Kâr": f"${t.kar_usd/1e6:.2f}M",
                        "Kârlılık": f"{t.brut_karlilik:.1%}",
                        "Başabaş ($/m²)": f"${t.breakeven_usd_m2:,.0f}",
                        "%30 Hedef ($/m²)": f"${t.target_30_usd_m2:,.0f}",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

                # ── Grafikler ──
                g1, g2 = st.columns(2)
                with g1:
                    st.markdown("#### Alan Dağılımı")
                    area_df = pd.DataFrame({
                        "Tip": [f"{emojis.get(t.name,'')} {t.name}" for t in r.types],
                        "Satılabilir (m²)": [t.satilabilir_alan_m2 for t in r.types],
                    }).set_index("Tip")
                    st.bar_chart(area_df, height=250)

                with g2:
                    st.markdown("#### Kâr Dağılımı")
                    profit_df = pd.DataFrame({
                        "Tip": [f"{emojis.get(t.name,'')} {t.name}" for t in r.types],
                        "Kâr ($M)": [t.kar_usd/1e6 for t in r.types],
                    }).set_index("Tip")
                    st.bar_chart(profit_df, height=250)

                # Maliyet vs Hasılat per tip
                st.markdown("#### 📊 Maliyet vs Hasılat (Tip Bazlı)")
                mv_df = pd.DataFrame({
                    "Maliyet ($M)": [t.toplam_maliyet_usd/1e6 for t in r.types],
                    "Hasılat ($M)": [t.satis_hasilati_usd/1e6 for t in r.types],
                }, index=[f"{emojis.get(t.name,'')} {t.name}" for t in r.types])
                st.bar_chart(mv_df, height=300)

                # Session'a kaydet (cash flow ile entegrasyon için)
                st.session_state["mixed_use_result"] = r.to_dict()
                st.success("✅ Sonuçlar hesaplandı! Nakit Akış sekmesinde bu projeyi analiz edebilirsin.")



# ============================================================================
# TAB 6: PİYASA FİYAT KARŞILAŞTIRMASI
# ============================================================================
with tab6:
    st.markdown("## 📍 Piyasa Fiyat Karşılaştırması")
    st.markdown("*Projenin hedef satış fiyatını bölgesel piyasa ortalamasıyla karşılaştır*")

    try:
        from core.market_data import (
            compare_to_market, get_iller, get_ilceler,
            get_il_stats, get_fiyat
        )
        md_ok = True
    except ImportError:
        st.error("⚠️ core/market_data.py bulunamadı.")
        md_ok = False

    if md_ok:
        import pandas as pd

        # ── Lokasyon Seçimi ──────────────────────────────────────────────
        st.markdown("### 📌 Lokasyon & Fiyat Girişi")
        loc1, loc2 = st.columns(2)
        with loc1:
            secili_il = st.selectbox("İl", get_iller(), key="md_il")
        with loc2:
            secili_ilce = st.selectbox("İlçe", get_ilceler(secili_il), key="md_ilce")

        # Mevcut outputs'tan fiyat al veya manuel gir
        outputs = st.session_state.get("outputs", {})
        default_konut = int(outputs.get("satis_birim_fiyat_usd_m2") or
                           outputs.get("target_30_usd_m2") or
                           get_fiyat(secili_il, secili_ilce, "konut") or 2000)

        st.markdown("#### Projenin Hedef Satış Fiyatları (USD/m²)")
        p1, p2, p3 = st.columns(3)
        with p1:
            p_konut  = st.number_input("🏠 Konut", 0, 20000, default_konut, 100, key="md_pkonut",
                                        help="0 = bu tip yok / hesaplama dışı")
        with p2:
            p_ofis   = st.number_input("🏢 Ofis",  0, 20000,
                int(get_fiyat(secili_il, secili_ilce, "ofis") or 0), 100, key="md_pofis")
        with p3:
            p_ticari = st.number_input("🏪 Ticari", 0, 20000,
                int(get_fiyat(secili_il, secili_ilce, "ticari") or 0), 100, key="md_pticari")

        if st.button("🔍 Piyasayla Karşılaştır", use_container_width=True,
                     type="primary", key="md_compare"):

            report = compare_to_market(
                il=secili_il, ilce=secili_ilce,
                proje_fiyat_konut=p_konut if p_konut > 0 else None,
                proje_fiyat_ofis=p_ofis   if p_ofis  > 0 else None,
                proje_fiyat_ticari=p_ticari if p_ticari > 0 else None,
            )

            if not report.comparisons:
                st.warning("Seçilen ilçe için fiyat verisi bulunamadı veya fiyat girilmedi.")
            else:
                # ── Karşılaştırma Kartları ───────────────────────────────
                st.markdown(f"### 🏙️ {secili_il} / {secili_ilce} — Piyasa Karşılaştırması")
                st.caption(f"Veri kaynağı: {report.kaynak} ({report.veri_tarihi})")

                cols = st.columns(len(report.comparisons))
                emojis = {"konut": "🏠", "ofis": "🏢", "ticari": "🏪"}
                colors = {
                    "🔴": "#EF4444", "🟠": "#F97316",
                    "🟡": "#F59E0B", "🟢": "#10B981"
                }

                for i, (c, col) in enumerate(zip(report.comparisons, cols)):
                    deg_emoji = c.degerlendirme.split()[0]
                    color = colors.get(deg_emoji, "#6B7280")
                    fark_sign = "+" if c.fark_usd_m2 >= 0 else ""
                    with col:
                        st.markdown(f"""
                        <div style='border:2px solid {color}44;border-radius:12px;
                                    padding:1.2rem;text-align:center;
                                    background:{color}11;'>
                            <div style='font-size:1.2em;'>{emojis.get(c.tip,"")} {c.tip.upper()}</div>
                            <hr style='border-color:{color}33;'>
                            <div style='font-size:0.85em;color:#6B7280;'>Piyasa Ortalaması</div>
                            <div style='font-size:1.4em;font-weight:bold;'>${c.piyasa_fiyat_usd_m2:,.0f}/m²</div>
                            <br>
                            <div style='font-size:0.85em;color:#6B7280;'>Proje Fiyatı</div>
                            <div style='font-size:1.4em;font-weight:bold;color:{color};'>${c.proje_fiyat_usd_m2:,.0f}/m²</div>
                            <br>
                            <div style='font-size:1.1em;font-weight:bold;color:{color};'>
                                {fark_sign}${c.fark_usd_m2:,.0f}/m² ({c.fark_pct:+.1%})
                            </div>
                            <div style='margin-top:0.5rem;font-size:0.85em;'>{c.degerlendirme}</div>
                        </div>
                        """, unsafe_allow_html=True)

                # Öneriler
                st.markdown("### 💡 Değerlendirme & Öneriler")
                for c in report.comparisons:
                    st.info(f"**{emojis.get(c.tip,'')} {c.tip.title()}:** {c.oneri}")

                # ── İl Geneli İstatistik ─────────────────────────────────
                st.markdown(f"### 📊 {secili_il} Geneli Fiyat Aralığı")
                il_stats = get_il_stats(secili_il)
                if il_stats:
                    stat_rows = []
                    for tip, s in il_stats.items():
                        proje_f = {"konut": p_konut, "ofis": p_ofis, "ticari": p_ticari}.get(tip, 0)
                        ilce_f  = get_fiyat(secili_il, secili_ilce, tip) or 0
                        stat_rows.append({
                            "Tip": f"{emojis.get(tip,'')} {tip.title()}",
                            "İl Min": f"${s['min']:,}",
                            "İl Ort": f"${s['ort']:,.0f}",
                            "İl Max": f"${s['max']:,}",
                            f"{secili_ilce} Piyasa": f"${ilce_f:,}" if ilce_f else "-",
                            "Projeniz": f"${proje_f:,}" if proje_f > 0 else "-",
                        })
                    st.dataframe(pd.DataFrame(stat_rows), use_container_width=True, hide_index=True)

                # ── Komşu İlçe Karşılaştırması ───────────────────────────
                st.markdown(f"### 🗺️ {secili_il} İlçe Fiyat Haritası (Konut)")
                if report.nearby_prices:
                    nearby_data = {secili_ilce: {"konut": report.piyasa_ortalama_konut}}
                    nearby_data.update({k: v for k, v in report.nearby_prices.items()})

                    chart_rows = sorted(
                        [(ilce, d.get("konut", 0)) for ilce, d in nearby_data.items() if d.get("konut")],
                        key=lambda x: x[1], reverse=True
                    )
                    chart_df = pd.DataFrame(chart_rows, columns=["İlçe", "Konut ($/m²)"]).set_index("İlçe")
                    st.bar_chart(chart_df, height=350)
                    st.caption(f"Turuncu çubuk: seçilen ilçe ({secili_ilce}) — yatay sıralama fiyata göre")

        # Veri notu
        with st.expander("ℹ️ Veri Hakkında"):
            st.markdown("""
            **Fiyat verisi:** REIDIN, Endeksa ve Sahibinden.com kaynaklı 2025-Q4 ortalama değerleri.
            Bu değerler **tahmini** olup gerçek piyasadan ±%15 sapabilir.

            **Güncelleme:** Fiyatları manuel güncellemek için `core/market_data.py` dosyasındaki
            `MARKET_DB` sözlüğünü düzenleyebilirsin.

            **Eksik ilçe?** Yeni ilçe eklemek için:
            ```python
            MARKET_DB["İstanbul"]["YeniİlçeAdı"] = {"konut": 2500, "ofis": 3000, "ticari": 5000}
            ```
            """)


# ============================================================================
# FOOTER
# ============================================================================
st.divider()
st.markdown("""
<div style='text-align: center; color: #94A3B8; font-size: 0.9em; padding: 1rem 0;'>
    Made with ❤️ by <strong>GGtech</strong> • omurtezcan@gmail.com<br>
    <small>AI-powered feasibility analysis for residential projects</small>
</div>
""", unsafe_allow_html=True)


