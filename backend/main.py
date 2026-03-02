"""FastAPI app: analyze routes, history, export, static frontend."""
import csv
import io
import json
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Body
from fastapi.responses import FileResponse, StreamingResponse

from backend.config import HOST, PORT, ALLOWED_EXTENSIONS, LEXICON_API_BASE_URL
from backend.database import (
    init_db,
    insert_analysis,
    get_history,
    get_all_for_export,
    clear_history,
    get_verdict_counts,
    get_lexicon_track_ids_by_verdict,
    get_analysis_by_id,
)
from backend.analyzer import analyze_file, compute_spectrogram, ALLOWED_SUFFIXES
from backend import lexicon_client

APP_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = APP_DIR.parent / "frontend"

app = FastAPI(title="Audio Analyzer", version="0.1.0")


@app.on_event("startup")
def startup():
    init_db()


def _check_path_allowed(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def _analyze_one(original_name: str, contents: bytes, suf: str, lexicon_track_id: Optional[int] = None) -> dict:
    """Run analysis on one file's contents; return result dict or error."""
    try:
        with tempfile.NamedTemporaryFile(suffix=suf, delete=False) as tmp:
            tmp.write(contents)
            tmp.flush()
            tmp_path = tmp.name
        try:
            out = analyze_file(tmp_path)
            out["file_size"] = len(contents)
            out["file_name"] = original_name
            out["file_path"] = original_name
            row_id = insert_analysis(
                file_path=original_name,
                file_name=original_name,
                file_size=out["file_size"],
                format=out["format"],
                verdict=out["verdict"],
                score=out["score"],
                diagnostic=out.get("diagnostic"),
                duration_sec=out.get("duration_sec"),
                bitrate_kbps=out.get("bitrate_kbps"),
                actual_bitrate_kbps=out.get("actual_bitrate_kbps"),
                clipping_pct=out.get("clipping_pct"),
                peak_dbfs=out.get("peak_dbfs"),
                lexicon_track_id=lexicon_track_id,
            )
            out["id"] = row_id
            return out
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        return {"file_name": original_name, "error": str(e)}


def _analyze_path(file_path: str, file_name: str, lexicon_track_id: Optional[int] = None) -> dict:
    """Run analysis on a file on disk; return result dict or error."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return {"file_name": file_name, "error": "File not found"}
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return {"file_name": file_name, "error": f"Unsupported format: {path.suffix}"}
    try:
        out = analyze_file(path)
        out["file_path"] = str(path)
        out["file_name"] = file_name or path.name
        row_id = insert_analysis(
            file_path=str(path),
            file_name=out["file_name"],
            file_size=out.get("file_size", 0),
            format=out["format"],
            verdict=out["verdict"],
            score=out["score"],
            diagnostic=out.get("diagnostic"),
            duration_sec=out.get("duration_sec"),
            bitrate_kbps=out.get("bitrate_kbps"),
            actual_bitrate_kbps=out.get("actual_bitrate_kbps"),
            clipping_pct=out.get("clipping_pct"),
            peak_dbfs=out.get("peak_dbfs"),
            lexicon_track_id=lexicon_track_id,
        )
        out["id"] = row_id
        return out
    except Exception as e:
        return {"file_name": file_name or path.name, "error": str(e)}


@app.post("/api/analyze")
async def analyze_upload(files: list[UploadFile] = File(...)):
    """Analyze one or more uploaded WAV/FLAC/AIFF files."""
    if not files:
        raise HTTPException(400, "No files provided")
    results = []
    for f in files:
        if not f.filename:
            continue
        suf = Path(f.filename).suffix.lower()
        if suf not in ALLOWED_SUFFIXES:
            results.append({"file_name": f.filename, "error": f"Unsupported format: {suf}"})
            continue
        try:
            contents = await f.read()
            results.append(_analyze_one(f.filename, contents, suf))
        except Exception as e:
            results.append({"file_name": f.filename, "error": str(e)})
    return {"results": results}


@app.get("/api/history")
def history(
    search: Optional[str] = Query(None),
    verdict: Optional[str] = Query(None),
    limit: int = Query(500, le=2000),
    clear: Optional[str] = Query(None),
):
    """Return history. If clear=1, clear all. Optional verdict filter: fake, suspicious, real."""
    if clear == "1":
        deleted = clear_history()
        return {"items": [], "cleared": True, "deleted": deleted}
    return {"items": get_history(search=search, verdict=verdict, limit=limit)}


@app.get("/api/history/counts")
def history_counts():
    """Return counts by verdict: fake, suspicious, real, total."""
    return get_verdict_counts()


@app.get("/api/spectrum")
def spectrum(id: int = Query(..., description="Analysis id")):
    """
    Return spectrogram data for a track (freqs, times, mag_db) for display.
    Only works when the analysis has a file_path that exists on disk (e.g. from Lexicon).
    """
    row = get_analysis_by_id(id)
    if not row:
        raise HTTPException(404, "Analysis not found")
    file_path = row.get("file_path") or ""
    path = Path(file_path)
    if not path.is_absolute() or not path.exists() or not path.is_file():
        raise HTTPException(
            404,
            "Spectrum only available for tracks analyzed from disk (e.g. Lexicon). File path not found.",
        )
    try:
        data = compute_spectrogram(path)
        data["file_name"] = row.get("file_name")
        data["verdict"] = row.get("verdict")
        return data
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _lexicon_debug_shape():
    """Fetch Lexicon GET /v1/tracks once and return response shape (keys only, no track data)."""
    try:
        raw = lexicon_client._req(
            LEXICON_API_BASE_URL, "GET", "/v1/tracks",
            params={"limit": 2, "offset": 0},
            body={"limit": 2, "offset": 0},
        )
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}
    top_keys = list(raw.keys()) if isinstance(raw, dict) else None
    is_list = isinstance(raw, list)
    sample = None
    data_val = raw.get("data") or raw.get("tracks") or raw.get("items") if isinstance(raw, dict) else None
    if isinstance(data_val, list) and data_val and isinstance(data_val[0], dict):
        sample = list(data_val[0].keys())
    elif isinstance(data_val, dict):
        for v in data_val.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                sample = list(v[0].keys())
                break
    if sample is None and is_list and len(raw) > 0 and isinstance(raw[0], dict):
        sample = list(raw[0].keys())
    elif sample is None and isinstance(raw, dict):
        for key in ("tracks", "data", "items", "result", "rows"):
            arr = raw.get(key)
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                sample = list(arr[0].keys())
                break
    return {"top_level_keys": top_keys, "is_list": is_list, "sample_track_keys": sample, "data_is_list": isinstance(data_val, list) if data_val is not None else None}


@app.get("/api/lexicon/status")
def lexicon_status(debug: Optional[str] = Query(None)):
    """
    Check if Lexicon Local API is reachable.
    If ?debug=1, also return the shape of Lexicon's tracks response (so we can fix parsing).
    """
    out = lexicon_client.get_status(LEXICON_API_BASE_URL)
    if debug == "1":
        out["debug"] = _lexicon_debug_shape()
    return out


@app.get("/api/lexicon/tracks")
def lexicon_tracks(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Fetch a page of tracks from Lexicon (id, title, artist, path, format)."""
    try:
        return lexicon_client.get_tracks(LEXICON_API_BASE_URL, limit=limit, offset=offset)
    except lexicon_client.LexiconConnectionError as e:
        raise HTTPException(503, detail=str(e))
    except lexicon_client.LexiconAPIError as e:
        raise HTTPException(e.code if 400 <= e.code < 600 else 502, detail=e.reason)


FAKE_PLAYLIST_NAME = "Audio Analyzer – Fake"
SUSPICIOUS_PLAYLIST_NAME = "Audio Analyzer – Suspicious"


@app.post("/api/lexicon/analyze")
def lexicon_analyze(body: dict = Body(...)):
    """
    Analyze Lexicon library tracks. Body: { "all": true } or { "trackIds": [1, 2, ...] }.
    Only WAV/FLAC/AIFF with a valid path are analyzed; results are stored with lexicon_track_id.
    """
    try:
        all_tracks = body.get("all") is True
        track_ids = body.get("trackIds")
        if not all_tracks and not isinstance(track_ids, list):
            raise HTTPException(400, "Provide 'all': true or 'trackIds': [ ... ]")
        if all_tracks:
            tracks = list(lexicon_client.get_all_tracks_paginated(LEXICON_API_BASE_URL))
        else:
            tracks = []
            offset = 0
            page_size = 200
            needed = set(int(x) for x in track_ids)
            while needed:
                page = lexicon_client.get_tracks(LEXICON_API_BASE_URL, limit=page_size, offset=offset)
                for t in page.get("tracks") or []:
                    raw_id = t.get("id")
                    tid = int(raw_id) if raw_id is not None else None
                    if tid is not None and tid in needed:
                        t["id"] = tid
                        tracks.append(t)
                        needed.discard(tid)
                if len(page.get("tracks") or []) < page_size:
                    break
                offset += page_size
        results = []
        analyzed = 0
        skipped = 0
        errors = 0
        for t in tracks:
            path = t.get("path")
            if not path or not isinstance(path, str) or not path.strip():
                skipped += 1
                continue
            suf = Path(path).suffix.lower()
            if suf not in ALLOWED_EXTENSIONS:
                skipped += 1
                continue
            name = t.get("title") or t.get("artist") or Path(path).name
            tid = t.get("id")
            out = _analyze_path(path.strip(), name, lexicon_track_id=int(tid) if tid is not None else None)
            results.append(out)
            if "error" in out:
                errors += 1
            else:
                analyzed += 1
        return {
            "analyzed": analyzed,
            "skipped": skipped,
            "errors": errors,
            "results": results,
        }
    except lexicon_client.LexiconConnectionError as e:
        raise HTTPException(503, detail=str(e))
    except lexicon_client.LexiconAPIError as e:
        raise HTTPException(e.code if 400 <= e.code < 600 else 502, detail=e.reason)


@app.post("/api/lexicon/playlists/sync")
def lexicon_playlists_sync():
    """
    Create or update Lexicon playlists "Audio Analyzer – Fake" and "Audio Analyzer – Suspicious"
    with track IDs from analysis history (only rows that have lexicon_track_id set).
    """
    try:
        by_verdict = get_lexicon_track_ids_by_verdict()
        fake_ids = by_verdict.get("fake") or []
        suspicious_ids = by_verdict.get("suspicious") or []
        playlists = lexicon_client.get_playlists(LEXICON_API_BASE_URL)
        by_name = {p.get("name"): p for p in playlists if p.get("name")}

        def ensure_playlist(name: str) -> int:
            if name in by_name:
                return int(by_name[name]["id"])
            created = lexicon_client.create_playlist(LEXICON_API_BASE_URL, name, type="2")
            pid = created.get("id") if isinstance(created.get("id"), int) else int(created["id"])
            return pid

        fake_pl_id = ensure_playlist(FAKE_PLAYLIST_NAME)
        suspicious_pl_id = ensure_playlist(SUSPICIOUS_PLAYLIST_NAME)
        lexicon_client.update_playlist_tracks(LEXICON_API_BASE_URL, fake_pl_id, fake_ids)
        lexicon_client.update_playlist_tracks(LEXICON_API_BASE_URL, suspicious_pl_id, suspicious_ids)
        return {
            "fake": len(fake_ids),
            "suspicious": len(suspicious_ids),
            "playlists_updated": True,
        }
    except lexicon_client.LexiconConnectionError as e:
        raise HTTPException(503, detail=str(e))
    except lexicon_client.LexiconAPIError as e:
        raise HTTPException(e.code if 400 <= e.code < 600 else 502, detail=e.reason)


@app.get("/api/export")
def export_report(fmt: str = Query("csv", pattern="^(csv|json)$", alias="format")):
    """Export full history as CSV or JSON."""
    rows = get_all_for_export()
    if fmt == "json":
        import json
        return StreamingResponse(
            io.BytesIO(json.dumps(rows, indent=2).encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audio_analyzer_history.json"},
        )
    # CSV
    if not rows:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["file_path", "file_name", "file_size", "format", "verdict", "score", "diagnostic", "analyzed_at"])
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audio_analyzer_history.csv"},
        )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(rows[0].keys())
    for r in rows:
        w.writerow(r.values())
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audio_analyzer_history.csv"},
    )


# Serve frontend: explicit routes so /api is never handled by static file handling
@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html", media_type="text/html")


@app.get("/styles.css")
def serve_css():
    return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")


@app.get("/app.js")
def serve_js():
    return FileResponse(FRONTEND_DIR / "app.js", media_type="application/javascript")


@app.get("/assets/spectral-truth-favicon.png")
def serve_favicon():
    return FileResponse(FRONTEND_DIR / "assets" / "spectral-truth-favicon.png", media_type="image/png")


@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(FRONTEND_DIR / "manifest.json", media_type="application/manifest+json")


def run():
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    run()
