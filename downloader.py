import os
import re
import json
import uuid
import asyncio
import logging
import aiohttp
import aiofiles
import yt_dlp
import imageio_ffmpeg

logger = logging.getLogger(__name__)

# Pinterest havolalarini aniqlash uchun regex
PINTEREST_REGEX = re.compile(
    r'(https?://(?:[a-zA-Z0-9_-]+\.)?pinterest\.[a-z.]+/pin/[0-9a-zA-Z_-]+/?|https?://pin\.it/[a-zA-Z0-9_-]+)',
    re.IGNORECASE
)

STANDARD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

def extract_pinterest_url(text: str) -> str | None:
    """Matn ichidan Pinterest havolasini tezkor ajratib oladi."""
    if not text:
        return None
    match = PINTEREST_REGEX.search(text)
    if match:
        return match.group(1).strip()
    return None

def rank_mp4(url: str) -> int:
    """
    MP4 havolalarini sifati va mosligi bo'yicha baholaydi.
    expMp4 va /mc/ universal H.264 kodekda bo'lib, barcha qurilmalarda tezkor va konvertatsiyasiz ochiladi.
    """
    score = 0
    u_lower = url.lower()

    if "expmp4" in u_lower or "/mc/" in u_lower:
        score += 100
    elif "h265" in u_lower or "hevc" in u_lower:
        # H.265 ba'zi tizimlarda sekin ochiladi, shuning uchun H.264 dan pastroq
        score += 20

    if "1080" in u_lower:
        score += 50
    elif "720" in u_lower:
        score += 40
    elif "540" in u_lower or "480" in u_lower:
        score += 20
    elif "360" in u_lower or "240" in u_lower:
        score += 10

    return score

async def extract_fast_direct_video(url: str, session: aiohttp.ClientSession) -> dict | None:
    """
    Pinterest sahifasidan to'g'ridan-to'g'ri MP4 video manzilini (CDN) va metama'lumotlarni
    1-2 soniya ichida ajratib oladi. Barcha redirectlarni bitta so'rovda hal qiladi.
    HECH QANDAY format konvertatsiyasiga HOJAT YO'Q, chunki bu tayyor H.264 MP4!
    """
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        # Barcha redirect zanjirlarini (pin.it -> api.pinterest.com -> at.pinterest.com/pin/...) oxirigacha oladi
        async with session.get(url, headers=STANDARD_HEADERS, allow_redirects=True, timeout=timeout) as resp:
            if resp.status != 200:
                logger.warning(f"Sahifa status kodi: {resp.status}")
                return None
            html = await resp.text()
            final_url = str(resp.url)
    except Exception as e:
        logger.warning(f"Sahifani yuklashda xatolik: {e}")
        return None

    # Sarlavhani (title) ajratib olish
    title_m = re.search(r'<title>([^<]+)</title>', html)
    title = "Pinterest Video"
    if title_m:
        raw_t = title_m.group(1).replace(" | Pinterest", "").replace("Pinterest", "").strip()
        if raw_t:
            title = raw_t

    # 1. HTML ichidagi barcha to'g'ridan-to'g'ri MP4 havolalarini topamiz
    all_mp4s = set(re.findall(r'https?://(?:v1|v)\.pinimg\.com/videos/[^\s"\'<>]+\.mp4', html))

    # 2. Agar HTML da topilmasa, __PWS_DATA__ JSON ichidan ham qidiramiz
    if not all_mp4s:
        pws_match = re.search(r'<script id="__PWS_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if pws_match:
            try:
                data = json.loads(pws_match.group(1))
                def scan_dict(d):
                    if isinstance(d, dict):
                        for k, v in d.items():
                            if isinstance(v, str) and v.endswith(".mp4") and "pinimg.com/videos" in v:
                                all_mp4s.add(v)
                            else:
                                scan_dict(v)
                    elif isinstance(d, list):
                        for item in d:
                            scan_dict(item)
                scan_dict(data)
            except Exception as e:
                logger.warning(f"JSON skanerlashda xato: {e}")

    if not all_mp4s:
        return None

    # Eng yaxshi sifatdagi H.264 MP4 faylni saralaymiz
    sorted_mp4s = sorted(all_mp4s, key=rank_mp4, reverse=True)
    best_mp4 = sorted_mp4s[0]
    logger.info(f"Topilgan eng maqbul MP4: {best_mp4}")

    # Optimal o'lchamlarni belgilaymiz
    width, height = 720, 1280
    if "1080" in best_mp4:
        width, height = 1080, 1920
    elif "720" in best_mp4:
        width, height = 720, 1280
    elif "540" in best_mp4 or "480" in best_mp4:
        width, height = 480, 854

    return {
        "direct_url": best_mp4,
        "title": title,
        "width": width,
        "height": height,
        "duration": None,
        "resolved_url": final_url
    }

async def download_direct_mp4_file(direct_url: str, session: aiohttp.ClientSession, output_dir: str = "downloads") -> str:
    """
    To'g'ridan-to'g'ri MP4 oqimini maksimal tezlikda yuklab oladi.
    Fayl allaqachon tayyor MP4 bo'lgani sababli konvertatsiya umuman qilinmaydi!
    """
    os.makedirs(output_dir, exist_ok=True)
    task_id = str(uuid.uuid4())
    dest_path = os.path.join(output_dir, f"{task_id}.mp4")

    timeout = aiohttp.ClientTimeout(total=30)
    async with session.get(direct_url, headers=STANDARD_HEADERS, timeout=timeout) as resp:
        if resp.status != 200:
            raise ValueError(f"Videoni yuklab bo'lmadi (HTTP {resp.status})")

        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > 50 * 1024 * 1024:
            raise ValueError("Video hajmi 50MB dan katta bo'lgani sababli Telegram orqali yuborib bo'lmaydi.")

        content_bytes = await resp.read()
        async with aiofiles.open(dest_path, "wb") as f:
            await f.write(content_bytes)

    return dest_path

def download_with_ytdlp_fast(url: str, output_dir: str = "downloads") -> dict:
    """
    Zaxira variant: Faqat to'g'ridan-to'g'ri MP4 topilmagan hollarda ishga tushadi.
    Maksimal tezlik uchun 'best[ext=mp4]/best' tanlanadi.
    """
    os.makedirs(output_dir, exist_ok=True)
    task_id = str(uuid.uuid4())
    outtmpl = os.path.join(output_dir, f"{task_id}.%(ext)s")

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_exe = None

    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'concurrent_fragment_downloads': 8,
        'max_filesize': 50 * 1024 * 1024,
        'http_headers': STANDARD_HEADERS
    }
    if ffmpeg_exe and os.path.exists(ffmpeg_exe):
        ydl_opts['ffmpeg_location'] = ffmpeg_exe

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise ValueError("Video ma'lumotlari topilmadi.")

        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)

        for ext in ['.mp4', '.mkv', '.webm']:
            cand = base + ext
            if os.path.exists(cand):
                filename = cand
                break

        if not os.path.exists(filename):
            raise FileNotFoundError(f"Yuklangan video fayli topilmadi: {filename}")

        return {
            'file_path': filename,
            'title': info.get('title') or info.get('description') or "Pinterest Video",
            'duration': info.get('duration'),
            'width': info.get('width'),
            'height': info.get('height'),
            'thumbnail': info.get('thumbnail')
        }

def cleanup_file(file_path: str):
    """Vaqtinchalik yuklangan faylni xavfsiz o'chiradi."""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Vaqtinchalik fayl o'chirildi: {file_path}")
    except Exception as e:
        logger.warning(f"Faylni o'chirishda xatolik ({file_path}): {e}")
