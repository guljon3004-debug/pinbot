import os
import logging
import aiohttp
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Siz aqlli, xushmuomala va do'stona AI assistantsiz (Google Gemini modeli asosida). "
    "Foydalanuvchilarga doimo tushunarli, aniq, foydali va samimiy javob bering. "
    "Foydalanuvchi qaysi tilda murojaat qilsa, o'sha tilda (asosan o'zbek tilida) ravon javob qaytaring. "
    "Kerakli o'rinlarda emojilardan foydalaning, ro'yxatlar va muhim fikrlarni chiroyli ajratib ko'rsating."
)


class GeminiChatService:
    """Google Gemini REST API orqali asinxron muloqot qiluvchi xizmat."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = (api_key or GEMINI_API_KEY or "").strip()
        self.model = (model or GEMINI_MODEL or "gemini-flash-latest").strip()
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
        """Joriy model nomini qaytaradi."""
        return (self.model or os.getenv("GEMINI_MODEL", "gemini-flash-latest")).strip()

    def clear_history(self, user_id: int):
        """Foydalanuvchi suhbat tarixini tozalash."""
        if user_id in self.user_histories:
            self.user_histories.pop(user_id, None)

    async def ask(self, user_id: int, prompt: str, session: aiohttp.ClientSession) -> str:
        """
        Foydalanuvchi savoliga Gemini AI orqali javob oladi.
        Kontekst (suhbat tarixi) avtomatik ravishda saqlanadi.
        """
        api_key = self.get_api_key()

        # Agar API kalit kiritilmagan bo'lsa
        if not self.is_configured():
            return (
                "⚠️ <b>Gemini API kaliti topilmadi!</b>\n\n"
                "AI Chat xizmatidan foydalanish uchun bot papkasidagi <b><code>.env</code></b> faylini oching va "
                "<b><code>GEMINI_API_KEY=...</code></b> qatoriga o'z API kalitingizni kiriting.\n\n"
                "🔑 <i>API kalitni bepul olish uchun:</i>\n"
                "<a href=\"https://aistudio.google.com/app/apikey\">https://aistudio.google.com/app/apikey</a> saytiga kiring."
            )

        model = self.get_model()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        # Foydalanuvchi tarixini olamiz yoki yangi boshlaymiz
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
                "temperature": 0.7,
                "maxOutputTokens": 2048,
            }
        }

        headers = {
            "Content-Type": "application/json"
        }

        try:
            timeout = aiohttp.ClientTimeout(total=45)
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                data = await resp.json()

                if resp.status == 200:
                    candidates = data.get("candidates", [])
                    if candidates:
                        candidate = candidates[0]
                        content = candidate.get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            reply_text = "".join(p.get("text", "") for p in parts).strip()

                            # Javobni tarixga qo'shamiz
                            new_contents.append({
                                "role": "model",
                                "parts": [{"text": reply_text}]
                            })

                            # Tarixni maksimal o'lchamda ushlab turamiz
                            if len(new_contents) > self.max_history_turns:
                                new_contents = new_contents[-self.max_history_turns:]

                            self.user_histories[user_id] = new_contents
                            return reply_text

                    return "🤔 AI dan bo'sh javob qaytdi. Iltimos, boshqacha savol berib ko'ring."

                # Agar xatolik bo'lsa
                error_info = data.get("error", {})
                error_msg = error_info.get("message", "Noma'lum xatolik")
                status_code = resp.status

                logger.error(f"Gemini API Error [{status_code}]: {error_msg}")

                if status_code == 400:
                    if "API key not valid" in error_msg or "INVALID_ARGUMENT" in str(error_info):
                        return (
                            "❌ <b>Gemini API kaliti yaroqsiz!</b>\n\n"
                            "Iltimos, <code>.env</code> faylidagi <code>GEMINI_API_KEY</code> to'g'ri kiritilganini tekshiring."
                        )
                    return f"❌ <b>So'rovda xatolik:</b>\n{error_msg}"
                elif status_code == 429:
                    return (
                        "⏳ <b>So'rovlar limiti oshdi!</b>\n\n"
                        "Gemini API bepul tarifi bo'yicha limitga yetildi. Iltimos, birozdan keyin qayta urinib ko'ring."
                    )
                else:
                    return f"⚠️ <b>Gemini xizmatida xatolik ({status_code}):</b>\n{error_msg}"

        except aiohttp.ClientConnectorError:
            return "📡 <b>Internet yoki tarmoqqa ulanishda muammo bo'ldi.</b> Iltimos, internetingizni tekshiring."
        except asyncio.TimeoutError:
            return "⏱ <b>Gemini AI javob berish vaqti tugadi (Timeout).</b> Iltimos, qayta urinib ko'ring."
        except Exception as e:
            logger.exception("Gemini so'rovida kutilmagan xatolik:")
            return f"⚠️ <b>Kutilmagan xatolik yuz berdi:</b> {str(e)}"

    async def ask_audio(
        self,
        user_id: int,
        audio_bytes: bytes,
        mime_type: str,
        session: aiohttp.ClientSession
    ) -> str:
        """
        Foydalanuvchi yuborgan ovozli/audio xabarni Gemini AI ga yuboradi va javob matnini oladi.
        """
        import base64

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

        # Yangi audio so'rov
        user_content = {
            "role": "user",
            "parts": [
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": audio_b64
                    }
                },
                {
                    "text": (
                        "Foydalanuvchi ushbu ovozli xabarni yubordi. "
                        "Uning nutqini tinglab, savoliga mos ravishda, o'zbek tilida samimiy, aniq va "
                        "ovoz bilan o'qishga qulay qilib (juda cho'zmasdan) javob bering."
                    )
                }
            ]
        }

        new_contents = list(history)
        new_contents.append(user_content)

        payload = {
            "contents": new_contents,
            "systemInstruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1024,
            }
        }

        headers = {"Content-Type": "application/json"}

        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                data = await resp.json()

                if resp.status == 200:
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            reply_text = "".join(p.get("text", "") for p in parts).strip()

                            # Javobni tarixga qo'shamiz
                            new_contents.append({
                                "role": "model",
                                "parts": [{"text": reply_text}]
                            })

                            if len(new_contents) > self.max_history_turns:
                                new_contents = new_contents[-self.max_history_turns:]

                            self.user_histories[user_id] = new_contents
                            return reply_text

                    return "Audio xabaringiz eshitildi, ammo javob hosil qilib bo'lmadi. Iltimos, qayta yuboring."

                error_info = data.get("error", {})
                error_msg = error_info.get("message", "Noma'lum xatolik")
                logger.error(f"Gemini Audio Error [{resp.status}]: {error_msg}")
                return f"⚠️ <b>Ovozni tahlil qilishda xatolik ({resp.status}):</b> {error_msg}"

        except Exception as e:
            logger.exception("Gemini audio so'rovida xatolik:")
            return f"⚠️ <b>Xatolik yuz berdi:</b> {str(e)}"


# Global Gemini chat servisi
gemini_service = GeminiChatService()
