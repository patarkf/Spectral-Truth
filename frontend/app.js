(function () {
  const API = "/api";
  let currentItems = [];
  let sortBy = null;   // "bitrate" | "actual" | null
  let sortOrder = "asc"; // "asc" | "desc"

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
      const rowId = row.id != null ? row.id : "";
      return `
        <tr data-id="${rowId}">
          <td><div class="track-name"><span class="track-icon" aria-hidden="true">♪</span>${name}</div></td>
          <td>${quality}</td>
          <td class="metrics-cell">${bitrate}</td>
          <td class="${actualClass}">${actualText}</td>
          <td class="metrics-cell">${clipping}</td>
          <td class="metrics-cell">${peak}</td>
          <td class="date-cell">${date}</td>
          <td class="size-cell">${size}</td>
          <td class="format-cell">${format}</td>
          <td class="spectrum-cell"><button type="button" class="spectrum-btn" data-id="${rowId}" aria-label="View frequency spectrum">View</button></td>
        </tr>
      `;
    }).join("");
    setupSpectrumButtons();
  }

  // Spek default palette: SoX (Rob Sykes) — blue → purple → red → yellow → white.
  // https://github.com/alexkay/spek/blob/master/src/spek-palette.cc (sox(), PALETTE_DEFAULT = PALETTE_SOX)
  function spectrumPalette(level) {
    level = Math.max(0, Math.min(1, level));
    let r = 0, g = 0, b = 0;
    if (level >= 0.13 && level < 0.73) {
      r = Math.sin(((level - 0.13) / 0.6) * (Math.PI / 2));
    } else if (level >= 0.73) {
      r = 1;
    }
    if (level >= 0.6 && level < 0.91) {
      g = Math.sin(((level - 0.6) / 0.31) * (Math.PI / 2));
    } else if (level >= 0.91) {
      g = 1;
    }
    if (level < 0.6) {
      b = 0.5 * Math.sin((level / 0.6) * Math.PI);
    } else if (level >= 0.78) {
      b = (level - 0.78) / 0.22;
    }
    return [
      Math.round(r * 255),
      Math.round(g * 255),
      Math.round(b * 255)
    ];
  }

  function drawSpectrogram(canvas, data) {
    const freqs = data.freqs || [];
    const times = data.times || [];
    const magDb = data.mag_db || [];
    if (!freqs.length || !times.length || !magDb.length) return;
    const nF = freqs.length;
    const nT = times.length;
    const leftPad = 58;
    const bottomPad = 36;
    const rightPad = 88;
    const topPad = 10;
    const specW = nT;
    const specH = nF;
    const w = leftPad + specW + rightPad;
    const h = topPad + specH + bottomPad;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    // Fixed scale -140 to 0 dB (Spek-style) so quiet content isn't clipped; linear-ish mapping so colors match Spek
    const minDb = -140;
    const maxDb = 0;
    const dbRange = maxDb - minDb;
    const levelCap = 0.82; // no white at top
    const gamma = 1.15;    // near-linear so faint high-freq content is visible (Spek uses linear)
    function dbToLevel(linear) {
      const clamped = Math.max(0, Math.min(1, linear));
      return Math.min(levelCap, Math.pow(clamped, gamma));
    }

    ctx.fillStyle = "#0a0a0e";
    ctx.fillRect(0, 0, w, h);

    // 1:1 pixel mapping (Spek-style): one pixel per (time, freq) — no upscaling = sharp
    const imageData = ctx.createImageData(specW, specH);
    const buf = imageData.data;
    for (let py = 0; py < specH; py++) {
      const fi = specH - 1 - py;
      for (let px = 0; px < specW; px++) {
        const ti = px;
        const db = magDb[fi][ti];
        const linear = (db - minDb) / dbRange;
        const level = dbToLevel(linear);
        const [r, g, b] = spectrumPalette(level);
        const i = (py * specW + px) * 4;
        buf[i] = r;
        buf[i + 1] = g;
        buf[i + 2] = b;
        buf[i + 3] = 255;
      }
    }
    ctx.putImageData(imageData, leftPad, topPad);

    const maxFreq = freqs[nF - 1];
    const durationSec = times[nT - 1] || 0;

    // Styles for axes
    ctx.strokeStyle = "rgba(255,255,255,0.4)";
    ctx.fillStyle = "#e8e8ec";
    ctx.font = "11px Inter, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";

    // Left axis: frequency (kHz)
    ctx.beginPath();
    ctx.moveTo(leftPad, topPad);
    ctx.lineTo(leftPad, topPad + specH);
    ctx.stroke();
    const freqSteps = [0, 5, 10, 15, 20].filter((k) => k <= maxFreq / 1000);
    if (maxFreq / 1000 > 20) freqSteps.push(Math.round(maxFreq / 1000));
    freqSteps.forEach((kHz) => {
      const frac = kHz / (maxFreq / 1000);
      const y = topPad + specH * (1 - frac);
      ctx.fillText(kHz + " kHz", leftPad - 6, y);
    });

    // Bottom axis: time (M:SS) — minute marks like Spek / Faking the Funk
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.beginPath();
    ctx.moveTo(leftPad, topPad + specH);
    ctx.lineTo(leftPad + specW, topPad + specH);
    ctx.stroke();
    const totalMinutes = Math.ceil(durationSec / 60) || 1;
    const step = totalMinutes <= 10 ? 1 : totalMinutes <= 30 ? 5 : Math.ceil(totalMinutes / 6);
    for (let m = 0; m <= totalMinutes; m += step) {
      const x = leftPad + (m / totalMinutes) * specW;
      ctx.fillText(m + ":00", x, topPad + specH + 6);
    }
    const lastMin = Math.floor(durationSec / 60);
    const lastSec = Math.round(durationSec % 60);
    const lastLabel = lastMin + ":" + (lastSec < 10 ? "0" : "") + lastSec;
    ctx.fillText(lastLabel, leftPad + specW, topPad + specH + 6);

    // Right: color bar + dB scale + label (what the colors mean)
    const barW = 12;
    const barX = w - rightPad + 4;
    for (let py = 0; py < specH; py++) {
      const linear = 1 - py / specH;
      const level = levelCap * linear;
      const [r, g, b] = spectrumPalette(level);
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(barX, topPad + py, barW, 2);
    }
    ctx.strokeStyle = "rgba(255,255,255,0.4)";
    ctx.strokeRect(barX, topPad, barW, specH);
    ctx.fillStyle = "#e8e8ec";
    ctx.font = "10px Inter, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    [-140, -120, -100, -80, -60, -40, -20, 0].forEach((db) => {
      const linear = (db - minDb) / dbRange;
      const level = dbToLevel(linear);
      const y = topPad + specH * (1 - level / levelCap);
      ctx.fillText(db + " dB", barX + barW + 6, y);
    });
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = "rgba(232,232,236,0.9)";
    ctx.font = "11px Inter, sans-serif";
    ctx.fillText("Amplitude (dB)", barX + barW / 2, topPad - 4);

    // Border around spectrogram
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.strokeRect(leftPad, topPad, specW, specH);
  }

  function openSpectrumModal(data) {
    const modal = document.getElementById("spectrum-modal");
    const title = document.getElementById("spectrum-modal-title");
    const canvas = document.getElementById("spectrum-canvas");
    const helpPanel = document.getElementById("spectrum-help");
    if (!modal || !title || !canvas) return;
    title.textContent = (data.file_name || "Frequency spectrum") + (data.verdict ? ` (${data.verdict})` : "");
    if (helpPanel) helpPanel.setAttribute("hidden", "");
    drawSpectrogram(canvas, data);
    modal.style.display = "flex";
  }

  function closeSpectrumModal() {
    const modal = document.getElementById("spectrum-modal");
    if (modal) modal.style.display = "none";
  }

  function setupSpectrumButtons() {
    document.querySelectorAll(".spectrum-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!id) return;
        try {
          const res = await fetch(API + "/spectrum?id=" + encodeURIComponent(id), { cache: "no-store" });
          if (res.status === 404) {
            let msg = "Spectrum only available for tracks analyzed from disk (e.g. Lexicon).";
            try {
              const j = await res.json();
              if (j.detail) msg = typeof j.detail === "string" ? j.detail : msg;
            } catch (e) {}
            showStatus(msg, "error");
            return;
          }
          if (!res.ok) throw new Error(await res.text());
          const data = await res.json();
          openSpectrumModal(data);
        } catch (e) {
          showStatus("Error loading spectrum: " + e.message, "error");
        }
      });
    });
  }

  function setupSpectrumModal() {
    const modal = document.getElementById("spectrum-modal");
    const closeBtn = document.getElementById("spectrum-modal-close");
    const infoBtn = document.getElementById("spectrum-modal-info");
    const helpPanel = document.getElementById("spectrum-help");
    const backdrop = modal?.querySelector(".spectrum-modal-backdrop");
    if (closeBtn) closeBtn.addEventListener("click", closeSpectrumModal);
    if (backdrop) backdrop.addEventListener("click", closeSpectrumModal);
    if (infoBtn && helpPanel) {
      infoBtn.addEventListener("click", () => {
        const isHidden = helpPanel.hasAttribute("hidden");
        if (isHidden) helpPanel.removeAttribute("hidden");
        else helpPanel.setAttribute("hidden", "");
      });
    }
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSpectrumModal(); });
  }

  function buildHistoryParams() {
    const search = document.getElementById("search-input")?.value?.trim() || "";
    const verdict = document.getElementById("quality-filter")?.value?.trim() || "";
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (verdict) params.set("verdict", verdict);
    return params.toString();
  }

  async function loadCounts() {
    const el = document.getElementById("quality-counters");
    if (!el) return;
    try {
      const res = await fetch(API + "/history/counts", { cache: "no-store" });
      if (!res.ok) return;
      const c = await res.json();
      const total = c.total || 0;
      if (total === 0) {
        el.innerHTML = "";
        el.style.display = "none";
        return;
      }
      el.style.display = "flex";
      el.innerHTML = `
        <span class="count count-fake">Fake: ${c.fake ?? 0}</span>
        <span class="count count-suspicious">Suspicious: ${c.suspicious ?? 0}</span>
        <span class="count count-real">Real: ${c.real ?? 0}</span>
        <span class="count count-total">Total: ${total}</span>
      `;
    } catch (e) {
      el.innerHTML = "";
      el.style.display = "none";
    }
  }

  function applySort() {
    if (!currentItems.length || !sortBy) {
      renderTable(currentItems);
      return;
    }
    const key = sortBy === "bitrate" ? "bitrate_kbps" : "actual_bitrate_kbps";
    const sorted = [...currentItems].sort((a, b) => {
      const pushNullLast = sortOrder === "asc" ? Infinity : -Infinity;
      const va = a[key] != null ? Number(a[key]) : pushNullLast;
      const vb = b[key] != null ? Number(b[key]) : pushNullLast;
      if (va === vb) return 0;
      const cmp = va < vb ? -1 : 1;
      return sortOrder === "asc" ? cmp : -cmp;
    });
    renderTable(sorted);
  }

  function updateSortButtons() {
    document.querySelectorAll(".th-sort").forEach((btn) => {
      const col = btn.getAttribute("data-sort");
      const label = col === "bitrate" ? "Bitrate" : "Actual";
      const arrow = sortBy === col ? (sortOrder === "asc" ? " ↑" : " ↓") : "";
      btn.textContent = label + arrow;
    });
  }

  function setSort(column) {
    if (sortBy === column) {
      sortOrder = sortOrder === "asc" ? "desc" : "asc";
    } else {
      sortBy = column;
      sortOrder = "asc";
    }
    applySort();
    updateSortButtons();
  }

  async function loadHistory() {
    const q = buildHistoryParams();
    const url = q ? API + "/history?" + q : API + "/history";
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error("Failed to load history");
    const data = await res.json();
    currentItems = data.items || [];
    applySort();
    updateSortButtons();
    loadCounts();
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

  function setupReloadApp() {
    const btn = document.getElementById("reload-app-btn");
    if (btn) btn.addEventListener("click", () => { location.reload(); });
  }

  function setupSortableHeaders() {
    document.querySelectorAll(".th-sort").forEach((btn) => {
      btn.addEventListener("click", () => setSort(btn.getAttribute("data-sort")));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadHistory();
    setupUpload();
    setupExport();
    setupClearHistory();
    setupLexicon();
    setupReloadApp();
    setupSortableHeaders();
    setupSpectrumModal();
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
