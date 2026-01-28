# 🏗️ AI Konut Fizibilite Asistanı

**AI-Powered Residential Real Estate Feasibility Analysis Tool**

Modern, profesyonel konut projesi fizibilite analizi için Streamlit tabanlı web uygulaması. OpenAI GPT entegrasyonu ile doğal dil desteği, otomatik hesaplamalar ve kapsamlı raporlama.

---

## ✨ Özellikler

### 🤖 AI Asistan
- Doğal dil ile veri girişi
- GPT-4o-mini ile akıllı veri çıkarımı
- Konuşma tabanlı etkileşim
- Adım adım rehberlik

### 📊 Hızlı Hesaplama
- Form bazlı hızlı giriş
- 2 kolonlu organize düzen
- Gerçek zamanlı hesaplama
- Otomatik varsayılan değerler

### 📈 Modern Dashboard
- 4 gradient KPI kartı
- İnteraktif grafikler
- Progress bar göstergeleri
- Renk kodlu metrikler

### 🔄 Senaryo Karşılaştırma
- Çoklu senaryo kaydı
- Yan yana karşılaştırma tablosu
- Görsel kâr analizi
- Excel export

### 📄 Raporlama
- **PDF Export:** Profesyonel 4 sayfalık rapor
- **Excel Export:** 4 sheet + pie chart
- **Karşılaştırma Excel:** Tüm senaryolar

### 💱 Kur Entegrasyonu
- TCMB otomatik kur çekimi
- Manuel kur override
- USD & TRY çift gösterim

### 📊 Grafikler
- Maliyet dağılımı (progress bars)
- Fiyat karşılaştırma (bar chart)
- Gelir akışı (gradient visual)
- Kârlılık göstergesi

---

## 🚀 Kurulum

### Gereksinimler
```bash
Python 3.10+
pip
```

### 1. Repository'yi Klonla
```bash
git clone https://github.com/YOUR_USERNAME/ai-konut-fizibilite.git
cd ai-konut-fizibilite
```

### 2. Bağımlılıkları Yükle
```bash
pip install -r requirements.txt
```

### 3. Secrets Ayarla
`.streamlit/secrets.toml` dosyası oluştur:
```toml
OPENAI_API_KEY = "sk-your-api-key-here"
OPENAI_MODEL = "gpt-4o-mini"
DAILY_LIMIT = 5
```

### 4. Uygulamayı Çalıştır
```bash
streamlit run app_modern.py
```

Tarayıcıda `http://localhost:8501` adresini aç.

---

## 📁 Dosya Yapısı

```
ai-konut-fizibilite/
├── app_modern.py          # Ana Streamlit uygulaması
├── feasibility.py         # Fizibilite hesaplama motoru
├── pdf_report.py          # PDF rapor oluşturma
├── excel_export.py        # Excel rapor oluşturma
├── requirements.txt       # Python bağımlılıkları
├── README.md             # Bu dosya
├── .streamlit/
│   └── secrets.toml      # API anahtarları (git'e ekleme!)
└── docs/
    ├── UI_MOCKUP.md      # Arayüz mockup
    ├── YENI_OZELLIKLER.md # Özellik listesi
    └── UI_IMPROVEMENTS.md # İyileştirme notları
```

---

## 🎯 Kullanım

### Hızlı Başlangıç

#### 1️⃣ AI Asistan ile
```
💬 AI Asistan sekmesine git
→ Bilgileri doğal dilde yaz:
  "8500 m² arsa, emsal 2.0, kapalı otopark, 
   yüksek sınıf, arsa değeri 5.5M$"
→ AI otomatik hesaplar ve önerir
```

#### 2️⃣ Hızlı Hesap ile
```
📊 Hızlı Hesap sekmesine git
→ Sol kolon: Arsa bilgileri
→ Sağ kolon: Gelişmiş ayarlar
→ 🧮 Hesapla butonuna bas
```

#### 3️⃣ Sonuçları İncele
```
📈 Sonuçlar sekmesine git
→ KPI kartlarını gör
→ Grafikleri incele
→ PDF veya Excel indir
```

### Senaryo Karşılaştırma

```bash
1. Hesaplama yap
2. "💾 Senaryoyu Kaydet" butonuna bas
3. Parametreleri değiştir
4. Tekrar hesapla ve kaydet
5. Karşılaştırma bölümünü gör
6. "📊 Karşılaştırma Excel'i İndir"
```

---

## 📊 Hesaplama Metodolojisi

### Ana Formüller

**Emsal İnşaat Alanı:**
```
Emsal İnşaat = Arsa Alanı × Emsal
```

**Satılabilir Alan:**
```
Satılabilir Alan = Emsal İnşaat × Satılabilir Katsayı
(Tipik: 1.20 - 1.35)
```

**Toplam İnşaat Alanı:**
```
Toplam İnşaat = Satılabilir Alan × Otopark Katsayısı
Açık Otopark: 1.20
Kapalı Otopark: 1.60
```

**Toplam Maliyet:**
```
Maliyet = (Toplam İnşaat × İnşaat Birim Maliyeti) + Arsa Değeri
```

**Başabaş Satış Fiyatı:**
```
Başabaş = Toplam Maliyet ÷ Satılabilir Alan
```

**Hedef Fiyatlar:**
```
%10 Kâr = Başabaş × 1.10
%30 Kâr = Başabaş × 1.30
%50 Kâr = Başabaş × 1.50
```

**Brüt Kârlılık:**
```
Brüt Kârlılık = (Hasılat - Maliyet) ÷ Maliyet
```

### Varsayılan Değerler

| Parametre | Alt Sınıf | Orta Sınıf | Yüksek Sınıf |
|-----------|-----------|------------|--------------|
| İnşaat Maliyeti | $700/m² | $900/m² | $1,100/m² |
| Satılabilir Katsayı | 1.25 | 1.25 | 1.25 |
| Ortalama Konut | 100 m² | 120 m² | 150 m² |

---

## 🎨 Arayüz Özellikleri

### KPI Kartları
```
┌─────────────┐
│    🏗️       │
│  SATILABIR  │
│    ALAN     │
│  22,100 m²  │
│             │
│  [gradient] │
└─────────────┘
```

### Progress Bars
```
Kârlılık Oranı
[████████████████████░░░░] 43.3%
Renk: Yeşil (>30% = İyi)
```

### Renk Şeması
- **Primary:** Navy mavi (#1E3A8A)
- **Success:** Yeşil (#10B981)
- **Warning:** Amber (#F59E0B)
- **Danger:** Kırmızı (#EF4444)

---

## 🔒 Güvenlik

### API Anahtarları
- `.streamlit/secrets.toml` dosyasını **asla** git'e eklemeyin
- `.gitignore` dosyasına ekleyin:
  ```
  .streamlit/secrets.toml
  *.pyc
  __pycache__/
  ```

### Kota Yönetimi
- Günlük hesaplama limiti (varsayılan: 5)
- Session bazlı takip
- User-Agent + IP hash

---

## 📝 Örnek Kullanım Senaryoları

### Senaryo 1: Tek Proje Analizi
```
Girdi:
- Arsa: 8,500 m²
- Emsal: 2.0
- Kapalı otopark
- Yüksek sınıf
- Arsa değeri: $5.5M

Çıktı:
- Satılabilir: 22,100 m²
- Konut: 163 adet
- Maliyet: $43.2M
- Başabaş: $1,954/m²
- %30 hedef: $2,540/m²
```

### Senaryo 2: Alternatif Karşılaştırması
```
3 farklı emsal değeri test et:
- Emsal 1.5: Kâr $12M
- Emsal 2.0: Kâr $18.7M ✓ En iyi
- Emsal 2.5: Kâr $16M

Karar: Emsal 2.0 optimal
```

---

## 🛠️ Geliştirme

### Yeni Özellik Ekleme

1. **Backend (feasibility.py):**
```python
def new_calculation(inputs):
    # Yeni hesaplama
    return result
```

2. **Frontend (app_modern.py):**
```python
with tab_new:
    st.markdown("### Yeni Özellik")
    result = new_calculation(inputs)
    st.metric("Sonuç", result)
```

3. **Export (excel_export.py):**
```python
ws_new = wb.create_sheet("Yeni Sheet")
# Yeni sheet içeriği
```

### Test
```bash
# Local test
streamlit run app_modern.py

# Production deploy
git push heroku main
```

---

## 🐛 Sorun Giderme

### API Hatası
```
Error: OpenAI API key not found
Çözüm: .streamlit/secrets.toml dosyasını kontrol et
```

### Kur Çekilemiyor
```
Warning: TCMB bağlantısı kurulamadı
Çözüm: Manuel kur kullan (checkbox)
```

### Font Hatası (PDF)
```
Warning: DejaVu font not found
Çözüm: Türkçe karakterler otomatik ASCII'ye dönüşür
```

### Kota Doldu
```
Error: Günlük limit doldu
Çözüm: Yarın tekrar dene veya DAILY_LIMIT artır
```

---

## 📚 Belgeler

- **UI_MOCKUP.md:** Arayüz görünümü
- **YENI_OZELLIKLER.md:** Özellik detayları
- **UI_IMPROVEMENTS.md:** İyileştirme notları

---

## 🤝 Katkıda Bulunma

1. Fork'la
2. Feature branch oluştur (`git checkout -b feature/amazing`)
3. Commit'le (`git commit -m 'Add amazing feature'`)
4. Push'la (`git push origin feature/amazing`)
5. Pull Request aç

---

## 📄 Lisans

Bu proje özel kullanım içindir. Ticari kullanım için iletişime geçin.

---

## 👨‍💻 Geliştirici

**Dr. Ömür Tezcan / GGtech**
- Email: omurtezcan@gmail.com
- GitHub: [@omurtezcan](https://github.com/omurtezcan)

---

## 🙏 Teşekkürler

- OpenAI (GPT-4o-mini)
- Streamlit Team
- ReportLab
- TCMB (Kur API)

---

## 📈 Changelog

### v2.0.0 (2026-01-28)
- ✨ 3 sekme yapısı (AI Asistan, Hızlı Hesap, Sonuçlar)
- 📊 Grafikler ve görselleştirmeler
- 🔄 Senaryo karşılaştırma sistemi
- 📊 Excel export (4 sheet + chart)
- 🎨 Modern gradient UI
- 📱 Responsive tasarım

### v1.0.0 (2025-12-15)
- 🤖 AI asistan entegrasyonu
- 📄 PDF export
- 💱 TCMB kur entegrasyonu
- 📊 Temel hesaplamalar

---

**Made with ❤️ by GGtech**
