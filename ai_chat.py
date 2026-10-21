import os
import base64
import asyncio
import logging
import aiohttp
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Siz o'zbek tilida gapiruvchi aqlli, xushmuomala va do'stona shaxsiy AI assistantsiz. "
    "Sizning eng birinchi va muhim qoidangiz — faqat SOF, ANIQ, RAVON va ADABIY O'ZBEK TILIDA javob berishdir.\n\n"
    "Qat'iy qoidalar:\n"
    "1. Doimo toza va ravon o'zbek adabiy tilida gapiring. Ruscha, inglizcha yoki aralash so'zlardan (masalan, 'konechno', 'ponyatno', 'davay' kabi) mutlaqo foydalanmang.\n"
    "2. Fikringizni aniq, lo'nda, tushunarli va mantiqiy bayon qiling. Keraksiz ortiqcha gaplar bilan cho'zmang.\n"
    "3. Grammatika, imlo va so'z tanlashda o'zbek tilining sof me'yorlariga rioya qiling.\n"
    "4. Ovozli tarzda eshitilishi uchun jumlalarni ravon, quloqqa yoqimli va tabiiy qilib tuzing.\n"
    "5. Har bir savolga samimiy, do'stona va amaliy yordam beradigan tarzda javob qaytaring."
)

VOICE_PROMPT = (
    "Foydalanuvchi ushbu ovozli xabarni yubordi. "
    "Uning nutqini tinglab, savoliga mos ravishda, FAQAT SOF VA RAVON O'ZBEK TILIDA javob bering. "
    "Javobingiz ovoz bilan o'qilishi uchun qisqa (2-4 jumla), lo'nda va tabiiy jonli inson ovozidek jarangdor bo'lsin. "
    "Begona va aralash so'zlarni aslo ishlatmang."
)


class GeminiChatService:
    """Google Gemini REST API orqali tezkor va sof o'zbek tilida muloqot qiluvchi xizmat."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = (api_key or GEMINI_API_KEY or "").strip()
        self.model = (model or GEMINI_MODEL or "gemini-flash-lite-latest").strip()
        # Foydalanuvchilarning suhbat konteksti (tarixi): user_id -> list of contents
        self.user_histories: dict[int, list[dict]] = {}
        # Tarixda saqlanadigan maksimal xabarlar soni
        self.max_history_turns = 10

    def is_configured(self) -> bool:
        """API kaliti sozlanganligini tekshiradi."""
        key = (self.api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        return bool(key and key != "SIZNING_GEMINI_API_KALITINGIZ")

    def get_api_key(self) -> str:
        """Har gal joriy API kalitini qaytaradi (muhitdan ham tekshiradi)."""
        current_key = (self.api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        return current_key

    def get_model(self) -> str:
        """Joriy model nomini qaytaradi (eng tezkor: gemini-flash-lite-latest)."""
        return (self.model or os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")).strip()

    def clear_history(self, user_id: int):
        """Foydalanuvchi suhbat tarixini tozalash."""
        if user_id in self.user_histories:
            self.user_histories.pop(user_id, None)

    async def _make_request(self, session: aiohttp.ClientSession, url: str, payload: dict, timeout_seconds: int = 20) -> dict | None:
        """API ga xavfsiz so'rov yuborish va 503 xatoligida tezkor qayta urinish."""
        headers = {"Content-Type": "application/json"}
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        for attempt in range(2):
            try:
                async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        return data
                    elif resp.status == 503 and attempt == 0:
                        logger.warning("Gemini 503 olindi, 1 soniyadan keyin qayta urinilmoqda...")
                        await asyncio.sleep(1.0)
                        continue
                    else:
                        error_msg = data.get("error", {}).get("message", "Noma'lum xatolik")
                        logger.error(f"Gemini API Error [{resp.status}]: {error_msg}")
                        return {"_error_status": resp.status, "_error_msg": error_msg}
            except asyncio.TimeoutError:
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                return {"_error_status": 408, "_error_msg": "Javob berish vaqti tugadi"}
            except Exception as e:
                logger.error(f"Gemini so'rov xatosi: {e}")
                return {"_error_status": 500, "_error_msg": str(e)}

        return None

    async def ask(self, user_id: int, prompt: str, session: aiohttp.ClientSession) -> str:
        """
        Foydalanuvchi matnli savoliga Gemini AI orqali tezkor (0.8s) va sof o'zbekcha javob oladi.
        """
        api_key = self.get_api_key()
        if not self.is_configured():
            return (
                "⚠️ <b>Gemini API kaliti topilmadi!</b>\n\n"
                "AI Chat xizmatidan foydalanish uchun <code>.env</code> faylini oching va "
                "<code>GEMINI_API_KEY</code> qatoriga o'z kalitingizni kiriting."
            )

        model = self.get_model()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        history = self.user_histories.get(user_id, [])

        # Yangi savolni qo'shamiz
        new_contents = list(history)
        new_contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        payload = {
            "contents": new_contents,
            "systemInstruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "generationConfig": {
                "temperature": 0.6,
                "maxOutputTokens": 1536,
            }
        }

        data = await self._make_request(session, url, payload, timeout_seconds=15)
        if not data:
            return "⚠️ AI serveri javob bermadi. Iltimos, qayta urinib ko'ring."

        if "_error_status" in data:
            status_code = data["_error_status"]
            error_msg = data.get("_error_msg", "")
            if status_code == 429:
                return "⏳ <b>So'rovlar limiti oshdi.</b> Iltimos, bir oz kuting."
            return f"⚠️ <b>Xatolik yuz berdi ({status_code}):</b> {error_msg}"

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                reply_text = "".join(p.get("text", "") for p in parts).strip()

                # Faqat matnli qismni tarixga qo'shamiz (yengil va tez ishlashi uchun)
                new_contents.append({
                    "role": "model",
                    "parts": [{"text": reply_text}]
                })

                if len(new_contents) > self.max_history_turns:
                    new_contents = new_contents[-self.max_history_turns:]

                self.user_histories[user_id] = new_contents
                return reply_text

        return "🤔 Savolingiz tushunildi, ammo javob hosil bo'lmadi. Qayta savol bering."

    async def ask_audio(
        self,
        user_id: int,
        audio_bytes: bytes,
        mime_type: str,
        session: aiohttp.ClientSession
    ) -> str:
        """
        Ovozli xabarni tahlil qilib, sof va qisqa o'zbek tilida javob qaytaradi.
        Tarixga ulkan audio base64 saqlanmaydi, faqat matn saqlanadi (tezlikni 30 barobar oshiradi).
        """
        api_key = self.get_api_key()
        if not self.is_configured():
            return (
                "⚠️ <b>Gemini API kaliti topilmadi!</b>\n\n"
                "Ovozli AI xizmatidan foydalanish uchun <code>.env</code> fayliga "
                "<code>GEMINI_API_KEY</code> ni kiriting."
            )

        model = self.get_model()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        history = self.user_histories.get(user_id, [])

        # Hozirgi ovozli so'rov
        current_user_part = {
            "role": "user",
            "parts": [
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": audio_b64
                    }
                },
                {
                    "text": VOICE_PROMPT
                }
            ]
        }

        # Tarix bilan birlashtiramiz (tarixda faqat matnlar bor, og'ir audio yo'q)
        payload_contents = list(history) + [current_user_part]

        payload = {
            "contents": payload_contents,
            "systemInstruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "generationConfig": {
                "temperature": 0.5,
                "maxOutputTokens": 512,
            }
        }

        data = await self._make_request(session, url, payload, timeout_seconds=15)
        if not data:
            return "Ovozli xabaringiz qabul qilindi, ammo server band. Qayta urinib ko'ring."

        if "_error_status" in data:
            status_code = data["_error_status"]
            error_msg = data.get("_error_msg", "")
            return f"⚠️ <b>Ovozni tahlil qilishda xatolik ({status_code}):</b> {error_msg}"

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                reply_text = "".join(p.get("text", "") for p in parts).strip()

                # MUHIM: Tarixga ulkan base64 audioni EMAS, balki faqat matnni yozamiz!
                # Bu keyingi barcha so'rovlar bir zumda (1 soniyada) ishlashini ta'minlaydi!
                updated_history = list(history)
                updated_history.append({
                    "role": "user",
                    "parts": [{"text": "[Foydalanuvchining ovozli xabari]"}]
                })
                updated_history.append({
                    "role": "model",
                    "parts": [{"text": reply_text}]
                })

                if len(updated_history) > self.max_history_turns:
                    updated_history = updated_history[-self.max_history_turns:]

                self.user_histories[user_id] = updated_history
                return reply_text

        return "Audio xabaringiz eshitildi, ammo javob hosil bo'lmadi. Iltimos, qayta yuboring."


# Global Gemini chat servisi
gemini_service = GeminiChatService()
