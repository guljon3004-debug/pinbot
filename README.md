# 📌 Pinterest Video Downloader & 🎵 Shazam Music MP3 & 🤖 Gemini AI Bot

Ushbu bot **Python** dasturlash tili va zamonaviy asinxron **Aiogram 3** freymvorki yordamida yaratilgan. Bot quyidagi kuchli imkoniyatlarga ega:
1. **Pinterest Video Downloader:** Pinterest video havolasini (link) yuborganingizda, uni bir zumda **MP4** video formatida yuklab beradi.
2. **🎵 Musiqa va MP3 (Shazam orqali aniqlash):** Har bir yuklangan videodagi musiqani Shazam algoritmi orqali aniqlab, yuqori sifatli **MP3** audio formatida (nomi, ijrochisi, janri bilan) jo'natadi! Shuningdek, Telegram orqali to'g'ridan-to'g'ri yuborilgan har qanday videodan ham musiqani ajratib MP3 qilib beradi.
3. **🤖 Google Gemini AI Chat:** Eng so'nggi Google Gemini sun'iy intellekti bilan to'g'ridan-to'g'ri Telegram orqali o'zbek tilida matnli va ovozli muloqot qilish.

---

## ✨ Imkoniyatlari

### 🎬 Pinterest Video Yuklash & 🎵 MP3 Musiqa
- 🎯 **Barcha turdagi havolalarni qo'llab-quvvatlaydi:**
  - Qisqa havolalar: `https://pin.it/...`
  - To'liq havolalar: `https://www.pinterest.com/pin/...`
  - Mobil ilovadan ulashilgan matn ichidagi havolalar
- 🚀 **Ikki bosqichli yuklash tizimi:**
  - 1-bosqich: To'g'ridan-to'g'ri MP4 oqimi (bir necha soniyada)
  - 2-bosqich: `yt-dlp` dvigateli (zaxira tizim)
- 🎧 **Musiqani Shazam orqali aniqlash:**
  - Videodagi qo'shiq nomi, ijrochisi va janri avtomatik aniqlanadi.
  - Video bilan birga tayyor Telegram audio (MP3) fayli jo'natiladi.
- 📹 **To'g'ridan-to'g'ri videolarni MP3 ga o'tkazish:**
  - Botga istalgan video yuborsangiz, undagi musiqani ajratib MP3 formatida qaytaradi.
- 🧹 **Xotirani avtomatik tozalash:** Yuklangan fayllar avtomatik tarzda tozalanadi.

### 🤖 Google Gemini AI Chat (Matn va Ovoz)
- 🧠 **Google Gemini modeli:** Aqlli, do'stona va ravon o'zbek tilida suhbatlashadi.
- 🎙 **Ovozli muloqot (Speech-to-Speech):** Siz ovozli xabar (voice) yuborsangiz, bot uni tinglaydi va o'zbekcha tabiiy ovoz bilan audio formatda javob qaytaradi!
- 👥 **Guruhlarda aqlli ishlash:** Botni guruhlarga qo'shish mumkin. Bot guruhda faqat o'zi chaqirilganda (bot username yozilganda yoki uning xabariga 'Reply' qilinganda) javob beradi va boshqa foydalanuvchilarning o'zaro suhbatiga aslo xalaqit bermaydi!
- 📢 **Majburiy kanal obunasi (Force Subscription):** Botdan foydalanishdan oldin foydalanuvchilar sizning kanalingizga a'zo bo'lishi talab qilinadi.
- 💬 **Kontekstni eslab qolish:** Oldingi savol-javoblarni eslab qoladi va muloqotni davom ettiradi.
- ⚡️ **Tezkor buyruqlar:** `/ai <savol>` orqali rejimga o'tmasdan ham bir zumda javob olish mumkin.
- 🧹 **Tarixni tozalash:** `🗑 Suhbatni tozalash` tugmasi yoki `/clear` buyrug'i orqali xotirani yangilash.
- 📱 **Qulay menyu:** Asosiy va AI rejimlari o'rtasida qulay Reply tugmalar.

---

## 📁 Loyiha tarkibi

```text
pinterest bot/
├── bot.py             # Botning asosiy kodi (Aiogram 3, menyu, audio va marshrutlar)
├── audio_service.py   # FFmpeg orqali MP3 ajratish va Shazam song recognition moduli
├── ai_chat.py         # Google Gemini AI integratsiyasi va muloqot xizmati
├── tts_service.py     # Microsoft Edge TTS va FFmpeg bilan ovoz yaratish
├── downloader.py      # Pinterest videosini yuklash moduli
├── config.py          # Sozlamalar va tekshiruvlar
├── requirements.txt   # Kerakli Python kutubxonalari
├── start.bat          # Windows uchun bitta bosishda ishga tushirish fayli (avto-restart bilan)
├── stop_bot.bat       # Bot jarayonini to'xtatish
├── run_background.vbs # Fon rejimida oynasiz ishga tushirish
├── run_loop.bat       # Avtomatik qayta ulanish davrasi
├── .env.example       # Konfiguratsiya namunasi
├── .env               # Telegram bot va Gemini API kaliti
└── README.md          # Qo'llanma
```

---

## 🛠 O'rnatish va Sozlash

### 1-qadam: Telegram Bot Token olish
1. Telegramda [@BotFather](https://t.me/BotFather) botiga kiring.
2. `/newbot` buyrug'ini yuboring va botingiz nomini tanlang.
3. Berilgan `BOT_TOKEN` ni saqlab oling.

### 2-qadam: Google Gemini API kalitini olish
1. [Google AI Studio](https://aistudio.google.com/app/apikey) sahifasiga kiring (Google hisobingiz orqali).
2. **«Create API key»** tugmasini bosing va kalitni nusxalang.

### 3-qadam: `.env` faylini to'ldirish
Loyiha papkasidagi `.env` faylini oching:
```env
BOT_TOKEN=8709965660:AAEKwXEf_tEtWiie60m3W6078CISVS9LeJA
DOWNLOADS_DIR=downloads

# O'zingiz olgan Gemini API kalitini shu yerga yozing:
GEMINI_API_KEY=SIZNING_GEMINI_API_KALITINGIZ
GEMINI_MODEL=gemini-1.5-flash
```

### 4-qadam: Botni ishga tushirish
- **Oddiy konsol oynasi bilan:** `start.bat` faylini ikki marta bosing.
- **Terminal orqali:**
  ```bash
  python bot.py
  ```

---

## 📱 Botdan foydalanish

1. Telegramda botga `/start` yuboring.
2. **Video yuklash uchun:** Pinterest havolasini yuboring.
3. **AI Chat bilan muloqot uchun:** 
   - `🤖 AI Chat (Gemini)` tugmasini bosing yoki
   - `/ai O'zbekistonning diqqatga sazovor joylari qaysilar?` deb yozing.
