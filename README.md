# overheardr

Convert YouTube videos (for example band “What’s In My Bag?” clips) into private Spotify playlists. Paste a URL, review extracted albums, and create a playlist with every track from the albums you keep.

Phase 1 is **Spotify-only**: a “Download from Soulseek” control is visible but disabled. See [docs/SPEC.md](docs/SPEC.md) and [docs/AGENT_BRIEF.md](docs/AGENT_BRIEF.md) for full architecture and milestones.

## Requirements

- Python **3.12+**
- [ffmpeg](https://ffmpeg.org/)
- [deno](https://deno.land/) on `PATH` (required for yt-dlp YouTube JS challenges)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) with remote EJS components: always pass `--remote-components ejs:github` when invoking yt-dlp
- [Ollama](https://ollama.com/) for local LLM gap-fill (default model **`qwen2.5:3b`**; optional **`qwen2.5:7b`** on 16 GB hosts — see `.env.example`)

## Environment variables

Copy `.env.example` to `.env` and set values as needed. **Never commit `.env`.**

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_HOST` | `127.0.0.1` | Bind address for native uvicorn |
| `APP_PORT` | `8765` | Port |
| `SPOTIFY_CLIENT_ID` | *(empty)* | Spotify Developer app client ID (PKCE, no secret) |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8765/callback` | OAuth redirect (must match Spotify dashboard) |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` (native) / `http://ollama:11434` (Compose) | Ollama HTTP API |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Model tag; `qwen2.5:7b` optional on 16 GB |
| `WHISPER_MODEL` | `small` | faster-whisper model |
| `WHISPER_COMPUTE_TYPE` | `int8` | CPU quantisation |
| `DATA_DIR` | `/data` (Docker) or a local path | SQLite, cache, transcripts |

## Run with Docker Compose

```bash
cp .env.example .env
# Optional: edit .env (Spotify client ID, OLLAMA_MODEL)
docker compose up --build
```

The app is published at **http://127.0.0.1:8765**. Health check: `GET /health`.

On first start, the **`ollama-init`** service pulls `${OLLAMA_MODEL:-qwen2.5:3b}` (~0.5–2 GB depending on tag). Models persist in the `ollama-models` volume; app cache and whisper weights use `app-data` and `whisper-models`.

Inside the container the app binds **`0.0.0.0:8765`**; the host mapping is **`127.0.0.1:8765:8765`** so the service stays loopback-only on your machine.

## Run natively (venv)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# System packages (Debian/Ubuntu example):
# sudo apt install ffmpeg
# deno: see https://docs.deno.com/runtime/getting_started/installation/

cp .env.example .env
# Set OLLAMA_BASE_URL=http://127.0.0.1:11434 and DATA_DIR to a writable directory, e.g. ./data
mkdir -p data
export DATA_DIR=./data

# Start Ollama locally and pull the model:
ollama pull qwen2.5:3b

uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765**.

## Home server and Spotify redirect

Spotify only allows **`http`** redirect URIs on **loopback** (`127.0.0.1`, optionally `::1`). A bare `http://homeserver.local:8765/callback` is rejected.

Recommended approach when the app runs on a home server:

1. Keep the Spotify dashboard redirect as `http://127.0.0.1:8765/callback`. On your laptop, open an SSH local tunnel (`ssh -L 8765:127.0.0.1:8765 user@homeserver`) and complete login in the browser at that loopback URL.
2. If you need LAN or Tailscale access without a tunnel, put **Caddy** or **nginx** in front with HTTPS, add `https://<host>/callback` as a *second* redirect URI, and set `SPOTIFY_REDIRECT_URI` accordingly.

The app reads `SPOTIFY_REDIRECT_URI` from the environment so the same image can serve both modes. Do not use a client secret or Client Credentials flow for user playlist creation.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Default tests are offline and use `fixtures/TtDMUz6TBIc/`.

## Project layout

```
app/           FastAPI application
templates/     Jinja2 + HTMX templates
static/        CSS
fixtures/      Offline test data (TtDMUz6TBIc)
docs/          SPEC.md, AGENT_BRIEF.md
tests/         pytest suite
```

## Milestone status

- **M1 (scaffold + Docker):** health endpoint, placeholder home page, Compose stack with Ollama + model pull
- **M2–M7:** ingest, extraction, Spotify match, review UI, playlist PKCE, Soulseek stub — not yet implemented