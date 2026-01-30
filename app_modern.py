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
tab1, tab2, tab3 = st.tabs(["💬 AI Asistan", "📊 Hizli Hesap", "📈 Sonuclar"])

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
# FOOTER
# ============================================================================
st.divider()
st.markdown("""
<div style='text-align: center; color: #94A3B8; font-size: 0.9em; padding: 1rem 0;'>
    Made with ❤️ by <strong>GGtech</strong> • omurtezcan@gmail.com<br>
    <small>AI-powered feasibility analysis for residential projects</small>
</div>
""", unsafe_allow_html=True)


