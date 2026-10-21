import os
import sys
import re
import time
import uuid
import asyncio
import logging
import aiohttp
import aiofiles

# Windows konsolida UTF-8 va emojilar to'g'ri ko'rinishi uchun
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    FSInputFile,
    URLInputFile,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.enums import ChatAction, ChatType
from aiogram.utils.chat_action import ChatActionSender
from aiogram.exceptions import TelegramBadRequest

from config import (
    BOT_TOKEN,
    DOWNLOADS_DIR,
    validate_config,
    GEMINI_API_KEY,
    REQUIRED_CHANNEL,
    CHANNEL_URL,
    ADMIN_ID
)
from downloader import (
    extract_pinterest_url,
    extract_fast_direct_video,
    download_direct_mp4_file,
    download_with_ytdlp_fast,
    cleanup_file
)
from ai_chat import gemini_service
from tts_service import generate_voice_message
from audio_service import process_video_audio

# Log sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Konfiguratsiyani tekshirish
validate_config()

# Bot va Dispatcher obyektlari
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Tarmoq ulanishlarini qayta ishlatish uchun global aiohttp sessiyasi
http_session: aiohttp.ClientSession | None = None

# Foydalanuvchilarning joriy rejimi: user_id -> "default" | "ai_chat"
user_modes: dict[int, str] = {}


# ==========================================
# OBUNA VA KANALLAR BILAN ISHLASH
# ==========================================

async def is_subscribed(user_id: int) -> bool:
    """Foydalanuvchi majburiy kanalga a'zo ekanligini tekshiradi."""
    # Bot egasi / Admin uchun doimo ruxsat berilgan
    if ADMIN_ID and str(user_id) == str(ADMIN_ID):
        return True
    if not REQUIRED_CHANNEL or not REQUIRED_CHANNEL.strip():
        return True
    try:
        target_chat = REQUIRED_CHANNEL.strip()
        if not (target_chat.startswith("@") or target_chat.startswith("-100")):
            target_chat = f"@{target_chat}"
        member = await bot.get_chat_member(chat_id=target_chat, user_id=user_id)
        # Statuslar: creator, administrator, member, restricted (cheklovli bo'lsa ham a'zo)
        return member.status in ["creator", "administrator", "member", "restricted"]
    except Exception as e:
        logger.warning(f"Obunani tekshirishda xatolik ({e}). O'tkazib yuboriladi.")
        # Agar bot kanalda admin bo'lmasa yoki kanal noto'g'ri bo'lsa, xatolik berib qotib qolmaslik uchun True
        return True


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Kanalga obuna bo'lish tugmalari."""
    channel_link = CHANNEL_URL.strip() if CHANNEL_URL else ""
    if not channel_link and REQUIRED_CHANNEL:
        clean_ch = REQUIRED_CHANNEL.strip().lstrip("@")
        channel_link = f"https://t.me/{clean_ch}"

    buttons = []
    if channel_link:
        buttons.append([InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=channel_link)])
    buttons.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_subscription_prompt(message: types.Message):
    """Obuna bo'lmagan foydalanuvchiga ogohlantirish yuborish."""
    user_name = message.from_user.first_name if message.from_user else "do'stim"
    text = (
        f"👋 <b>Assalomu alaykum, {user_name}!</b>\n\n"
        f"⚠️ <b>Botdan to'liq foydalanish uchun rasmiy kanalimizga a'zo bo'lishingiz kerak!</b>\n\n"
        f"Iltimos, quyidagi tugma orqali kanalga obuna bo'ling va keyin <b>«✅ Obunani tekshirish»</b> tugmasini bosing:"
    )
    await message.reply(text, reply_markup=get_subscription_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: types.CallbackQuery):
    """Obunani tekshirish tugmasi bosilganda."""
    user_id = callback.from_user.id
    if await is_subscribed(user_id):
        await callback.answer("✅ Rahmat! Obunangiz tasdiqlandi.", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        if callback.message:
            await callback.message.answer(
                "🎉 <b>Kanalimizga obuna bo'lganingiz tasdiqlandi!</b>\n\n"
                "Endi botning barcha imkoniyatlaridan to'liq foydalanishingiz mumkin:\n"
                "• 🎬 Pinterest video havolasini yuboring\n"
                "• 🤖 Gemini AI bilan yozishing yoki ovozli xabar yuboring!",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
    else:
        await callback.answer(
            "❌ Siz hali kanalga a'zo bo'lmadingiz!\nIltimos, avval kanalga obuna bo'ling va qayta tekshiring.",
            show_alert=True
        )


# ==========================================
# MENYU TUGMALARI VA YORDAMCHI FUNKSIYALAR
# ==========================================

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Asosiy menyu tugmalari."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Pinterest Video Yuklash"), KeyboardButton(text="🤖 AI Chat (Gemini)")],
            [KeyboardButton(text="🎵 Musiqani aniqlash (MP3)"), KeyboardButton(text="ℹ️ Yordam")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Havola yoki video yuboring..."
    )


def get_ai_keyboard() -> ReplyKeyboardMarkup:
    """AI Chat rejimi tugmalari."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗑 Suhbatni tozalash")],
            [KeyboardButton(text="🔙 Asosiy menyu")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Gemini AI ga savolingizni yozing..."
    )


def get_quick_ai_inline_kb() -> InlineKeyboardMarkup:
    """Tezkor AI chatga o'tish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 AI Chatga o'tish", callback_data="open_ai_chat")]
        ]
    )


async def is_bot_addressed_in_group(message: types.Message) -> tuple[bool, str]:
    """
    Guruhda bot chaqirilganligini tekshiradi va tozalangan matnni qaytaradi.
    Qaytaradi: (chaqirilganmi: bool, tozalangan_matn: str)
    """
    bot_info = await bot.get_me()
    bot_username = (bot_info.username or "").lower()
    bot_id = bot_info.id

    user_text = message.text or message.caption or ""

    # 1. Botning xabariga 'Reply' qilinganmi?
    is_reply = bool(
        message.reply_to_message and
        message.reply_to_message.from_user and
        message.reply_to_message.from_user.id == bot_id
    )

    # 2. Xabarda @bot_username yozilganmi?
    is_mention = bool(bot_username and f"@{bot_username}" in user_text.lower())

    if not (is_reply or is_mention):
        return False, ""

    # Bot username ni matndan tozalaymiz
    clean_text = user_text
    if bot_username:
        clean_text = re.sub(rf"@{re.escape(bot_username)}", "", clean_text, flags=re.IGNORECASE).strip()

    return True, clean_text


async def send_split_message(message: types.Message, text: str):
    """
    Uzun xabarlarni Telegram limiti (4096 belgi) bo'yicha bo'lib jo'natadi.
    HTML teglari xatolik bersa, oddiy matn ko'rinishida jo'natadi.
    """
    max_len = 3900
    if len(text) <= max_len:
        chunks = [text]
    else:
        chunks = []
        lines = text.split("\n")
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_len:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                while len(line) > max_len:
                    chunks.append(line[:max_len])
                    line = line[max_len:]
                current_chunk = line
            else:
                current_chunk = f"{current_chunk}\n{line}" if current_chunk else line
        if current_chunk:
            chunks.append(current_chunk)

    for chunk in chunks:
        try:
            await message.reply(chunk, parse_mode="HTML")
        except TelegramBadRequest:
            await message.reply(chunk, parse_mode=None)


# ==========================================
# ASOSIY BUYRUQLAR HANDLERLARI
# ==========================================

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    """Foydalanuvchi /start bosganida ishga tushadi."""
    user_id = message.from_user.id if message.from_user else 0
    is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    if not is_group and not await is_subscribed(user_id):
        await send_subscription_prompt(message)
        return

    user_modes[user_id] = "default"
    user_name = message.from_user.first_name if message.from_user else "do'stim"

    text = (
        f"👋 <b>Assalomu alaykum, {user_name}!</b>\n\n"
        f"Xush kelibsiz! Ushbu bot quyidagi imkoniyatlarga ega:\n\n"
        f"1️⃣ <b>🎬 Pinterest Video Downloader:</b>\n"
        f"Pinterest'dagi istalgan video havolasini yuboring, uni bir necha soniyada <b>MP4</b> formatida yuklab beraman!\n\n"
        f"2️⃣ <b>🎵 Musiqani aniqlash va MP3 olish (Shazam):</b>\n"
        f"Har bir yuklangan videodagi qo'shiqni avtomatik aniqlayman va uni <b>MP3 audio</b> formatida ham taqdim etaman! Shuningdek, istalgan videoni botga yuborsangiz, undagi musiqani ajratib MP3 qilib beraman.\n\n"
        f"3️⃣ <b>🤖 Google Gemini AI Chat (Matn va Ovoz):</b>\n"
        f"Gemini sun'iy intellekti bilan suhbatlashing! Menga <b>ovozli xabar (audio)</b> yuborsangiz, men ham sizga <b>ovozli formatda</b> javob qaytaraman! 🎙⚡️\n\n"
        f"👥 <b>Guruhlarda ishlash:</b>\n"
        f"Botni guruhga qo'shib, unga savol berishingiz mumkin. Bot guruhda faqat o'zi chaqirilganda javob beradi va boshqa suhbatlarga xalaqit bermaydi!\n\n"
        f"<i>Quyidagi menyudan kerakli bo'limni tanlang:</i>"
    )
    if is_group:
        await message.reply(text, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(Command("help"))
async def help_handler(message: types.Message):
    """Foydalanuvchi /help yozganida yoki 'ℹ️ Yordam' bosganida ishga tushadi."""
    text = (
        "📖 <b>Botdan foydalanish qo'llanmasi:</b>\n\n"
        "🎬 <b>Pinterest videolarini yuklash:</b>\n"
        "1. Pinterest ilovasida videoni oching.\n"
        "2. «Ulashish» (Share) -> «Havolani nusxalash» (Copy link) ni bosing.\n"
        "3. Havolani shu botga yuboring — bot bir zumda MP4 qilib qaytaradi! ⚡️\n\n"
        "🎵 <b>Musiqani aniqlash va MP3 formatga o'tkazish (Shazam):</b>\n"
        "• Pinterest'dan video yuklaganingizda bot videodagi qo'shiqni Shazam orqali aniqlaydi va tayyor <b>MP3 audio</b> formatida ham yuboradi.\n"
        "• Shuningdek, Telegram orqali istalgan videoni to'g'ridan-to'g'ri botga yuborsangiz ham, bot undagi musiqani MP3 qilib chiqarib beradi! 🎧\n\n"
        "🤖 <b>Gemini AI Chat bilan gaplashish:</b>\n"
        "• <b>«🤖 AI Chat (Gemini)»</b> tugmasini bosing va to'g'ridan-to'g'ri suhbatlashing.\n"
        "• Yoki istalgan paytda <code>/ai savolingiz</code> ko'rinishida savol bering.\n"
        "• Ovozli xabar yuborsangiz, bot sizga ovozli xabar bilan javob qaytaradi! 🎙\n\n"
        "👥 <b>Guruhda foydalanish:</b>\n"
        "• Botni guruhingizga qo'shing.\n"
        "• Botga savol berish uchun uni belgilang (masalan: <code>@jurpinbot O'zbekiston poytaxti qayer?</code>) yoki botning xabariga 'Reply' (javob) bering!\n"
        "• Bot guruhdagi boshqa shaxsiy suhbatlarga aralashmaydi.\n"
    )
    await message.reply(text, parse_mode="HTML")


@dp.message(Command("ai"))
async def ai_command_handler(message: types.Message, command: CommandObject):
    """
    /ai buyrug'i. Agar argument bo'lsa darhol javob beradi,
    bo'sh bo'lsa shaxsiy chatda AI Chat rejimini yoqadi.
    """
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    user_id = message.from_user.id if message.from_user else 0
    is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    # Obunani tekshiramiz
    if not await is_subscribed(user_id):
        await send_subscription_prompt(message)
        return

    prompt = (command.args or "").strip()

    if prompt:
        async with ChatActionSender(bot=bot, chat_id=message.chat.id, action=ChatAction.TYPING):
            reply = await gemini_service.ask(user_id, prompt, http_session)
            await send_split_message(message, reply)
    else:
        if is_group:
            bot_info = await bot.get_me()
            await message.reply(
                f"Guruhda savol berish uchun: <code>/ai savolingiz</code> deb yozing yoki meni chaqiring: @{bot_info.username} savolingiz",
                parse_mode="HTML"
            )
        else:
            user_modes[user_id] = "ai_chat"
            await message.answer(
                "🤖 <b>Google Gemini AI Chat rejimiga xush kelibsiz!</b>\n\n"
                "Menga istalgan savolingizni yozing yoki ovozli xabar yuboring, barchasiga batafsil javob beraman. 💬\n\n"
                "Rejimdan chiqish uchun <b>«🔙 Asosiy menyu»</b> tugmasini bosing yoki <code>/exit</code> deb yozing.",
                reply_markup=get_ai_keyboard(),
                parse_mode="HTML"
            )


@dp.message(Command("exit"))
async def exit_command_handler(message: types.Message):
    """AI rejimidan chiqish."""
    user_id = message.from_user.id if message.from_user else 0
    user_modes[user_id] = "default"
    await message.answer(
        "🏠 <b>Asosiy menyuga qaytdingiz.</b>\n\nPinterest video havolasini yuborishingiz mumkin!",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


@dp.message(Command("clear"))
async def clear_command_handler(message: types.Message):
    """AI suhbat tarixini tozalash."""
    user_id = message.from_user.id if message.from_user else 0
    gemini_service.clear_history(user_id)
    await message.reply(
        "🧹 <b>Suhbat tarixi tozalandi!</b>\n\nYangi mavzuda savol berishingiz mumkin.",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "open_ai_chat")
async def open_ai_callback(callback: types.CallbackQuery):
    """Inline tugma orqali AI Chat rejimiga o'tish."""
    user_id = callback.from_user.id if callback.from_user else 0

    if not await is_subscribed(user_id):
        if callback.message:
            await send_subscription_prompt(callback.message)
        await callback.answer()
        return

    user_modes[user_id] = "ai_chat"
    await callback.answer("🤖 AI Chat rejimi faollashdi")
    if callback.message:
        await callback.message.answer(
            "🤖 <b>Google Gemini AI Chat rejimiga o'tdingiz!</b>\n\n"
            "Menga o'zingizni qiziqtirgan savolni yozing yoki ovozli xabar yuboring. 💬\n\n"
            "Rejimdan chiqish uchun <b>«🔙 Asosiy menyu»</b> tugmasini bosing.",
            reply_markup=get_ai_keyboard(),
            parse_mode="HTML"
        )


# ==========================================
# OVOZLI VA AUDIO XABARLAR HANDLERI
# ==========================================

@dp.message(F.voice | F.audio)
async def voice_audio_message_handler(message: types.Message):
    """
    Foydalanuvchi ovozli yoki audio xabar yuborganida ishga tushadi:
    - Guruhda faqat botga 'Reply' qilinganda yoki bot username ko'rsatilganda ishlaydi.
    - Shaxsiy chatda doim ishlaydi (obuna tekshiruvi bilan).
    """
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    user_id = message.from_user.id if message.from_user else 0
    is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    # Guruhda bo'lsa: faqat botga murojaat qilingandagina javob beramiz
    if is_group:
        bot_info = await bot.get_me()
        bot_id = bot_info.id
        bot_username = (bot_info.username or "").lower()

        is_reply = bool(
            message.reply_to_message and
            message.reply_to_message.from_user and
            message.reply_to_message.from_user.id == bot_id
        )
        is_caption_mention = bool(
            message.caption and
            bot_username and
            f"@{bot_username}" in message.caption.lower()
        )

        if not (is_reply or is_caption_mention):
            # Guruh a'zolarining o'zaro shaxsiy ovozli xabarlariga aralashmaymiz!
            return

    # Majburiy obunani tekshirish
    if not await is_subscribed(user_id):
        await send_subscription_prompt(message)
        return

    voice_file_to_clean = None
    input_file_path = None

    async with ChatActionSender(bot=bot, chat_id=message.chat.id, action=ChatAction.RECORD_VOICE):
        status_msg = await message.reply("🎙 <b>Ovozingiz tinglanmoqda va tahlil qilinmoqda...</b>", parse_mode="HTML")
        try:
            file_obj = message.voice or message.audio
            if not file_obj:
                return

            file_info = await bot.get_file(file_obj.file_id)
            if not file_info.file_path:
                await status_msg.edit_text("⚠️ Audio faylni Telegramdan yuklab bo'lmadi.", parse_mode="HTML")
                return

            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            ext = os.path.splitext(file_info.file_path)[1] or (".ogg" if message.voice else ".mp3")
            unique_name = f"input_audio_{uuid.uuid4().hex[:8]}{ext}"
            input_file_path = os.path.join(DOWNLOADS_DIR, unique_name)

            await bot.download_file(file_info.file_path, destination=input_file_path)

            mime_type = "audio/ogg" if message.voice else (message.audio.mime_type or "audio/mp3")

            async with aiofiles.open(input_file_path, "rb") as af:
                audio_bytes = await af.read()

            reply_text = await gemini_service.ask_audio(
                user_id=user_id,
                audio_bytes=audio_bytes,
                mime_type=mime_type,
                session=http_session
            )

            # Agar xatolik bo'lsa ovozga aylantirmasdan to'g'ridan-to'g'ri matnni chiqaramiz
            if reply_text.startswith("⚠️") or reply_text.startswith("❌") or reply_text.startswith("⏳"):
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                await send_split_message(message, reply_text)
                return

            # Javobni TTS orqali tabiiy ovozli xabarga aylantiramiz
            voice_file_to_clean = await generate_voice_message(reply_text, output_dir=DOWNLOADS_DIR)

            if voice_file_to_clean and os.path.exists(voice_file_to_clean):
                voice_input = FSInputFile(voice_file_to_clean, filename="voice_reply.ogg")
                caption = f"🎙 <b>AI Javobi:</b>\n{reply_text}" if len(reply_text) <= 900 else None

                try:
                    await message.reply_voice(
                        voice=voice_input,
                        caption=caption,
                        parse_mode="HTML" if caption else None
                    )
                except Exception:
                    await message.reply_voice(
                        voice=voice_input,
                        caption=reply_text if len(reply_text) <= 900 else None,
                        parse_mode=None
                    )

                if not caption:
                    await send_split_message(message, f"📝 <b>Matn ko'rinishi:</b>\n{reply_text}")

                try:
                    await status_msg.delete()
                except Exception:
                    pass
            else:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                await send_split_message(message, reply_text)


        except Exception as e:
            logger.exception("Ovozli xabarni qayta ishlashda xatolik:")
            await status_msg.edit_text(f"⚠️ <b>Xatolik yuz berdi:</b> {str(e)}", parse_mode="HTML")
        finally:
            if input_file_path and os.path.exists(input_file_path):
                cleanup_file(input_file_path)
            if voice_file_to_clean and os.path.exists(voice_file_to_clean):
                cleanup_file(voice_file_to_clean)


# ==========================================
# BARCHA MATNLI XABARLARNI YO'NALTIRUVCHI HANDLER
# ==========================================

@dp.message(F.text)
async def message_router_handler(message: types.Message):
    """
    Barcha matnli xabarlarni yo'naltiruvchi asosiy handler.
    Guruhlarda faqat bot chaqirilganda javob beradi.
    """
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    user_text = message.text.strip()
    user_id = message.from_user.id if message.from_user else 0
    is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    # 1. Guruhda bot chaqirilganmi yoki yo'qligini tekshiramiz
    is_addressed = False
    clean_prompt = user_text
    if is_group:
        is_addressed, clean_prompt = await is_bot_addressed_in_group(message)

    # 2. Pinterest havolasi bormi?
    pinterest_url = extract_pinterest_url(user_text)
    if pinterest_url:
        if not await is_subscribed(user_id):
            await send_subscription_prompt(message)
            return
        await process_pinterest_download(message, pinterest_url)
        return

    # 3. Agar guruhda bo'lsa va bot chaqirilmagan bo'lsa — SUHBATLARGA MUTLAQO ARALASHMAYMIZ!
    if is_group and not is_addressed:
        return

    # 4. Majburiy obunani tekshirish
    if not await is_subscribed(user_id):
        await send_subscription_prompt(message)
        return

    # 5. Guruhda bot chaqirilgan holat
    if is_group and is_addressed:
        if not clean_prompt:
            bot_info = await bot.get_me()
            await message.reply(
                f"Assalomu alaykum! Men shu yerdaman. Savolingizni yozing yoki Pinterest havolasini yuboring. 💬",
                parse_mode="HTML"
            )
            return

        async with ChatActionSender(bot=bot, chat_id=message.chat.id, action=ChatAction.TYPING):
            reply = await gemini_service.ask(user_id, clean_prompt, http_session)
            await send_split_message(message, reply)
        return

    # 6. Shaxsiy chatdagi menyu tugmalari
    if user_text == "🔙 Asosiy menyu":
        user_modes[user_id] = "default"
        await message.answer(
            "🏠 <b>Asosiy menyuga qaytdingiz.</b>\n\nPinterest video havolasini yuborishingiz mumkin!",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        return

    if user_text == "🗑 Suhbatni tozalash":
        gemini_service.clear_history(user_id)
        await message.answer(
            "🧹 <b>Suhbat tarixi tozalandi!</b>\n\nYangi mavzuda savol berishingiz mumkin.",
            parse_mode="HTML"
        )
        return

    if user_text == "🤖 AI Chat (Gemini)":
        user_modes[user_id] = "ai_chat"
        await message.answer(
            "🤖 <b>Google Gemini AI Chat rejimiga xush kelibsiz!</b>\n\n"
            "Menga istalgan savolingizni yozing yoki ovozli xabar yuboring, barchasiga batafsil javob beraman. 💬\n\n"
            "💡 <i>Eslatma: Pinterest video havolasini yuborsangiz, bot darhol videoni yuklab beradi.</i>\n\n"
            "Rejimdan chiqish uchun <b>«🔙 Asosiy menyu»</b> tugmasini bosing.",
            reply_markup=get_ai_keyboard(),
            parse_mode="HTML"
        )
        return

    if user_text == "🎬 Pinterest Video Yuklash":
        await message.answer(
            "📌 <b>Pinterest Video Yuklash:</b>\n\n"
            "Menga shunchaki Pinterest'dagi video havolasini (link) yuboring.\n"
            "Misol: <code>https://pin.it/...</code> yoki <code>https://pinterest.com/pin/...</code>",
            parse_mode="HTML"
        )
        return

    if user_text in ["🎵 Musiqani aniqlash (MP3)", "/music"]:
        await message.answer(
            "🎵 <b>Videodan musiqa aniqlash va MP3 formatga o'tkazish:</b>\n\n"
            "1️⃣ <b>Pinterest havolasi:</b> Pinterest'dan istalgan video havolasini yuboring. Bot videoning o'zini ham, undagi qo'shiqni ham (Shazam orqali aniqlab) <b>MP3 formatda</b> taqdim etadi!\n\n"
            "2️⃣ <b>To'g'ridan-to'g'ri video:</b> Telegram orqali botga istalgan video yuboring yoki forward qiling. Bot videodagi musiqani Shazam orqali aniqlaydi va sizga MP3 audio formatda taqdim etadi! 🎧",
            parse_mode="HTML"
        )
        return

    if user_text == "ℹ️ Yordam":
        await help_handler(message)
        return

    # 7. Shaxsiy chatda AI Chat rejimida bo'lsa
    current_mode = user_modes.get(user_id, "default")
    if current_mode == "ai_chat":
        async with ChatActionSender(bot=bot, chat_id=message.chat.id, action=ChatAction.TYPING):
            reply = await gemini_service.ask(user_id, user_text, http_session)
            await send_split_message(message, reply)
        return

    # 8. Asosiy rejimda bo'lib, Pinterest havolasi ham bo'lmasa
    await message.reply(
        "ℹ️ <b>Pinterest havolasi topilmadi!</b>\n\n"
        "• 📌 Video va MP3 musiqa yuklash uchun Pinterest havolasini yuboring.\n"
        "• 📹 Yoki istalgan videoni botga yuborsangiz, undagi qo'shiqni MP3 qilib beraman.\n"
        "• 🤖 Gemini AI bilan suhbatlashish uchun esa <b>«🤖 AI Chat (Gemini)»</b> tugmasini bosing yoki <code>/ai savolingiz</code> deb yozing!",
        reply_markup=get_quick_ai_inline_kb(),
        parse_mode="HTML"
    )


# ==========================================
# TO'G'RIDAN-TO'G'RI YUBORILGAN VIDEOLARNI QAYTA ISHLASH (MP3 + SHAZAM)
# ==========================================

@dp.message(F.video | (F.document & F.document.mime_type.startswith("video/")))
async def direct_video_handler(message: types.Message):
    """
    Foydalanuvchi Telegram orqali to'g'ridan-to'g'ri video yuborganida,
    undagi musiqani aniqlab, MP3 audio formatida qaytaradi.
    """
    user_id = message.from_user.id if message.from_user else 0
    if not await is_subscribed(user_id):
        await send_subscription_prompt(message)
        return

    video_obj = message.video or message.document
    if not video_obj:
        return

    # Telegram Bot API get_file cheklovi (20 MB)
    if video_obj.file_size and video_obj.file_size > 20 * 1024 * 1024:
        await message.reply(
            "⚠️ <b>Video hajmi 20 MB dan katta!</b>\n\n"
            "Telegram botlari to'g'ridan-to'g'ri faqat <b>20 MB</b> gacha bo'lgan videolarni qabul qila oladi.\n"
            "Agar video Pinterest'da bo'lsa, uning havolasini yuborsangiz, bot istalgan hajmda yuklab beradi!",
            parse_mode="HTML"
        )
        return

    status_msg = await message.reply("⚡️ <b>Video qabul qilindi. Musiqa aniqlanmoqda va MP3 ga o'tkazilmoqda...</b>", parse_mode="HTML")
    video_temp_path = None
    mp3_temp_path = None

    try:
        async with ChatActionSender(bot=bot, chat_id=message.chat.id, action=ChatAction.RECORD_VOICE):
            bot_info = await bot.get_me()
            bot_username = bot_info.username or "PinterestBot"

            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            unique_id = uuid.uuid4().hex[:8]
            video_temp_path = os.path.join(DOWNLOADS_DIR, f"direct_vid_{unique_id}.mp4")

            file_info = await bot.get_file(video_obj.file_id)
            await bot.download_file(file_info.file_path, video_temp_path)

            audio_res = await process_video_audio(
                video_temp_path,
                DOWNLOADS_DIR,
                fallback_title="Telegram Video Audio",
                fallback_artist="Audio"
            )

            if not audio_res.get("has_audio") or not audio_res.get("mp3_path"):
                await status_msg.edit_text("⚠️ <b>Ushbu videoda audio trek topilmadi (ovozsiz video).</b>", parse_mode="HTML")
                return

            mp3_temp_path = audio_res["mp3_path"]
            if audio_res.get("matched"):
                caption = (
                    f"🎵 <b>{audio_res['title']} — {audio_res['artist']}</b>\n"
                )
                if audio_res.get("genre"):
                    caption += f"🏷 <b>Janr:</b> {audio_res['genre']}\n"
                caption += (
                    f"🔍 <i>Shazam orqali aniqlandi</i>\n\n"
                    f"📥 @{bot_username} orqali olindi."
                )
            else:
                caption = (
                    f"🎵 <b>Audio trek (MP3 formatda)</b>\n"
                    f"ℹ️ <i>Videodan ajratib olingan audio</i>\n\n"
                    f"📥 @{bot_username} orqali olindi."
                )

            audio_fs = FSInputFile(mp3_temp_path, filename=f"{audio_res['title'][:50]}.mp3")
            await message.reply_audio(
                audio=audio_fs,
                title=audio_res["title"],
                performer=audio_res["artist"],
                duration=audio_res.get("duration"),
                caption=caption,
                parse_mode="HTML"
            )
            try:
                await status_msg.delete()
            except Exception:
                pass

    except Exception as e:
        logger.exception("Videoni qayta ishlashda xatolik:")
        await status_msg.edit_text(f"⚠️ <b>Xatolik yuz berdi:</b> {str(e)}", parse_mode="HTML")
    finally:
        if video_temp_path and os.path.exists(video_temp_path):
            cleanup_file(video_temp_path)
        if mp3_temp_path and os.path.exists(mp3_temp_path):
            cleanup_file(mp3_temp_path)


# ==========================================
# PINTEREST YUKLASH JARAYONI (VIDEO + MP3 AUDIO)
# ==========================================

async def process_pinterest_download(message: types.Message, pinterest_url: str):
    """Pinterest videosini yuklash va musiqasini MP3 formatda aniqlab berish jarayoni."""
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    status_msg = await message.reply("⚡️ <b>Video tahlil qilinmoqda...</b>", parse_mode="HTML")
    temp_files_to_clean = []
    t_start = time.time()

    try:
        async with ChatActionSender(bot=bot, chat_id=message.chat.id, action=ChatAction.UPLOAD_VIDEO):
            bot_info = await bot.get_me()
            bot_username = bot_info.username or "PinterestBot"

            video_filepath = None
            raw_title = "Pinterest Video"
            video_duration = None
            video_width = None
            video_height = None

            # 1-BOSQICH: To'g'ridan-to'g'ri tayyor MP4 video oqimini qidiramiz
            video_info = await extract_fast_direct_video(pinterest_url, http_session)

            if video_info and video_info.get("direct_url"):
                logger.info(f"MP4 topildi ({time.time() - t_start:.2f}s): {video_info['direct_url']}")
                direct_url = video_info["direct_url"]
                raw_title = video_info.get("title") or "Pinterest Video"
                video_duration = video_info.get("duration")
                video_width = video_info.get("width")
                video_height = video_info.get("height")

                # To'g'ridan-to'g'ri faylni diskka yuklaymiz (audio ajratish uchun)
                downloaded_path = await download_direct_mp4_file(direct_url, http_session, DOWNLOADS_DIR)
                if downloaded_path:
                    video_filepath = downloaded_path
                    temp_files_to_clean.append(downloaded_path)

            # 2-BOSQICH: Agar to'g'ridan-to'g'ri MP4 topilmasa yoki yuklanmasa, yt-dlp ishga tushadi
            if not video_filepath:
                logger.info("To'g'ridan-to'g'ri MP4 topilmadi yoki yuklanmadi. yt-dlp dvigateliga murojaat qilinmoqda...")
                ytdlp_data = await download_with_ytdlp_fast(pinterest_url, DOWNLOADS_DIR)
                video_filepath = ytdlp_data["filepath"]
                temp_files_to_clean.append(video_filepath)
                raw_title = ytdlp_data.get("title") or raw_title
                video_duration = ytdlp_data.get("duration") or video_duration
                video_width = ytdlp_data.get("width") or video_width
                video_height = ytdlp_data.get("height") or video_height

            if len(raw_title) > 200:
                clean_title = raw_title[:197] + "..."
            else:
                clean_title = raw_title

            caption_video = (
                f"🎬 <b>{clean_title}</b>\n\n"
                f"📥 @{bot_username} orqali yuklab olindi."
            )

            # 1. MP4 Videoni yuborish va Audioni ajratishni BIR VAQTDA (PARALLEL) bajaramiz!
            fs_video = FSInputFile(video_filepath, filename="pinterest_video.mp4")

            async def _send_video():
                return await message.reply_video(
                    video=fs_video,
                    caption=caption_video,
                    parse_mode="HTML",
                    supports_streaming=True,
                    duration=video_duration,
                    width=video_width,
                    height=video_height
                )

            async def _process_audio():
                return await process_video_audio(
                    video_path=video_filepath,
                    output_dir=DOWNLOADS_DIR,
                    fallback_title=clean_title,
                    fallback_artist="Pinterest"
                )

            # Ikkala vazifani bir vaqtda parallel bajaramiz!
            video_res, audio_data = await asyncio.gather(
                _send_video(),
                _process_audio(),
                return_exceptions=True
            )

            if isinstance(video_res, Exception):
                logger.error(f"Videoni yuborishda xatolik: {video_res}")
            else:
                logger.info(f"Video yuborildi ({time.time() - t_start:.2f}s)")

            # Audio allaqachon parallel rejimda tayyor bo'lgan! Darhol MP3 jo'natamiz:
            if not isinstance(audio_data, Exception) and audio_data.get("has_audio") and audio_data.get("mp3_path"):
                mp3_file = audio_data["mp3_path"]
                temp_files_to_clean.append(mp3_file)

                if audio_data.get("matched"):
                    caption_audio = (
                        f"🎵 <b>{audio_data['title']} — {audio_data['artist']}</b>\n"
                    )
                    if audio_data.get("genre"):
                        caption_audio += f"🏷 <b>Janr:</b> {audio_data['genre']}\n"
                    caption_audio += (
                        f"🔍 <i>Shazam orqali aniqlandi</i>\n\n"
                        f"📥 @{bot_username} orqali yuklab olindi."
                    )
                else:
                    caption_audio = (
                        f"🎵 <b>Audio trek (MP3 formatda)</b>\n"
                        f"🎬 {clean_title}\n\n"
                        f"📥 @{bot_username} orqali yuklab olindi."
                    )

                audio_fs = FSInputFile(
                    mp3_file,
                    filename=f"{audio_data['title'][:40]}.mp3"
                )
                await message.reply_audio(
                    audio=audio_fs,
                    title=audio_data["title"],
                    performer=audio_data["artist"],
                    duration=audio_data.get("duration"),
                    caption=caption_audio,
                    parse_mode="HTML"
                )
                logger.info(f"MP3 audio yuborildi ({time.time() - t_start:.2f}s)")

            try:
                await status_msg.delete()
            except Exception:
                pass


    except ValueError as ve:
        await status_msg.edit_text(
            f"❌ <b>Xatolik yuz berdi:</b>\n{str(ve)}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("Videoni yuklashda xatolik:")
        await status_msg.edit_text(
            "⚠️ <b>Videoni yuklab bo'lmadi!</b>\n"
            "Havola to'g'riligini va unda aynan video borligini tekshirib ko'ring (rasmlar yuklanmaydi).",
            parse_mode="HTML"
        )
    finally:
        for f in temp_files_to_clean:
            cleanup_file(f)



async def main():
    """Botni ishga tushirish asosiy funksiyasi."""
    global http_session
    http_session = aiohttp.ClientSession()

    logger.info("Bot ishga tushmoqda...")

    # Telegram menyusi uchun buyruqlarni o'rnatamiz
    commands = [
        BotCommand(command="start", description="Botni ishga tushirish va menyu"),
        BotCommand(command="music", description="Musiqani aniqlash (Shazam + MP3)"),
        BotCommand(command="ai", description="Gemini AI Chat / Savol berish"),
        BotCommand(command="clear", description="AI suhbat tarixini tozalash"),
        BotCommand(command="help", description="Qo'llanma va yordam"),
        BotCommand(command="exit", description="Asosiy menyuga qaytish"),
    ]
    await bot.set_my_commands(commands)

    # Eski kutilayotgan yangilanishlarni tozalaymiz
    await bot.delete_webhook(drop_pending_updates=True)

    bot_info = await bot.get_me()
    print("=" * 60, flush=True)
    print(f"Bot muvaffaqiyatli ishga tushdi: @{bot_info.username}", flush=True)
    print("Pinterest MP4 Video + MP3 Musiqa (Shazam) + Google Gemini AI Chat!", flush=True)
    if REQUIRED_CHANNEL:
        print(f"Majburiy obuna kanali: {REQUIRED_CHANNEL}", flush=True)
    print("Guruhlarda chaqirilganda javob berish faollashtirildi!", flush=True)
    print("=" * 60, flush=True)

    try:
        await dp.start_polling(bot)
    finally:
        if http_session and not http_session.closed:
            await http_session.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
