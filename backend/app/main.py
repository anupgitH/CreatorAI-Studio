from pathlib import Path
import shutil, uuid
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session
from .config import settings
from .database import Base, engine, get_db
from .models import Project
from .media import MEDIA_ROOT, make_audio, make_video, edit_uploaded_videos, MediaError

Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="1.0.0", description="Audio and video creation API")
origins = [x.strip() for x in settings.frontend_origins.split(',') if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get('/api/health')
def health():
    return {"status": "ok", "app": settings.app_name}

@app.get('/api/projects')
def list_projects(db: Session = Depends(get_db)):
    rows = db.query(Project).order_by(Project.created_at.desc()).limit(100).all()
    return [serialize(p) for p in rows]

def serialize(p: Project):
    return {"id": p.id, "title": p.title, "kind": p.kind, "status": p.status, "script": p.script, "media_path": p.media_path, "created_at": p.created_at.isoformat()}

@app.post('/api/audio/generate')
def generate_audio(title: str = Form('My voiceover'), script: str = Form(...), language: str = Form('en'), db: Session = Depends(get_db)):
    try:
        audio = make_audio(script, language)
        p = Project(title=title[:180], kind='audio', status='completed', script=script, media_path=audio.name)
        db.add(p); db.commit(); db.refresh(p)
        return {**serialize(p), "download_url": f"/api/download/{audio.name}"}
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.post('/api/video/generate')
def generate_video(title: str = Form('My video'), script: str = Form(...), language: str = Form('en'), images: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    if len(images) > 20:
        raise HTTPException(413, 'Upload no more than 20 images per video.')
    saved = []
    try:
        for image in images:
            if image.content_type not in ('image/png', 'image/jpeg', 'image/webp'):
                raise HTTPException(415, f'Unsupported image type: {image.filename}. Use PNG, JPEG, or WebP.')
            dest = MEDIA_ROOT / f"upload_{uuid.uuid4().hex}_{Path(image.filename or 'image').name}"
            size = 0
            with dest.open('wb') as f:
                while chunk := image.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f'Each image must be smaller than {settings.max_upload_mb} MB.')
                    f.write(chunk)
            saved.append(dest)
        audio = make_audio(script, language)
        video = make_video(saved, script, audio)
        p = Project(title=title[:180], kind='video', status='completed', script=script, media_path=video.name)
        db.add(p); db.commit(); db.refresh(p)
        return {**serialize(p), "download_url": f"/api/download/{video.name}"}
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        for path in saved:
            path.unlink(missing_ok=True)

@app.get('/api/download/{filename}')
def download_file(filename: str):
    # Only serve files from the media directory; reject traversal paths.
    if Path(filename).name != filename:
        raise HTTPException(400, 'Invalid filename')
    path = (MEDIA_ROOT / filename).resolve()
    if path.parent != MEDIA_ROOT or not path.is_file():
        raise HTTPException(404, 'File not found or expired')
    suffix = path.suffix.lower()
    media_type = {' .mp4':'video/mp4', '.mp4':'video/mp4', '.mp3':'audio/mpeg', '.wav':'audio/wav'}.get(suffix, 'application/octet-stream')
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get('/api/projects/{project_id}/export/{format_name}')
def export_project(project_id: int, format_name: str, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, 'Project not found')
    if format_name not in ('txt', 'srt', 'vtt'):
        raise HTTPException(400, 'Supported export formats: txt, srt, vtt')
    script = p.script.strip()
    if format_name == 'txt':
        content = script + ('\n' if script else '')
        media_type = 'text/plain; charset=utf-8'
    else:
        # Basic phrase-level captions with estimated timing, not speech-aligned subtitles.
        import re
        chunks = [x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+', script) if x.strip()] or [script]
        def stamp(seconds: int, vtt: bool = False) -> str:
            h, rem = divmod(seconds, 3600); m, sec = divmod(rem, 60)
            return (f'{h:02}:{m:02}:{sec:02}.000' if vtt else f'{h:02}:{m:02}:{sec:02},000')
        rows = []
        for i, chunk in enumerate(chunks):
            start = i * 4; end = start + 4
            rows.append((f'{i+1}\n' if format_name == 'srt' else '') + f'{stamp(start, format_name == "vtt")} --> {stamp(end, format_name == "vtt")}\n{chunk}')
        content = ('WEBVTT\n\n' if format_name == 'vtt' else '') + '\n\n'.join(rows) + '\n'
        media_type = 'text/vtt; charset=utf-8' if format_name == 'vtt' else 'application/x-subrip; charset=utf-8'
    return PlainTextResponse(content, media_type=media_type, headers={'Content-Disposition': f'attachment; filename="creatorai-project-{p.id}.{format_name}"'})

@app.delete('/api/projects/{project_id}')
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, 'Project not found')
    if p.media_path:
        (MEDIA_ROOT / Path(p.media_path).name).unlink(missing_ok=True)
    db.delete(p); db.commit()
    return {"deleted": True}


@app.post('/api/video/edit')
def edit_video(
    title: str = Form('Edited video'),
    script: str = Form(''),
    language: str = Form('en'),
    keep_original_audio: bool = Form(True),
    clips: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload existing clips, normalize and join them, and optionally add TTS narration."""
    if not clips or len(clips) > 10:
        raise HTTPException(400, 'Upload between 1 and 10 video clips.')
    saved = []
    allowed = {'video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska', 'video/3gpp', 'application/octet-stream'}
    try:
        for clip in clips:
            suffix = Path(clip.filename or '').suffix.lower()
            if suffix not in {'.mp4', '.mov', '.webm', '.mkv', '.3gp', '.m4v'}:
                raise HTTPException(415, f'Unsupported video file: {clip.filename}. Use MP4, MOV, WebM, MKV, M4V or 3GP.')
            dest = MEDIA_ROOT / f"upload_{uuid.uuid4().hex}{suffix}"
            size = 0
            with dest.open('wb') as f:
                while chunk := clip.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f'Each clip must be smaller than {settings.max_upload_mb} MB.')
                    f.write(chunk)
            saved.append(dest)
        video = edit_uploaded_videos(saved, script=script, language=language, keep_original_audio=keep_original_audio)
        p = Project(title=(title or 'Edited video')[:180], kind='video', status='completed', script=script, media_path=video.name)
        db.add(p); db.commit(); db.refresh(p)
        return {**serialize(p), 'download_url': f'/api/download/{video.name}'}
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        for path in saved:
            path.unlink(missing_ok=True)
