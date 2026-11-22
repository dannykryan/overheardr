# video-to-playlist — Phase 1 specification

A local web app: paste a YouTube URL (for example a band "What's In My Bag?" video), extract every album mentioned, review them, and create a private Spotify playlist containing every track of the albums you tick.

Phase 1 is Spotify-only. A "Download from Soulseek" button is visible but disabled. Nothing here spends money, creates accounts, or calls a paid AI API.

## 1. Goals and non-goals

**Goals**

- Run on Danny's ThinkPad T480 (Linux, CPU only, 8–16 GB RAM) as a single-user local app bound to `127.0.0.1:8765`.
- Stay self-contained and Docker-friendly so the same image can later move to a home server.
- Prefer deterministic parsing of the video description; use a free local LLM (Ollama) only to fill gaps from the transcript.
- Match albums on Spotify with fuzzy and alternate-title support (including native-script titles).
- Show a review screen, then create a private Spotify playlist of all tracks from the ticked albums.

**Non-goals (phase 1)**

- Soulseek / file download (stub only).
- Multi-user accounts, hosted SaaS, or a public website.
- Paid transcription or LLM APIs.
- Editing the generated playlist after creation (Spotify itself can do that).
- Perfect identification of every spoken aside; the acceptance bar is the 21 bag picks in `fixtures/TtDMUz6TBIc/expected_albums.json`.

## 2. Runtime and later deploy

**Local (phase 1 default).** The app listens on `http://127.0.0.1:8765`. Spotify OAuth uses Authorization Code with PKCE, client ID only (no client secret), redirect URI exactly `http://127.0.0.1:8765/callback`, scopes `playlist-modify-private playlist-modify-public user-read-private`.

**Home server later.** Spotify only allows `http` redirect URIs on loopback (`127.0.0.1`, optionally `::1`). A bare `http://homeserver.local:8765/callback` will be rejected.

Recommended approach, in order:

1. Keep the registered redirect as `http://127.0.0.1:8765/callback`. On the client machine, open an SSH local tunnel (`ssh -L 8765:127.0.0.1:8765 user@homeserver`) and complete login in a browser at that loopback URL. No Spotify dashboard change, still PKCE, still no secret. This is the default recommendation.
2. If the app must be opened from other devices on the LAN or via Tailscale without a tunnel, put Caddy or nginx in front with HTTPS (Let's Encrypt, or Tailscale Serve). Add `https://<host>/callback` as a *second* redirect URI on the Spotify developer app. The process reads `SPOTIFY_REDIRECT_URI` from the environment so the same image works in both modes.

Do not invent a client secret or switch to the Client Credentials flow for user playlist creation. Client Credentials cannot create playlists in a user's account.

## 3. Architecture

Single-user, one Python process plus a sibling Ollama container.

```
Browser (HTMX / Jinja)
    |
    v
FastAPI  :8765
    |-- yt-dlp + deno   (metadata, description, captions or audio)
    |-- faster-whisper  (small, CPU, int8) if no captions
    |-- description parser (deterministic)
    |-- Ollama HTTP API (gap-fill from transcript)
    |-- Spotify Web API (search, covers, auth, playlist)
    |-- MusicBrainz + Cover Art Archive (aliases + covers when Spotify has none)
    '-- SQLite + cache volume
```

Jobs are persisted in SQLite so a refresh does not lose work. Audio, transcripts, and downloaded cover art live under a cache directory (Docker volume). Whisper weights and Ollama models have their own volumes so they are not re-downloaded on every restart.

### Stack

- Backend: Python 3.12+, FastAPI, Uvicorn, Pydantic, httpx, Jinja2.
- Frontend: server-rendered Jinja templates + HTMX + a small CSS file. No Node build step, so the Docker image stays Python + ffmpeg + yt-dlp + deno.
- Storage: SQLite (SQLAlchemy or aiosqlite).
- Matching: `rapidfuzz` (or equivalent) for string scores.
- Ingest: `yt-dlp` (must be invoked with `--remote-components ejs:github`; `deno` on `PATH`), `ffmpeg`, `faster-whisper` model `small`, `compute_type=int8`.
- LLM: Ollama HTTP API, default model `qwen2.5:3b` (see §7).
- Spotify: Authorization Code with PKCE; tokens stored in a local file or the SQLite db with `0600` permissions, never in git.

## 4. Data model

**Job.** `id` (uuid), `url`, `video_id`, `status` (`queued`, `fetching`, `transcribing`, `extracting`, `matching`, `ready`, `creating_playlist`, `done`, `error`), `status_detail`, `error_message`, `created_at`, `updated_at`, `playlist_id`, `playlist_url`, `playlist_name`, `warnings` (JSON list of human-readable warnings, e.g. "Ollama unavailable; used description only").

**Video.** One-to-one with Job: `title`, `channel`, `duration_seconds`, `upload_date`, `description`, `thumbnail_url`, `has_captions`, raw `info.json` path, `chapter` list.

**Transcript.** `source` (`captions` | `whisper`), `text`, `timed_text` (optional), `model` / `language` if whisper, path to cached audio.

**AlbumRow.** One per merged album shown on the review screen:

- `artist`, `album`, `year` (nullable)
- `alternate_titles` (list)
- `role` (`bag_pick` | `mention`)
- `sources` (subset of `description`, `transcript_llm`)
- `confidence`
- `evidence` (short quote, nullable)
- `speaker` (nullable)
- `selected` (bool; default true iff a Spotify match exists and `role=bag_pick`)
- `on_spotify` (bool)
- `spotify_album_id`, `spotify_url`, `spotify_album_name`, `spotify_artist_name`, `match_score`
- `cover_url` (Spotify image, else Cover Art Archive, else null)
- `musicbrainz_release_group_id` (nullable)
- `unavailable_reason` (nullable)

**SpotifySession.** `access_token`, `refresh_token`, `expires_at`, `display_name`, `user_id`. Single row is enough.

Keep a cache table for Spotify search responses and MusicBrainz lookups keyed by normalized `(artist, album)` so re-runs of the test video do not hammer the APIs.

## 5. Pipeline

Triggered when the user submits a URL. Run on a background worker (FastAPI `BackgroundTasks` is enough for a single user; a thin queue is fine too). Never block the request that created the job.

1. **Validate URL.** Accept standard YouTube watch, youtu.be, and shorts URLs. Reject non-YouTube URLs with a clear error.
2. **Fetch metadata.** `yt-dlp --skip-download --write-info-json` (or equivalent Python API) with `--remote-components ejs:github` and `deno` available. Persist title, channel, description, thumbnail, duration, chapters, and whether manual or automatic captions exist. Drop bulky `formats` / `heatmap` lists from stored JSON.
3. **Captions or transcribe.** If usable captions exist (prefer manual over automatic, prefer the video language then English), download and normalise them to plain text plus optional timestamps. Otherwise download audio only (`bestaudio`), convert with ffmpeg if needed, and transcribe with faster-whisper `small`, CPU, int8. Cache audio and transcript by `video_id` so a retry does not re-download.
4. **Extract from the description (deterministic, first).** See §6. This is the primary source when the description already lists the albums, as the Amoeba "What's In My Bag?" videos do.
5. **Extract from the transcript (Ollama, gap-fill).** See §6–7. If Ollama is down, times out, or returns invalid JSON, continue with description results and add a warning. Do not fail the job.
6. **Merge and dedupe.** See §6.
7. **Match on Spotify, then covers.** See §8. For rows not on Spotify, try MusicBrainz + Cover Art Archive for artwork and aliases (aliases may trigger one more Spotify search).
8. **Mark job `ready`.** The review UI is now usable.

Creating the playlist is a separate user action after review, not part of this pipeline.

## 6. Album extraction

### 6.1 Description parser

Scan the description for list blocks: lines starting with `•`, `-`, `*`, `·`, or a number/`1.` prefix. Also accept dense "Artist - Album" / en-dash / em-dash lines under a heading that looks like "picks", "albums", or "tracklist".

For each line, parse `Artist - Album` (first delimiter only). Strip trailing format tags such as `(CD)`, `(LP)`, `(vinyl)`, `[OST]`. Keep `[OST]` / `(Original Soundtrack)` information as an alternate or as part of the album title when it is the work's name (see Seatbelts). Treat the description list in the test fixture as `role=bag_pick`, `confidence=high`, `sources=["description"]`.

Ignore bare URLs, hashtags, shop links, and "get the artist's music" blurbs. "Blood Incantation's new ambient synth album Timewave Zero…" in the intro blurb is a mention of their own release, not a bag pick — do not add it from that sentence if it is not in the picks list.

Unit-test this parser against `fixtures/TtDMUz6TBIc/description.txt`. It must return all 21 bag picks, in listed order, with no extras.

### 6.2 Ollama gap-fill

Send the transcript (timestamped if available; otherwise the plain text) plus the description-derived list, and ask the model only to:

- confirm or correct titles/artists the transcript supports
- add albums clearly presented in the transcript that the description missed
- attach alternate titles (including non-English / native script) when the text or common discography makes that reasonable
- mark each item `bag_pick` or `mention`
- quote a short evidence span

Do not let the model drop a high-confidence description pick just because the transcript is messy. Description picks stay unless the user later unticks them.

**System prompt (use a close variation; keep the schema stable):**

```
You extract music albums from a YouTube video transcript.
Return ONLY valid JSON that matches this schema, with no markdown fences:
{
  "albums": [
    {
      "artist": "string",
      "album": "string",
      "year": 1983,
      "alternate_titles": ["string"],
      "role": "bag_pick" | "mention",
      "confidence": "high" | "medium" | "low",
      "evidence": "short quote from the transcript",
      "speaker": "string or null"
    }
  ]
}
Rules:
- Do not invent albums that the transcript does not support.
- role=bag_pick only when someone is presenting a record they picked or have in the bag.
- role=mention for albums cited in passing (influences, earlier records, the band's own catalogue, something shown on a nearby sleeve).
- Prefer the official album title, not a track name mentioned while showing the sleeve.
- If you know a native-script or alternate official title, put it in alternate_titles (example: Yukihiro Takahashi's "Tomorrow's Just Another Day" is also 薔薇色の明日).
- year may be null if not stated. Do not guess wildly.
- If the speech is garbled, still emit your best reading at confidence=low rather than dropping a clearly presented pick.
```

The user message should include: video title, the already-parsed description list (so the model can attach alternates rather than rediscover the list from scratch), and the transcript. Temperature `0`. Ask Ollama for JSON mode if the model tag supports it (`format: json`).

**Chunking.** Keep `num_ctx` modest (4096 default, 8192 maximum) so a T480 does not swap. If title + description list + transcript will not fit in half the context, split the transcript on chapter boundaries or timestamp gaps with a small overlap, run one request per chunk, and merge. A 15-minute whisper transcript is expected to need chunking at 4096.

### 6.3 Merge

Key: fuzzy match on normalized artist + album (see §8 normalisation), also comparing alternate titles.

- Description row wins the canonical `artist` / `album` spelling.
- Union `alternate_titles`.
- If either source says `bag_pick`, the row is a bag pick.
- `sources` records both origins when they agree.
- LLM-only bag picks with `confidence=low` still appear, but default `selected=false` until a Spotify match is confirmed (and still only auto-tick if `role=bag_pick` and `on_spotify`).
- Mentions may be shown in a visually secondary group or omitted from the default view behind a "Show mentions" toggle. They must never be auto-ticked. Mentions that are clearly not albums (a TV series) must be dropped.

## 7. Ollama model recommendation

**Default: `qwen2.5:3b`** (Ollama's default Q4_K_M tag, about 1.9 GB on disk).

Why this, and not a 7B, on a T480:

- The T480 is 8th-gen Intel, CPU only for our purposes (UHD 620 is not a useful inference device). Many machines in this class have 8 GB RAM, some 16 GB. The app also loads faster-whisper `small` (roughly 1–1.5 GB) plus the Python process, ffmpeg, and a browser.
- `qwen2.5:3b` typically sits around 4–5 GB resident with a short context — comfortable on 8 GB if the browser is not huge, and easy on 16 GB even beside Whisper.
- Qwen2.5 follows instructions and emits structured JSON more reliably than similarly sized Llama 3.2 models, which is the entire job here (extract a list, not chat).
- A 7B (`qwen2.5:7b`, about 4.7 GB weights) will load on 16 GB, but on CPU it is slow and on 8 GB it leaves almost no headroom once Whisper is resident. Make it an opt-in upgrade, not the default.
- `llama3.2:3b` is a fine fallback if Qwen cannot be pulled; set it via `OLLAMA_MODEL`. Do not default to 7B/8B/14B.

Config: `OLLAMA_MODEL=qwen2.5:3b` and `OLLAMA_BASE_URL=http://ollama:11434` in Docker, or `http://127.0.0.1:11434` on a native install. An optional `OLLAMA_MODEL=qwen2.5:7b` note belongs in `.env.example` for 16 GB hosts who would rather wait longer for slightly better gap-fill.

Docker Compose must include an Ollama service and a one-shot model-pull step (`ollama pull $OLLAMA_MODEL`) that waits for the daemon to be ready, so the first job does not race an empty model store.

## 8. Spotify matching

Normalise strings before comparison: Unicode NFKC, lowercase, `&` / `and` / `+` equivalence, strip `feat.` / `ft.` / `featuring`, strip punctuation, collapse whitespace, drop a leading "the". Parentheticals such as `(remaster)`, `(deluxe)`, `(2022 remaster)` are ignored for the *query* but may add a small score bonus when choosing among otherwise equal hits. Do not use year as a hard filter — the copy in the bag is often a reissue.

**Search sequence** for each row (stop early on a confident hit):

1. `album:"<title>" artist:"<artist>"`
2. `"<title>" "<artist>"`
3. Repeat 1–2 for each `alternate_title` (this is how Takahashi is expected to resolve: `薔薇色の明日`).
4. If still weak, MusicBrainz release-group search; collect aliases (and artist aliases); retry Spotify with those names.
5. Special artist equivalences to encode in tests and, if needed, a small synonym table: Seatbelts / SEAT BELTS / Yoko Kanno & The Seatbelts; The Dave Brubeck Quartet / Dave Brubeck; Carlos Santana & John McLaughlin / Mahavishnu Orchestra; Tears For Fears / Tears for Fears.

**Scoring.** Combine rapidfuzz token-set (or WRatio) scores for album title and artist (against the album's artist list). Prefer `album` type over compilation / single. Small bonus for a year within 1 of the extracted year, and for a remaster of the same work rather than a namesake. Accept when album score ≥ 85 and artist score ≥ 80, or when the normalised album title is exact and artist ≥ 70. Otherwise mark `on_spotify=false`. Do not attach a low-confidence hit just to fill the row (wrong album in the playlist is worse than a disabled checkbox).

**Covers.** Use the Spotify album image when matched. Otherwise request Cover Art Archive via the MusicBrainz release-group or release id. Cache images locally and serve them from the app so the review page does not depend on third-party hotlink uptime.

**Known tricky rows** (must be covered by offline tests with fixture search payloads):

| Album | Expectation |
|---|---|
| Yukihiro Takahashi — Tomorrow's Just Another Day | Match Spotify release titled 薔薇色の明日, 2022 Yoshinori Sunahara remaster |
| Karma Moffett — Sitting Still Within / Sitting Still Without | `on_spotify=false` (probable). Row still visible, checkbox disabled |
| Bernard Xolotl — Music By Xolotl | Unconfirmed. Job must succeed whether or not a match is found; do not invent a different Xolotl album |
| Steve Hillage — Rainbow Dome Musick | Spelling is Musick; transcript may say "music" |
| Seatbelts — Cowboy Bebop (Original Soundtrack) | 1998 anime OST, not the 2021 Netflix soundtrack |
| Abigor — Leytmotif Luzifer | Full title often includes "(The 7 Temptations of Man)"; hint id `0D0xCqUDfhkLk4sKTOEiou` |

## 9. Spotify auth and playlist creation

- Public client, PKCE S256, no client secret anywhere (not even in `.env.example` as a placeholder that looks real).
- `SPOTIFY_CLIENT_ID` and `SPOTIFY_REDIRECT_URI` come from the environment. Default redirect: `http://127.0.0.1:8765/callback`.
- Login starts at `GET /auth/spotify/login` (random `state` + `code_verifier` stored server-side). The callback is `GET /callback` to match the registered URI.
- Refresh the access token as needed. If refresh fails, ask the user to log in again.
- "Create Spotify playlist" is disabled until a session exists; the click path should send the user through login and then resume the create action.
- Create a **private** playlist. Default name: a shortened video title, e.g. `What's In My Bag? – Blood Incantation`. Let the review page edit the name before submit.
- For each ticked row with a `spotify_album_id`, page through all album tracks and add them (batch up to 100 uris). Preserve review order (album order, then track order).
- Handle 429 with `Retry-After`. Surface a partial-failure warning if some albums add and others fail.
- Store `playlist_id` / url on the job and link out to Spotify.

## 10. HTTP routes

HTML (HTMX-friendly):

- `GET /` — URL form, plus a note if Spotify is not yet connected.
- `GET /jobs/{id}` — progress, then the review table. Poll or SSE for status while running.
- `GET /callback` — OAuth redirect target.

JSON API:

- `POST /api/jobs` `{ "url": "..." }` → `{ "id", "status" }`
- `GET /api/jobs/{id}` — job + video + warnings + album rows
- `PATCH /api/jobs/{id}/albums/{album_id}` `{ "selected": true }` — ignore / 400 if the row is not on Spotify
- `POST /api/jobs/{id}/playlist` `{ "name": "..." }` — requires auth; returns playlist url
- `GET /auth/spotify/login`
- `GET /auth/spotify/status` — `{ "connected": bool, "display_name": ... }`
- `POST /auth/spotify/logout`

Static cache: `GET /media/covers/{id}` or similar.

## 11. UI

One page after submit is enough.

- Header: video title, channel, thumbnail, duration, transcript source (`captions` or `whisper`).
- Warnings banner (Ollama skipped, unmatched albums, etc.).
- Table: one row per album — cover, title, artist, year if known, a clear "On Spotify" / "Not on Spotify" badge, checkbox. Checkboxes are ticked by default only when `on_spotify` and `role=bag_pick`. Not-on-Spotify rows stay visible, badge included, checkbox disabled.
- Optional collapsed "Mentions" section.
- Primary button: **Create Spotify playlist**. Secondary button: **Download from Soulseek**, visible, disabled, with a short "coming later" title/tooltip. Do not hide it.
- Playlist name field next to the primary button.
- If Spotify is not connected, the primary button labels itself as needing login and starts the PKCE flow.

Keep typography and layout simple and readable. No framework SPA.

## 12. Docker and config

`Dockerfile` (app): Python slim, install ffmpeg, yt-dlp, and deno (official binary is fine), plus the app and `faster-whisper` deps. Default command: `uvicorn` on `0.0.0.0:8765` (binding all interfaces *inside* the container is correct; publish `127.0.0.1:8765:8765` on the host for the local setup).

`docker-compose.yml`:

- `app` — build `.`, env file, depends on Ollama healthy, volumes for `/data/cache` and `/data/whisper-models`, port 8765.
- `ollama` — official `ollama/ollama` image, volume for `/root/.ollama`, healthcheck against `http://127.0.0.1:11434/api/tags`.
- `ollama-init` (or an entrypoint sidecar) — same image, `network_mode` / depends on Ollama, runs `ollama pull ${OLLAMA_MODEL:-qwen2.5:3b}` and exits 0. Document that the first pull is several hundred MB to ~2 GB.

`.env.example` (committed; `.env` is gitignored):

```
APP_HOST=127.0.0.1
APP_PORT=8765
SPOTIFY_CLIENT_ID=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8765/callback
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b
WHISPER_MODEL=small
WHISPER_COMPUTE_TYPE=int8
DATA_DIR=/data
# Optional on a 16 GB machine: OLLAMA_MODEL=qwen2.5:7b
```

Native (non-Docker) install should also be documented briefly in the README the agent writes: system packages for ffmpeg and deno, a venv, and a local Ollama daemon. Same env vars, with `OLLAMA_BASE_URL=http://127.0.0.1:11434`.

## 13. Error handling

Fail the job with a readable message for: invalid URL, yt-dlp extract errors (deleted, private, JS-challenge failure — mention deno / `--remote-components` in the log), ffmpeg missing, whisper failure after retries, disk full.

Do **not** fail the job for: no captions (that's the whisper path), Ollama down or bad JSON (description-only + warning), individual Spotify search misses, MusicBrainz misses, Xolotl unconfirmed.

Auth errors belong on the playlist action, not the extract pipeline. 401 after login → prompt to reconnect. 429 → retry, then warn. Creating a playlist with zero ticked Spotify rows → 400 with an explanation, not an empty playlist.

Log to stdout (Docker-friendly). Do not log access tokens or the PKCE verifier.

## 14. Test plan

All CI / default tests are offline. Use `fixtures/TtDMUz6TBIc/`. Mock yt-dlp, whisper, Ollama, Spotify, and MusicBrainz.

Required tests:

1. Description parser vs `description.txt` → 21 bag picks, correct artist/album strings, listed order, no extras.
2. Merge: description list + a mocked LLM payload that adds an alternate title for Takahashi (`薔薇色の明日`) and a mention (Parallels) → 21 bag picks, Takahashi has the alternate, Parallels not auto-selected.
3. Transcript-only fallback: empty description, mocked LLM returns the 21 picks → rows still appear.
4. Ollama invalid JSON / connection error → job still reaches `ready` from the description, warning set.
5. Spotify matcher, with recorded/canned search JSON: Takahashi English title plus the Japanese title hit; Karma no acceptable hit; Seatbelts aliases; Hillage "Musick"; Abigor long title; a wrong-year remaster still accepted.
6. API: create job from a stubbed fixture ingest, `GET` review payload, `PATCH` cannot select a non-Spotify row, playlist handler (mocked Spotify) adds all tracks of ticked albums only, in order, in batches of 100 if needed.
7. PKCE: login starts with a challenge, callback without a matching state is rejected, client secret is never sent.
8. Acceptance helper: after a fixture run, every `bag_picks` entry in `expected_albums.json` is present (fuzzy artist+title), and `mentioned_only` entries are not auto-ticked. Karma expects `on_spotify=false` (soft warning if a future real match appears). Xolotl may be matched or not.

A live optional script (`scripts/live_smoke.py` or a documented manual path) may hit real YouTube / Ollama / Spotify, gated behind an env flag, never run in default CI.

## 15. Phase 2 — Soulseek (do not implement)

Leave the disabled button in the UI. A later phase should:

- Talk to a local [slskd](https://github.com/slskd/slskd) instance (HTTP API) rather than embedding a Soulseek client, so credentials and shares stay out of this app.
- For each ticked (or "not on Spotify") album, search by artist + album, prefer a complete lossless folder, and queue a download into a user-chosen directory.
- Show per-album search status; never start downloads without an explicit click.
- Stay honest about legality and Soulseek's terms; this app should not scrape or redistribute.

Phase 1 must not depend on slskd being installed.

## 16. Fixtures

Canonical test case: `https://www.youtube.com/watch?v=TtDMUz6TBIc` (Blood Incantation, Amoeba "What's In My Bag?", 2022-11-28, 912 s, no captions). Files live in `fixtures/TtDMUz6TBIc/`:

- `description.txt`, `info.json` (formats/heatmap stripped)
- `TtDMUz6TBIc.txt`, `TtDMUz6TBIc_timestamps.txt` (faster-whisper `small`, CPU, int8)
- `albums.csv` (working notes, including mentions)
- `expected_albums.json` — the acceptance list

## 17. Security and repo rules

- Never commit `.env`, tokens, client secrets, audio caches, or whisper/Ollama weights.
- Client secret is not used and must not be added "for later".
- Draft PR only; do not merge, and do not create a GitHub repo from the agent.
- Personal-use ingest of a YouTube URL the user pasted is in scope; do not add batch scrapers or bypasses of YouTube or Spotify restrictions.
