# Ad Localizer

Localize English Instagram ad videos into Indian regional languages — translated voiceover + translated overlay text + same original visuals — in one click.

Supports: Hindi, Hinglish, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, Punjabi.

## How it works

Upload an MP4 (9:16, 15–60s, English voiceover, static centered overlay text, no background music) and pick a target language. The backend will:

1. Extract audio with FFmpeg
2. Transcribe the English voiceover with OpenAI Whisper (forced `language=en`)
3. Translate the script with Claude (Sonnet 4.6) or OpenAI GPT-4o
4. Generate a localized voiceover with ElevenLabs (`eleven_multilingual_v2`) and time-stretch it to match the original duration via `rubberband`/`atempo`
5. Extract a representative frame, detect the overlay text with Google Vision (`DOCUMENT_TEXT_DETECTION`), and merge the paragraph boxes into one bounding box
6. Translate the overlay text with the same LLM as the script
7. Show you both translations in a review UI with a live still-frame preview
8. On "Render Final", render an MP4 that blurs the original-text region, overlays the translated text rendered via Pillow + HarfBuzz, and replaces the audio track

## Architecture

- **Frontend:** Next.js 15 (App Router) + React 19 + TypeScript + Tailwind
- **Backend:** FastAPI + Python 3.11 + SQLModel + SQLite, FastAPI `BackgroundTasks` for the job queue
- **STT:** Groq `whisper-large-v3` (free tier) if `GROQ_API_KEY` set, else OpenAI Whisper
- **LLM:** Groq `llama-3.3-70b-versatile` → Claude Sonnet 4.6 → OpenAI GPT-4o (priority chain, whichever key is set)
- **TTS:** ElevenLabs (curated voice ID per language)
- **OCR:** Google Vision (precise bbox) if `GOOGLE_VISION_API_KEY` set, else OCR.space (free tier, text-only + estimated centered bbox)
- **Video:** FFmpeg via `subprocess` — must be built with `libx264`, `librubberband`, `libfreetype`
- **Text rendering:** Pillow ≥10 + libraqm (HarfBuzz shaping) → transparent PNG → FFmpeg `overlay` filter (FFmpeg `drawtext` does NOT shape Indic scripts correctly)

```
LJORGANICVOICEOVER/
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── main.py
│   │   ├── api/             routers per endpoint
│   │   ├── services/        pipeline, ffmpeg_ops, tts, stt, translator, ocr, text_renderer
│   │   └── fonts/           bundled Noto fonts (download separately)
│   └── storage/             runtime artifacts (per-job dirs)
├── frontend/                Next.js app (upload + review + render)
├── docker-compose.yml
└── README.md
```

## Local setup

### Prerequisites

- Python 3.11+
- Node 20+ and `npm` or `pnpm`
- FFmpeg with `libx264`, `librubberband`, `libfreetype` — verify:
  ```
  ffmpeg -hide_banner -buildconf | grep -E 'libx264|librubberband|libfreetype'
  ```
  - Windows: download the BtbN full build from https://github.com/BtbN/FFmpeg-Builds/releases (`ffmpeg-master-latest-win64-gpl-shared.zip`). Add it to PATH.
  - macOS: `brew install ffmpeg` (the default formula includes libx264; `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-rubberband` adds rubberband).
  - Linux (Debian/Ubuntu): `sudo apt install ffmpeg` covers most; for rubberband use a static contrib build or compile from source.
- Pillow with libraqm — on Debian/Ubuntu: `sudo apt install libraqm0`. macOS: `brew install libraqm`. Windows: prebuilt Pillow wheels include libraqm.

### Bundle the fonts

Download Noto Sans **Bold** for each script and drop into `backend/app/fonts/`:

```
NotoSans-Bold.ttf
NotoSansDevanagari-Bold.ttf
NotoSansTamil-Bold.ttf
NotoSansTelugu-Bold.ttf
NotoSansKannada-Bold.ttf
NotoSansMalayalam-Bold.ttf
NotoSansBengali-Bold.ttf
NotoSansGujarati-Bold.ttf
NotoSansGurmukhi-Bold.ttf
```

Get them from https://fonts.google.com/noto or the per-script `notofonts/<script>` GitHub repos. The script-specific files include the conjunct GSUB tables — the generic `NotoSans-Bold.ttf` does NOT, so don't substitute.

### Configure environment

```
cp backend/.env.example backend/.env
```

#### Free-tier setup (recommended for first run)

Three free signups, no credit card required:

| Key | Where | Free tier | Covers |
|---|---|---|---|
| `GROQ_API_KEY` | https://console.groq.com/keys | 30 RPM chat / 20 RPM Whisper | LLM translation + Whisper STT |
| `ELEVENLABS_API_KEY` | https://elevenlabs.io/app/settings/api-keys | 10k chars/month (~3–4 ads) | Voiceover |
| `OCR_SPACE_API_KEY` | https://ocr.space/ocrapi/freekey | 25k requests/month | Overlay text detection |

Fill those three into `backend/.env` and you're ready. The priority chain falls through to paid providers automatically when those keys are added — no code changes needed.

#### Paid upgrades (optional)

| Key | Where | What it upgrades |
|---|---|---|
| `CLAUDE_API_KEY` | https://console.anthropic.com/settings/keys | Translation uses Claude Sonnet 4.6 instead of Llama 3.3 (better South-Indian / Bengali quality) |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys | Falls back to GPT-4o + Whisper-1 if Groq is unavailable |
| `GOOGLE_VISION_API_KEY` | https://console.cloud.google.com/apis/credentials | Tighter overlay bounding box (paragraph-level Vision OCR vs centered estimate) |

#### Selection priority

- **LLM:** `GROQ_API_KEY` → `CLAUDE_API_KEY` → `OPENAI_API_KEY`
- **STT:** `GROQ_API_KEY` → `OPENAI_API_KEY`
- **OCR:** `GOOGLE_VISION_API_KEY` → `OCR_SPACE_API_KEY`

### Run

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

### Docker

```
docker compose up --build
```

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/upload` | Multipart `video` + `target_language` → kicks off prep pipeline. Returns `{id, status, ...}`. |
| `GET`  | `/api/job/{id}` | Poll status + URLs of all artifacts. |
| `POST` | `/api/transcribe/{id}` | Re-run the full prep chain. |
| `POST` | `/api/translate-script/{id}` | Re-translate from the saved transcript. |
| `PUT`  | `/api/translate-script/{id}` | `{text}` — save user-edited script. |
| `POST` | `/api/translate-overlay/{id}` | Re-translate overlay (background). |
| `PUT`  | `/api/translate-overlay/{id}` | `{text}` — save user-edited overlay. |
| `POST` | `/api/generate-voiceover/{id}` | `{text?}` — re-run ElevenLabs with current/given script. |
| `POST` | `/api/detect-text/{id}` | Re-run OCR on the cached frame. |
| `POST` | `/api/render-preview/{id}` | `{text}` — returns a still PNG with the overlay composited on the pre-blurred frame. Use for live preview (debounced 400ms). |
| `POST` | `/api/render-final/{id}` | Render the localized MP4 in the background. |
| `GET`  | `/api/languages` | Supported languages + ElevenLabs voice metadata. |
| `GET`  | `/api/health` | FFmpeg features probe. |

Artifacts are served under `/files/job_<id>/...`.

## Verification (end-to-end)

1. Upload `Resize V7_4x5.mp4` from the project root → pick **Malayalam**.
2. Wait until status reaches `awaiting_review` (~30–60s, mostly TTS time).
3. Compare:
   - The detected overlay text matches the English in the reference MP4.
   - The translated overlay reads like the Malayalam reference.
   - The voiceover audio length is within ±15% of the original (look at `generated_voiceover_duration_s`).
4. Tweak the translations if needed; click **Regenerate voiceover** if you edited the script.
5. Click **Render final video**. Wait. Inspect the result with:
   ```
   ffprobe -v error -show_entries stream=codec_name,duration,nb_frames:format=duration backend/storage/job_<id>/final.mp4
   ```
   - Video codec = h264, has frames, duration close to original.
   - Audio codec = aac.
6. Spot-check Hindi (Devanagari conjuncts), Tamil (combining marks), and Hinglish (mixed script) on the same MP4 — these are the highest-risk languages for the text-rendering pipeline.

## Cost (per ~30s ad, ballpark)

- Whisper STT: ~$0.006
- LLM translation (Claude or GPT-4o): <$0.02
- ElevenLabs `eleven_multilingual_v2`: ~$0.30 (character-based)
- Google Vision: ~$0.0015
- **Total:** ~$0.33 per render. Re-renders cost $0 (no re-translation, no new TTS).

## Scaling notes

- **Bulk multi-language:** the transcript + bbox are language-agnostic. Translating + TTS + rendering the same source video across all 10 languages reuses ~80% of the work vs running 10 independent jobs. The pipeline is already shaped to allow this — a future `POST /api/bulk` endpoint would fan out per-language sub-jobs sharing the prep artifacts.
- **GPU:** swap `-c:v libx264` → `-c:v h264_nvenc` in `backend/app/services/ffmpeg_ops.py` for ~5× faster encodes on GPU hosts.
- **Storage swap:** all artifact writes go through `StorageBackend` in `backend/app/services/storage.py`. The S3 adapter is ~40 lines using `boto3` + presigned URLs.
- **Queue swap:** `JobRunner` in `backend/app/services/runner.py` is the only place async work is launched. Replace `BackgroundTaskRunner` with an RQ/Celery adapter when you want to scale workers horizontally.
- **Rate limits:** ElevenLabs caps concurrency at ~2 on most plans. The TTS service already chunks at sentence boundaries (≤250 chars) and concatenates with crossfade. For >2 jobs in parallel, gate at the `JobRunner` layer with an asyncio semaphore.

## Engineering trade-offs

| Decision | Why |
|---|---|
| Pillow + libraqm (not FFmpeg `drawtext`) | `drawtext` has no HarfBuzz shaping; Devanagari/Tamil/Bengali conjuncts break. Pillow with libraqm fixes this. |
| `rubberband` over chained `atempo` | Chained `atempo` muddies vowels in Indic languages. `rubberband` preserves formants up to ±22%. |
| Hybrid duration matching (compact + natural variants) | Indian languages expand 15–35% vs English. Asking the LLM for two variants lets us fall back without re-prompting. |
| `DOCUMENT_TEXT_DETECTION` + paragraph cluster | `TEXT_DETECTION` returns word-level boxes that don't group multi-line overlays. Paragraph-level + central-band filter + vertical clustering gives one bbox. |
| Still-frame preview only on text edit | Re-encoding MP4 per keystroke is prohibitive (5–15s). A PNG composite over a cached pre-blurred frame is <300ms. |
| Force Whisper `language=en` | Auto-detect hallucinates Hindi mid-sentence on accented English. |
| `ffprobe` gate on every render | FFmpeg can silently produce a container with no video stream when a filter fails. We assert `nb_frames > 0` and `duration > 0.5×expected` before reporting success. |

## What's out of scope (planned for v2)

- Dynamic / animated overlay text (motion tracking, per-frame placement)
- Multi-region overlay (more than one text box per ad)
- AI inpainting for the original-text region (vs the current blur patch)
- Voice cloning (the brand's own voice as the regional speaker)
- Bulk render across all 10 languages in one job
- Template saving for repeat ad creatives
- S3 storage, GPU acceleration, RQ/Celery workers — abstractions are in place
