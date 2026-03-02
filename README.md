<p align="center">
  <img src="frontend/assets/spectral-truth-favicon.png" width="128" height="128" alt="Spectral Truth" />
</p>

# Spectral Truth

**Spectral Truth** is a local-only app that spots fake or lossy-upconverted “lossless” files (WAV, FLAC, AIFF) using spectral cutoff and clipping checks—in the spirit of tools like VerifAI Audio and Faking the Funk.

- **Analyze** files by upload or by pulling your library from [Lexicon](https://www.lexicondj.com/) (Local API).
- **History** with filters (Fake / Suspicious / Real), search, and CSV/JSON export.
- **Lexicon integration:** create or update “Audio Analyzer – Fake” and “Audio Analyzer – Suspicious” playlists so you can find and replace bad copies.

Stack: Python, FastAPI, SQLite, librosa/scipy; single-page dark UI.

## Stack & architecture

| Layer | Choice | Why |
|-------|--------|-----|
| **Backend** | Python 3.10+ with FastAPI | Async, WebSocket for folder progress, type hints, auto OpenAPI. |
| **Audio analysis** | librosa, soundfile, numpy, scipy | Widely adopted; spectral analysis and FFT are standard. |
| **Database** | SQLite | No server; one file for history and results. |
| **Frontend** | Single-page HTML/CSS/JS | Served by FastAPI; VerifAI-style dark UI, no build step. |

**Detection approach (v1):** Cutoff-frequency analysis using mainstream libraries (librosa, numpy). Lossy codecs (MP3, AAC) discard content above a certain frequency; upconverted “lossless” files keep that brick-wall signature. True lossless (e.g. 44.1 kHz CD) has content up to Nyquist (~22 kHz) with no sharp cutoff below.

- **Effective cutoff:** We compute an average magnitude spectrum and find the highest frequency where level is still within ~35 dB of the peak. Below that, the spectrum has “dropped off”.
- **Reference cutoffs** (from [Erik’s Tech Corner](https://erikstechcorner.com/2020/09/how-to-check-if-your-flac-files-are-really-lossless/) and [spectral analysis literature](https://blog.alex.balgavy.eu/determining-mp3-audio-quality-with-spectral-analysis/)):
  - ≤ 11 kHz → 64 kbps (fake)
  - ≤ 16 kHz → 128 kbps (fake)
  - ≤ 19 kHz → 192 kbps (suspicious)
  - ≤ 20 kHz → 320 kbps (suspicious)
  - Content to Nyquist (~22 kHz at 44.1 kHz) → likely true lossless (real)
- **High-band energy ratio** (e.g. above 15 kHz) is used to reinforce the verdict.

Results are mapped to **Real** / **Suspicious** / **Fake** plus a short diagnostic (e.g. “Sharp cutoff ~16 kHz — consistent with 128 kbps MP3 (fake lossless)” or “No sharp cutoff; content to Nyquist — likely true lossless”). Thresholds and constants are in `backend/analyzer.py` for tuning.

## Project layout

```
spectral-truth/
├── README.md
├── requirements.txt
├── run.py                    # Start server (opens browser)
├── .gitignore
├── backend/
│   ├── __init__.py
│   ├── main.py               # FastAPI app, routes, static serve
│   ├── config.py             # Paths, port, Lexicon API URL
│   ├── database.py            # SQLite schema and access
│   ├── analyzer.py            # Spectral + clipping analysis → verdict
│   └── lexicon_client.py      # Lexicon Local API client
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── docs/
│   ├── ANALYSIS_TECHNIQUES.md
│   └── LEXICON_INTEGRATION.md
└── data/                     # Created at runtime (gitignored)
    └── audio_analyzer.db
```

## Install

**Requirements:** Python 3.9+ (3.10+ recommended).

```bash
# Clone the repo (or download and extract)
cd spectral-truth

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux
#  or  .venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt
```

**Optional – Lexicon integration:** If you use [Lexicon](https://www.lexicondj.com/) and want to analyze your library or sync Fake/Suspicious playlists, enable the Local API in Lexicon: **Settings → Integrations**. No extra install steps; the app talks to Lexicon at `http://localhost:48624` when it’s running.

## Run

```bash
# From the project root, with venv activated
python run.py
```

The app will start on `http://127.0.0.1:8765` and open the page in your browser. The SQLite DB and `data/` folder are created automatically on first run.

## Build plan (phases)

1. **Phase 1 – Core engine**
   - Implement `analyzer.py`: load WAV/FLAC (librosa/soundfile), compute rolloff + high-band energy (and optionally flatness), score → verdict + diagnostic.
   - Add tests on a few known files (one clearly lossy, one true lossless) to calibrate.

2. **Phase 2 – Backend API and DB**
   - SQLite schema: `analyses` (id, file_path, file_name, file_size, format, verdict, score, diagnostic, analyzed_at).
   - FastAPI: `POST /analyze` (single file or list of paths), `GET /history` (with optional search), `GET /export` (CSV/JSON).
   - Optional: `POST /analyze-folder` with WebSocket or polling for progress.

3. **Phase 3 – Web UI**
   - Single page: header “Analysis History”, subtitle “View and manage your past audio analyses”, “Your Analysis History” + search + Export Report.
   - Table: Track name (with icon), Quality (Fake | Suspicious | Real bar + triangle + diagnostic text), Date, Size, Format.
   - Upload area: drag-and-drop + “Add folder” for batch.
   - Wire search and export to the API.

4. **Phase 4 – Polish**
   - Tune detection thresholds from real usage.
   - Add “Analyze folder” with progress indicator.
   - Optional: simple spectrogram view for “why did it flag this?”.

## Formats

- **WAV**, **FLAC**, and **AIFF** (.aif). Other formats may be added later.
