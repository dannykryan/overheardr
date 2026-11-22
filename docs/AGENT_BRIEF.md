# Agent brief — video-to-playlist, phase 1

Build phase 1 of **video-to-playlist** in this empty repo. Follow `SPEC.md` for full architecture, prompts, matching rules, Docker, and error handling. This brief is the execution plan: milestones, tests, acceptance, and constraints.

## Product

Local web app (Danny's ThinkPad T480, Linux, CPU only, 8–16 GB RAM). Paste a YouTube URL. The app fetches metadata/description with yt-dlp, uses captions if present, otherwise transcribes audio with faster-whisper `small` (CPU, int8). It parses album lists out of the description first, then asks a local Ollama model to fill gaps from the transcript, merges and dedupes, and matches each album on Spotify (fuzzy, including native-script titles). The review screen shows one row per album (cover, title, artist, on-Spotify badge, checkbox). "Create Spotify playlist" makes a **private** playlist containing **all tracks** of the ticked albums. "Download from Soulseek" is visible but disabled.

Later the same app should move to a home server. Keep it self-contained and Docker-friendly. Spotify only allows `http` redirects on loopback; see SPEC §2 for the SSH-tunnel / HTTPS-proxy plan. Implement `SPOTIFY_REDIRECT_URI` as config, default `http://127.0.0.1:8765/callback`.

## Constraints

- No paid APIs, no sign-ups, no spending. Free local Ollama only for LLM work.
- Spotify auth is Authorization Code + PKCE, **client ID only, no client secret**. Scopes: `playlist-modify-private playlist-modify-public user-read-private`. Redirect: `http://127.0.0.1:8765/callback`.
- Never commit `.env`, tokens, secrets, audio, or model weights. Commit `.env.example` with empty `SPOTIFY_CLIENT_ID`.
- Draft PR only. Do not merge, do not create a GitHub repo, do not force-push, do not publish a package.
- Do not implement Soulseek. Stub the button only.
- Default tests must be offline and use fixtures. Mock Spotify, Ollama, yt-dlp, whisper, MusicBrainz.

## Stack (do not substitute without a strong reason)

Python 3.12+, FastAPI, Jinja2 + HTMX (no Node/Vite build; keeps the image small and Docker-simple), SQLite, httpx, pydantic, rapidfuzz, yt-dlp, deno (required for yt-dlp JS challenges), ffmpeg, faster-whisper, Ollama HTTP API. Default model: **`qwen2.5:3b`**. yt-dlp must be called with `--remote-components ejs:github` and deno on `PATH`.

Dockerfile + `docker-compose.yml`: `app` service (publish `127.0.0.1:8765:8765`) and `ollama` service, plus a model-pull init/sidecar (`ollama pull ${OLLAMA_MODEL:-qwen2.5:3b}`). Volumes for app cache, whisper weights, and Ollama models.

## Fixtures

`fixtures/TtDMUz6TBIc/` is already in the repo (copy it in if it is not):

- `description.txt`, `info.json` — live metadata, no captions
- `TtDMUz6TBIc.txt`, `TtDMUz6TBIc_timestamps.txt` — whisper transcript
- `albums.csv` — working notes
- `expected_albums.json` — **acceptance list** (21 bag picks + mentioned-only records)

Test video: `https://www.youtube.com/watch?v=TtDMUz6TBIc` (Blood Incantation, Amoeba "What's In My Bag?"). Description lists the 21 picks. There are no captions, so a live run transcribes. Tricky rows are flagged in `expected_albums.json`:

- Karma Moffett — *Sitting Still Within / Sitting Still Without*: probably **not** on Spotify; row must still appear, checkbox disabled.
- Bernard Xolotl — *Music By Xolotl*: Spotify match **unconfirmed**; job must succeed either way; do not invent a different Xolotl album.
- Yukihiro Takahashi — *Tomorrow's Just Another Day*: on Spotify as **薔薇色の明日** (2022 Yoshinori Sunahara remaster).

## Milestones

Ship in this order. Each milestone should leave the repo installable and tests passing for the work added so far.

### 1. Scaffold + Docker

Repo layout, README (run natively and with Compose), `.gitignore`, `.env.example`, FastAPI app skeleton, Dockerfile, `docker-compose.yml` with `app`, `ollama`, and model-pull step, SQLite + `DATA_DIR`, health endpoint. App binds `0.0.0.0:8765` in the container; host publish is loopback. Document the home-server redirect constraint (SPEC §2) in the README.

### 2. Ingest + transcribe

`POST /api/jobs` + background pipeline: validate YouTube URL; yt-dlp metadata + description; if captions, use them; else audio + faster-whisper `small` / int8. Cache by `video_id`. Job statuses from the spec. Offline tests inject the fixture description/transcript and must not call the network.

### 3. Extraction

Deterministic description-list parser first (bullets, `Artist - Album`, strip `(LP)` / `(CD)`). Ollama gap-fill second, using the SPEC §6.2 JSON schema and prompt (temperature 0, JSON mode if available, chunk long transcripts). Merge + dedupe as in SPEC §6.3. Description picks are not dropped because the transcript is messy. If Ollama fails, continue with description-only and a warning.

### 4. Spotify match + covers

Search + fuzzy scoring + alternate/native titles + a short artist-synonym list (Seatbelts / SEAT BELTS / Yoko Kanno & The Seatbelts, etc.). Year is a bonus, not a hard filter. MusicBrainz aliases and Cover Art Archive when Spotify has no match or no image. Cache searches. Karma → not on Spotify. Takahashi → Japanese title. Xolotl may or may not match.

### 5. Review UI

`GET /` form and `GET /jobs/{id}` review page (HTMX poll or SSE while running). One row per album: cover, title, artist, year, on-Spotify badge, checkbox ticked by default only for bag picks that are on Spotify; disabled if not. Optional collapsed mentions. Warnings banner. Playlist name field. Soulseek button present, disabled, tooltip "coming later".

### 6. Playlist creation

PKCE login (`GET /auth/spotify/login`, callback at `GET /callback`). No client secret, ever. "Create Spotify playlist" requires a session (login then resume). Private playlist, all tracks of ticked albums, review order, 100-uri batches, 429 retries. Persist playlist URL. 400 if nothing eligible is ticked.

### 7. Soulseek stub

No further behaviour beyond the disabled button and a README/SPEC pointer to phase 2 (slskd later). Do not add slskd as a dependency.

## Tests to write

Put tests under `tests/`. Use pytest + httpx/FastAPI TestClient. Fixture path: `fixtures/TtDMUz6TBIc/`.

- Parser: `description.txt` yields the 21 bag picks, in order, no extras.
- Merge: description + mocked LLM adds Takahashi alternate `薔薇色の明日` and a mention (Parallels) → 21 bag picks, alternate attached, mention not auto-ticked.
- Transcript-only: empty description, mocked LLM returns the 21 picks → rows appear.
- Ollama down / invalid JSON → job still `ready`, warning set, description picks kept.
- Matcher with canned search payloads: Takahashi English + Japanese title; Karma no hit; Seatbelts aliases; Hillage *Musick*; Abigor long title; remaster year accepted.
- API: stubbed fixture ingest, GET job, PATCH cannot select a non-Spotify row, mocked playlist add uses only ticked albums, in order.
- PKCE: challenge created, bad `state` rejected, no client secret in token request.
- Acceptance: every `bag_picks` entry in `expected_albums.json` is present (fuzzy artist+title). `mentioned_only` items are not auto-ticked. Karma expects `on_spotify=false` (soft warning if a future live match appears). Xolotl match optional.

A live smoke script is optional and must be gated by an env flag; it must not run in default CI.

## Acceptance criteria

Phase 1 is done when all of the following hold:

1. `docker compose up` (after the model pull) and a documented native venv install both start the app at `http://127.0.0.1:8765`.
2. Offline tests pass, including the fixture acceptance test above.
3. Against the test video fixtures, the review list contains all 21 bag picks from `expected_albums.json`. Mentions are not required and must not be auto-ticked.
4. Rows without a Spotify match are visible, untickable, and excluded from playlist creation. Cover art still shows if MusicBrainz has it (mocked in tests).
5. A mocked "Create Spotify playlist" call creates one private playlist and adds every track of the ticked albums.
6. The Soulseek button is visible and disabled.
7. README explains env vars, deno + `--remote-components ejs:github`, the default Ollama model and the 7B opt-in, and the home-server redirect plan.
8. No secrets in git. PR is a **draft**. Not merged.

## Implementation notes

- Single user; `BackgroundTasks` (or a thin in-process worker) is enough. Persist jobs in SQLite so a refresh is safe.
- Cache audio, transcripts, covers, and search responses under `DATA_DIR`.
- Keep Ollama `num_ctx` at 4096 (8192 max) and chunk the transcript; a 15-minute whisper dump will not fit in one 4k prompt with the schema.
- Default `OLLAMA_MODEL=qwen2.5:3b` because it fits an 8 GB T480 alongside whisper and is strong at JSON. Document `qwen2.5:7b` as a 16 GB optional upgrade. `llama3.2:3b` is the fallback tag.
- Do not fail a job because Ollama or one Spotify search failed.
- Log to stdout. Never log access tokens or the PKCE verifier.

Read `SPEC.md` before writing code. If something conflicts, SPEC wins on behaviour; this brief wins on sequencing and repo rules.
