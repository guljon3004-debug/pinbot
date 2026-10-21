import os
import re
import uuid
import asyncio
import logging
import warnings
import subprocess
import imageio_ffmpeg

# pydub warningini tozalaymiz
warnings.filterwarnings("ignore", category=RuntimeWarning, module="pydub")
from shazamio import Shazam

logger = logging.getLogger(__name__)

# FFmpeg yo'lini muhitga qo'shamiz
_ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
_ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
if _ffmpeg_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

# Global Shazam mijozi
shazam_client = Shazam()


def get_media_duration(file_path: str) -> int:
    """FFmpeg orqali audio/video davomiyligini sekundlarda hisoblaydi."""
    try:
        cmd = [_ffmpeg_exe, "-i", file_path]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr)
        if m:
            h, mn, s = m.groups()
            return int(h) * 3600 + int(mn) * 60 + int(float(s))
    except Exception as e:
        logger.debug(f"Davomiylikni aniqlashda xatolik: {e}")
    return 0


async def extract_mp3_from_video(
    video_path: str,
    output_dir: str = "downloads",
    title: str = "Pinterest Audio",
    artist: str = "Pinterest"
) -> tuple[str | None, int]:
    """
    Video fayldan maksimal tezlikda MP3 audio ajratib oladi va ID3 teglarini o'rnatadi.
    Agar videoda ovoz yo'q bo'lsa (ovozsiz video/GIF), None qaytaradi.
    Qaytaradi: (mp3_path, duration_seconds)
    """
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return None, 0

    os.makedirs(output_dir, exist_ok=True)
    unique_id = uuid.uuid4().hex[:8]
    mp3_path = os.path.join(output_dir, f"audio_{unique_id}.mp3")

    clean_title = (title or "Pinterest Audio").replace('"', '').strip()[:80]
    clean_artist = (artist or "Pinterest").replace('"', '').strip()[:60]

    # Maksimal tezlik uchun -threads 0 va optimallashtirilgan parametrlar
    cmd = [
        _ffmpeg_exe,
        "-y",
        "-threads", "0",
        "-i", video_path,
        "-vn",                      # Faqat audio trek
        "-c:a", "libmp3lame",       # MP3
        "-b:a", "192k",             # Yuqori tezlikdagi 192kbps MP3
        "-metadata", f"title={clean_title}",
        "-metadata", f"artist={clean_artist}",
        mp3_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        err_text = stderr.decode("utf-8", "ignore")

        if proc.returncode != 0:
            if "does not contain any stream" in err_text or "Output file is empty" in err_text:
                logger.info("Videoda audio oqimi topilmadi (ovozsiz video).")
            else:
                logger.warning(f"FFmpeg MP3 ga o'girishda xatolik: {err_text[:200]}")
            if os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except Exception:
                    pass
            return None, 0

        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
            return None, 0

        # Davomiylikni bevosita FFmpeg stderr logidan tezkor ajratib olamiz (ikkinchi jarayon ochmasdan)
        duration = 0
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err_text)
        if m:
            h, mn, s = m.groups()
            duration = int(h) * 3600 + int(mn) * 60 + int(float(s))
        else:
            duration = get_media_duration(mp3_path)

        return mp3_path, duration

    except Exception as e:
        logger.exception(f"Videodan MP3 ajratishda xatolik: {e}")
        if os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except Exception:
                pass
        return None, 0


async def recognize_song(audio_path: str, timeout: float = 3.5) -> dict:
    """
    Shazam algoritmi orqali audio fayldagi qo'shiqni, ijrochisini va janrini tezkor aniqlaydi.
    Xavfsiz timeout (3.5s) bilan ishlaydi, hech qachon botni qotirib qo'ymaydi.
    """
    result = {
        "matched": False,
        "title": None,
        "artist": None,
        "genre": None,
        "shazam_url": None,
        "cover_url": None
    }

    if not audio_path or not os.path.exists(audio_path):
        return result

    try:
        shazam_data = await asyncio.wait_for(
            shazam_client.recognize(audio_path),
            timeout=timeout
        )

        track = shazam_data.get("track")
        if track:
            result["matched"] = True
            result["title"] = track.get("title")
            result["artist"] = track.get("subtitle")
            genres = track.get("genres", {})
            result["genre"] = genres.get("primary")
            share = track.get("share", {})
            result["shazam_url"] = share.get("href")
            images = track.get("images", {})
            result["cover_url"] = images.get("coverart") or images.get("coverarthq")

            logger.info(f"Qo'shiq aniqlandi: {result['title']} - {result['artist']}")
        else:
            logger.info("Shazam qo'shiq topmadi (fon ovozi yoki so'zlashuv).")

    except asyncio.TimeoutError:
        logger.info(f"Shazam qidiruvi {timeout} soniyada vaqt tugashi bilan o'tkazib yuborildi (MP3 tezkor yuboriladi).")
    except Exception as e:
        logger.debug(f"Shazam orqali qo'shiqni aniqlashda xatolik: {e}")

    return result


async def process_video_audio(
    video_path: str,
    output_dir: str = "downloads",
    fallback_title: str = "Pinterest Audio",
    fallback_artist: str = "Pinterest"
) -> dict:
    """
    Videodan MP3 audioni tezkor ajratadi va qo'shiqni aniqlaydi.
    1-bosqich: FFmpeg yuqori tezlikda MP3 ajratadi (~0.2s)
    2-bosqich: Shazam tezkor aniqlaydi (~0.8s)
    """
    mp3_path, duration = await extract_mp3_from_video(
        video_path=video_path,
        output_dir=output_dir,
        title=fallback_title,
        artist=fallback_artist
    )

    if not mp3_path:
        return {
            "has_audio": False,
            "mp3_path": None,
            "duration": 0,
            "matched": False,
            "title": fallback_title,
            "artist": fallback_artist,
            "genre": None,
            "shazam_url": None,
            "cover_url": None
        }

    # Qo'shiqni Shazam orqali tezkor aniqlaymiz (maksimal 3.5 soniya)
    rec = await recognize_song(mp3_path, timeout=3.5)

    final_title = rec["title"] if rec["matched"] and rec["title"] else fallback_title
    final_artist = rec["artist"] if rec["matched"] and rec["artist"] else fallback_artist

    return {
        "has_audio": True,
        "mp3_path": mp3_path,
        "duration": duration,
        "matched": rec["matched"],
        "title": final_title,
        "artist": final_artist,
        "genre": rec["genre"],
        "shazam_url": rec["shazam_url"],
        "cover_url": rec["cover_url"]
    }
