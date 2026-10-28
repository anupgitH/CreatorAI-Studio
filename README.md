# CreatorAI Studio — Upload & AI-Assisted Video Editing

A local-first full-stack starter for editing uploaded clips and generating voiceovers.

## Features
- React + Vite workspace with Video Editor, Audio Studio, preview, project history and download links.
- FastAPI backend and SQLAlchemy persistence (SQLite by default; MySQL supported through `DATABASE_URL`).
- Upload 1–10 existing clips (MP4, MOV, WebM, MKV, M4V, 3GP), normalize to 720p H.264/AAC, concatenate with FFmpeg, and export MP4.
- Optional gTTS narration mixed with original clip audio or used as the replacement audio track.
- Audio-only text-to-speech, MP3 downloads, TXT/SRT/VTT script exports, delete projects.

> This is AI-assisted media processing, not a generative video model. It does not yet provide scene understanding, automatic silence detection, precise timeline trimming, or speech-aligned captions. Subtitle exports use estimated phrase timings. gTTS requires internet access. Only edit media you own or are authorized to use.

## Requirements
- Python 3.11+ recommended
- Node.js 20+ and npm
- FFmpeg with libx264 enabled (`brew install ffmpeg` on macOS)

## Run locally on macOS

### 1. Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

Check `http://localhost:8000/api/health` and interactive API docs at `http://localhost:8000/docs`.

### 2. Frontend (new terminal)
```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```
Open `http://localhost:5173`.

Keep both terminals running. Upload up to 10 short clips. Each file is limited to `MAX_UPLOAD_MB` (default 20 MB). Set the limit in `backend/.env` for local testing, keeping available disk and memory in mind.

## Environment variables

Backend `backend/.env`:
- `APP_NAME`: API title.
- `SECRET_KEY`: replace with a long random value before public deployment.
- `DATABASE_URL`: defaults to `sqlite:///./creatorai.db`; for MySQL use `mysql+pymysql://USER:PASSWORD@HOST:3306/creatorai` (URL-encode special characters in credentials).
- `MEDIA_DIR`: generated and temporary media directory.
- `FRONTEND_ORIGINS`: comma-separated frontend origins, e.g. `http://localhost:5173`.
- `MAX_UPLOAD_MB`: per-file upload limit.
- `FFMPEG_PATH`: optional if ffmpeg isn't found on PATH.

Frontend `frontend/.env`:
```env
VITE_API_URL=http://localhost:8000
```
Restart Vite after changing frontend environment variables.

## Main endpoints
- `GET /api/health`
- `GET /api/projects`
- `POST /api/audio/generate` — multipart `title`, `script`, `language`
- `POST /api/video/edit` — multipart `title`, optional `script`, `language`, `keep_original_audio`, repeated `clips` files
- `GET /api/download/{filename}`
- `GET /api/projects/{id}/export/{txt|srt|vtt}`
- `DELETE /api/projects/{id}`

## Free-tier deployment guidance
- Frontend: deploy `frontend` as a static Vite site on a static host such as Cloudflare Pages.
- Backend: choose a Python service host only if it currently supports your required runtime and resource needs. FFmpeg renders are CPU/memory intensive; many free instances sleep or have ephemeral storage.
- Database: use managed MySQL/PostgreSQL if available, and configure `DATABASE_URL` accordingly.
- Media: use persistent disk or object storage. The default local `MEDIA_DIR` is not durable on ephemeral hosts.
- Set `VITE_API_URL` to the deployed API URL and set `FRONTEND_ORIGINS` to the deployed frontend origin. Use HTTPS.

Before exposing publicly, add authentication/authorization, per-user project ownership, upload rate limits, media retention/cleanup, request timeouts, durable object storage and background jobs. The starter API currently has no user authentication and should only be used locally or behind a trusted access layer.
