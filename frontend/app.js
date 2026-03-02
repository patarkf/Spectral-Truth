(function () {
  const API = "/api";

  function formatDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  function formatSize(bytes) {
    if (bytes == null) return "—";
    const mb = bytes / (1024 * 1024);
    return mb >= 1 ? mb.toFixed(2) + " MB" : (bytes / 1024).toFixed(1) + " KB";
  }

  function showStatus(message, type) {
    const el = document.getElementById("status");
    if (!el) return;
    el.textContent = message;
    el.className = "status " + (type || "info");
    el.style.display = "block";
    if (type === "success" || type === "error") {
      setTimeout(() => { el.style.display = "none"; }, 4000);
    }
  }

  function renderQualityCell(verdict, diagnostic) {
    const v = (verdict || "").toLowerCase();
    const diag = diagnostic || "";
    return `
      <div class="quality-cell" data-verdict="${v}">
        <div class="quality-bar-wrap">
          <div class="segment fake"></div>
          <div class="segment suspicious"></div>
          <div class="segment real"></div>
          <div class="quality-indicator" aria-hidden="true"></div>
        </div>
        <div class="quality-labels">
          <span>Fake</span>
          <span>Suspicious</span>
          <span>Real</span>
        </div>
        <div class="quality-diagnostic">
          <span class="diag-icon" aria-hidden="true">ⓘ</span>
          <span>${escapeHtml(diag)}</span>
        </div>
      </div>
    `;
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function renderTable(items) {
    const tbody = document.getElementById("history-body");
    const empty = document.getElementById("empty-state");
    if (!tbody) return;

    if (!items || items.length === 0) {
      tbody.innerHTML = "";
      if (empty) empty.style.display = "block";
      const msg = document.getElementById("empty-state-message");
      if (msg) {
        const hasFilter = document.getElementById("quality-filter")?.value || document.getElementById("search-input")?.value?.trim();
        msg.textContent = hasFilter ? "No tracks match this filter." : "No analyses yet. Upload WAV, FLAC, or AIFF files above to start.";
      }
      return;
    }
    if (empty) empty.style.display = "none";

    tbody.innerHTML = items.map((row) => {
      const name = escapeHtml(row.file_name || "—");
      const quality = renderQualityCell(row.verdict, row.diagnostic);
      const MAX_SANE_KBPS = 5000;
      const br = row.bitrate_kbps != null ? Math.round(row.bitrate_kbps) : null;
      const bitrate = br != null && br <= MAX_SANE_KBPS ? br + " kbps" : "—";
      const rawActual = row.actual_bitrate_kbps != null ? row.actual_bitrate_kbps : (row.bitrate_kbps != null ? Math.round(row.bitrate_kbps) : null);
      const actualKbps = rawActual != null && rawActual <= MAX_SANE_KBPS ? Math.round(rawActual) : null;
      const actualText = actualKbps != null ? actualKbps + " kbps" : "—";
      const actualOk = row.verdict === "real" || row.actual_bitrate_kbps === 320;
      const actualClass = actualText === "—" ? "metrics-cell" : (actualOk ? "metrics-cell actual-ok" : "metrics-cell actual-bad");
      const clipping = row.clipping_pct != null ? row.clipping_pct + "%" : "—";
      const peak = row.peak_dbfs != null ? row.peak_dbfs + " dBFS" : "—";
      const date = formatDate(row.analyzed_at);
      const size = formatSize(row.file_size);
      const format = escapeHtml((row.format || "").toUpperCase());
      return `
        <tr>
          <td><div class="track-name"><span class="track-icon" aria-hidden="true">♪</span>${name}</div></td>
          <td>${quality}</td>
          <td class="metrics-cell">${bitrate}</td>
          <td class="${actualClass}">${actualText}</td>
          <td class="metrics-cell">${clipping}</td>
          <td class="metrics-cell">${peak}</td>
          <td class="date-cell">${date}</td>
          <td class="size-cell">${size}</td>
          <td class="format-cell">${format}</td>
        </tr>
      `;
    }).join("");
  }

  function buildHistoryParams() {
    const search = document.getElementById("search-input")?.value?.trim() || "";
    const verdict = document.getElementById("quality-filter")?.value?.trim() || "";
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (verdict) params.set("verdict", verdict);
    return params.toString();
  }

  async function loadHistory() {
    const q = buildHistoryParams();
    const url = q ? API + "/history?" + q : API + "/history";
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error("Failed to load history");
    const data = await res.json();
    renderTable(data.items || []);
  }

  function onSearch() {
    loadHistory();
  }

  function showLoader(visible) {
    const wrap = document.getElementById("loader-wrap");
    if (wrap) wrap.style.display = visible ? "flex" : "none";
  }

  async function analyzeFiles(files) {
    if (!files || files.length === 0) return;
    const form = new FormData();
    for (let i = 0; i < files.length; i++) form.append("files", files[i]);
    showLoader(true);
    showStatus("Analyzing " + files.length + " file(s)...", "info");
    try {
      const res = await fetch(API + "/analyze", { method: "POST", body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const results = data.results || [];
      const ok = results.filter((r) => !r.error).length;
      const err = results.filter((r) => r.error).length;
      showStatus(
        "Done: " + ok + " analyzed" + (err ? ", " + err + " failed" : "") + ".",
        err ? "error" : "success"
      );
      loadHistory();
    } catch (e) {
      showStatus("Error: " + e.message, "error");
    } finally {
      showLoader(false);
    }
  }

  function setupUpload() {
    const input = document.getElementById("file-input");
    const zone = document.getElementById("upload-zone");
    if (!input || !zone) return;

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
      const files = Array.from(e.dataTransfer.files).filter((f) =>
        /\.(wav|flac|aiff|aif)$/i.test(f.name)
      );
      if (files.length) analyzeFiles(files);
      else showStatus("Please drop WAV, FLAC, or AIFF files.", "error");
    });
    input.addEventListener("change", () => {
      const files = input.files;
      if (files && files.length) analyzeFiles(Array.from(files));
      input.value = "";
    });
  }

  function setupExport() {
    const btn = document.getElementById("export-btn");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const format = document.getElementById("export-format")?.value || "csv";
      window.location.href = API + "/export?format=" + format;
    });
  }

  async function clearHistory() {
    if (!confirm("Clear all analysis history? This cannot be undone.")) return;
    try {
      const res = await fetch(API + "/history?clear=1", { method: "GET", cache: "no-store" });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const n = data.deleted != null ? data.deleted : 0;
      renderTable(data.items || []);
      showStatus("History cleared." + (n ? " " + n + " record(s) removed." : ""), "success");
    } catch (e) {
      showStatus("Error: " + e.message, "error");
    }
  }

  function setupClearHistory() {
    const btn = document.getElementById("clear-btn");
    if (!btn) return;
    btn.addEventListener("click", clearHistory);
  }

  async function lexiconRefreshStatus() {
    const el = document.getElementById("lexicon-status");
    if (!el) return;
    try {
      const res = await fetch(API + "/lexicon/status", { cache: "no-store" });
      const data = await res.json();
      if (data.ok) {
        el.textContent = "Lexicon connected";
        el.className = "lexicon-status connected";
      } else {
        el.textContent = "Lexicon not connected (" + (data.error || "enable API in Lexicon → Integrations") + ")";
        el.className = "lexicon-status disconnected";
      }
    } catch (e) {
      el.textContent = "Lexicon not connected";
      el.className = "lexicon-status disconnected";
    }
  }

  function lexiconMessage(msg, type) {
    const el = document.getElementById("lexicon-message");
    if (!el) return;
    el.textContent = msg;
    el.className = "lexicon-message " + (type || "");
    el.style.display = "block";
  }

  async function lexiconFetchLibrary() {
    lexiconMessage("", "");
    try {
      const res = await fetch(API + "/lexicon/tracks?limit=50&offset=0", { cache: "no-store" });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const tracks = data.tracks || [];
      const total = data.total != null ? data.total : tracks.length;
      const count = total > 0 ? total : tracks.length;
      if (count === 0) {
        lexiconMessage(
          "Library reported 0 tracks. If Lexicon has tracks, check the API response: open " + window.location.origin + "/api/lexicon/status?debug=1 in your browser.",
          "error"
        );
      } else {
        lexiconMessage(
          "Library has " + (total > 0 ? total + " track(s)" : count + " track(s) in this page") + ". Run \"Analyze from Lexicon\" to scan WAV/FLAC/AIFF.",
          "info"
        );
      }
    } catch (e) {
      lexiconMessage("Error: " + e.message, "error");
    }
  }

  async function lexiconAnalyze() {
    const btn = document.getElementById("lexicon-analyze-btn");
    if (btn) btn.disabled = true;
    showLoader(true);
    lexiconMessage("Analyzing Lexicon library (WAV/FLAC/AIFF only)…", "info");
    try {
      const res = await fetch(API + "/lexicon/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ all: true }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const a = data.analyzed || 0;
      const s = data.skipped || 0;
      const e = data.errors || 0;
      lexiconMessage("Done: " + a + " analyzed, " + s + " skipped, " + e + " errors.", e ? "error" : "success");
      loadHistory();
    } catch (err) {
      lexiconMessage("Error: " + err.message, "error");
    } finally {
      showLoader(false);
      if (btn) btn.disabled = false;
    }
  }

  async function lexiconSyncPlaylists() {
    const btn = document.getElementById("lexicon-sync-btn");
    if (btn) btn.disabled = true;
    lexiconMessage("Syncing playlists…", "info");
    try {
      const res = await fetch(API + "/lexicon/playlists/sync", { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      lexiconMessage(
        "Playlists updated: " + (data.fake || 0) + " fake, " + (data.suspicious || 0) + " suspicious.",
        "success"
      );
    } catch (err) {
      lexiconMessage("Error: " + err.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function setupLexicon() {
    const fetchBtn = document.getElementById("lexicon-fetch-btn");
    const analyzeBtn = document.getElementById("lexicon-analyze-btn");
    const syncBtn = document.getElementById("lexicon-sync-btn");
    if (fetchBtn) fetchBtn.addEventListener("click", lexiconFetchLibrary);
    if (analyzeBtn) analyzeBtn.addEventListener("click", lexiconAnalyze);
    if (syncBtn) syncBtn.addEventListener("click", lexiconSyncPlaylists);
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadHistory();
    setupUpload();
    setupExport();
    setupClearHistory();
    setupLexicon();
    lexiconRefreshStatus();
    const searchInput = document.getElementById("search-input");
    if (searchInput) {
      searchInput.addEventListener("input", () => onSearch());
      searchInput.addEventListener("keydown", (e) => { if (e.key === "Enter") onSearch(); });
    }
    const qualityFilter = document.getElementById("quality-filter");
    if (qualityFilter) qualityFilter.addEventListener("change", () => loadHistory());
  });
})();
