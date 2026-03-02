"""
Analyze WAV/FLAC for signs of lossy-to-lossless upscaling (fake lossless).

Detection is based on spectral cutoff frequency: lossy codecs (MP3, AAC) discard
content above a certain frequency, so upconverted files keep that "brick wall"
signature. True lossless (e.g. CD 44.1 kHz) has content up to ~22 kHz.

References:
- https://erikstechcorner.com/2020/09/how-to-check-if-your-flac-files-are-really-lossless/
- https://blog.alex.balgavy.eu/determining-mp3-audio-quality-with-spectral-analysis/
"""
from pathlib import Path
from typing import Literal, Union, Tuple, Optional

import librosa
import numpy as np

Verdict = Literal["real", "suspicious", "fake"]
ALLOWED_SUFFIXES = {".wav", ".flac", ".aiff", ".aif"}

# Cutoff frequency (Hz) vs likely source bitrate — from Erik's Tech Corner & spectral analysis literature.
# If the spectrum has a sharp cutoff at or below these frequencies, the file was likely transcoded from that bitrate.
CUTOFF_64_KBPS_HZ = 11000   # 64 kbps
CUTOFF_128_KBPS_HZ = 16000  # 128 kbps (often 16–17 kHz in practice)
CUTOFF_192_KBPS_HZ = 19000  # 192 kbps
CUTOFF_320_KBPS_HZ = 20000  # 320 kbps
# True lossless (44.1 kHz) extends to Nyquist ~22.05 kHz with no sharp cutoff below that.

# Verdict thresholds: score 0 = fake, 1 = real
FAKE_THRESHOLD = 0.35
SUSPICIOUS_THRESHOLD = 0.65

# How far below peak (dB) to consider "effective cutoff" — lossy has sharp drop
CUTOFF_DB_BELOW_PEAK = 35.0
# "Huge fall" over a few bins (LAS): > this many dB = codec-style brick wall
HUGE_FALL_DB = 25.0
HUGE_FALL_WINDOW_BINS = 5
# Smoothing: rolling window over 1% of spectrum bins (FakeFLAC-style)
SMOOTH_WINDOW_PCT = 0.01
# Multi-segment: segment length in seconds; we take start, middle, end
SEGMENT_DURATION_SEC = 30


def _db(x: float) -> float:
    """Linear magnitude to dB (avoid log(0))."""
    return 10.0 * np.log10(x + 1e-12)


def _smooth_spectrum_db(mag: np.ndarray) -> np.ndarray:
    """Convert to dB and apply rolling mean over ~1% of bins for stable cutoff (FakeFLAC-style)."""
    mag_db = _db(mag)
    n = len(mag_db)
    window = max(5, int(n * SMOOTH_WINDOW_PCT))
    kernel = np.ones(window) / window
    smoothed = np.convolve(mag_db, kernel, mode="same")
    return np.asarray(smoothed, dtype=np.float64)


def _effective_cutoff_hz(mag_db: np.ndarray, freqs: np.ndarray, peak_db: float) -> float:
    """Highest frequency where magnitude is still above (peak_db - CUTOFF_DB_BELOW_PEAK)."""
    nyquist = freqs[-1] if len(freqs) else 0
    threshold_db = peak_db - CUTOFF_DB_BELOW_PEAK
    above = np.where(mag_db >= threshold_db)[0]
    if len(above) == 0:
        return 0.0
    return float(freqs[above[-1]])


def _huge_fall_hz(mag_db: np.ndarray, freqs: np.ndarray) -> Optional[float]:
    """
    Detect a steep drop (codec brick wall). LAS: if mag_db[i] - mag_db[i+window] > 25 dB,
    that's the cutoff. Scan from high to low, return frequency at top of first such fall.
    """
    n = len(mag_db)
    w = HUGE_FALL_WINDOW_BINS
    if n < w + 1:
        return None
    for i in range(n - w - 1, 0, -1):
        if mag_db[i] - mag_db[i + w] >= HUGE_FALL_DB:
            return float(freqs[i])
    return None


def _analyze_one_segment(y_seg: np.ndarray, sr: int) -> Tuple[float, float, np.ndarray, np.ndarray]:
    """
    Analyze one segment: return (cutoff_hz, peak_db, mag_smooth_db, freqs).
    Uses smoothed spectrum and combines threshold cutoff with huge-fall cutoff (take lower = more conservative).
    """
    if y_seg.ndim == 2:
        y_seg = y_seg.mean(axis=1)
    n_fft = 4096
    hop = n_fft // 2
    S = np.abs(librosa.stft(y_seg, n_fft=n_fft, hop_length=hop))
    mag = np.mean(S, axis=1)
    mag_smooth_db = _smooth_spectrum_db(mag)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)[: mag.shape[0]]
    peak_db = float(np.max(mag_smooth_db))

    cutoff_threshold = _effective_cutoff_hz(mag_smooth_db, freqs, peak_db)
    cutoff_fall = _huge_fall_hz(mag_smooth_db, freqs)
    if cutoff_fall is not None and cutoff_fall < cutoff_threshold:
        cutoff_hz = cutoff_fall
    else:
        cutoff_hz = cutoff_threshold
    return cutoff_hz, peak_db, mag_smooth_db, freqs


def _analyze_spectral(y: np.ndarray, sr: int):
    """
    v2: Multi-segment validation + smoothed spectrum + huge-fall detection.
    Compute score [0,1], diagnostic, and estimated source bitrate (kbps or None for lossless).
    """
    if y.ndim == 2:
        y_mono = np.asarray(y.mean(axis=0), dtype=np.float64)
    else:
        y_mono = np.asarray(y, dtype=np.float64).ravel()
    n_frames = len(y_mono)
    duration_sec = n_frames / sr if sr else 0
    segment_samples = int(SEGMENT_DURATION_SEC * sr)
    nyquist = sr / 2.0

    cutoffs = []
    if duration_sec <= SEGMENT_DURATION_SEC * 1.5:
        # Short file: one segment (full length)
        seg = y_mono[-segment_samples:] if n_frames > segment_samples else y_mono
        cutoff_hz, _, _, _ = _analyze_one_segment(seg, sr)
        cutoffs.append(cutoff_hz)
    else:
        # Multi-segment: start, middle, end (FakeFLAC/LAS/FLAC Detective style)
        for start in [
            0,
            max(0, (n_frames - segment_samples) // 2),
            max(0, n_frames - segment_samples),
        ]:
            end = min(start + segment_samples, n_frames)
            seg = y_mono[start:end]
            if len(seg) < 1024:
                continue
            cutoff_hz, _, _, _ = _analyze_one_segment(seg, sr)
            cutoffs.append(cutoff_hz)
    if not cutoffs:
        cutoffs = [0.0]

    # Conservative: use minimum cutoff across segments (any segment showing lossy → flag)
    cutoff_hz = float(np.min(cutoffs))

    # Score and high-band energy from first segment (or only segment)
    if duration_sec <= SEGMENT_DURATION_SEC * 1.5:
        seg = y_mono[-segment_samples:] if len(y_mono) > segment_samples else y_mono
        _, _, mag_db, freqs = _analyze_one_segment(seg, sr)
    else:
        _, _, mag_db, freqs = _analyze_one_segment(y_mono[:segment_samples], sr)
    high_cut_hz = 15000.0
    high_mask = freqs >= high_cut_hz
    mag_linear = 10.0 ** (mag_db / 10.0)
    total_energy = np.sum(mag_linear ** 2)
    high_energy = np.sum(mag_linear[high_mask] ** 2)
    high_ratio = (high_energy / total_energy) if total_energy > 0 else 0.0
    high_norm = min(1.0, high_ratio * 25.0)
    cutoff_norm = (cutoff_hz / nyquist) if nyquist > 0 else 0.0
    score = 0.65 * cutoff_norm + 0.35 * high_norm

    actual_kbps = None
    if cutoff_hz <= CUTOFF_64_KBPS_HZ:
        diagnostic = "Sharp cutoff ~11 kHz — consistent with 64 kbps (fake lossless)"
        actual_kbps = 64
    elif cutoff_hz <= CUTOFF_128_KBPS_HZ:
        diagnostic = "Sharp cutoff ~16 kHz — consistent with 128 kbps MP3 (fake lossless)"
        actual_kbps = 128
    elif cutoff_hz <= CUTOFF_192_KBPS_HZ:
        diagnostic = "Cutoff ~19 kHz — consistent with 192 kbps (possibly upscaled)"
        actual_kbps = 192
    elif cutoff_hz <= CUTOFF_320_KBPS_HZ:
        diagnostic = "Cutoff ~20 kHz — consistent with 320 kbps (possibly upscaled)"
        actual_kbps = 320
    elif cutoff_hz >= nyquist * 0.92:
        diagnostic = "No sharp cutoff; content to Nyquist — likely true lossless"
    else:
        diagnostic = "High-frequency content present; likely lossless"

    return float(np.clip(score, 0.0, 1.0)), diagnostic, actual_kbps


def _analyze_clipping(y: np.ndarray):
    """Return clipping_pct (0–100) and peak_dbfs (max level in dBFS). y is mono float [-1, 1]."""
    if y.ndim == 2:
        y = y.mean(axis=1)
    y = np.asarray(y, dtype=np.float64).ravel()
    n = len(y)
    if n == 0:
        return 0.0, -np.inf
    # Clipping: samples at or very near ±1 (digital ceiling)
    clip_threshold = 0.999
    clipped = np.sum(np.abs(y) >= clip_threshold)
    clipping_pct = 100.0 * clipped / n
    # Peak in dBFS (0 dBFS = full scale)
    peak_linear = float(np.max(np.abs(y)))
    peak_dbfs = 20.0 * np.log10(peak_linear + 1e-12)
    return round(clipping_pct, 4), round(peak_dbfs, 2)


def analyze_file(path: Union[str, Path]) -> dict:
    """
    Load one WAV/FLAC, run spectral + clipping checks, return verdict and metadata.
    """
    path = Path(path)
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported format: {path.suffix}")

    file_size = path.stat().st_size
    fmt = path.suffix.lower().lstrip(".")

    y, sr = librosa.load(path, sr=None, mono=False)
    score, diagnostic, actual_kbps = _analyze_spectral(y, sr)
    clipping_pct, peak_dbfs = _analyze_clipping(y)

    # Duration: use sample count (y.shape[-1] works for mono or stereo)
    n_frames = int(y.shape[-1]) if y.ndim >= 1 else 0
    duration_sec = n_frames / sr if sr and n_frames else 0
    # File bitrate: (file_size_bytes * 8) / duration_sec → kbps (rounded to integer)
    bitrate_kbps = round((file_size * 8) / (duration_sec * 1000)) if duration_sec > 0 else None

    if score < FAKE_THRESHOLD:
        verdict: Verdict = "fake"
    elif score < SUSPICIOUS_THRESHOLD:
        verdict = "suspicious"
        if actual_kbps is None:
            diagnostic = (
                f"Borderline: no low cutoff detected (full bitrate) but high-frequency content "
                f"below typical lossless. Score {score:.2f} (real ≥ {SUSPICIOUS_THRESHOLD}). "
                f"Possible gentle roll-off, quiet segment, or limited master — may still be true lossless."
            )
    else:
        verdict = "real"

    return {
        "file_path": str(path.resolve()),
        "file_name": path.name,
        "file_size": file_size,
        "format": fmt.upper(),
        "verdict": verdict,
        "score": round(score, 4),
        "diagnostic": diagnostic,
        "duration_sec": round(duration_sec, 2),
        "bitrate_kbps": bitrate_kbps,
        "actual_bitrate_kbps": actual_kbps,
        "clipping_pct": clipping_pct,
        "peak_dbfs": peak_dbfs,
    }


# Display spectrogram: Spek uses 1:1 pixel mapping (one FFT column per time pixel,
# one bin per freq pixel) for sharpness. We target similar resolution for crisp output.
SPEC_FREQ_BINS = 600
SPEC_TIME_BINS = 800


def _spectrogram_db(mag: np.ndarray, n_fft: int) -> np.ndarray:
    """Convert STFT magnitude to dB using Spek/SoX-style normalization: 20*log10(mag/n_fft)."""
    return 20.0 * np.log10(mag / n_fft + 1e-12)


def compute_spectrogram(path: Union[str, Path]) -> dict:
    """
    Load audio and compute a spectrogram for display (Spek/SoX-style).
    Uses same FFT size (2048), Hann window, and dB normalization as Spek so results
    match other tools (Spek, Faking the Funk, MiniMeters). Returns { freqs, times, mag_db }.
    """
    path = Path(path)
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported format: {path.suffix}")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    y, sr = librosa.load(path, sr=None, mono=True)
    # Match Spek: FFT 2^11 = 2048, 50% overlap, Hann window (Spek default)
    n_fft = 2048
    hop_length = n_fft // 2
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length, window="hann"))
    mag_db = _spectrogram_db(S, n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)[: S.shape[0]]
    times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop_length)

    n_f, n_t = mag_db.shape
    if n_f > SPEC_FREQ_BINS or n_t > SPEC_TIME_BINS:
        # Freq: sample evenly 0 to Nyquist (22 kHz for 44.1k) so high-end is visible
        if n_f > SPEC_FREQ_BINS:
            indices = np.linspace(0, n_f - 1, SPEC_FREQ_BINS, dtype=int)
            mag_db = mag_db[indices, :]
            freqs = freqs[indices]
        # Time: average consecutive frames per output column (Spek averages per pixel column)
        if n_t > SPEC_TIME_BINS:
            block = n_t // SPEC_TIME_BINS
            mag_db = np.array([
                np.mean(mag_db[:, i * block : min((i + 1) * block, n_t)], axis=1)
                for i in range(SPEC_TIME_BINS)
            ]).T
            times = np.array([
                float(np.mean(times[i * block : min((i + 1) * block, n_t)]))
                for i in range(SPEC_TIME_BINS)
            ])
        else:
            times = times[:SPEC_TIME_BINS]
        n_f, n_t = mag_db.shape

    # Spek uses -140..0 in range options; avoid clipping quiet content (e.g. high-freq)
    mag_db = np.clip(mag_db, -140, 0)
    return {
        "freqs": freqs.tolist(),
        "times": times.tolist(),
        "mag_db": mag_db.tolist(),
        "sr": sr,
        "duration_sec": float(times[-1]) if len(times) else 0,
    }
