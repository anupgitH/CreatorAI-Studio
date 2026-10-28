import os, subprocess, uuid
from pathlib import Path
from gtts import gTTS
from PIL import Image, ImageOps, ImageDraw
from .config import settings

MEDIA_ROOT = Path(settings.media_dir).resolve()
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

class MediaError(Exception):
    pass

def safe_name(name: str) -> str:
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in name)[:100] or 'media'

def make_audio(text: str, lang: str = 'en') -> Path:
    if not text.strip():
        raise MediaError('Please enter a script before generating audio.')
    path = MEDIA_ROOT / f"voice_{uuid.uuid4().hex}.mp3"
    try:
        gTTS(text=text[:5000], lang=lang).save(str(path))
    except Exception as exc:
        raise MediaError(f"Text-to-speech failed. Check your internet connection and language code. Details: {exc}") from exc
    return path

def make_video(image_paths: list[Path], script: str, audio_path: Path, seconds_per_scene: int = 4) -> Path:
    if not image_paths:
        raise MediaError('Upload at least one image to create a video.')
    if not script.strip():
        raise MediaError('Please enter a script before creating a video.')
    ffmpeg = os.environ.get('FFMPEG_PATH', 'ffmpeg')
    out = MEDIA_ROOT / f"video_{uuid.uuid4().hex}.mp4"
    work = MEDIA_ROOT / f"work_{uuid.uuid4().hex}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        normalized = []
        for i, source in enumerate(image_paths):
            try:
                im = Image.open(source).convert('RGB')
                im = ImageOps.fit(im, (1280, 720), method=Image.Resampling.LANCZOS)
                draw = ImageDraw.Draw(im)
                lines = script.strip().splitlines()
                caption = lines[min(i, len(lines)-1)][:100] if lines else ''
                if caption:
                    draw.rectangle((0, 620, 1280, 720), fill=(0,0,0))
                    draw.text((36, 650), caption, fill=(255,255,255), stroke_width=1)
                p = work / f"scene_{i:03}.jpg"
                im.save(p, quality=92)
                normalized.append(p)
            except Exception as exc:
                raise MediaError(f"Could not process image {source.name}: {exc}") from exc
        # Build a slideshow at 25 fps; audio is padded/trimmed to rendered duration.
        concat = work / 'concat.txt'
        with concat.open('w', encoding='utf-8') as f:
            for p in normalized:
                f.write(f"file '{p.as_posix()}'\n")
                f.write(f"duration {seconds_per_scene}\n")
            f.write(f"file '{normalized[-1].as_posix()}'\n")
        temp = work / 'silent.mp4'
        cmd = [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', str(concat), '-vf', 'fps=25,format=yuv420p', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(temp)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode:
            raise MediaError('FFmpeg video rendering failed. Ensure FFmpeg is installed with libx264 support. ' + proc.stderr[-800:])
        cmd = [ffmpeg, '-y', '-i', str(temp), '-i', str(audio_path), '-c:v', 'copy', '-c:a', 'aac', '-shortest', '-movflags', '+faststart', str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode:
            raise MediaError('Could not combine video and audio: ' + proc.stderr[-800:])
        return out
    except FileNotFoundError as exc:
        raise MediaError('FFmpeg was not found. Install it and ensure the ffmpeg command works in your terminal.') from exc
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


def edit_uploaded_videos(video_paths: list[Path], script: str = '', language: str = 'en', keep_original_audio: bool = True) -> Path:
    """Normalize uploaded clips, concatenate them, and optionally add generated narration."""
    if not video_paths:
        raise MediaError('Upload at least one video clip to edit.')
    ffmpeg = os.environ.get('FFMPEG_PATH', 'ffmpeg')
    out = MEDIA_ROOT / f"edited_{uuid.uuid4().hex}.mp4"
    work = MEDIA_ROOT / f"edit_work_{uuid.uuid4().hex}"
    work.mkdir(parents=True, exist_ok=True)
    normalized = []
    try:
        for i, source in enumerate(video_paths):
            target = work / f"clip_{i:03}.mp4"
            # Normalize dimensions, frame rate, codec and audio so clips can be joined reliably.
            probe = subprocess.run([os.environ.get('FFPROBE_PATH', 'ffprobe'), '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(source)], capture_output=True, text=True, timeout=30)
            has_audio = probe.returncode == 0 and bool(probe.stdout.strip())
            cmd = [ffmpeg, '-y', '-i', str(source)]
            if not has_audio:
                cmd += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100']
            cmd += ['-map', '0:v:0', '-map', ('0:a:0' if has_audio else '1:a:0'),
                    '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=25,format=yuv420p',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-ar', '44100', '-ac', '2', '-shortest', '-movflags', '+faststart', str(target)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            if proc.returncode:
                raise MediaError(f"Could not process clip {source.name}: {proc.stderr[-500:]}")
            normalized.append(target)
        concat_file = work / 'concat.txt'
        with concat_file.open('w', encoding='utf-8') as f:
            for clip in normalized:
                # Paths are generated internally and contain no apostrophes.
                f.write(f"file '{clip.as_posix()}'\n")
        joined = work / 'joined.mp4'
        cmd = [ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_file), '-c', 'copy', '-movflags', '+faststart', str(joined)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if proc.returncode:
            raise MediaError('Could not join clips. ' + proc.stderr[-600:])
        if script.strip():
            narration = make_audio(script, language)
            if keep_original_audio:
                cmd = [ffmpeg, '-y', '-i', str(joined), '-i', str(narration), '-filter_complex', '[0:a]volume=0.22[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]', '-map', '0:v:0', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', str(out)]
            else:
                cmd = [ffmpeg, '-y', '-i', str(joined), '-i', str(narration), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', str(out)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            narration.unlink(missing_ok=True)
            if proc.returncode:
                raise MediaError('Could not add narration. ' + proc.stderr[-600:])
        else:
            import shutil
            shutil.copy2(joined, out)
        return out
    except FileNotFoundError as exc:
        raise MediaError('FFmpeg was not found. Install FFmpeg and confirm `ffmpeg -version` works.') from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError('Video editing took too long. Try shorter clips or fewer files.') from exc
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
