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
    Video fayldan yuqori sifatli MP3 audio ajratib oladi va ID3 teglarini o'rnatadi.
    Agar videoda ovoz yo'q bo'lsa (ovozsiz video/GIF), None qaytaradi.
    Qaytaradi: (mp3_path, duration_seconds)
    """
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return None, 0

    os.makedirs(output_dir, exist_ok=True)
    unique_id = uuid.uuid4().hex[:8]
    mp3_path = os.path.join(output_dir, f"audio_{unique_id}.mp3")

    # Toza sarlavha va ijrochi
    clean_title = (title or "Pinterest Audio").replace('"', '').strip()[:80]
    clean_artist = (artist or "Pinterest").replace('"', '').strip()[:60]

    cmd = [
        _ffmpeg_exe,
        "-y",
        "-i", video_path,
        "-vn",                      # Video trekni o'chirib, faqat audioni oladi
        "-c:a", "libmp3lame",       # Yuqori sifatli MP3 kodlovchi
        "-q:a", "2",                # VBR ~190 kbps (juda yuqori sifat va ixcham hajm)
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

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "ignore")
            # Agar videoda audio oqimi bo'lmasa
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


async def recognize_song(audio_path: str, timeout: float = 6.0) -> dict:
    """
    Shazam algoritmi orqali audio fayldagi qo'shiqni, ijrochisini va janrini aniqlaydi.
    Hech qanday holatda xatolik bilan to'xtamaydi, xavfsiz timeout bilan ishlaydi.
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
        # Shazamio orqali trekni qidiramiz (timeout bilan)
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
            logger.info("Shazam mos keluvchi qo'shiq topmadi (fon ovozi yoki gaplashuv).")

    except asyncio.TimeoutError:
        logger.warning(f"Shazam qidiruvi {timeout} soniyada vaqt tugashi sababli to'xtatildi.")
    except Exception as e:
        logger.warning(f"Shazam orqali qo'shiqni aniqlashda xatolik: {e}")

    return result


async def process_video_audio(
    video_path: str,
    output_dir: str = "downloads",
    fallback_title: str = "Pinterest Audio",
    fallback_artist: str = "Pinterest"
) -> dict:
    """
    Videodan MP3 audioni ajratadi va qo'shiqni aniqlaydi.
    Natija:
    {
        "has_audio": bool,
        "mp3_path": str | None,
        "duration": int,
        "matched": bool,
        "title": str,
        "artist": str,
        "genre": str | None,
        "shazam_url": str | None,
        "cover_url": str | None
    }
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

    # Qo'shiqni Shazam orqali aniqlaymiz
    rec = await recognize_song(mp3_path, timeout=6.0)

    final_title = rec["title"] if rec["matched"] and rec["title"] else fallback_title
    final_artist = rec["artist"] if rec["matched"] and rec["artist"] else fallback_artist

    # Agar qo'shiq aniqlangan bo'lsa, MP3 metadata'sini rasmiy qo'shiq nomi bilan yangilaymiz
    if rec["matched"] and rec["title"]:
        try:
            temp_tagged = mp3_path + ".tagged.mp3"
            tag_cmd = [
                _ffmpeg_exe,
                "-y",
                "-i", mp3_path,
                "-c", "copy",
                "-metadata", f"title={final_title.replace('\"', '')}",
                "-metadata", f"artist={final_artist.replace('\"', '')}",
                temp_tagged
            ]
            tproc = await asyncio.create_subprocess_exec(
                *tag_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await tproc.communicate()
            if os.path.exists(temp_tagged) and os.path.getsize(temp_tagged) > 0:
                os.replace(temp_tagged, mp3_path)
        except Exception as te:
            logger.debug(f"Metadata yangilashda xatolik: {te}")

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
