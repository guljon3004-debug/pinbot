import os
import re
import uuid
import asyncio
import logging
import subprocess
import imageio_ffmpeg
import edge_tts

logger = logging.getLogger(__name__)

# Standart ovoz (O'zbek tili uchun eng tabiiy va yoqimli ayol ovozi)
DEFAULT_VOICE = os.getenv("TTS_VOICE", "uz-UZ-MadinaNeural")

CYRILLIC_TO_LATIN = {
    'А': 'A', 'а': 'a', 'Б': 'B', 'б': 'b', 'В': 'V', 'в': 'v', 'Г': 'G', 'г': 'g',
    'Д': 'D', 'д': 'd', 'Е': 'E', 'е': 'e', 'Ё': 'Yo', 'ё': 'yo', 'Ж': 'J', 'ж': 'j',
    'З': 'Z', 'з': 'z', 'И': 'I', 'и': 'i', 'Й': 'Y', 'й': 'y', 'К': 'K', 'к': 'k',
    'Л': 'L', 'l': 'l', 'М': 'M', 'м': 'm', 'Н': 'N', 'н': 'n', 'О': 'O', 'о': 'o',
    'П': 'P', 'п': 'p', 'Р': 'R', 'р': 'r', 'С': 'S', 'с': 's', 'Т': 'T', 'т': 't',
    'У': 'U', 'у': 'u', 'Ф': 'F', 'ф': 'f', 'Х': 'X', 'х': 'x', 'Ц': 'Ts', 'ц': 'ts',
    'Ч': 'Ch', 'ч': 'ch', 'Ш': 'Sh', 'ш': 'sh', 'Щ': 'Sh', 'щ': 'sh', 'Ъ': "'", 'ъ': "'",
    'Ь': '', 'ь': '', 'Э': 'E', 'э': 'e', 'Ю': 'Yu', 'ю': 'yu', 'Я': 'Ya', 'я': 'ya',
    'Ў': "O'", 'ў': "o'", 'Қ': 'Q', 'қ': 'q', 'Ғ': "G'", 'ғ': "g'", 'Ҳ': 'H', 'ҳ': 'h'
}

def clean_text_for_tts(text: str) -> str:
    """
    Matndan Markdown belgilarini, keraksiz belgilarni va havolalarni
    ovozli o'qishga qulay qilib tozalaydi.
    Kirill yozuvidagi matnni lotinga o'giradi (chunki uz-UZ-MadinaNeural faqat lotinni qabul qiladi).
    """
    if not text:
        return ""

    # Havolalarni tozalash: [matn](url) -> matn
    cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # URL larni olib tashlash
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    # HTML teglarni olib tashlash
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    # Markdown qalin, qiya, kod belgilarini olib tashlash
    cleaned = re.sub(r'[*_`~#]', '', cleaned)
    # Ro'yxat chiziqchalarini to'g'irlash
    cleaned = re.sub(r'^\s*[-•]\s*', '', cleaned, flags=re.MULTILINE)
    # Kirill belgilarini lotinga o'giramiz
    cleaned = "".join(CYRILLIC_TO_LATIN.get(char, char) for char in cleaned)
    # Ketma-ket bo'shliqlarni bittaga keltirish
    cleaned = re.sub(r'\n+', '\n', cleaned).strip()

    return cleaned


async def generate_voice_message(text: str, output_dir: str = "downloads", voice: str = DEFAULT_VOICE) -> str | None:
    """
    Matnni Microsoft Edge TTS orqali tabiiy ovozga aylantiradi
    va Telegram uchun mos OGG (Opus) formatida saqlaydi.
    Hosil bo'lgan .ogg fayl yo'lini qaytaradi.
    """
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        return None

    os.makedirs(output_dir, exist_ok=True)
    unique_id = uuid.uuid4().hex[:8]
    temp_mp3 = os.path.join(output_dir, f"tts_{unique_id}.mp3")
    final_ogg = os.path.join(output_dir, f"voice_{unique_id}.ogg")

    try:
        # 1. Edge-TTS orqali MP3 audio yaratamiz
        communicate = edge_tts.Communicate(cleaned_text, voice)
        await communicate.save(temp_mp3)

        if not os.path.exists(temp_mp3) or os.path.getsize(temp_mp3) == 0:
            logger.error("TTS MP3 fayli yaratilmadi yoki bo'sh.")
            return None

        # 2. FFmpeg orqali Telegram voice uchun OGG (Opus) formatiga konvertatsiya qilamiz
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", temp_mp3,
            "-c:a", "libopus",
            "-b:a", "32k",
            "-vbr", "on",
            final_ogg
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(f"FFmpeg OGG ga o'gira olmadi ({stderr.decode('utf-8', 'ignore')}), MP3 qaytariladi.")
            return temp_mp3

        # Vaqtinchalik MP3 ni o'chiramiz
        if os.path.exists(temp_mp3):
            try:
                os.remove(temp_mp3)
            except Exception:
                pass

        return final_ogg

    except Exception as e:
        logger.exception("Ovoz yaratishda (TTS) xatolik:")
        if os.path.exists(temp_mp3):
            try:
                os.remove(temp_mp3)
            except Exception:
                pass
        return None
