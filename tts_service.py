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

# Emojilar va maxsus piktogrammalarni tozalash regexi
EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf\u2300-\u23ff\u2b50\u200d\ufe0f]",
    flags=re.UNICODE
)

CYRILLIC_TO_LATIN = {
    'А': 'A', 'а': 'a', 'Б': 'B', 'б': 'b', 'В': 'V', 'в': 'v', 'Г': 'G', 'г': 'g',
    'Д': 'D', 'д': 'd', 'Е': 'E', 'е': 'e', 'Ё': 'Yo', 'ё': 'yo', 'Ж': 'J', 'ж': 'j',
    'З': 'Z', 'з': 'z', 'И': 'I', 'и': 'i', 'Й': 'Y', 'й': 'y', 'К': 'K', 'к': 'k',
    'Л': 'L', 'l': 'l', 'М': 'M', 'м': 'm', 'Н': 'N', 'н': 'n', 'О': 'O', 'о': 'o',
    'П': 'P', 'п': 'p', 'Р': 'R', 'р': 'r', 'С': 'S', 'с': 's', 'Т': 'T', 't': 't',
    'У': 'U', 'у': 'u', 'Ф': 'F', 'ф': 'f', 'Х': 'X', 'х': 'x', 'Ц': 'Ts', 'ц': 'ts',
    'Ч': 'Ch', 'ч': 'ch', 'Ш': 'Sh', 'ш': 'sh', 'Щ': 'Sh', 'щ': 'sh', 'Ъ': "'", 'ъ': "'",
    'Ь': '', 'ь': '', 'Э': 'E', 'э': 'e', 'Ю': 'Yu', 'ю': 'yu', 'Я': 'Ya', 'я': 'ya',
    'Ў': "O'", 'ў': "o'", 'Қ': 'Q', 'қ': 'q', 'Ғ': "G'", 'ғ': "g'", 'Ҳ': 'H', 'ҳ': 'h'
}

def clean_text_for_tts(text: str) -> str:
    """
    Matndan emojilarni, Markdown belgilarini va keraksiz belgilarni tozalaydi.
    Kirill yozuvidagi matnni to'liq ravon lotinga o'giradi (uz-UZ-MadinaNeural uchun).
    O'zbek tilidagi tutuq belgilarini (o', g') to'g'ri shaklga keltiradi.
    """
    if not text:
        return ""

    # 1. Havolalarni tozalash: [matn](url) -> matn
    cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # 2. URL larni olib tashlash
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    # 3. HTML teglarni olib tashlash
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    # 4. Barcha emojilarni olib tashlash (chunki TTS ularni buzib o'qiydi)
    cleaned = EMOJI_PATTERN.sub('', cleaned)
    # 5. Markdown qalin, qiya, kod belgilarini olib tashlash
    cleaned = re.sub(r'[*_`~#|]', '', cleaned)
    # 6. Ro'yxat chiziqchalarini to'g'irlash
    cleaned = re.sub(r'^\s*[-•–—]\s*', '', cleaned, flags=re.MULTILINE)
    # 7. Tutuq belgilarini bir xil standartga keltirish
    cleaned = re.sub(r"[`‘ʼ’´]", "'", cleaned)
    # 8. Kirill belgilarini lotinga o'giramiz
    cleaned = "".join(CYRILLIC_TO_LATIN.get(char, char) for char in cleaned)
    # 9. Ketma-ket bo'shliqlarni bittaga keltirish
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned


async def generate_voice_message(text: str, output_dir: str = "downloads", voice: str = DEFAULT_VOICE) -> str | None:
    """
    Matnni Microsoft Edge TTS orqali ravon, sof va tabiiy ovozga aylantiradi
    va Telegram uchun mos OGG (Opus) formatida saqlaydi.
    Nutq tezligi +10% bilan o'rnatilgan bo'lib, jonli va qotmasdan gapiradi.
    """
    cleaned_text = clean_text_for_tts(text)
    if not cleaned_text:
        return None

    # Ovoz juda uzun bo'lib ketmasligi uchun (masalan 1200 belgidan ko'p bo'lsa) dastlabki qismini olamiz
    if len(cleaned_text) > 1000:
        cleaned_text = cleaned_text[:997] + "..."

    os.makedirs(output_dir, exist_ok=True)
    unique_id = uuid.uuid4().hex[:8]
    temp_mp3 = os.path.join(output_dir, f"tts_{unique_id}.mp3")
    final_ogg = os.path.join(output_dir, f"voice_{unique_id}.ogg")

    try:
        # 1. Edge-TTS orqali MP3 audio yaratamiz (+10% nutq tezligi bilan so'zlashadi)
        communicate = edge_tts.Communicate(cleaned_text, voice, rate="+10%")
        await communicate.save(temp_mp3)

        if not os.path.exists(temp_mp3) or os.path.getsize(temp_mp3) == 0:
            logger.error("TTS MP3 fayli yaratilmadi yoki bo'sh.")
            return None

        # 2. FFmpeg orqali Telegram voice uchun OGG (Opus) formatiga tezkor konvertatsiya qilamiz
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-y",
            "-threads", "0",
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
