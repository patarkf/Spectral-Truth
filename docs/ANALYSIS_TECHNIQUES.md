# Analysis techniques for true lossless verification

A research summary of methods to verify that WAV/FLAC files are genuinely lossless (not transcoded from MP3/AAC or otherwise degraded). Written from an audiophile and technical perspective.

---

## What we already do (v1 + v2)

- **Spectral cutoff** – Detect the frequency above which the spectrum “drops off” (brick wall). Map cutoff to estimated source bitrate (64 / 128 / 192 / 320 kbps) using known MP3/lowpass behaviour.
- **High-band energy** – Ratio of energy above ~15 kHz vs total; reinforces the cutoff-based verdict.
- **File bitrate** – From file size and duration; sanity check vs declared format.
- **Clipping %** – Share of samples at digital ceiling (~0.999); indicates heavy limiting or clipping.
- **Peak dBFS** – Maximum level; helps spot crushed dynamics.
- **Smoothed spectrum (v2)** – Rolling mean over ~1% of frequency bins (FakeFLAC-style) for stable cutoff.
- **"Huge fall" detection (v2)** – Steep drop ≥25 dB over a few bins (LAS) → codec brick wall.
- **Multi-segment validation (v2)** – Start/middle/end 30 s segments; use minimum cutoff (any segment lossy → flag).

References: [Erik's Tech Corner](https://erikstechcorner.com/2020/09/how-to-check-if-your-flac-files-are-really-lossless/), [Balgavy spectral analysis](https://blog.alex.balgavy.eu/determining-mp3-audio-quality-with-spectral-analysis/), [FakingTheFunk](https://fakinthefunk.net/).

---

## Additional techniques we could add (v2+)

### 1. **Smoother cutoff detection (rolling average)**

**Idea:** Lossy encoders apply a lowpass; the transition can be sharp. Averaging the spectrum over time and smoothing it (e.g. rolling average over frequency) gives a cleaner “contour” and reduces false triggers from single-frame spikes.

**Source:** [FakeFLAC (van der Schee)](https://www.maurits.vdschee.nl/fakeflac/) – average spectrum over ~30 s, normalize with log10, then rolling average over 1/100 of the frequency range to get a stable line and detect missing highs.

**Audiophile angle:** Reduces false positives on material with natural spectral dips (e.g. some vinyl, old masters) so we don’t flag real lossless as fake.

---

### 2. **“Huge fall” / steepness of drop**

**Idea:** Don’t only look at *where* the spectrum ends, but *how* it drops. A very steep drop over a narrow band (e.g. >25 dB over a few bins) is typical of codec lowpass; true lossless usually has a gentler roll-off near Nyquist.

**Source:** [LAS (Lossy Audio Spotter)](https://blog.pkh.me/p/6-las-lossy-audio-spotter.html) – scan from high to low frequency and detect either (a) sudden fluctuation vs neighbours, or (b) a “huge fall” (e.g. >25 dB over a small window). Threshold ~21 kHz to call lossy vs lossless.

**Audiophile angle:** Complements cutoff frequency; helps separate “codec brick wall” from “natural” or anti-aliasing roll-off.

---

### 3. **Spectral flatness in the high band**

**Idea:** In the band above ~15–18 kHz, lossy often leaves a flatter, more “noise-like” residue; true lossless can have more structured (tonal/harmonic) content. Spectral flatness (geometric mean / arithmetic mean of magnitude spectrum) in that band can be one more feature.

**Source:** General signal processing; [librosa `spectral_flatness`](https://librosa.org/doc/latest/generated/librosa.feature.spectral_flatness.html). FLAC Detective and similar tools use multiple spectral-derived rules.

**Audiophile angle:** Extra discriminant for “suspicious” files (e.g. upscaled or processed) without relying only on cutoff.

---

### 4. **Multi-segment / multi-window validation**

**Idea:** Analyze several segments (e.g. first 30 s, middle, end). If only one segment shows a low cutoff, it might be silence or very soft content; if *all* segments show the same cutoff, stronger evidence of a global codec limit.

**Source:** FLAC Detective’s “multi-segment validation”; [FakeFLAC](https://www.maurits.vdschee.nl/fakeflac/) uses first 30 s only but averaging many windows.

**Audiophile angle:** Fewer false positives on intros/outros or tracks with long quiet parts.

---

### 5. **Pre-echo / transient artifacts (advanced)**

**Idea:** Transform codecs (MP3, AAC) can produce “pre-echo”: smearing of quantization noise *before* sharp transients (e.g. cymbals, castanets). Detecting this in the time domain or via a transient-sensitive representation could flag prior lossy encoding.

**Source:** [Pre-echo (Wikipedia)](https://en.wikipedia.org/wiki/Pre-echo), [LAME pre-echo](https://lame.sourceforge.io/preecho.php); FLAC Detective mentions “compression artifact detection”.

**Audiophile angle:** Directly targets a *sound* that audiophiles dislike; good for “sounds like MP3” even when spectrum is borderline.

**Caveat:** Needs careful tuning and possibly per-codec models; higher implementation cost.

---

### 6. **Blockiness / “knocked-out” regions in spectrogram**

**Idea:** Lossy codecs work in blocks/frames. Transcoded files can show “blocky” or rectangular patterns in a time–frequency spectrogram (missing or attenuated regions that follow encoder block boundaries).

**Source:** [DJ Basilisk](https://djbasilisk.com/resources/verifying-lossless-audio-quality-with-spectral-analysis/), [iPlayer fake FLAC guide](https://www.iplayermusic.com/en/blog/fake-lossless-flac-guide-2026.html).

**Audiophile angle:** Visual/algorithmic counterpart to “weird gaps” or “hollow” highs that careful listeners report on transcodes.

**Caveat:** Likely needs 2D (time–frequency) analysis and pattern heuristics; more complex.

---

### 7. **Allow cutoffs above X Hz (configurable)**

**Idea:** Hi-res (e.g. 24/96, 24/192) and some masters have little or no content above ~24–32 kHz. A fixed “lossless = content to 22 kHz” rule can false-positive on them. Let the user set “allow cutoffs above XXX Hz” so files with cutoff at e.g. 30 kHz are not flagged as lossy.

**Source:** [FakingTheFunk forum](http://fakin-the-funk.125.s1.nabble.com/Actual-Bitrate-td834.html) – they mention this option for hi-res.

**Audiophile angle:** Aligns with real high-res and “extended but not full-band” masters.

---

### 8. **Dynamic range / crest factor (informational)**

**Idea:** Don’t use as a lossy detector, but report RMS or dynamic range (e.g. dB between peak and average level). Heavily limited “loudness war” material has low dynamic range; audiophiles care about this for quality assessment.

**Source:** Standard metering; [EBU R128](https://tech.ebu.ch/docs/r/r128.pdf), [Audio Precision dynamic range](https://www.ap.com/news/measuring-dynamic-range-in-apx500/).

**Audiophile angle:** “True lossless” can still be badly mastered; DR is a separate, complementary metric.

---

### 9. **Noise floor in very high band (e.g. 20–22 kHz)**

**Idea:** In true 44.1 kHz lossless, the band just below Nyquist can contain low-level content or dither. Some transcodes show *no* energy there at all. Quantifying “energy in top octave” (e.g. 18–22 kHz) as a ratio or level could reinforce lossless vs lossy.

**Source:** Implied by spectrum-based tools; we already use high-band energy but could narrow the band and report it explicitly.

**Audiophile angle:** One more “is there real information up there?” check.

---

### 10. **AI upscaling / artificial high-frequency “fog”**

**Idea:** Some tools add synthetic content above 20 kHz. That can look like “full spectrum” but with a uniform, artificial character (“fog”) rather than natural instrument overtones. Detecting overly uniform or statistically odd content above 20 kHz could flag “fake hi-res” or processed upscaling.

**Source:** [2026 fake FLAC guide](https://www.iplayermusic.com/en/blog/fake-lossless-flac-guide-2026.html).

**Audiophile angle:** Protects against “lossless by format but not by origin” (e.g. upscaled MP3 or AI-enhanced).

**Caveat:** Research and tuning needed; may need training data or heuristics.

---

## Suggested priority for v2

| Priority | Technique | Why |
|----------|-----------|-----|
| **High** | Smoother cutoff + “huge fall” detection | More stable and reliable than raw cutoff; well documented (FakeFLAC, LAS). |
| **High** | Multi-segment validation | Fewer false positives on intros/outros and quiet segments. |
| **Medium** | Configurable “allow cutoff above X Hz” | Respects hi-res and non-full-band masters. |
| **Medium** | Spectral flatness in high band | Extra signal for “suspicious” without heavy new dependencies. |
| **Medium** | Dynamic range (informational) | Audiophile-relevant; does not replace lossy detection. |
| **Lower** | Pre-echo / transient artifacts | Strong signal but harder to implement and tune. |
| **Lower** | Blockiness / 2D spectrogram | Good conceptually; implementation and robustness are non-trivial. |
| **Later** | AI upscaling / high-band “fog” | Newer threat; needs more research and possibly ML. |

---

## References (short list)

- [Erik's Tech Corner – Check if FLAC is really lossless](https://erikstechcorner.com/2020/09/how-to-check-if-your-flac-files-are-really-lossless/)
- [Balgavy – MP3 quality via spectral analysis](https://blog.alex.balgavy.eu/determining-mp3-audio-quality-with-spectral-analysis/)
- [FakingTheFunk](https://fakinthefunk.net/) and [forum (Actual Bitrate)](http://fakin-the-funk.125.s1.nabble.com/Actual-Bitrate-td834.html)
- [FakeFLAC – Detecting fake FLAC (van der Schee)](https://www.maurits.vdschee.nl/fakeflac/)
- [LAS – Lossy Audio Spotter (blog.pkh.me)](https://blog.pkh.me/p/6-las-lossy-audio-spotter.html)
- [DJ Basilisk – Verifying lossless with spectral analysis](https://djbasilisk.com/resources/verifying-lossless-audio-quality-with-spectral-analysis/)
- [HydrogenAudio – Distinguishing lossless vs lossy](https://hydrogenaudio.org/)
- [Pre-echo (Wikipedia)](https://en.wikipedia.org/wiki/Pre-echo)
- [librosa – spectral_flatness, spectral_rolloff](https://librosa.org/doc/latest/feature.html)

---

*This document is a living summary for the Audio Analyzer project. Prioritisation reflects a balance between impact, implementation cost, and audiophile relevance.*
