from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# Color palette - Modern professional theme
PRIMARY_COLOR = colors.HexColor("#1E3A8A")      # Navy blue
SECONDARY_COLOR = colors.HexColor("#3B82F6")    # Bright blue
ACCENT_COLOR = colors.HexColor("#10B981")       # Green
WARNING_COLOR = colors.HexColor("#F59E0B")      # Amber
DANGER_COLOR = colors.HexColor("#EF4444")       # Red
LIGHT_BG = colors.HexColor("#F8FAFC")           # Very light gray
MEDIUM_BG = colors.HexColor("#E2E8F0")          # Light gray
TEXT_DARK = colors.HexColor("#1E293B")          # Almost black
TEXT_MUTED = colors.HexColor("#64748B")         # Gray

def _register_fonts():
    """Register Turkish-compatible fonts with font family"""
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping
    
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    italic_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"
    bold_italic_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"
    
    fonts_registered = False
    
    try:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont("DejaVu", font_path))
            fonts_registered = True
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold_path))
        if os.path.exists(italic_path):
            pdfmetrics.registerFont(TTFont("DejaVu-Italic", italic_path))
        if os.path.exists(bold_italic_path):
            pdfmetrics.registerFont(TTFont("DejaVu-BoldItalic", bold_italic_path))
        
        # Register font family mappings (important for proper bold/italic rendering)
        if fonts_registered:
            addMapping('DejaVu', 0, 0, 'DejaVu')           # Normal
            addMapping('DejaVu', 1, 0, 'DejaVu-Bold')      # Bold
            addMapping('DejaVu', 0, 1, 'DejaVu-Italic')    # Italic
            addMapping('DejaVu', 1, 1, 'DejaVu-BoldItalic') # Bold+Italic
    except Exception as e:
        # Silently fail - will use Helvetica fallback
        fonts_registered = False
    
    return fonts_registered

def tr_to_en(text: str) -> str:
    """
    Convert Turkish characters to English equivalents for PDF compatibility
    I -> I, i -> i, S -> S, s -> s, G -> G, g -> g, U -> U, u -> u, O -> O, o -> o, C -> C, c -> c
    """
    if not isinstance(text, str):
        return str(text)
    
    char_map = {
        'I': 'I',
        'i': 'i',
        'S': 'S',
        's': 's',
        'G': 'G',
        'g': 'g',
        'U': 'U',
        'u': 'u',
        'O': 'O',
        'o': 'o',
        'C': 'C',
        'c': 'c',
    }
    
    result = text
    for tr_char, en_char in char_map.items():
        result = result.replace(tr_char, en_char)
    
    return result

def money_usd(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"${x:,.0f}"

def money_try(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"₺{x:,.0f}"

def num(x: Optional[float], d: int = 2) -> str:
    if x is None:
        return "-"
    return f"{x:,.{d}f}"

# Safe Paragraph wrapper that converts Turkish characters
_OriginalParagraph = Paragraph
def Paragraph(text, style, **kwargs):
    """Wrapper around Paragraph that converts Turkish chars to English"""
    if isinstance(text, str):
        text = tr_to_en(text)
    return _OriginalParagraph(text, style, **kwargs)

def create_header_box(text: str, styles) -> Table:
    """Create a colored header box"""
    # Convert Turkish chars
    text = tr_to_en(text)
    # Don't use  tags - use style instead for Turkish chars
    p = Paragraph(f"<font color='white'>{text}</font>", styles["HeaderBox"])
    t = Table([[p]], colWidths=[16*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), PRIMARY_COLOR),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    return t

def create_kpi_box(title: str, value: str, subtitle: str, styles, bg_color=LIGHT_BG) -> Table:
    """Create a KPI metric box"""
    # Convert Turkish chars
    title = tr_to_en(title)
    value = tr_to_en(value)
    subtitle = tr_to_en(subtitle)
    
    title_p = Paragraph(f"<font color='#64748B' size='9'>{title}</font>", styles["Normal"])
    # Use KPIValue style which has bold font
    value_p = Paragraph(f"<font color='#1E293B' size='16'>{value}</font>", styles["KPIValue"])
    subtitle_p = Paragraph(f"<font color='#94A3B8' size='8'>{subtitle}</font>", styles["Normal"])
    
    t = Table([[title_p], [value_p], [subtitle_p]], colWidths=[5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), bg_color),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
    ]))
    return t

def build_pdf(
    path: str,
    project_title: str,
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    warnings: List[str],
    usd_try_rate: Optional[float],
    rate_source: Optional[str],
):
    # Convert all Turkish characters to English equivalents
    project_title = tr_to_en(project_title)
    rate_source = tr_to_en(rate_source) if rate_source else None
    warnings = [tr_to_en(w) for w in warnings]
    
    fonts_ok = _register_fonts()
    
    # Safe font selection with fallback
    if fonts_ok and "DejaVu" in pdfmetrics.getRegisteredFontNames():
        base_font = "DejaVu"
        bold_font = "DejaVu-Bold"
    else:
        # Fallback to Helvetica (always available)
        base_font = "Helvetica"
        bold_font = "Helvetica-Bold"
    italic_font = "DejaVu-Italic" if fonts_ok else "Helvetica-Oblique"

    # Custom styles
    styles = getSampleStyleSheet()
    
    # Cover page styles
    styles.add(ParagraphStyle(
        name="CoverTitle",
        fontName=bold_font,
        fontSize=28,
        leading=34,
        textColor=PRIMARY_COLOR,
        alignment=TA_CENTER,
        spaceAfter=12
    ))
    
    styles.add(ParagraphStyle(
        name="CoverSubtitle",
        fontName=base_font,
        fontSize=14,
        leading=18,
        textColor=TEXT_MUTED,
        alignment=TA_CENTER,
        spaceAfter=6
    ))
    
    # Section headers
    styles.add(ParagraphStyle(
        name="SectionHeader",
        fontName=bold_font,
        fontSize=16,
        leading=20,
        textColor=PRIMARY_COLOR,
        spaceBefore=16,
        spaceAfter=10
    ))
    
    styles.add(ParagraphStyle(
        name="HeaderBox",
        fontName=bold_font,
        fontSize=13,
        leading=16,
        textColor=colors.white,
    ))
    
    # Body text
    styles.add(ParagraphStyle(
        name="Body",
        fontName=base_font,
        fontSize=10,
        leading=14,
        textColor=TEXT_DARK,
        spaceAfter=6
    ))
    
    styles.add(ParagraphStyle(
        name="BodyBold",
        fontName=bold_font,
        fontSize=10,
        leading=14,
        textColor=TEXT_DARK,
        spaceAfter=6
    ))
    
    styles.add(ParagraphStyle(
        name="BodyMuted",
        fontName=base_font,
        fontSize=9,
        leading=13,
        textColor=TEXT_MUTED,
    ))
    
    styles.add(ParagraphStyle(
        name="KPIValue",
        fontName=bold_font,
        fontSize=16,
        leading=20,
        textColor=TEXT_DARK,
    ))
    
    styles.add(ParagraphStyle(
        name="TableHeader",
        fontName=bold_font,
        fontSize=10,
        leading=13,
        textColor=TEXT_DARK,
    ))
    
    styles.add(ParagraphStyle(
        name="TableCell",
        fontName=base_font,
        fontSize=9,
        leading=12,
        textColor=TEXT_DARK,
    ))

    # Document setup
    doc = SimpleDocTemplate(
        path, 
        pagesize=A4,
        leftMargin=2.0*cm, 
        rightMargin=2.0*cm,
        topMargin=2.0*cm, 
        bottomMargin=2.0*cm
    )

    story = []

    # ============================================================
    # COVER PAGE
    # ============================================================
    story.append(Spacer(1, 3*cm))
    
    # Logo/Brand area
    brand_box = Table([[Paragraph("GGtech", styles["CoverTitle"])]], colWidths=[16*cm])
    brand_box.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), PRIMARY_COLOR),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 20),
        ("BOTTOMPADDING", (0,0), (-1,-1), 20),
    ]))
    story.append(brand_box)
    story.append(Spacer(1, 1*cm))
    
    story.append(Paragraph("Konut Projesi Fizibilite Raporu", styles["CoverTitle"]))
    story.append(Paragraph("AI Destekli Analiz", styles["CoverSubtitle"]))
    story.append(Spacer(1, 2*cm))
    
    # Project info box
    info_data = [
        [Paragraph("Proje:", styles["BodyBold"]), Paragraph(project_title, styles["Body"])],
        [Paragraph("Tarih:", styles["BodyBold"]), Paragraph(datetime.now().strftime('%d.%m.%Y'), styles["Body"])],
    ]
    if usd_try_rate is not None:
        src = rate_source or "USD/TRY"
        info_data.append([
            Paragraph("Kur:", styles["BodyBold"]), 
            Paragraph(f"1 USD = {num(usd_try_rate, 4)} TL ({src})", styles["Body"])
        ])
    
    info_data.append([
        Paragraph("Hazirlayan:", styles["BodyBold"]),
        Paragraph("Dr. Omur Tezcan", styles["Body"])
    ])
    
    info_table = Table(info_data, colWidths=[4*cm, 12*cm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LIGHT_BG),
        ("GRID", (0,0), (-1,-1), 0.5, MEDIUM_BG),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(info_table)
    
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph(
        "<i>Bu rapor hizli on fizibilite amaclidir. Nihai karar icin detayli proje butcesi ve uzman gorusu onerilir.</i>",
        styles["BodyMuted"]
    ))
    
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Iletisim: omurtezcan@gmail.com", styles["BodyMuted"]))
    
    story.append(PageBreak())

    # ============================================================
    # EXECUTIVE SUMMARY - KPI CARDS
    # ============================================================
    story.append(create_header_box("📊 Ozet", styles))
    story.append(Spacer(1, 0.5*cm))
    
    # Top 4 KPIs in simple layout
    kpi_box1 = create_kpi_box(
        "Satilabilir Alan",
        f"{num(outputs.get('satilabilir_alan_m2'),0)} m²",
        "Toplam satilabilir bagimsiz bolum",
        styles
    )
    kpi_box2 = create_kpi_box(
        "Toplam Insaat Alani",
        f"{num(outputs.get('toplam_insaat_alani_m2'),0)} m²",
        "Otopark dahil",
        styles
    )
    kpi_box3 = create_kpi_box(
        "Toplam Maliyet (USD)",
        money_usd(outputs.get("toplam_proje_maliyeti_usd")),
        "Arsa + insaat",
        styles,
        bg_color=colors.HexColor("#FEF3C7")
    )
    kpi_box4 = create_kpi_box(
        "Toplam Maliyet (TL)",
        money_try(outputs.get("toplam_proje_maliyeti_try")),
        f"Kur: {num(usd_try_rate, 2) if usd_try_rate else '-'}",
        styles,
        bg_color=colors.HexColor("#FEF3C7")
    )
    
    # Arrange in 2x2 grid
    kpi_grid = Table([
        [kpi_box1, kpi_box2],
        [kpi_box3, kpi_box4],
    ], colWidths=[7.8*cm, 7.8*cm], rowHeights=[3*cm, 3*cm])
    kpi_grid.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(kpi_grid)
    
    story.append(Spacer(1, 0.8*cm))

    # ============================================================
    # PRICING STRATEGY TABLE
    # ============================================================
    story.append(Paragraph("🎯 Satis Fiyat Stratejisi", styles["SectionHeader"]))
    story.append(Spacer(1, 0.3*cm))
    
    pricing_data = [
        [
            Paragraph("Hedef", styles["TableHeader"]),
            Paragraph("USD/m²", styles["TableHeader"]),
            Paragraph("TL/m²", styles["TableHeader"]),
            Paragraph("Aciklama", styles["TableHeader"])
        ],
        [
            Paragraph("Basabas", styles["TableHeader"]),
            Paragraph(f"{num(outputs.get('breakeven_usd_m2'),0)}", styles["TableCell"]),
            Paragraph(f"{num(outputs.get('breakeven_try_m2'),0)}", styles["TableCell"]),
            Paragraph("Maliyet karsilama noktasi", styles["BodyMuted"])
        ],
        [
            Paragraph("%10 Brut Kâr", styles["TableCell"]),
            Paragraph(f"{num(outputs.get('target_10_usd_m2'),0)}", styles["TableCell"]),
            Paragraph(f"{num(outputs.get('target_10_try_m2'),0)}", styles["TableCell"]),
            Paragraph("Muhafazakar hedef", styles["BodyMuted"])
        ],
        [
            Paragraph("%30 Brut Kâr", styles["TableCell"]),
            Paragraph(f"{num(outputs.get('target_30_usd_m2'),0)}", styles["TableCell"]),
            Paragraph(f"{num(outputs.get('target_30_try_m2'),0)}", styles["TableCell"]),
            Paragraph("Dengeli hedef", styles["BodyMuted"])
        ],
        [
            Paragraph("%50 Brut Kâr", styles["TableCell"]),
            Paragraph(f"{num(outputs.get('target_50_usd_m2'),0)}", styles["TableCell"]),
            Paragraph(f"{num(outputs.get('target_50_try_m2'),0)}", styles["TableCell"]),
            Paragraph("Agresif hedef", styles["BodyMuted"])
        ],
    ]
    
    pricing_table = Table(pricing_data, colWidths=[3*cm, 3*cm, 3*cm, 7*cm])
    pricing_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), PRIMARY_COLOR),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("BACKGROUND", (0,1), (-1,1), colors.HexColor("#FEE2E2")),
        ("BACKGROUND", (0,2), (-1,2), colors.HexColor("#DBEAFE")),
        ("BACKGROUND", (0,3), (-1,3), colors.HexColor("#D1FAE5")),
        ("BACKGROUND", (0,4), (-1,4), colors.HexColor("#FEF3C7")),
        ("GRID", (0,0), (-1,-1), 0.5, MEDIUM_BG),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,1), (2,-1), "RIGHT"),
    ]))
    story.append(pricing_table)
    
    story.append(Spacer(1, 0.5*cm))
    
    # Unit count info with proper bold
    unit_info_text = (
        f"Konut Adedi: ~{int(outputs.get('yaklasik_konut_adedi') or 0)} adet "
        f"(Ortalama {num(inputs.get('ortalama_konut_m2', 120), 0)} m²/konut) • "
        f"Kalan Alan: {num(outputs.get('kalan_satilabilir_alan_m2'),0)} m²"
    )
    unit_info = Paragraph(unit_info_text, styles["BodyBold"])
    story.append(unit_info)

    # ============================================================
    # REVENUE & PROFITABILITY (if sales price exists)
    # ============================================================
    if outputs.get("satis_birim_fiyat_usd_m2"):
        story.append(Spacer(1, 0.8*cm))
        story.append(create_header_box("💰 Gelir ve Kârlilik Analizi", styles))
        story.append(Spacer(1, 0.5*cm))
        
        # Selected price
        selected_price_text = (
            f"Secilen Satis Fiyati: {num(outputs.get('satis_birim_fiyat_usd_m2'),0)} $/m² "
            f"({num(outputs.get('satis_birim_fiyat_try_m2'),0)} ₺/m²)"
        )
        selected_price = Paragraph(selected_price_text, styles["BodyBold"])
        story.append(selected_price)
        story.append(Spacer(1, 0.3*cm))
        
        # Financial metrics in 2 columns
        revenue_data = [
            [
                Paragraph("Metrik", styles["TableHeader"]),
                Paragraph("USD", styles["TableHeader"]),
                Paragraph("TL", styles["TableHeader"])
            ],
            [
                Paragraph("Proje Hasilati", styles["TableCell"]),
                Paragraph(money_usd(outputs.get("proje_hasilati_usd")), styles["TableCell"]),
                Paragraph(money_try(outputs.get("proje_hasilati_try")), styles["TableCell"])
            ],
            [
                Paragraph("Toplam Maliyet", styles["TableCell"]),
                Paragraph(money_usd(outputs.get("toplam_proje_maliyeti_usd")), styles["TableCell"]),
                Paragraph(money_try(outputs.get("toplam_proje_maliyeti_try")), styles["TableCell"])
            ],
            [
                Paragraph("Proje Kâri", styles["TableHeader"]),
                Paragraph(f"{money_usd(outputs.get('proje_kari_usd'))}", styles["TableHeader"]),
                Paragraph(f"{money_try(outputs.get('proje_kari_try'))}", styles["TableHeader"])
            ],
        ]
        
        revenue_table = Table(revenue_data, colWidths=[5*cm, 5.5*cm, 5.5*cm])
        
        # Color code based on profitability
        profit_margin = outputs.get("brut_karlilik_orani", 0)
        if profit_margin < 0:
            profit_bg = colors.HexColor("#FEE2E2")  # Red
        elif profit_margin < 0.10:
            profit_bg = colors.HexColor("#FEF3C7")  # Yellow
        elif profit_margin < 0.30:
            profit_bg = colors.HexColor("#DBEAFE")  # Blue
        else:
            profit_bg = colors.HexColor("#D1FAE5")  # Green
        
        revenue_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), PRIMARY_COLOR),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("BACKGROUND", (0,1), (-1,2), LIGHT_BG),
            ("BACKGROUND", (0,3), (-1,3), profit_bg),
            ("GRID", (0,0), (-1,-1), 0.5, MEDIUM_BG),
            ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (1,1), (2,-1), "RIGHT"),
        ]))
        story.append(revenue_table)
        
        story.append(Spacer(1, 0.3*cm))
        
        # Profitability indicator
        profit_text = f"Brut Kârlilik Orani: {num(profit_margin*100, 1)}%"
        if profit_margin < 0:
            profit_text += " ⚠️ ZARAR"
        elif profit_margin < 0.10:
            profit_text += " ⚠️ Dusuk"
        elif profit_margin < 0.30:
            profit_text += " ✓ Orta"
        else:
            profit_text += " ✓✓ Iyi"
        
        story.append(Paragraph(profit_text, styles["BodyBold"]))

    story.append(PageBreak())

    # ============================================================
    # DETAILED BREAKDOWN
    # ============================================================
    story.append(create_header_box("📋 Detayli Hesaplamalar", styles))
    story.append(Spacer(1, 0.5*cm))
    
    # Areas breakdown
    story.append(Paragraph("Alan Dagilimi", styles["SectionHeader"]))
    areas_data = [
        ["Emsal Insaat Alani", f"{num(outputs.get('emsal_insaat_alani_m2'),0)} m²"],
        ["Satilabilir Alan", f"{num(outputs.get('satilabilir_alan_m2'),0)} m²"],
        ["Toplam Insaat (Otopark dahil)", f"{num(outputs.get('toplam_insaat_alani_m2'),0)} m²"],
    ]
    areas_table = Table(areas_data, colWidths=[10*cm, 6*cm])
    areas_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LIGHT_BG),
        ("GRID", (0,0), (-1,-1), 0.5, MEDIUM_BG),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
    ]))
    story.append(areas_table)
    
    story.append(Spacer(1, 0.5*cm))
    
    # Cost breakdown
    story.append(Paragraph("Maliyet Dagilimi", styles["SectionHeader"]))
    cost_data = [
        [
            Paragraph("Kalem", styles["TableHeader"]),
            Paragraph("USD", styles["TableHeader"]),
            Paragraph("TL", styles["TableHeader"])
        ],
        [
            "Arsa Degeri",
            money_usd(outputs.get("arsa_degeri_usd")),
            money_try(outputs.get("arsa_degeri_try"))
        ],
        [
            "Insaat Maliyeti",
            money_usd(outputs.get("insaat_maliyeti_usd")),
            money_try(outputs.get("insaat_maliyeti_try"))
        ],
        [
            Paragraph("Toplam", styles["TableHeader"]),
            Paragraph(f"{money_usd(outputs.get('toplam_proje_maliyeti_usd'))}", styles["TableHeader"]),
            Paragraph(f"{money_try(outputs.get('toplam_proje_maliyeti_try'))}", styles["TableHeader"])
        ],
    ]
    cost_table = Table(cost_data, colWidths=[6*cm, 5*cm, 5*cm])
    cost_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), PRIMARY_COLOR),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("BACKGROUND", (0,1), (-1,2), LIGHT_BG),
        ("BACKGROUND", (0,3), (-1,3), MEDIUM_BG),
        ("GRID", (0,0), (-1,-1), 0.5, MEDIUM_BG),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,1), (2,-1), "RIGHT"),
    ]))
    story.append(cost_table)

    # ============================================================
    # WARNINGS & NOTES
    # ============================================================
    if warnings:
        story.append(Spacer(1, 0.8*cm))
        story.append(Paragraph("⚠️ Uyarilar ve Notlar", styles["SectionHeader"]))
        story.append(Spacer(1, 0.3*cm))
        
        for w in warnings:
            icon = "🚩" if "zarar" in w.lower() else "⚠️" if "⚠️" in w else "ℹ️"
            warning_p = Paragraph(f"{icon} {w}", styles["Body"])
            story.append(warning_p)
            story.append(Spacer(1, 0.2*cm))

    story.append(PageBreak())

    # ============================================================
    # ASSUMPTIONS & INPUTS
    # ============================================================
    story.append(create_header_box("📝 Girdiler ve Kabuller", styles))
    story.append(Spacer(1, 0.5*cm))
    
    # Pretty input names
    input_labels = {
        "arsa_alani_m2": "Arsa Alani",
        "emsal": "Emsal",
        "satilabilir_katsayi": "Satilabilir Alan Katsayisi",
        "otopark_tipi": "Otopark Tipi",
        "otopark_katsayi": "Otopark Katsayisi",
        "konut_sinifi": "Konut Sinifi",
        "insaat_maliyet_usd_m2": "Insaat Maliyeti ($/m²)",
        "arsa_toplam_degeri_usd": "Arsa Toplam Degeri ($)",
        "ortalama_konut_m2": "Ortalama Konut Buyuklugu (m²)",
        "satis_birim_fiyat_usd_m2": "Satis Birim Fiyati ($/m²)",
    }
    
    input_rows = [
        [Paragraph("Parametre", styles["TableHeader"]), 
         Paragraph("Deger", styles["TableHeader"])]
    ]
    
    for k, v in inputs.items():
        label = input_labels.get(k, k)
        value_str = str(v)
        
        # Format numbers nicely
        if k in ["arsa_alani_m2", "ortalama_konut_m2"]:
            value_str = f"{float(v):,.0f} m²"
        elif k in ["emsal", "satilabilir_katsayi", "otopark_katsayi"]:
            value_str = f"{float(v):.2f}"
        elif k in ["insaat_maliyet_usd_m2", "satis_birim_fiyat_usd_m2"]:
            value_str = f"${float(v):,.0f}"
        elif k == "arsa_toplam_degeri_usd":
            value_str = f"${float(v):,.0f}"
        
        input_rows.append([
            Paragraph(label, styles["TableCell"]),
            Paragraph(value_str, styles["TableCell"])
        ])
    
    input_table = Table(input_rows, colWidths=[10*cm, 6*cm])
    input_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), PRIMARY_COLOR),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("BACKGROUND", (0,1), (-1,-1), LIGHT_BG),
        ("GRID", (0,0), (-1,-1), 0.5, MEDIUM_BG),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,1), (1,-1), "RIGHT"),
    ]))
    story.append(input_table)
    
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        "<i>Not: Bu rapordaki tum hesaplamalar yukaridaki girdilere ve kabullere dayanmaktadir. "
        "Gercek sonuclar piyasa kosullari, proje yonetimi ve diger faktorler nedeniyle farklilik gosterebilir.</i>",
        styles["BodyMuted"]
    ))

    # ============================================================
    # BUILD PDF with custom footer
    # ============================================================
    def footer(canvas, doc_):
        canvas.saveState()
        
        # Footer line
        canvas.setStrokeColor(MEDIUM_BG)
        canvas.setLineWidth(1)
        canvas.line(2.0*cm, 1.8*cm, A4[0]-2.0*cm, 1.8*cm)
        
        # Footer text
        canvas.setFont(base_font, 9)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawString(2.0*cm, 1.3*cm, "GGtech • Dr. Omur Tezcan")
        canvas.drawCentredString(A4[0]/2, 1.3*cm, "omurtezcan@gmail.com")
        canvas.drawRightString(A4[0]-2.0*cm, 1.3*cm, f"Sayfa {doc_.page}")
        
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)



        
        # Footer text
        canvas.setFont(base_font, 9)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawString(2.0*cm, 1.3*cm, "GGtech • Dr. Omur Tezcan")
        canvas.drawCentredString(A4[0]/2, 1.3*cm, "omurtezcan@gmail.com")
        canvas.drawRightString(A4[0]-2.0*cm, 1.3*cm, f"Sayfa {doc_.page}")
        
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
