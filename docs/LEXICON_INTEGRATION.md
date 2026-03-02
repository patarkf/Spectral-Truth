# Lexicon integration – research and proposal

## What is Lexicon?

[Lexicon](https://www.lexicondj.com/) is a DJ music library management app. It has a **Local REST API** so other apps (like this one) can read and write library data while Lexicon is running.

## Lexicon API – what’s available

- **Base URL:** `http://localhost:48624`
- **Enabled in Lexicon:** Settings → **Integrations** (API is off by default).
- **Auth:** None at the moment (they plan to add it later).

### Tracks

- **GET** `/v1/tracks`  
  - Query/body: `limit`, `offset` (e.g. `{"limit": 10, "offset": 0}`).  
  - Returns track list; you can request specific **fields** (e.g. `fields=title&fields=artist`).  
  - Filtering: e.g. `/search/tracks?filter[artist]=...&filter[title]=...`.

So we can:

- Paginate through the whole library with `limit`/`offset`.
- Request fields needed for our flow (at least **track id** and **file path/location** so we can run the analyzer and then map results back to Lexicon track IDs).

The exact field name for the file path (e.g. `path`, `location`, `filePath`) is not fully documented in the public API reference; the plugin docs refer to the “Track Fields” schema in the Local API reference. In practice we’ll need to call `GET /v1/tracks` once and inspect the response, or check the API reference / Discord if needed.

### Playlists

From the **plugin** documentation (which mirrors the Local API):

- **Create playlist:** same parameters as the **POST /playlist** endpoint:  
  `name`, `parentId`, `type`  
  - `type`: `'1'` = folder, `'2'` = normal playlist, `'3'` = smartlist.
- **Update playlist:** playlist objects have a `trackIds` array; you can set `playlist.trackIds = [id1, id2, ...]` and the API supports updating the `tracks` (or equivalent) field.

So we can:

- Create two playlists, e.g. **“Audio Analyzer – Fake”** and **“Audio Analyzer – Suspicious”**.
- After analyzing Lexicon tracks in our app, we can create/update these playlists with the Lexicon track IDs that got verdict **fake** or **suspicious**.

The exact REST paths (e.g. `POST /v1/playlist` vs `POST /v1/playlists`, and `PATCH /v1/playlist/{id}` for updating `trackIds`) are not fully specified in the public docs; they can be inferred from the plugin examples or confirmed via the API reference / Lexicon Discord (#developers).

### Other

- Cues, beatgrids, tags, custom tags, etc. are available but not required for the “fake/suspicious playlists” workflow.
- **Plugins** run inside Lexicon and use the same API under the hood; our integration uses the **REST API** from this app (no plugin needed).

---

## Suggested integration with this app

### Goal

- Read your music **from Lexicon** (tracks list + file paths).
- **Analyze** those tracks in the Audio Analyzer (existing WAV/FLAC/AIFF logic).
- Create (or update) **Lexicon playlists** for **“Fake”** and **“Suspicious”** so you can quickly find and replace them.

### High-level flow

1. **User** ensures Lexicon is running and the API is enabled (Integrations).
2. **App** calls Lexicon `GET /v1/tracks` (with pagination) and optionally restricts to supported formats (e.g. by file extension in path).
3. **App** runs the existing analyzer on each track’s **file path** (only WAV/FLAC/AIFF).
4. **App** creates or finds two playlists in Lexicon (e.g. “Audio Analyzer – Fake”, “Audio Analyzer – Suspicious”) and sets their **trackIds** to the Lexicon track IDs that received the corresponding verdict.
5. **User** sees the new/updated playlists in Lexicon and can use them to find alternatives.

### Features to implement

| Feature | Description |
|--------|-------------|
| **Lexicon connection check** | GET Lexicon base URL; show in UI whether Lexicon is reachable (and API enabled). |
| **Import library list** | Fetch tracks from Lexicon (id + path + optional title/artist); show count and list in the app (and optionally filter to WAV/FLAC/AIFF). |
| **Analyze from Lexicon** | For each selected (or all) Lexicon tracks with a local path, run `analyze_file(path)` and store results in existing history. |
| **Create “Fake” / “Suspicious” playlists** | Create or update two Lexicon playlists and set their `trackIds` from the analysis results (by Lexicon track id). |
| **One-shot “Sync”** | Single action: fetch tracks → analyze supported files → update the two playlists (with progress/feedback). |

### Technical notes

- **File path:** Lexicon must expose the track’s filesystem path so we can call `analyze_file(path)`. If the API returns a relative path, we may need a configurable “Lexicon library root” to resolve it.
- **Performance:** Large libraries: paginate tracks, analyze in batches, and optionally allow “analyze only selected” or “analyze only new/changed” to avoid re-running every time.
- **Idempotence:** Re-running “create playlists” can **replace** the contents of “Audio Analyzer – Fake” and “Audio Analyzer – Suspicious” with the current analysis results so the playlists stay in sync.

---

## Implementation outline

- **Config:** Add `LEXICON_API_BASE_URL` (default `http://localhost:48624`). No API key for now.
- **Backend:**  
  - Small **Lexicon client** module: `GET /v1/tracks` (paginated), and when documented/confirmed: `POST` create playlist, `PATCH`/`PUT` update playlist `trackIds`.  
  - New routes, e.g.:  
    - `GET /api/lexicon/status` – check if Lexicon is reachable.  
    - `GET /api/lexicon/tracks` – return list of Lexicon tracks (id, path, title, artist, format).  
    - `POST /api/lexicon/analyze` – body: list of Lexicon track ids (or “all”); for each, resolve path, run analyzer, return results and optionally persist to history.  
    - `POST /api/lexicon/playlists/sync` – create or update “Fake” and “Suspicious” playlists from current analysis history (keyed by Lexicon track id or by file path match).  
  - Store **Lexicon track id** in analysis history if we analyze from Lexicon (new column or JSON field), so we can map verdict → Lexicon id when syncing playlists.
- **Frontend:**  
  - **Lexicon** section: status, “Fetch library”, “Analyze from Lexicon”, “Update Fake/Suspicious playlists”, and optionally a combined “Sync” button.  
  - Show last sync time and counts (e.g. fake / suspicious) and link to history filtered by verdict.

---

## References

- [Lexicon Local API](https://www.lexicondj.com/docs/developers/api)  
- [Lexicon Plugins](https://www.lexicondj.com/docs/developers/plugin) (playlist create/update, track fields)  
- [Example plugins (GitHub)](https://github.com/rekordcloud/lexicon-example-plugins) (`playlist.create.js`, `playlist.tracks.js`, `tracks.count.js`)  
- [Lexicon forum – Developers](https://discuss.lexicondj.com/c/advanced/developers/31)  
- [Lexicon Discord](http://chat.lexicondj.com/) (#developers)
