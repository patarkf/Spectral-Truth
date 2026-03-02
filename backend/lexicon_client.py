"""
Minimal client for Lexicon Local API (http://localhost:48624).

- Enable the API in Lexicon: Settings → Integrations.
- Tracks: GET /v1/tracks (limit, offset).
- Playlists: create/update endpoints to be confirmed (see docs/LEXICON_INTEGRATION.md).
"""
import json
import urllib.error
import urllib.request
from typing import Any, Optional

# Default timeout for local Lexicon server
TIMEOUT = 10


def _url(base: str, path: str) -> str:
    base = base.rstrip("/")
    path = path if path.startswith("/") else "/" + path
    return base + path


def _req(
    base_url: str,
    method: str,
    path: str,
    body: Optional[dict] = None,
    params: Optional[dict] = None,
) -> dict:
    url = _url(base_url, path)
    if params:
        from urllib.parse import urlencode
        url = url + "?" + urlencode(params)
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.data = data
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        raise LexiconAPIError(e.code, e.reason, body)
    except urllib.error.URLError as e:
        raise LexiconConnectionError(str(e.reason))
    except TimeoutError:
        raise LexiconConnectionError("Connection timed out")
    except json.JSONDecodeError as e:
        raise LexiconAPIError(0, "Invalid JSON response", {"detail": str(e)})


class LexiconConnectionError(Exception):
    """Lexicon is not reachable (off, API disabled, or network)."""
    pass


class LexiconAPIError(Exception):
    """Lexicon API returned an error (HTTP 4xx/5xx or invalid response)."""
    def __init__(self, code: int, reason: str, body: dict):
        self.code = code
        self.reason = reason
        self.body = body
        super().__init__(f"Lexicon API error {code}: {reason}")


def get_status(base_url: str) -> dict:
    """
    Check if Lexicon API is reachable.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    try:
        _req(base_url, "GET", "/v1/tracks", params={"limit": 1, "offset": 0})
        return {"ok": True}
    except LexiconConnectionError as e:
        return {"ok": False, "error": str(e)}
    except LexiconAPIError as e:
        # If we get any HTTP response, the server is up (API might be disabled or return error)
        return {"ok": False, "error": f"{e.code}: {e.reason}"}


def _track_path(track: dict) -> Optional[str]:
    """Try to get filesystem path from a Lexicon track object."""
    for key in ("path", "location", "filePath", "file_path", "pathId"):
        v = track.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Some APIs return path list
    pl = track.get("paths") or track.get("pathList") or track.get("locations")
    if isinstance(pl, list) and pl and isinstance(pl[0], str):
        return pl[0].strip()
    if isinstance(pl, list) and pl and isinstance(pl[0], dict):
        p = pl[0].get("path") or pl[0].get("location") or pl[0].get("filePath")
        if isinstance(p, str) and p.strip():
            return p.strip()
    return None


def get_tracks(
    base_url: str,
    limit: int = 100,
    offset: int = 0,
    include_path: bool = True,
) -> dict:
    """
    Fetch a page of tracks from Lexicon.
    Returns {"tracks": [{"id", "title", "artist", "path", "format"}...], "total": N if available}.
    Lexicon allows params as query string or JSON body for GET; we send both for compatibility.
    """
    params = {"limit": limit, "offset": offset}
    body = {"limit": limit, "offset": offset}
    # Some implementations only read GET body, not query string
    raw = _req(base_url, "GET", "/v1/tracks", params=params, body=body)
    # Response shape: Lexicon returns { "data": <array or object> }. If data is an object, list may be inside it.
    data_val = raw.get("tracks") or raw.get("data") or raw.get("items") or raw.get("result") or raw.get("rows")
    if data_val is None and isinstance(raw, list):
        data_val = raw
    tracks_raw = []
    total = raw.get("total") or raw.get("totalCount") or raw.get("count")
    if isinstance(data_val, list):
        tracks_raw = data_val
        if total is None and len(tracks_raw) > 0:
            total = len(tracks_raw)
    elif isinstance(data_val, dict):
        # Nested: e.g. { "data": { "tracks": [...] } } or { "data": { "items": [...] } }
        inner = (
            data_val.get("tracks")
            or data_val.get("data")
            or data_val.get("items")
            or data_val.get("result")
            or data_val.get("rows")
        )
        if isinstance(inner, list):
            tracks_raw = inner
        else:
            # Any key whose value is a list
            for v in data_val.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    tracks_raw = v
                    break
        total = total or data_val.get("total") or data_val.get("totalCount") or data_val.get("count")
    if total is not None and not isinstance(total, int):
        total = int(total) if isinstance(total, (float, str)) and str(total).isdigit() else None
    out = []
    for t in tracks_raw:
        if not isinstance(t, dict):
            continue
        tid = t.get("id") or t.get("trackId") or t.get("uuid")
        if tid is None:
            continue
        row = {
            "id": tid,
            "title": t.get("title") or t.get("name") or "",
            "artist": t.get("artist") or "",
            "format": (t.get("format") or t.get("fileExtension") or "").lower().lstrip("."),
        }
        if include_path:
            row["path"] = _track_path(t)
        out.append(row)
    return {"tracks": out, "total": total}


def get_all_tracks_paginated(
    base_url: str,
    page_size: int = 200,
    max_tracks: Optional[int] = None,
) -> list[dict]:
    """
    Fetch all tracks from Lexicon by paginating. Yields same shape as get_tracks()["tracks"].
    """
    offset = 0
    total_seen = 0
    while True:
        page = get_tracks(base_url, limit=page_size, offset=offset)
        tracks = page.get("tracks") or []
        if not tracks:
            break
        for t in tracks:
            yield t
            total_seen += 1
            if max_tracks is not None and total_seen >= max_tracks:
                return
        if len(tracks) < page_size:
            break
        offset += page_size


# --- Playlists (plugin docs: POST /playlist with name, parentId, type; update trackIds) ---

def get_playlists(base_url: str) -> list[dict]:
    """Fetch all playlists. Returns list of { id, name, ... }."""
    try:
        raw = _req(base_url, "GET", "/v1/playlist", params={"limit": 5000, "offset": 0})
    except LexiconAPIError:
        raw = _req(base_url, "GET", "/v1/playlists", params={"limit": 5000, "offset": 0})
    items = raw.get("playlists", raw.get("playlist", raw.get("data", raw if isinstance(raw, list) else [])))
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict) and x.get("id") is not None]


def create_playlist(base_url: str, name: str, parent_id: Optional[int] = None, type: str = "2") -> dict:
    """Create a playlist. type: '1'=folder, '2'=playlist, '3'=smartlist. Returns created playlist with id."""
    body = {"name": name, "type": type}
    if parent_id is not None:
        body["parentId"] = parent_id
    try:
        return _req(base_url, "POST", "/v1/playlist", body=body)
    except LexiconAPIError:
        return _req(base_url, "POST", "/v1/playlists", body=body)


def update_playlist_tracks(base_url: str, playlist_id: int, track_ids: list[int]) -> dict:
    """Set a playlist's track list. track_ids: list of Lexicon track IDs."""
    body = {"trackIds": track_ids}
    try:
        return _req(base_url, "PATCH", f"/v1/playlist/{playlist_id}", body=body)
    except LexiconAPIError:
        return _req(base_url, "PATCH", f"/v1/playlists/{playlist_id}", body=body)
