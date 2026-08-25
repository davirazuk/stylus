#!/usr/bin/env python3
"""GPU vectorscope/oscilloscope of system audio. CRT-phosphor look, live controls.

The record player lives in its own app (ritual.py). This file is the
oscilloscope and nothing else.
"""
import argparse
import collections
import colorsys
import ctypes
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time

import numpy as np
import pygame
from OpenGL.GL import *

try:
    import pyaudio
except Exception:
    pyaudio = None




# Fallback rate only, used if pactl-based rate detection fails for any
# reason — AudioCapture detects and opens the stream at the real
# PipeWire/PulseAudio graph rate instead (see detect_graph_rate). Opening
# at any rate other than the graph's actual rate forces an extra silent
# resample of every block before this app ever sees it — inaudible for
# normal listening, but a real, avoidable precision loss for the kind of
# tightly-encoded waveform lissajous_xy/beam mode exists to reproduce
# faithfully.
RATE = 44100
BLOCK = 512
# Samples shown per drawn frame. Kept close to one render-frame's worth of
# new audio (RATE/60 ~= 735) so consecutive frames don't redraw mostly the
# same slice of waveform on top of themselves — that overlap is what turned
# the trace into a fuzzy blob instead of a crisp curve. Persistence/trail
# comes only from the decay feedback buffer between frames, not from a long
# rolling window drawn every frame.
TRACE_N = 760

# Capture window specifically for the plain lissajous_xy view (raw L/R
# plotted straight as X/Y — the actual encoding real oscilloscope-music
# tracks draw pictures with). TRACE_N above is tuned for generic reactive
# visualization (~1 render-frame of new audio, so frames don't redraw
# mostly-overlapping content into a fuzzy blob) but a full picture cycle in
# engineered content commonly needs far more samples than that — these
# tracks often draw at 15-40 Hz specifically to fit detailed images, and
# 44100/20 Hz alone is 2205 samples, nearly 3x TRACE_N. If the window is
# shorter than one full image period, the complete shape literally cannot
# appear in any single frame regardless of anything else — no amount of
# persistence or filtering fixes a window that's just too short. Only
# lissajous_xy uses this; every other mode (including the mid-side
# "lissajous" swirl, which isn't how oscilloscope-music pictures are
# actually encoded) keeps the short, snappier TRACE_N window.
XY_BUF_N = 3200  # ~72ms @ 44.1kHz, covers a full cycle down to ~14 Hz
# Display point count for lissajous_xy specifically. TRACE_N display points
# stretched across XY_BUF_N samples would average ~4.2 raw samples per
# displayed point — a real loss of fine detail compared to every other
# mode's roughly 1:1 ratio. This keeps the resample close to that same
# density despite the much longer time window.
XY_TRACE_N = 2200

# Search range (in Hz) for estimate_xy_cycle_len below — stateless, unlike
# the old cross-frame trigger/phase-lock ("the lock") that was removed;
# this only picks how much of the buffer to resample from, recomputed
# fresh every frame with zero memory of previous frames. Converted to a
# lag range in samples inside the function itself, against the real
# detected capture rate — not precomputed here, since the real rate isn't
# known until AudioCapture opens its stream.
XY_CYCLE_MIN_HZ = 20.0
XY_CYCLE_MAX_HZ = 500.0
XY_CYCLE_MIN_SAMPLES = 300

# Capture window for the time-domain trace modes (mono/dual) specifically —
# same LPF'd stream as the default `buf`, just longer, so trigger_slice
# (see below) has real headroom to search for a trigger point and still
# leave enough samples after it for a meaningful display window. A real
# scope's Y-t trace is always trigger-locked (that's what keeps it from
# scrolling/jittering); TRACE_N alone has no room to search for a trigger
# point without running out of samples to actually display afterward.
# ~54ms @ 44.1kHz: comfortably several cycles even for fairly low bass
# content, without capturing so much that the resample loses detail.
TRIG_BUF_N = 2400

# Seconds for the waterfall mode's spectrogram to fully scroll across the
# screen once. Expressed as a UV fraction per frame (1/(this*60fps)) so it's
# resolution-independent.
WATERFALL_SCROLL_SECONDS = 6.0

# Seconds for the CRT power-off collapse animation on quit (see shutdown_t
# in main()) — mirrors power_on_curve's warm-up flicker on start, but for
# shutting down: real CRTs lose vertical deflection first (the picture
# flattens to a bright horizontal line), then horizontal (the line rushes
# to a point, with a brief brightness flash as the energy concentrates into
# a shrinking spot), and only then does the beam itself actually cut out.
SHUTDOWN_DURATION = 0.5

# Kaleidoscope fold count (dihedral symmetry: alternating mirror+rotate
# copies of the same trace). Also doubles as the upper bound used to size
# the line VBO, since split-mode only ever needs 2 strips.
KALEIDO_FOLDS = 6
MAX_STRIPS = KALEIDO_FOLDS

N_BANDS = 28  # spectrum analyzer bar count
SPEC_FFT_N = 2048
SPEC_MIN_HZ = 40.0
SPEC_MAX_HZ = 15000.0
# dB-normalization window for the waterfall spectrogram specifically (see
# AudioCapture.spectrum_db) — real spectrogram tools always display in dB,
# not linear magnitude, because it's the only mapping that doesn't either
# crush quiet-but-real detail toward invisible or saturate a wide loud
# range down to a single indistinguishable 'maxed out' value. Measured
# empirically against this codebase's own FFT/band-averaging pipeline: a
# full-scale 440Hz tone lands around +47dB in these (uncalibrated, internal)
# units, a quiet-but-present one around -30 to -40dB.
SPEC_DB_FLOOR = -40.0
SPEC_DB_CEIL = 48.0

COLORS = {
    "green":  (0.06, 1.0, 0.16),
    "amber":  (1.0, 0.55, 0.04),
    "neon":   (1.0, 0.16, 0.86),
    "white":  (0.82, 0.92, 1.00),
    "blue":   (0.22, 0.55, 1.00),
    "cyan":   (0.10, 0.95, 0.90),
    "yellow": (1.0, 0.92, 0.10),
    "orange": (1.0, 0.40, 0.05),
    "red":    (1.0, 0.12, 0.10),
    "purple": (0.62, 0.20, 1.0),
}
MODES = ["polar", "lissajous", "lissajous_xy", "mono", "dual", "wire3d", "phase", "waterfall"]
STATE_PATH = os.path.expanduser("~/.local/share/stylus/deck-state.json")
DEFAULTS = {
    "mode": "lissajous", "color": "green", "zoom": 1.9, "decay": 0.55,
    "line_w": 1.15, "beam": False, "rainbow": False, "custom_hue": 0.5, "bloom": 1.0,
    "xy_swap": False, "xy_inv_x": False, "xy_inv_y": False,
    # "true scope" fidelity mode — see the K_y handler and the
    # lissajous_xy branch in main(). Off by default: the adaptive
    # behaviours it disables genuinely do make engineered
    # oscilloscope-music look crisper, they are just not what a real
    # instrument does.
    "true_scope": False,
    # groove ring: the vinyl-style progress arc. On by default — it is the
    # main thing that makes this feel like a listening ritual rather than a
    # readout.
    "groove": True,
}


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump({k: state[k] for k in DEFAULTS}, f, indent=2)
    except Exception:
        pass


def find_monitor_source():
    # Override explícito. Serve para dois casos reais: mais de um sink tocando
    # ao mesmo tempo (a heurística do RUNNING pega o primeiro e pode ser o
    # errado), e conferir o visualizador com som DE VERDADE sem som nenhum na
    # sala — manda o tocador para um sink nulo e aponta isto para o monitor
    # dele. Sinal real, silêncio real.
    forced = os.environ.get("STYLUS_DECK_SOURCE")
    if forced:
        return forced
    out = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if ".monitor" in l]
    for l in lines:
        if "RUNNING" in l:
            return l.split()[1]
    if lines:
        return lines[0].split()[1]
    return None


def detect_graph_rate(default=RATE):
    """Query PipeWire for its shared graph clock rate, so AudioCapture can
    open its capture stream at that same rate instead of a fixed guess.

    Deliberately reads the GRAPH's clock rate (`pw-metadata -n settings`),
    not any particular device's own negotiated hardware format (an earlier
    version of this function read a specific monitor source's reported
    "Sample Specification" via `pactl list sources` instead, which turned
    out to be the wrong layer — verified live on this machine: the USB
    DAC's own ALSA/ACP side had negotiated 96000Hz while the shared graph
    clock was at 48000Hz at the exact same moment, and a PulseAudio/
    PipeWire *monitor* source — what this app always reads — is a tap on
    the shared internal GRAPH, not a direct view of any one device's own
    format; those can legitimately differ and PipeWire resamples
    transparently between them). Capturing at any rate other than the
    graph's actual clock rate forces PipeWire to resample every block
    before handing it to this app — inaudible for normal listening, but a
    real extra processing stage that measurably degrades exactly the kind
    of precisely-encoded waveform lissajous_xy/beam mode exists to
    reproduce faithfully (real oscilloscope-music tracks — the "drawing
    with sound" genre, e.g. the content in Smarter Every Day's oscilloscope
    videos). Modern PipeWire setups commonly run their whole graph at
    48000Hz already, not the old 44100Hz CD-audio default this app used to
    hardcode unconditionally.

    Falls back to `default` if pw-metadata isn't available or parsing
    fails for any reason — a wrong-but-present rate guess is fine (just
    re-introduces the resampling this exists to avoid), never worth
    failing capture entirely over."""
    try:
        out = subprocess.run(
            ["pw-metadata", "-n", "settings"], capture_output=True, text=True, timeout=2
        ).stdout
        m = re.search(r"key:'clock\.rate'\s+value:'(\d+)'", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return default


# One-pole low-pass cutoff for the plotted trace. Raw full-bandwidth audio
# plotted sample-for-sample in X-Y space is a tangled scribble for any real
# song (that's just what broadband program material looks like at full
# resolution) — real scope/vectorscope visuals read as a clean flowing curve
# because the video is of a filtered/simple signal, not raw wideband music.
# Smoothing the trace itself (not the analysis, just what gets drawn) is what
# actually produces a legible curve instead of noise. Lowered from an
# earlier 1800Hz — reported directly as "too wavy"/"extra waves" on real
# (non-engineered) music specifically in lissajous/polar/mono/phase (the
# modes that use this cutoff): 1800Hz still keeps most musical harmonic
# detail, which is exactly what makes typical program material's mid-side
# Lissajous figure read as dense and undulating rather than a small number
# of clean, simple loops. Bass and low-mid content — most of a typical
# track's actual energy — stays well inside this lower cutoff; it's the
# thinner, busier upper-harmonic content that's being traded away here for
# a visibly calmer, prettier curve.
LPF_CUTOFF_HZ = 900.0

# Much lighter filtering for the lissajous_xy-specific buffer (see
# XY_BUF_N): that mode's whole purpose is rendering picture-drawing content
# accurately, where heavy smoothing actively works against the goal by
# blurring away the fine detail that makes an image legible. Still filtered,
# not fully raw, to knock down ultrasonic-ish noise/aliasing that would
# otherwise show up as static jitter in the non-beam default look; full raw
# fidelity is what beam mode's separate unfiltered buffer is for.
XY_LPF_CUTOFF_HZ = 6000.0

# Beam-realism's "raw" buffer used to be completely unfiltered — reported
# directly as looking bad/chaotic on real (non-engineered) music. The
# reasoning for going unfiltered originally (full detail for genuine
# picture-drawing content) still holds, but compute_beam_brightness reads
# LOCAL SAMPLE-TO-SAMPLE SPACING to decide brightness, and true full-
# bandwidth content has huge sample-to-sample jumps purely from inaudible
# ultrasonic-ish/aliasing energy — that alone was enough to make the beam
# flicker between bright/dim near-randomly on typical broadband music,
# reading as noisy/imprecise rather than as a real beam dwelling on a
# shape. This cutoff is deliberately still far above anything that matters
# for actual picture geometry (real oscilloscope-music line art doesn't
# carry meaningful shape information above this), so it costs picture-mode
# fidelity essentially nothing while cutting the specific noise that was
# making beam mode look bad on ordinary music.
BEAM_AA_CUTOFF_HZ = 14000.0


class OnePoleLPF:
    def __init__(self, cutoff_hz, rate):
        rc = 1.0 / (2 * np.pi * cutoff_hz)
        dt = 1.0 / rate
        self.alpha = dt / (rc + dt)
        self.y = np.zeros(2, dtype=np.float64)

    def apply(self, block):
        """block: (N,2) float32 -> low-passed (N,2) float32, filter state carried across calls."""
        out = np.empty_like(block, dtype=np.float64)
        y = self.y
        a = self.alpha
        for i in range(block.shape[0]):
            y = y + a * (block[i] - y)
            out[i] = y
        self.y = y
        return out.astype(np.float32)


class BandFlash:
    """Fast/slow energy-envelope onset detector: flashes up instantly on a hit
    in its band, then decays — the same trick a peak/VU light uses, just
    fast enough to read as 'reacting to a kick/hi-hat', not just 'loud'."""

    def __init__(self, fast_coeff=0.9, slow_coeff=0.05, scale=18.0, decay=0.75):
        self.fast = 0.0
        self.slow = 0.0
        self.value = 0.0
        self.fc = fast_coeff
        self.sc = slow_coeff
        self.scale = scale
        self.decay = decay

    def update(self, energy):
        self.fast += self.fc * (energy - self.fast)
        self.slow += self.sc * (energy - self.slow)
        raw = max(0.0, (self.fast - self.slow) * self.scale)
        self.value = max(raw, self.value * self.decay)
        return self.value


class AudioCapture:
    """Reads the monitor source on a background thread into a rolling ring buffer.

    Also derives simple level/transient metrics per block: VU-style L/R
    envelopes + peak hold for the meter bars, three per-band onset flashes
    (bass/mid/treble, via cheap one-pole band splits) so different
    instruments drive different parts of the visual, a smoothed log-spaced
    frequency spectrum for the analyzer bars, and a simple adaptive-threshold
    beat/BPM detector on bass-band energy.
    """

    def __init__(self, source_name):
        if pyaudio is None:
            import sys
            sys.stderr.write(
                "stylus: o deck precisa do PortAudio para ler o som que está "
                "tocando, e ele não está instalado (falta python-pyaudio).\n"
                "         Rode `stylus update` para trazer a versão que o "
                "inclui.\n")
            raise SystemExit(3)
        self.buf = np.zeros((TRACE_N, 2), dtype=np.float32)
        # Longer, lightly-filtered buffer feeding the default (non-beam)
        # lissajous_xy view (see XY_BUF_N) — long enough to hold a full
        # picture cycle even for low-fundamental engineered content.
        self.xy_buf = np.zeros((XY_BUF_N, 2), dtype=np.float32)
        # Near-raw twin of xy_buf, same (longer) size — beam-realism's
        # speed-based dimming already solves the 'avoid a tangled scribble'
        # problem more accurately than blanket low-pass filtering does (it
        # fades fast jumps instead of removing the frequency content that
        # makes them fast), so when beam mode is on for XY content it reads
        # from here instead, getting full audio detail instead of
        # pre-smoothed detail. Only anti-alias-filtered (see
        # BEAM_AA_CUTOFF_HZ), not literally unfiltered — that turned out to
        # read as noisy/flickery on ordinary (non-picture) music.
        self.raw_buf = np.zeros((XY_BUF_N, 2), dtype=np.float32)
        # Same LPF'd stream as self.buf (not a separately-filtered signal —
        # see _run: both are filled from the same `filtered` block every
        # read), just longer, giving trigger_slice room to search for a
        # trigger point for the mono/dual time-domain trace. See TRIG_BUF_N.
        self.trig_buf = np.zeros((TRIG_BUF_N, 2), dtype=np.float32)
        # Real graph rate, not a hardcoded guess — see detect_graph_rate.
        # Everything below that needs to convert between Hz and samples
        # (filter cutoffs, FFT bin frequencies) uses this, not the RATE
        # module constant, so it stays correct regardless of what rate the
        # system actually negotiates.
        self.rate = detect_graph_rate(default=RATE)
        self._lock = threading.Lock()
        self._stop = False
        self._lpf = OnePoleLPF(LPF_CUTOFF_HZ, self.rate)
        self._xy_lpf = OnePoleLPF(XY_LPF_CUTOFF_HZ, self.rate)
        self._beam_aa_lpf = OnePoleLPF(BEAM_AA_CUTOFF_HZ, self.rate)
        self._bass_lpf = OnePoleLPF(150.0, self.rate)
        self._midhi_lpf = OnePoleLPF(2500.0, self.rate)

        self.level_l = 0.0
        self.level_r = 0.0
        self.peak_l = 0.0
        self.peak_r = 0.0
        self._onset_flash = BandFlash(scale=18.0)
        self._bass_flash = BandFlash(scale=16.0, decay=0.80)
        self._treble_flash = BandFlash(scale=26.0, decay=0.68)
        self.onset = 0.0
        self.bass = 0.0
        self.treble = 0.0

        # --- spectrum analyzer ---
        self._spec_buf = np.zeros(SPEC_FFT_N, dtype=np.float32)
        self._hann = np.hanning(SPEC_FFT_N).astype(np.float32)
        freqs = np.fft.rfftfreq(SPEC_FFT_N, 1.0 / self.rate)
        edges = np.logspace(np.log10(SPEC_MIN_HZ), np.log10(SPEC_MAX_HZ), N_BANDS + 1)
        self._band_masks = [
            (freqs >= edges[i]) & (freqs < edges[i + 1]) for i in range(N_BANDS)
        ]
        for i, m in enumerate(self._band_masks):
            if not m.any():
                # guarantee every band has at least one bin (can happen for
                # the lowest bands at this FFT size/rate)
                idx = int(np.argmin(np.abs(freqs - edges[i])))
                m[idx] = True
        self.spectrum = np.zeros(N_BANDS, dtype=np.float32)
        # dB-normalized twin of self.spectrum, for the waterfall mode only
        # (see SPEC_DB_FLOOR/CEIL) — self.spectrum's log1p compression is
        # tuned for the bar-chart display and, measured against this exact
        # FFT pipeline, actually saturates flat across a ~20dB range of
        # real signal AND compresses quiet detail unevenly; a proper dB
        # scale is what actually reveals it, so this is a separate
        # computation rather than a retune of the shared one.
        self.spectrum_db = np.zeros(N_BANDS, dtype=np.float32)

        # --- beat / BPM detector: adaptive-threshold energy method on the
        # bass band. A beat fires when instantaneous bass energy spikes well
        # above its recent local average; inter-beat gaps feed a running
        # median tempo estimate. ---
        self._bass_hist = collections.deque(maxlen=43)  # ~0.5s at BLOCK/RATE
        self._last_beat_t = 0.0
        self._beat_intervals = collections.deque(maxlen=8)
        self.bpm = 0.0
        self.beat_pulse = 0.0

        os.environ["PULSE_SOURCE"] = source_name or ""
        self.p = pyaudio.PyAudio()
        dev_index = self._find_pulse_device()
        self.stream = self.p.open(
            format=pyaudio.paInt16, channels=2, rate=self.rate, input=True,
            input_device_index=dev_index, frames_per_buffer=BLOCK,
        )
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _find_pulse_device(self):
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            if info["name"] == "pulse" and info["maxInputChannels"] > 0:
                return i
        return None  # fall back to default input device

    def _update_spectrum(self, raw):
        mono = raw.mean(axis=1)
        self._spec_buf = np.roll(self._spec_buf, -len(mono))
        self._spec_buf[-len(mono):] = mono
        mag = np.abs(np.fft.rfft(self._spec_buf * self._hann))
        bands_raw = np.empty(N_BANDS, dtype=np.float32)
        for i, m in enumerate(self._band_masks):
            bands_raw[i] = mag[m].mean()

        bands = np.log1p(bands_raw * 35.0)
        bands = np.clip(bands / 4.0, 0.0, 1.4).astype(np.float32)
        atk, rel = 0.6, 0.10
        rising = bands > self.spectrum
        self.spectrum = np.where(
            rising,
            self.spectrum + atk * (bands - self.spectrum),
            self.spectrum + rel * (bands - self.spectrum),
        ).astype(np.float32)

        db = 20.0 * np.log10(np.maximum(bands_raw, 1e-8))
        db_norm = np.clip(
            (db - SPEC_DB_FLOOR) / (SPEC_DB_CEIL - SPEC_DB_FLOOR), 0.0, 1.0
        ).astype(np.float32)
        # Lighter smoothing than the bar chart above (which favors a
        # settled look): the waterfall's own scroll axis already supplies
        # temporal context, so more instantaneous response here preserves
        # transient detail instead of blurring it before it's even drawn.
        atk2, rel2 = 0.75, 0.25
        rising2 = db_norm > self.spectrum_db
        self.spectrum_db = np.where(
            rising2,
            self.spectrum_db + atk2 * (db_norm - self.spectrum_db),
            self.spectrum_db + rel2 * (db_norm - self.spectrum_db),
        ).astype(np.float32)

    def _update_beat(self, bass_energy):
        self._bass_hist.append(bass_energy)
        if len(self._bass_hist) >= 8:
            avg = sum(self._bass_hist) / len(self._bass_hist)
            now = time.time()
            if avg > 1e-7 and bass_energy > avg * 1.35 and (now - self._last_beat_t) > 0.24:
                if self._last_beat_t > 0.0:
                    interval = now - self._last_beat_t
                    if 0.24 < interval < 1.5:
                        self._beat_intervals.append(interval)
                self._last_beat_t = now
                self.beat_pulse = 1.0
                if len(self._beat_intervals) >= 3:
                    med = sorted(self._beat_intervals)[len(self._beat_intervals) // 2]
                    target_bpm = 60.0 / med
                    self.bpm = target_bpm if self.bpm <= 0 else self.bpm + 0.25 * (target_bpm - self.bpm)
        self.beat_pulse *= 0.86

    def _run(self):
        while not self._stop:
            try:
                data = self.stream.read(BLOCK, exception_on_overflow=False)
            except Exception:
                time.sleep(0.01)
                continue
            raw = np.frombuffer(data, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0
            filtered = self._lpf.apply(raw)
            xy_filtered = self._xy_lpf.apply(raw)
            beam_aa = self._beam_aa_lpf.apply(raw)
            with self._lock:
                self.buf = np.roll(self.buf, -len(filtered), axis=0)
                self.buf[-len(filtered):] = filtered
                self.xy_buf = np.roll(self.xy_buf, -len(xy_filtered), axis=0)
                self.xy_buf[-len(xy_filtered):] = xy_filtered
                self.raw_buf = np.roll(self.raw_buf, -len(beam_aa), axis=0)
                self.raw_buf[-len(beam_aa):] = beam_aa
                self.trig_buf = np.roll(self.trig_buf, -len(filtered), axis=0)
                self.trig_buf[-len(filtered):] = filtered

            rms_l = float(np.sqrt(np.mean(raw[:, 0] ** 2)))
            rms_r = float(np.sqrt(np.mean(raw[:, 1] ** 2)))
            atk, rel = 0.55, 0.06
            self.level_l += (atk if rms_l > self.level_l else rel) * (rms_l - self.level_l)
            self.level_r += (atk if rms_r > self.level_r else rel) * (rms_r - self.level_r)
            self.peak_l = max(rms_l * 1.4, self.peak_l - 0.012)
            self.peak_r = max(rms_r * 1.4, self.peak_r - 0.012)

            mono_energy = float(np.mean(raw ** 2))
            self.onset = self._onset_flash.update(mono_energy)

            bass_sig = self._bass_lpf.apply(raw)
            midhi_sig = self._midhi_lpf.apply(raw)
            treble_sig = raw - midhi_sig
            bass_energy = float(np.mean(bass_sig ** 2))
            self.bass = self._bass_flash.update(bass_energy)
            self.treble = self._treble_flash.update(float(np.mean(treble_sig ** 2)))

            self._update_beat(bass_energy)
            self._update_spectrum(raw)

    def progress(self):
        """(elapsed_seconds, total_seconds) or (0, 0) if unknown."""
        with self._lock:
            return self._position, self._length

    def snapshot(self):
        with self._lock:
            return self.buf.copy()

    def xy_snapshot(self):
        with self._lock:
            return self.xy_buf.copy()

    def raw_snapshot(self):
        with self._lock:
            return self.raw_buf.copy()

    def trig_snapshot(self):
        with self._lock:
            return self.trig_buf.copy()

    def close(self):
        self._stop = True
        self.thread.join(timeout=1)
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()


class NowPlaying:
    """Background MPRIS poller via playerctl (same tool/approach as
    ~/lyric-cards/mpris.py). Polls at low frequency on its own thread since
    spawning playerctl is relatively slow (tens of ms) — far too slow to do
    on the render thread every frame."""

    def __init__(self, poll_interval=1.0):
        self._available = shutil.which("playerctl") is not None
        self._lock = threading.Lock()
        self._artist = ""
        self._title = ""
        # Position/length drive the groove ring — see draw of the same name.
        # Both in seconds; length 0 means "unknown", which the ring treats as
        # "don't draw progress" rather than guessing.
        self._position = 0.0
        self._length = 0.0
        self._stop = False
        if self._available:
            self.thread = threading.Thread(target=self._run, args=(poll_interval,), daemon=True)
            self.thread.start()
        else:
            self.thread = None

    def _run(self, interval):
        while not self._stop:
            artist, title = "", ""
            try:
                status = subprocess.run(
                    ["playerctl", "status"], capture_output=True, text=True, timeout=2
                ).stdout.strip()
                if status in ("Playing", "Paused"):
                    out = subprocess.run(
                        ["playerctl", "metadata", "--format",
                         "{{artist}}\t{{title}}\t{{position}}\t{{mpris:length}}"],
                        capture_output=True, text=True, timeout=2,
                    ).stdout.strip()
                    if out:
                        parts = out.split("\t")
                        if len(parts) >= 2:
                            artist, title = parts[0], parts[1]
                            # playerctl reports both in MICROseconds.
                            try:
                                pos = float(parts[2]) / 1e6 if len(parts) > 2 and parts[2] else 0.0
                                ln = float(parts[3]) / 1e6 if len(parts) > 3 and parts[3] else 0.0
                            except ValueError:
                                pos, ln = 0.0, 0.0
            except Exception:
                pass
            with self._lock:
                self._artist, self._title = artist, title
                try:
                    self._position, self._length = pos, ln
                except NameError:
                    self._position, self._length = 0.0, 0.0
            time.sleep(interval)

    def snapshot(self):
        with self._lock:
            return self._artist, self._title

    def close(self):
        self._stop = True


LINE_VS = """
#version 330
layout(location=0) in vec2 pos;
uniform float zoom;
void main() { gl_Position = vec4(pos * zoom, 0.0, 1.0); }
"""
LINE_FS = """
#version 330
uniform vec3 color;
out vec4 frag;
void main() {
    // Soft radial falloff instead of a flat hardware point — the "electron
    // beam head" dot should read as a small glowing spot (bright core,
    // fading edge), not a hard-edged square/circle, matching how the trace
    // ribbon itself is shaded (see RIBBON_FS).
    vec2 d = gl_PointCoord - vec2(0.5);
    float r = length(d) * 2.0;
    float core = exp(-r * r * 3.2);
    frag = vec4(color * core, 1.0);
}
"""

QUAD_VS = """
#version 330
layout(location=0) in vec2 pos;
out vec2 uv;
void main() { uv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }
"""

DECAY_FS = """
#version 330
in vec2 uv;
out vec4 frag;
uniform sampler2D hist;
uniform float decay;
uniform float shift;
void main() {
    vec2 suv = uv + vec2(shift, 0.0);
    // Explicit black outside [0,1], not texture()'s CLAMP_TO_EDGE fallback:
    // with a nonzero shift (waterfall mode), the edge pixel would otherwise
    // get re-sampled (duplicated) every frame instead of receiving genuine
    // emptiness from 'beyond the buffer'. Since new content is additively
    // drawn on top of that same undecayed duplicate every frame, brightness
    // there follows R_k = decay*R_(k-1) + N, which converges to
    // N/(1-decay) = 1000x the new column's own brightness at decay=0.999 —
    // a runaway to a blown-out white screen within a few seconds. True
    // black here breaks that feedback loop: the edge starts genuinely
    // empty each frame, so it only ever shows that frame's own new data.
    if (suv.x < 0.0 || suv.x > 1.0) {
        frag = vec4(0.0, 0.0, 0.0, 1.0);
    } else {
        frag = texture(hist, suv) * decay;
    }
}
"""

BRIGHT_FS = """
#version 330
in vec2 uv;
out vec4 frag;
uniform sampler2D src;
void main() {
    vec3 c = texture(src, uv).rgb;
    float l = max(c.r, max(c.g, c.b));
    frag = vec4(c * smoothstep(0.35, 0.9, l), 1.0);
}
"""

BLUR_FS = """
#version 330
in vec2 uv;
out vec4 frag;
uniform sampler2D src;
uniform vec2 texel;
uniform vec2 dir;
void main() {
    vec3 sum = texture(src, uv).rgb * 0.227027;
    vec2 o1 = dir * texel * 1.3846153846;
    vec2 o2 = dir * texel * 3.2307692308;
    sum += texture(src, uv + o1).rgb * 0.3162162162;
    sum += texture(src, uv - o1).rgb * 0.3162162162;
    sum += texture(src, uv + o2).rgb * 0.0702702703;
    sum += texture(src, uv - o2).rgb * 0.0702702703;
    frag = vec4(sum, 1.0);
}
"""

COMPOSITE_FS = """
#version 330
in vec2 uv;
out vec4 frag;
uniform sampler2D base;
uniform sampler2D glow;
uniform float u_time;
uniform float u_power;
uniform float u_loud;
uniform float u_bass;
uniform float u_treble;
uniform float u_beat;
uniform float u_resolve;
uniform float u_bloom;
uniform float u_flat;
uniform float u_flash;


vec2 curve(vec2 u) {
    u = u * 2.0 - 1.0;
    vec2 offset = u.yx / 4.2;
    u += u * offset * offset;
    return u * 0.5 + 0.5;
}

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }

void main() {
    // u_flat (waterfall mode): the barrel-tube curve is radially symmetric
    // and was built for a centered trace — content that deliberately spans
    // full-height at the screen edge (a spectrogram column) gets warped off
    // a straight line by it, and near the corners gets pushed entirely
    // outside [0,1] and blacked out by the clip check below. A spectrogram
    // doesn't need the curved-tube look anyway, so this bypasses both.
    vec2 cuv = mix(curve(uv), uv, u_flat);
    if (u_flat < 0.5 && (cuv.x < 0.0 || cuv.x > 1.0 || cuv.y < 0.0 || cuv.y > 1.0)) {
        frag = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    vec2 d = cuv - 0.5;

    // Chromatic aberration: split channels slightly, growing toward the
    // edges, like dispersion through curved tube glass / a lens stack.
    vec2 ca = d * 0.006 * (1.0 - u_flat);
    vec3 b = vec3(
        texture(base, cuv + ca).r,
        texture(base, cuv).g,
        texture(base, cuv - ca).b
    );
    vec3 g = vec3(
        texture(glow, cuv + ca * 1.6).r,
        texture(glow, cuv).g,
        texture(glow, cuv - ca * 1.6).b
    );
    float breathe = 0.9 + u_loud * 1.4;
    float bloomK = u_bloom;
    g *= breathe * bloomK;

    float scan = 0.96 + 0.04 * sin(cuv.y * 900.0);

    float vig = 1.0 - dot(d, d) * 1.15;

    float grain = (hash(floor(cuv * 480.0) + u_time * 61.0) - 0.5) * mix(0.07, 0.02, min(1.0, u_loud));

    float glare = 1.0 - abs(dot(cuv - vec2(0.18, 0.12), vec2(0.8, -0.6)));
    glare = pow(max(glare, 0.0), 6.0) * 0.04;

    float sparkleCell = hash(floor(cuv * 260.0));
    float twinkle = 0.5 + 0.5 * sin(u_time * 8.0 + sparkleCell * 6.28);
    float sparkle = step(0.9955, sparkleCell) * u_treble * twinkle;

    vec3 col = (b + g) * scan * vig;
    col += vec3(0.01, 0.015, 0.01) * vig; // faint phosphor screen bias when idle
    col += grain * vig;
    col += glare * vig;
    col += vec3(0.85, 0.95, 1.0) * sparkle * vig;
    col *= u_power; // CRT power-on warm-up ramp
    col *= 1.0 + u_bass * 0.30; // kick/bass hits punch the whole screen brighter
    col *= 1.0 + u_beat * 0.18; // extra brief punch on a confirmed beat, distinct from raw bass energy
    col *= 1.0 + u_resolve * 0.35; // lissajous locking into a clean resolved figure gets an extra glow/brightness lift
    col *= 1.0 + u_flash; // brief bright flash at the instant of a CRT power-off collapse
    frag = vec4(max(col, 0.0), 1.0);
}
"""

UI_VS = """
#version 330
layout(location=0) in vec2 pos;
layout(location=1) in vec4 col;
out vec4 vcol;
void main() { vcol = col; gl_Position = vec4(pos, 0.0, 1.0); }
"""
UI_FS = """
#version 330
in vec4 vcol;
out vec4 frag;
void main() { frag = vcol; }
"""

# Ribbon (trace) rendering: filled triangle-strip geometry instead of
# GL_LINE_STRIP + glLineWidth (see build_ribbon_strip's docstring for why).
# Filled triangles have no built-in line smoothing though, so `edge` — a
# per-vertex cross-ribbon coordinate in [-1, 1], 0 at the centerline, ±1 at
# the physical boundary — carries a soft alpha falloff near the edge,
# the standard signed-distance-style technique for anti-aliased line
# rendering without MSAA.
RIBBON_VS = """
#version 330
layout(location=0) in vec2 pos;
layout(location=1) in vec4 col;
layout(location=2) in float edge;
out vec4 vcol;
out float vedge;
void main() { vcol = col; vedge = edge; gl_Position = vec4(pos, 0.0, 1.0); }
"""
RIBBON_FS = """
#version 330
in vec4 vcol;
in float vedge;
out vec4 frag;
void main() {
    // A real CRT/vector-display beam's cross-section is roughly Gaussian —
    // brightest dead-center, soft shoulders — not a flat-brightness bar
    // with a hard edge. A tight Gaussian core (peaking well above the flat
    // body) layered over a wider soft shoulder reads as an actual glowing
    // stroke instead of a filled polygon; the shoulder term still supplies
    // the anti-aliased falloff at the ribbon's true geometric boundary.
    float d = abs(vedge);
    float core = exp(-d * d * 4.5);
    float shoulder = 1.0 - smoothstep(0.55, 1.0, d);
    float a = max(core, shoulder * 0.62);
    frag = vec4(vcol.rgb * a, 1.0);
}
"""

TEXT_VS = """
#version 330
layout(location=0) in vec2 pos;
layout(location=1) in vec2 texcoord;
out vec2 uv;
void main() { uv = texcoord; gl_Position = vec4(pos, 0.0, 1.0); }
"""
LABEL_FS = """
#version 330
in vec2 uv;
out vec4 frag;
uniform sampler2D tex;
uniform float alpha;
void main() {
    vec4 t = texture(tex, uv);
    frag = vec4(t.rgb, t.a * alpha);
}
"""

TEXT_FS = """
#version 330
in vec2 uv;
out vec4 frag;
uniform sampler2D tex;
uniform vec4 tint;
void main() {
    vec4 t = texture(tex, uv);
    frag = vec4(tint.rgb, t.a * tint.a);
}
"""


def compile_shader(vs_src, fs_src):
    prog = glCreateProgram()
    for src, kind in ((vs_src, GL_VERTEX_SHADER), (fs_src, GL_FRAGMENT_SHADER)):
        sh = glCreateShader(kind)
        glShaderSource(sh, src)
        glCompileShader(sh)
        if not glGetShaderiv(sh, GL_COMPILE_STATUS):
            raise RuntimeError(glGetShaderInfoLog(sh).decode())
        glAttachShader(prog, sh)
        glDeleteShader(sh)
    glLinkProgram(prog)
    if not glGetProgramiv(prog, GL_LINK_STATUS):
        raise RuntimeError(glGetProgramInfoLog(prog).decode())
    return prog


def make_fbo(w, h):
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, None)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0)
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    return fbo, tex


QUAD_VERTS = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32)


def make_quad_vao():
    vao = glGenVertexArrays(1)
    vbo = glGenBuffers(1)
    glBindVertexArray(vao)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, QUAD_VERTS.nbytes, QUAD_VERTS, GL_STATIC_DRAW)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, None)
    glEnableVertexAttribArray(0)
    glBindVertexArray(0)
    return vao


def draw_quad(vao):
    glBindVertexArray(vao)
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
    glBindVertexArray(0)


def estimate_xy_cycle_len(mono, rate=RATE):
    """Cheap, fully stateless-per-frame period estimate (normalized
    autocorrelation with de-octave folding) — decides how many of the most
    recent samples to actually resample lissajous_xy from, NOT phase-lock
    frame to frame (that cross-frame prediction/tracking was 'the lock',
    removed on request; this carries zero memory between frames). A window
    long enough for the lowest supported picture-drawing frequency (see
    XY_BUF_N) contains many repetitions of a higher-frequency picture, and
    since the period is essentially never an exact integer number of
    samples, those repetitions don't perfectly overlay when resampled —
    verified empirically that direction-wobble in the resampled curve
    scales close to linearly with how many repetitions get crammed in.
    Frame-to-frame persistence already supplies visual continuity across
    time, so there's no benefit to multiple passes within one frame's own
    geometry — trimming to ~one detected cycle sharpens it for free.

    `rate` (the real detected capture rate — see AudioCapture.rate, NOT the
    RATE module constant, which is only ever a fallback) converts
    XY_CYCLE_MIN_HZ/MAX_HZ into a lag search range in samples; passing the
    wrong rate here would search the wrong actual frequency range and mislabel
    it as 20-500Hz regardless.

    Returns samples-per-cycle (float — see the parabolic refinement below,
    this is sub-sample precision, not rounded to the nearest integer lag),
    or None if not periodic enough to bother."""
    n = len(mono)
    m = mono - mono.mean()
    if float(np.dot(m, m)) < 1e-8:
        return None
    min_lag = max(2, int(rate / XY_CYCLE_MAX_HZ))
    max_lag = int(rate / XY_CYCLE_MIN_HZ)
    nfft = 1
    while nfft < 2 * n:
        nfft *= 2
    f = np.fft.rfft(m, n=nfft)
    ac = np.fft.irfft(f * np.conj(f), n=nfft)[:max_lag + 2]
    lo, hi = min_lag, min(max_lag, len(ac) - 2)
    if hi <= lo:
        return None
    sq = m * m
    cumsq = np.concatenate(([0.0], np.cumsum(sq)))
    lags = np.arange(lo, hi + 1)
    energy_a = cumsq[n - lags]
    energy_b = cumsq[n] - cumsq[lags]
    denom = np.sqrt(np.maximum(energy_a * energy_b, 1e-12))
    window = ac[lo:hi + 1] / denom
    # Find the true fundamental, not just the strongest peak: for a
    # genuinely periodic signal, autocorrelation peaks appear at EVERY
    # integer multiple of the real period (P, 2P, 3P, ...), often with
    # near-identical strength (verified: a real 245-sample period showed a
    # global argmax at 1715 = 7x, not 245, with the true period's peak
    # tied for strength at 1.000 vs 1.000) — dividing the global-best lag
    # by small integers only recovers 2x/3x/4x cases and silently misses
    # higher multiples entirely. Scanning from the shortest lag upward for
    # the first peak that's nearly as strong as the true global best
    # finds the fundamental directly, regardless of which multiple
    # happened to win the raw argmax.
    global_peak_val = float(np.max(window))
    if global_peak_val < 0.5:
        return None
    strong = np.where(window >= 0.92 * global_peak_val)[0]
    peak_i = int(strong[0]) if len(strong) else int(np.argmax(window))
    peak_val = float(window[peak_i])
    if peak_val < 0.5:
        return None
    # Sub-sample refinement via parabolic interpolation around the
    # integer-lag peak, instead of returning that raw integer bin directly:
    # the true period is essentially never an exact integer number of
    # samples (see above), so rounding to the nearest one is exactly the
    # source of the per-cycle drift/wobble this function's own docstring
    # already describes. Fitting a parabola through the peak and its two
    # immediate neighbors and using ITS vertex gets a fraction of a sample
    # closer to the true period — small per-cycle, but it's exactly what
    # compounds across the many repetitions a real picture-cycle window
    # contains, so this measurably reduces that drift instead of just
    # tolerating it.
    frac = 0.0
    if 0 < peak_i < len(window) - 1:
        y0, y1, y2 = float(window[peak_i - 1]), peak_val, float(window[peak_i + 1])
        curve = y0 - 2.0 * y1 + y2
        if abs(curve) > 1e-9:
            frac = max(-1.0, min(1.0, 0.5 * (y0 - y2) / curve))
    return float(lo + peak_i) + frac


# How many consecutive undetected frames to coast through before giving up
# and resetting the smoothing state. estimate_xy_cycle_len legitimately
# returns None on ordinary music several times a second (measured: 11 misses
# in 150 frames on Radiohead's "Kid A"), and discarding all state on each one
# meant the next good frame re-seeded the window with NO damping — a hard
# jump, several times a second. Coasting on the last good window through a
# short dropout is both cheaper and much steadier; the reset still happens if
# the signal is genuinely gone. ~8 frames ≈ 130ms at 60fps.
XY_MISS_GRACE = 8


def advance_xy_window(cycle_len, smooth, history, misses=0):
    """One frame of lissajous_xy window-length smoothing.

    `cycle_len` may be None (estimate_xy_cycle_len found nothing periodic
    enough). Handling that here rather than in the caller keeps all the
    frame-to-frame state logic in one testable place — it used to live in
    main(), where the None branch threw the state away outright.

    Returns (smooth, history, window_len, misses). `window_len` is None only
    when there is no usable state at all (no good frame yet, or the dropout
    outlasted XY_MISS_GRACE), in which case the caller should fall back to
    the full untrimmed buffer.

    Pulled out of main()'s render loop so it can actually be tested. It used
    to live inline, which meant the only way to evaluate a change to it was
    to launch the GUI and squint — and several rounds of "fix" shipped that
    way without ever being objectively measured. See tools/offline_render.py.

    Pure: takes the current raw estimate plus the previous (smooth, history)
    state, returns the new (smooth, history, window_len). No globals, no
    cross-frame object state beyond what's passed in.

    Returns (smooth, history, window_len).

    Behaviour, unchanged from the inline version:
      * First frame seeds `smooth` directly from the raw estimate.
      * A same-ballpark estimate (0.5-2x current) eases in at a base 0.15,
        throttled by how much the last ~10 RAW estimates agree with each
        other (coefficient of variation). Measured 2026-08-21 on synthetic
        inharmonic-partial audio approximating polyphonic music: peak_val
        (autocorrelation strength) stayed 0.86-0.92 even while the winning
        lag flipped between comparably-strong candidates, so single-frame
        confidence can't distinguish a settled fundamental from an ambiguous
        lag landscape — gating on it measured as no improvement at all. Only
        recent-agreement catches it. A flat slower rate buys similar
        stability but also slows real changes (rate=0.04 flat took ~780ms to
        follow a genuine 110->220Hz step vs 233ms at 0.15); agreement-gating
        measured both tighter AND faster: window range 493-925 (1.88x) ->
        607-925 (1.52x), step change still settling in ~370ms.
      * A wild outlier (outside 0.5-2x) eases in at a flat 0.04 regardless,
        so one bad frame can't destabilise the window.

    NOT yet verified against real music live — flag any regression if the
    picture feels laggy on deliberate tempo/section changes.
    """
    if cycle_len is None:
        misses += 1
        if smooth is None or misses > XY_MISS_GRACE:
            return None, [], None, misses
        # Coast: hold the last good window through a short dropout.
        window_len = int(np.clip(smooth * 1.08, XY_CYCLE_MIN_SAMPLES, XY_BUF_N))
        return smooth, history, window_len, misses

    misses = 0
    if smooth is None:
        smooth = cycle_len
        history = [cycle_len]
    else:
        history = (history + [cycle_len])[-10:]
        ratio = cycle_len / smooth
        if 0.5 < ratio < 2.0:
            cv = (np.std(history) / max(np.mean(history), 1e-9)
                  if len(history) >= 3 else 0.0)
            trust = np.clip(1.0 - cv / 0.25, 0.0, 1.0)
            rate = 0.15 * (0.07 + 0.93 * trust)
        else:
            rate = 0.04
        smooth += rate * (cycle_len - smooth)
    window_len = int(np.clip(smooth * 1.08, XY_CYCLE_MIN_SAMPLES, XY_BUF_N))
    return smooth, history, window_len, misses


def resample_stereo(buf, N):
    """Linearly interpolated resample of a (M, 2) buffer to N (L, R) points.

    Not nearest-neighbor (the old `linspace(...).astype(int)` approach):
    whenever N > len(buf), truncation-to-int repeats the same source sample
    many times in a row before jumping to the next one. That reads as a run of
    zero-distance points (spuriously 'the beam is dwelling here') followed
    by a real jump, which is a resampling artifact, not anything the beam
    actually did — it directly corrupts beam-realism's speed measurement,
    and just looks stair-steppy everywhere else too."""
    findex = np.linspace(0, len(buf) - 1, N)
    xp = np.arange(len(buf))
    L = np.interp(findex, xp, buf[:, 0]).astype(np.float32)
    R = np.interp(findex, xp, buf[:, 1]).astype(np.float32)
    return L, R


def apply_channel_fix(L, R, swap, inv_x, inv_y):
    """Real oscilloscope-music tracks are sometimes authored/exported with
    channel polarity that doesn't match this player's L->X, R->Y convention
    — a well-known real annoyance in that hobby scene (the "drawing with
    sound" genre showcased in e.g. Smarter Every Day's oscilloscope videos),
    not a bug in either the track or the player, just a mismatch in which
    convention was assumed when the track was mixed. A picture that looks
    scrambled/mirrored/upside-down here can genuinely just need a channel
    swap or a polarity flip on one axis to resolve correctly — there's no
    way to detect the "right" orientation from the signal alone, so this is
    a manual per-track toggle (x/l/t keys), not automatic.

    swap happens first, so inv_x/inv_y always mean "invert the X/Y axis of
    the resulting picture" regardless of swap state, not "invert whichever
    original channel." That's the more intuitive behavior when both are on
    at once: e.g. swap+inv_x mirrors-then-flips the same way real
    oscilloscope operators reason about it ("swap channels, then this axis
    is backwards too"), rather than the two toggles interacting in a way
    that depends on the order they happened to be pressed in."""
    if swap:
        L, R = R, L
    if inv_x:
        L = -L
    if inv_y:
        R = -R
    return L, R


def trigger_slice(buf, search_frac=0.6, lookback=60):
    """Classic scope level-trigger: return a FIXED-length window of `buf`
    starting at the most recent rising zero-crossing that had a real
    preceding dip, so mono/dual's time trace holds visually still frame to
    frame instead of scrolling/jittering with the raw window's arbitrary
    phase — the same reason every real oscilloscope triggers before drawing
    a Y-t trace at all. Stateless and recomputed fresh every single frame,
    exactly like estimate_xy_cycle_len above — no cross-frame phase
    prediction/tracking state machine, so none of the old cross-frame
    lock's failure modes apply here; this only ever looks at the current
    frame's own buffer.

    The window length is fixed (always `len(buf) - hi` samples) rather than
    "everything from the trigger point to the end of the buffer" — an
    earlier version did the latter, and since the trigger point legitimately
    lands anywhere within the first `search_frac` of the buffer depending on
    the signal's actual phase that frame, the DISPLAYED WIDTH swung by up to
    2.5x frame to frame even though the left edge was correctly phase-locked
    — which reads as several ghost copies of the same waveform fanned out at
    different apparent frequencies, not one stable trace. Anchoring the
    window to a real feature is only half of what a real scope's trigger
    does; holding the time/div (window length) fixed is the other half.

    The "real preceding dip" check (a Schmitt-trigger-style dead zone, sized
    to this buffer's own peak amplitude rather than a fixed absolute
    threshold so it scales down for quiet material instead of just never
    firing) exists to reject false triggers on tiny noise wiggles sitting
    right at zero — a plain zero-crossing search with no hysteresis
    re-triggers on every little wobble near the line, which reads as
    flicker/jitter, not a stable lock.

    Only searches the first `search_frac` of the buffer, guaranteeing the
    fixed-length window (the last `1 - search_frac` fraction of the buffer)
    always fits after whatever trigger point is found. Falls back to the
    same fixed-length window taken from the end of `buf`, untriggered
    (today's free-running behavior, just at the same constant width)
    whenever nothing qualifies — near silence, or content that never dips
    and crosses back — rather than ever freezing or resizing the display,
    matching how a real scope in auto-trigger mode free-runs instead of
    going blank when untriggered.
    """
    n = len(buf)
    hi = int(n * search_frac)
    display_len = n - hi
    if hi <= lookback + 1 or display_len < 2:
        return buf
    mono = (buf[:hi + 1, 0] + buf[:hi + 1, 1]) * 0.5
    amp = float(np.max(np.abs(mono))) if len(mono) else 0.0
    if amp >= 1e-5:
        hyst = max(0.004, 0.2 * amp)
        rising = np.nonzero((mono[:-1] < 0.0) & (mono[1:] >= 0.0))[0] + 1
        for idx in rising[::-1]:  # most recent candidate first
            start = max(0, idx - lookback)
            if float(np.min(mono[start:idx])) < -hyst:
                return buf[idx:idx + display_len]
    return buf[-display_len:]


def to_points(buf, mode, N, iso=(1.0, 1.0), xy_fix=(False, False, False)):
    """iso: (x_scale, y_scale) aspect-correction factors, one axis always
    1.0 and the other <1.0 on any non-square screen — see ISO_ASPECT in
    main(). Applied to every mode here except "mono": mono's X axis is
    time, not a spatial dimension paired with Y's amplitude, so unlike
    every other mode here (all genuine XY/geometric relationships: raw L/R,
    mid-side, phase-portrait, polar) it has no 'circle should look like a
    circle' requirement to preserve, and correcting it would just needlessly
    narrow the sweep instead of using the full screen width.

    xy_fix: (swap, invert_x, invert_y) manual channel-polarity correction
    for real oscilloscope-music content — see apply_channel_fix. Applied to
    every mode here (including "mono"): whatever polarity a track actually
    needs doesn't change depending on which mode you're viewing it in."""
    L, R = resample_stereo(buf, N)
    L, R = apply_channel_fix(L, R, *xy_fix)
    if mode == "lissajous_xy":
        x, y = L, R
    elif mode == "lissajous":
        x = (L + R) * 0.7071
        y = (R - L) * 0.7071
    elif mode == "mono":
        # classic single-trace scope: time on X, summed amplitude on Y.
        # Trigger-align the window (see trigger_slice) instead of using the
        # raw L/R computed above from the untriggered buffer — a real
        # scope's Y-t trace is always trigger-locked, never a free-scrolling
        # window of whatever happened to be in the buffer this frame.
        Lt, Rt = resample_stereo(trigger_slice(buf), N)
        Lt, Rt = apply_channel_fix(Lt, Rt, *xy_fix)
        x = np.linspace(-0.95, 0.95, N).astype(np.float32)
        y = np.clip((Lt + Rt) * 0.5 * 1.7, -1.2, 1.2)
    elif mode == "phase":
        # Phase portrait / delay embedding: X = signal, Y = its own rate of
        # change. A pure tone traces a perfect ellipse; real program
        # material traces flowing, looped rosette curves — a different,
        # classic way to turn oscillating audio into closed Lissajous-family
        # shapes, mathematically distinct from the direct L/R or mid-side
        # transforms the other modes use. Uses np.gradient on the resampled
        # (already LPF-smoothed) mono signal, not the raw one — an
        # unfiltered derivative is dominated by high-frequency content and
        # would be pure noise, the same reason the other modes need
        # smoothing to read as a clean curve instead of a scribble.
        mono = (L + R) * 0.5
        deriv = np.gradient(mono)
        d_scale = (np.std(mono) + 1e-4) / (np.std(deriv) + 1e-4)
        x = mono
        y = deriv * d_scale * 0.9
    else:  # polar
        theta = np.linspace(0, 2 * np.pi, N, endpoint=False)
        mid = (L + R) * 0.5
        side = (L - R) * 0.5
        radius = 0.55 + mid * 0.5
        x = np.cos(theta) * radius + side * 0.35 * np.sin(theta * 3.0)
        y = np.sin(theta) * radius + side * 0.35 * np.cos(theta * 3.0)
    if mode != "mono":
        x = x * iso[0]
        y = y * iso[1]
    pts = np.empty((N, 2), dtype=np.float32)
    pts[:, 0] = np.clip(x, -3, 3)
    pts[:, 1] = np.clip(y, -3, 3)
    return pts


def dual_points(buf, N, xy_fix=(False, False, False)):
    """Classic two-channel scope: L trace on the top half of the screen, R
    trace on the bottom half, time on X — two separate line strips (not
    joined), same convention as split_points. Both channels share one
    trigger point (see trigger_slice) rather than each independently — a
    real dual-trace scope triggers once and shares that same timebase
    alignment across both channels, not per-channel.

    xy_fix: manual channel-polarity correction, see apply_channel_fix — a
    swap here actually swaps which channel is drawn on which half."""
    L, R = resample_stereo(trigger_slice(buf), N)
    L, R = apply_channel_fix(L, R, *xy_fix)
    t = np.linspace(-0.92, 0.92, N).astype(np.float32)
    top = np.empty((N, 2), dtype=np.float32)
    top[:, 0] = t
    top[:, 1] = np.clip(L * 0.42, -0.42, 0.42) + 0.48
    bot = np.empty((N, 2), dtype=np.float32)
    bot[:, 0] = t
    bot[:, 1] = np.clip(R * 0.42, -0.42, 0.42) - 0.48
    return np.concatenate([top, bot], axis=0).astype(np.float32)


def shift_hue_rgb(rgb, delta):
    """Rotate an RGB color's hue by `delta` (0..1 fraction of a full turn),
    keeping its saturation/value. Used to give dual/split mode's second
    channel a distinct-but-related color instead of leaving both strips in
    the exact same flat color with only screen position telling them
    apart — real dual-trace scopes color-code channels the same way."""
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb((h + delta) % 1.0, s, v)


def hsv_to_rgb_np(h, s, v):
    """Vectorized HSV -> RGB (h/s/v arrays in [0,1], any broadcastable
    shape). Used for the rainbow-trace toggle — colorsys.hsv_to_rgb in a
    Python per-vertex loop would be real overhead at up to XY_TRACE_N
    vertices, 60 times a second."""
    h = np.asarray(h, dtype=np.float32)
    s = np.asarray(s, dtype=np.float32)
    v = np.asarray(v, dtype=np.float32)
    hh = (h % 1.0) * 6.0
    i = np.floor(hh).astype(np.int32) % 6
    f = hh - np.floor(hh)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    conds = [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5]
    r = np.select(conds, [v, q, p, p, t, v])
    g = np.select(conds, [t, v, v, q, p, p])
    b = np.select(conds, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1).astype(np.float32)


def rainbow_colors(n, hue_offset=0.0):
    """Per-vertex RGB with hue sweeping one full cycle along the trace's
    arc position (index 0..n-1), for the rainbow-trace toggle."""
    hues = np.linspace(0.0, 1.0, n, endpoint=False) + hue_offset
    return hsv_to_rgb_np(hues, 0.85, 1.0)


def compute_beam_brightness(pts, floor=0.012, ceiling=2.2, exponent=1.8, cutoff_mult=4.5):
    """Per-vertex brightness factor (default range 0.012..2.2) from local
    beam speed — a real vector/CRT display is bright where the beam moves
    slowly (dwelling on a stroke) and faint-to-invisible where it jumps fast
    between disconnected parts of a picture (the 'flyback'). Plotting XY
    content with one uniform-brightness line (the old default behavior,
    still available) makes any picture read as a tangled 'Lissajous swirl'
    instead of an actual drawn shape — this is what turns it into the
    latter.

    The curve gives real dynamic range across the whole speed range, not
    just a jump/no-jump cutoff: a segment at the frame's own typical spacing
    sits at a middling ~0.86 baseline, true dwell points (near-zero motion —
    direction-change vertices, corners) climb toward the ceiling, and speed
    beyond typical fades smoothly toward the floor. That vertex-glow is a
    real, distinctive trait of actual vector/CRT displays (the beam visibly
    decelerates at a corner) that a hard bright/dim split misses entirely.

    floor/ceiling/exponent/cutoff_mult let this one curve serve two jobs at
    two different strengths: the strong 'v' beam-realism toggle (defaults
    below — full picture-drawing dynamic range, including a hard flyback
    blank) and a much gentler always-on ambient variant (tighter
    floor/ceiling around 1.0, no hard cutoff) applied to every trace
    regardless of mode or toggle state, so even a plain default trace
    subtly reads as a real beam dwelling at corners rather than a flat-
    brightness vector outline. cutoff_mult=None disables the hard-blank
    cutoff entirely — used by the gentle variant, since a corner in a plain
    mono/polar trace should dim, not vanish.

    Scale-invariant by construction (normalizes against this frame's own
    median point spacing), so it doesn't matter whether `pts` is in raw
    sample space or already zoomed — same result either way."""
    n = len(pts)
    seg_vec = pts[1:] - pts[:-1]
    seg_dist = np.hypot(seg_vec[:, 0], seg_vec[:, 1])
    med = float(np.median(seg_dist)) + 1e-6
    ratio = np.clip(med / (seg_dist + med * 0.12), 0.0, 3.0)
    # Steeper exponent + lower floor than earlier tuning (in the default/
    # strong-beam case): parts of a picture that are genuinely supposed to
    # read as disconnected strokes were still showing as a clearly-visible
    # half-brightness line at any jump size — the falloff wasn't decisive
    # enough at the low end. A real fast-swept beam trace is genuinely very
    # faint, not 'medium dim'.
    seg_bright = np.clip(ratio ** exponent, floor, ceiling)
    # Hard zero past a real-jump threshold, on top of the smooth curve
    # above: a smooth asymptotic falloff, however steep, always leaves
    # *some* nonzero brightness — and with additive persistence (decay
    # feedback can multiply a steady per-frame contribution by ~2x or
    # more), even a very dim repeated contribution can still accumulate
    # into visibility over many frames of a looping picture. A genuine
    # pen-lift needs to actually hit zero, not just approach it, for parts
    # of a picture that are supposed to read as disconnected to actually
    # separate. 4.5x the frame's own typical spacing is comfortably above
    # normal stroke-speed variation (legitimate fast strokes/corners stay
    # within the smooth curve above) but well below a real flyback, which
    # is typically a jump across a meaningful fraction of the whole image.
    # Skipped entirely for the gentle variant (cutoff_mult=None) — see
    # docstring above.
    if cutoff_mult is not None:
        seg_bright = np.where(seg_dist > med * cutoff_mult, 0.0, seg_bright)
    vert_bright = np.empty(n, dtype=np.float32)
    if n > 1:
        vert_bright[0] = seg_bright[0]
        vert_bright[-1] = seg_bright[-1]
        # min, not average: GL linearly interpolates color/width along each
        # segment between its two vertex values, so a genuinely dark
        # 'flyback' segment needs BOTH its endpoints pulled down to that
        # darkness or the interpolated line never actually gets dark
        # anywhere — averaging with the neighboring bright segment just
        # produces a uniformly medium-dim line the whole way, diluting
        # exactly the disconnection effect this is supposed to produce.
        vert_bright[1:-1] = np.minimum(seg_bright[:-1], seg_bright[1:])
    elif n == 1:
        vert_bright[0] = 1.0
    return vert_bright


def groove_ring(elapsed, total, iso=(1.0, 1.0), n=360, radius=0.94):
    """A record's edge, and how far the needle has tracked into it.

    The point of the visualiser is the listening ritual, not just the trace —
    and the thing vinyl gives you that a digital player doesn't is a physical,
    glanceable sense of WHERE YOU ARE in the side. The groove ring is that:
    a faint full circle (the record) with a brighter arc swept clockwise from
    12 o'clock (how far in you are).

    Sits at the very edge of the frame so it never competes with the trace,
    and returns (points, colors) ready for build_ribbon_strip. Returns None
    when length is unknown — better to show nothing than to guess a position.
    """
    if total <= 0:
        return None
    frac = float(np.clip(elapsed / total, 0.0, 1.0))
    sx, sy = iso

    # Clockwise from 12 o'clock, the direction a record actually plays.
    theta = -np.pi / 2 + np.linspace(0.0, 2.0 * np.pi, n, endpoint=True)
    pts = np.stack([np.cos(theta) * radius * sx,
                    np.sin(theta) * radius * sy], axis=1).astype(np.float32)

    played = theta <= (-np.pi / 2 + 2.0 * np.pi * frac)
    colors = np.zeros((n, 4), dtype=np.float32)
    colors[:, 0:3] = 0.42          # unplayed groove: barely there
    colors[:, 3] = 0.16
    colors[played, 0:3] = 1.0      # played arc: bright
    colors[played, 3] = 0.62
    return pts, colors


def build_ribbon_strip(pts, half_width_px, W, H, colors):
    """Extrude a polyline (N, 2 NDC positions, already zoom-applied) into a
    filled triangle-strip 'ribbon' with the given per-vertex half-width (in
    pixels) and per-vertex RGBA color. Returns (2N, 7)
    [x, y, r, g, b, a, edge] ready for GL_TRIANGLE_STRIP with RIBBON_VS/FS
    (edge is ±1 at the two physical boundary vertices, interpolated to 0 at
    the centerline — RIBBON_FS uses it for a soft anti-aliased falloff),
    or an empty array if N < 2.

    Built as real geometry rather than GL_LINE_STRIP + glLineWidth: core
    profile GL deprecated wide lines, and several drivers (NVIDIA's Linux
    driver among them) clamp GL_SMOOTH_LINE_WIDTH_RANGE to [1, 1] in core
    contexts regardless of what glLineWidth requests, silently rendering
    every 'thick' trace as a 1px hairline. Filled triangles work
    identically on every driver, and per-vertex width (unlike a single
    glLineWidth call) lets beam-realism make the trace physically thicker
    where it dwells, not just brighter."""
    n = len(pts)
    if n < 2:
        return np.zeros((0, 7), dtype=np.float32)
    scale = np.array([W / 2.0, H / 2.0], dtype=np.float64)
    px = pts.astype(np.float64) * scale
    tangent = np.zeros_like(px)
    tangent[1:-1] = px[2:] - px[:-2]
    tangent[0] = px[1] - px[0]
    tangent[-1] = px[-1] - px[-2]
    tlen = np.hypot(tangent[:, 0], tangent[:, 1])
    tlen[tlen < 1e-6] = 1.0
    tangent /= tlen[:, None]
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    hw = np.asarray(half_width_px, dtype=np.float64)
    if hw.ndim == 0:
        hw = np.full(n, float(hw))
    offset = normal * hw[:, None]
    left = (px + offset) / scale
    right = (px - offset) / scale
    out = np.empty((2 * n, 7), dtype=np.float32)
    out[0::2, 0:2] = left
    out[1::2, 0:2] = right
    out[0::2, 2:6] = colors
    out[1::2, 2:6] = colors
    out[0::2, 6] = 1.0
    out[1::2, 6] = -1.0
    return out


def build_ribbon_segments(pts_pairs, half_width_px, W, H, color):
    """Like build_ribbon_strip but for K disconnected 2-point segments
    (pts_pairs: (2K, 2) NDC, as from wire3d_points) instead of one
    continuous polyline. `color` is either a single RGBA (broadcast to
    every vertex) or a per-segment (K, 4) array (each segment's color
    repeated across its 6 vertices, e.g. for a rainbow trace across
    disconnected edges). Returns GL_TRIANGLES-ready (6K, 7)
    [x, y, r, g, b, a, edge] vertices (two triangles per segment quad,
    edge as in build_ribbon_strip) — GL_TRIANGLES doesn't chain vertices
    across primitives, so no strip-restart handling is needed between
    unrelated edges."""
    k = len(pts_pairs) // 2
    if k < 1:
        return np.zeros((0, 7), dtype=np.float32)
    scale = np.array([W / 2.0, H / 2.0], dtype=np.float64)
    px = pts_pairs.astype(np.float64) * scale
    a = px[0::2]
    b = px[1::2]
    d = b - a
    dlen = np.hypot(d[:, 0], d[:, 1])
    dlen[dlen < 1e-6] = 1.0
    tangent = d / dlen[:, None]
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    offset = normal * half_width_px
    a0 = (a + offset) / scale
    a1 = (a - offset) / scale
    b0 = (b + offset) / scale
    b1 = (b - offset) / scale
    out = np.empty((k * 6, 7), dtype=np.float32)
    out[0::6, 0:2] = a0
    out[1::6, 0:2] = a1
    out[2::6, 0:2] = b0
    out[3::6, 0:2] = a1
    out[4::6, 0:2] = b1
    out[5::6, 0:2] = b0
    color_arr = np.asarray(color, dtype=np.float32)
    out[:, 2:6] = np.repeat(color_arr, 6, axis=0) if color_arr.ndim == 2 else color_arr
    out[0::6, 6] = 1.0
    out[1::6, 6] = -1.0
    out[2::6, 6] = 1.0
    out[3::6, 6] = -1.0
    out[4::6, 6] = -1.0
    out[5::6, 6] = 1.0
    return out


# --- synthetic rotating wireframe (a generative "3D oscilloscope" look,
# not decoded from any specific track's audio — tracks that already encode
# a rotating 3D object *in* their waveform are plain XY content and render
# correctly through lissajous_xy + beam-realism with no extra decoding
# needed; this mode is for when you just want that look reactively). ---
_CUBE_VERTS = np.array(
    [[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=np.float64
)
_CUBE_EDGES = [
    (i, j)
    for i in range(8)
    for j in range(i + 1, 8)
    if int(np.sum(_CUBE_VERTS[i] != _CUBE_VERTS[j])) == 1
]


def _rotation_matrix(ax, ay, az):
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def wire3d_points(elapsed, bass, treble, beat_pulse, iso=(1.0, 1.0)):
    """Rotating wireframe cube, auto-rotating with bass-reactive speed and a
    beat-reactive scale pulse. Returns a flat (24, 2) array — 12 edges * 2
    endpoints — meant to be drawn as GL_LINES (disconnected segments), not
    GL_LINE_STRIP. iso: aspect-correction factors (see to_points) — a cube
    is exactly the kind of shape that reads as visibly wrong (sheared,
    non-cubic) when stretched by a non-square screen, so this needs the
    same correction every other genuinely-3D/geometric mode gets."""
    speed = 0.5 + min(1.5, bass) * 1.3
    r = _rotation_matrix(elapsed * 0.31 * speed, elapsed * 0.47 * speed, elapsed * 0.19 * speed)
    scale = 0.55 + min(1.2, beat_pulse) * 0.14 + min(1.5, treble) * 0.05
    verts3 = (_CUBE_VERTS @ r.T) * scale
    dist = 3.2
    proj = verts3[:, :2] / (dist - verts3[:, 2:3]) * dist * 0.5
    pts = np.empty((len(_CUBE_EDGES) * 2, 2), dtype=np.float32)
    for k, (i, j) in enumerate(_CUBE_EDGES):
        pts[2 * k] = proj[i]
        pts[2 * k + 1] = proj[j]
    pts[:, 0] *= iso[0]
    pts[:, 1] *= iso[1]
    return np.clip(pts, -3, 3).astype(np.float32)


def split_points(buf, mode_a, mode_b, N):
    """Two scope modes rendered simultaneously, each squeezed into its own
    half of the screen (separate line strips — NOT one continuous strip
    joining the two halves, which would draw a spurious connecting line)."""
    a = to_points(buf, mode_a, N)
    b = to_points(buf, mode_b, N)
    a2 = a.copy()
    a2[:, 0] = a[:, 0] * 0.5 - 0.55
    a2[:, 1] = a[:, 1] * 0.9
    b2 = b.copy()
    b2[:, 0] = b[:, 0] * 0.5 + 0.55
    b2[:, 1] = b[:, 1] * 0.9
    return np.concatenate([a2, b2], axis=0).astype(np.float32)


def trace_coherence(pts, mode):
    """0..1 'how resolved/locked-in is this curve right now'.

    Only meaningful for lissajous/lissajous_xy/phase: a clean harmonic
    relationship makes the traced curve close back on nearly its own start
    point (a real repeating figure); noisy/inharmonic audio leaves a gap.
    Polar mode always plots a full theta loop by construction regardless of
    signal character, so this doesn't mean the same thing there — return 0
    and let polar be unaffected, matching what was actually observed.
    """
    if mode not in ("lissajous", "lissajous_xy", "phase"):
        return 0.0
    span = np.ptp(pts, axis=0)
    scale = max(float(np.hypot(span[0], span[1])), 1e-4)
    closure_gap = float(np.hypot(pts[-1, 0] - pts[0, 0], pts[-1, 1] - pts[0, 1]))
    return max(0.0, min(1.0, 1.0 - closure_gap / scale))


def kaleido_points(buf, mode, N, folds, iso=(1.0, 1.0), xy_fix=(False, False, False)):
    """Dihedral-symmetry kaleidoscope: `folds` copies of the same trace,
    alternating a mirror flip before rotating each copy by an even slice of
    a full turn, so it reads as a symmetric reflected pattern rather than
    plain rotational repetition. Scaled down so folded copies stay in view.

    iso (see to_points) is applied to the base shape BEFORE the fold
    rotation below, not after: true mirror/rotate symmetry is only
    geometrically correct in an isotropic coordinate system, so correcting
    post-rotation would leave the individual folds themselves still subtly
    sheared relative to each other on a non-square screen. xy_fix (see
    apply_channel_fix) likewise applies to the base shape before folding."""
    base = to_points(buf, mode, N, iso=iso, xy_fix=xy_fix)
    copies = []
    for i in range(folds):
        p = base.copy()
        if i % 2 == 1:
            p[:, 0] = -p[:, 0]
        ang = i * (2.0 * np.pi / folds)
        c, s = math.cos(ang), math.sin(ang)
        x = p[:, 0] * c - p[:, 1] * s
        y = p[:, 0] * s + p[:, 1] * c
        copies.append(np.stack([x, y], axis=1))
    pts = np.concatenate(copies, axis=0) * 0.62
    return pts.astype(np.float32)


NUM_SEGMENTS = 22
ZONE_GREEN = (0.10, 1.0, 0.25, 1.0)
ZONE_AMBER = (1.0, 0.62, 0.05, 1.0)
ZONE_RED = (1.0, 0.15, 0.10, 1.0)
ZONE_PEAK = (0.92, 0.97, 1.0, 1.0)


def px_to_ndc(x, y, W, H):
    return (x / W * 2.0 - 1.0, 1.0 - y / H * 2.0)


def _quad_verts(x0, y0, x1, y1, W, H, color):
    p0 = px_to_ndc(x0, y0, W, H)
    p1 = px_to_ndc(x1, y0, W, H)
    p2 = px_to_ndc(x1, y1, W, H)
    p3 = px_to_ndc(x0, y1, W, H)
    tris = (p0, p1, p2, p0, p2, p3)
    out = []
    for x, y in tris:
        out.extend((x, y, *color))
    return out


def build_vu_geometry(W, H, level_l, level_r, peak_l, peak_r):
    """Vertical LED-bargraph style stereo meter, one column near each screen edge."""
    margin_x = 40
    bar_w = 22
    bar_h_total = H * 0.46
    bar_bottom_y = H * 0.80
    seg_gap = 3
    seg_h = (bar_h_total - seg_gap * (NUM_SEGMENTS - 1)) / NUM_SEGMENTS

    verts = []

    def add_channel(x0, x1, level, peak):
        peak_frac = min(1.0, peak * 1.6)
        for i in range(NUM_SEGMENTS):
            frac_bottom = i / NUM_SEGMENTS
            frac_top = (i + 1) / NUM_SEGMENTS
            y_bottom = bar_bottom_y - i * (seg_h + seg_gap)
            y_top = y_bottom - seg_h
            if frac_bottom < 0.65:
                zone = ZONE_GREEN
            elif frac_bottom < 0.88:
                zone = ZONE_AMBER
            else:
                zone = ZONE_RED
            lit = level * 1.6 >= frac_bottom
            is_peak = frac_bottom <= peak_frac < frac_top
            if is_peak:
                color = ZONE_PEAK
            elif lit:
                color = zone
            else:
                color = (zone[0] * 0.16, zone[1] * 0.16, zone[2] * 0.16, 1.0)
            verts.extend(_quad_verts(x0, y_top, x1, y_bottom, W, H, color))

    add_channel(margin_x, margin_x + bar_w, level_l, peak_l)
    add_channel(W - margin_x - bar_w, W - margin_x, level_r, peak_r)
    return verts


def build_spectrum_geometry(W, H, spectrum, color):
    """Horizontal band of vertical bars along the bottom-center of the
    screen (between the two VU meter columns), tinted with the current
    phosphor color rather than introducing new colors of its own."""
    n = len(spectrum)
    margin_x = 120
    usable_w = W - 2 * margin_x
    gap = 4
    bar_w = (usable_w - gap * (n - 1)) / n
    base_y = H - 28
    max_h = 130

    verts = []
    for i, v in enumerate(spectrum):
        h = min(1.3, max(0.0, float(v))) / 1.3 * max_h
        if h < 1.0:
            continue
        x0 = margin_x + i * (bar_w + gap)
        x1 = x0 + bar_w
        y1 = base_y
        y0 = base_y - h
        bright = 0.35 + 0.65 * min(1.0, float(v))
        c = (color[0] * bright, color[1] * bright, color[2] * bright, 0.85)
        verts.extend(_quad_verts(x0, y0, x1, y1, W, H, c))
    return verts


def waterfall_heat_color(t, base_color):
    """Heat-map gradient for one waterfall magnitude reading: black (silent)
    -> base_color (moderate) -> white (loud/clipping), t in [0, 1].

    Not a flat brightness scale on the base color: human vision resolves
    hue/saturation changes far better than pure brightness steps, so a
    single-hue intensity ramp (the original version) compresses most of
    the actually-interesting dynamic range into 'looks about the same dim
    color' — this is the standard technique real spectrogram tools
    (Audacity, etc.) use for exactly that reason, and it also ties the
    user's selected phosphor color into the midtones rather than ignoring
    it in favor of a fixed palette."""
    t = max(0.0, min(1.0, t))
    r, g, b = base_color
    if t < 0.5:
        k = t * 2.0
        return (r * k, g * k, b * k)
    k = (t - 0.5) * 2.0
    return (r + (1.0 - r) * k, g + (1.0 - g) * k, b + (1.0 - b) * k)


def build_waterfall_column(W, H, spectrum_db, color):
    """One frame's worth of new spectrogram data: N_BANDS horizontal
    slices stacked to fill the screen height, drawn as a thin column at the
    right edge with a heat-map color keyed to that band's current dB level
    (see waterfall_heat_color) — a true spectrogram encoding, distinct from
    build_spectrum_geometry's height-based bars. Takes AudioCapture's
    already dB-normalized spectrum_db (0..1 over SPEC_DB_FLOOR..CEIL), not
    the bar-chart-tuned spectrum — measured against this codebase's own FFT
    pipeline, the bar-chart scaling actually saturates flat across a ~20dB
    range of real signal, which would hide real detail here instead of
    revealing it. Meant to be drawn into the same history buffer the trace
    itself persists in, right after that buffer has been shifted left by a
    couple pixels (see the 'waterfall' mode's shift-based decay pass) —
    repeated every frame, this builds up a genuine scrolling waterfall
    image over time, for free reusing the CRT bloom/vignette pipeline every
    other mode already gets."""
    n = len(spectrum_db)
    col_w = 3.0
    x1 = float(W)
    x0 = x1 - col_w
    verts = []
    for i, v in enumerate(spectrum_db):
        frac_bottom = i / n
        frac_top = (i + 1) / n
        y0 = H * (1.0 - frac_top)
        y1 = H * (1.0 - frac_bottom)
        # A gentle gamma lift on top of the already-dB-scaled value pulls
        # quiet-but-real detail further up out of nearly-black — the actual
        # 'show hidden stuff' ask, layered on the more fundamentally
        # accurate dB mapping rather than replacing it.
        t = float(np.clip(v, 0.0, 1.0)) ** 0.8
        r, g, bl = waterfall_heat_color(t, color)
        verts.extend(_quad_verts(x0, y0, x1, y1, W, H, (r, g, bl, 1.0)))
    return verts


class TextOSD:
    """Renders a short-lived (or persistent) caption to a GL texture.

    anchor: "bottom-left" | "bottom-right" | "top-left" | "top-right"
    persistent: if True, stays fully visible with no fade as long as text is
    set (used for the always-on BPM readout); otherwise holds then fades
    (used for the mode/color readout and the now-playing overlay).
    """

    def __init__(self, anchor="bottom-left", hold=2.0, fade=0.7, persistent=False, font_size=30):
        pygame.font.init()
        try:
            self.font = pygame.font.SysFont("dejavusansmono,monospace", font_size)
        except Exception:
            self.font = pygame.font.Font(None, font_size + 4)
        self.anchor = anchor
        self.hold = hold
        self.fade = fade
        self.persistent = persistent
        self.tex = glGenTextures(1)
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, 4 * 4 * 4, None, GL_DYNAMIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(8))
        glEnableVertexAttribArray(1)
        glBindVertexArray(0)
        self.text = None
        self.w = self.h = 0
        self.shown_at = 0.0

    def _anchor_pos(self, W, H):
        margin = 36
        if self.anchor == "bottom-left":
            return margin, H - 70
        if self.anchor == "bottom-right":
            return None, H - 70  # x resolved after we know text width
        if self.anchor == "top-left":
            return margin, margin
        if self.anchor == "right":
            # Ritual mode puts the record left of centre, so the right half is
            # empty. That is where the words go — the sleeve half of the ritual.
            return None, H // 2
        return None, margin  # top-right

    def clear(self):
        self.text = None

    def hold_open(self):
        """Segura a legenda acesa por mais um quadro, sem redesenhar.

        O desbotamento existe porque nome de faixa é um ACONTECIMENTO: apareceu,
        você leu, sai da frente do disco. VIRE O DISCO e FIM são ESTADO — a
        instrução sumia em 2,7s enquanto o motivo dela continuava valendo, e
        um lado B parado com a tela limpa parece o programa ter travado.
        """
        if self.text is not None:
            self.shown_at = time.time()

    def set_text(self, text, W, H):
        if text == self.text:
            return
        self.text = text
        self.shown_at = time.time()
        if text is None:
            return
        surf = self.font.render(text, True, (255, 255, 255)).convert_alpha()
        self.w, self.h = surf.get_size()
        data = pygame.image.tostring(surf, "RGBA", True)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, self.w, self.h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

        margin = 36
        x0, y0 = self._anchor_pos(W, H)
        if x0 is None:
            x0 = W - margin - self.w
        x1, y1 = x0 + self.w, y0 + self.h
        p0 = px_to_ndc(x0, y0, W, H)
        p1 = px_to_ndc(x1, y0, W, H)
        p2 = px_to_ndc(x1, y1, W, H)
        p3 = px_to_ndc(x0, y1, W, H)
        quad = np.array([
            *p0, 0.0, 1.0,
            *p1, 1.0, 1.0,
            *p2, 1.0, 0.0,
            *p3, 0.0, 0.0,
        ], dtype=np.float32)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, quad.nbytes, quad)

    def alpha(self):
        if self.text is None:
            return 0.0
        if self.persistent:
            return 1.0
        age = time.time() - self.shown_at
        if age < self.hold:
            return 1.0
        if age < self.hold + self.fade:
            return 1.0 - (age - self.hold) / self.fade
        return 0.0

    def draw(self, prog, color):
        a = self.alpha()
        if a <= 0.0 or self.text is None:
            return
        glUseProgram(prog)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glUniform1i(glGetUniformLocation(prog, "tex"), 0)
        glUniform4f(glGetUniformLocation(prog, "tint"), color[0], color[1], color[2], a)
        glBindVertexArray(self.vao)
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4)
        glBindVertexArray(0)


def power_on_curve(elapsed, warmup=0.6):
    if elapsed >= warmup:
        return 1.0
    base = elapsed / warmup
    flicker = 0.15 * math.sin(elapsed * 80.0) * (1 - base)
    return max(0.0, min(1.0, base + flicker))


def main():
    loaded = load_state()

    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=MODES, default=None)
    ap.add_argument("--color", choices=list(COLORS), default=None)
    ap.add_argument("--zoom", type=float, default=None)
    ap.add_argument("--res", default=None, help="WxH; defaults to native desktop resolution, fullscreen")
    ap.add_argument("--windowed", action="store_true", help="launch windowed instead of fullscreen")
    args = ap.parse_args()

    # display.init() specifically, NOT the blanket pygame.init(): the latter
    # also auto-initializes pygame.mixer — a real playback stream (confirmed
    # via pygame.mixer.get_init() -> (44100, -16, 2)) — which flatly
    # contradicts this file's own header docstring ("It never opens a
    # playback stream, so it cannot play sound back out") and, concretely,
    # was pinning the whole PipeWire graph to 44100Hz on launch regardless
    # of AudioCapture's own rate detection below, defeating it. Nothing
    # else here needs mixer/joystick/etc — font is separately initialized
    # by TextOSD, and event/time/key all work fine off display.init() alone.
    pygame.display.init()

    if args.res:
        W, H = (int(v) for v in args.res.split("x"))
    else:
        info = pygame.display.Info()
        W, H = info.current_w, info.current_h

    state = {
        "mode": args.mode or loaded.get("mode", DEFAULTS["mode"]),
        "color": args.color or loaded.get("color", DEFAULTS["color"]),
        "zoom": args.zoom if args.zoom is not None else loaded.get("zoom", DEFAULTS["zoom"]),
        "decay": loaded.get("decay", DEFAULTS["decay"]),
        "line_w": loaded.get("line_w", DEFAULTS["line_w"]),
        "prism": False,
        "split": False,
        "kaleido": False,
        "beam": loaded.get("beam", DEFAULTS["beam"]),
        "rainbow": loaded.get("rainbow", DEFAULTS["rainbow"]),
        "custom_hue": loaded.get("custom_hue", DEFAULTS["custom_hue"]),
        "bloom": loaded.get("bloom", DEFAULTS["bloom"]),
        "freeze": False,
        "xy_swap": loaded.get("xy_swap", DEFAULTS["xy_swap"]),
        "xy_inv_x": loaded.get("xy_inv_x", DEFAULTS["xy_inv_x"]),
        "xy_inv_y": loaded.get("xy_inv_y", DEFAULTS["xy_inv_y"]),
        "true_scope": loaded.get("true_scope", DEFAULTS["true_scope"]),
        "groove": loaded.get("groove", DEFAULTS["groove"]),
    }

    src = find_monitor_source()
    print(f"monitor source: {src}")
    print(
        "keys: 1-8 mode (polar/lissajous/xy/mono/dual/wire3d/phase/waterfall)  "
        "g/a/n/w/b/c/y/o/d/u color  h/,/. custom hue  p prism  "
        "m split  k kaleidoscope  v beam-realism  y true-scope  o groove-ring  r rainbow trace  z freeze  s screenshot  "
        "i/j bloom  9/0 line width  "
        "x swap L/R  l invert X  t invert Y (channel-polarity fix for real oscilloscope-music)  "
        "+/- zoom  [ ] persistence  f fullscreen toggle  esc/q quit"
    )

    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    flags = pygame.OPENGL | pygame.DOUBLEBUF
    if not args.windowed:
        flags |= pygame.FULLSCREEN
    pygame.display.set_mode((W, H), flags)
    pygame.display.set_caption("STYLUS — deck")

    line_prog = compile_shader(LINE_VS, LINE_FS)
    decay_prog = compile_shader(QUAD_VS, DECAY_FS)
    bright_prog = compile_shader(QUAD_VS, BRIGHT_FS)
    blur_prog = compile_shader(QUAD_VS, BLUR_FS)
    comp_prog = compile_shader(QUAD_VS, COMPOSITE_FS)
    ui_prog = compile_shader(UI_VS, UI_FS)
    ribbon_prog = compile_shader(RIBBON_VS, RIBBON_FS)
    text_prog = compile_shader(TEXT_VS, TEXT_FS)

    hist_fbo = [make_fbo(W, H) for _ in range(2)]
    bloom_w, bloom_h = W // 3, H // 3
    bright_fbo, bright_tex = make_fbo(bloom_w, bloom_h)
    blur_fbo = [make_fbo(bloom_w, bloom_h) for _ in range(2)]

    quad_vao = make_quad_vao()

    # Only used for the single-point 'electron beam head' dot now (see
    # ribbon_vbo/ribbon_vao below for the actual trace geometry) — a tiny
    # GL_POINTS draw, where glPointSize is far more reliably respected
    # across drivers than glLineWidth ever was for the main trace.
    line_vbo = glGenBuffers(1)
    line_vao = glGenVertexArrays(1)
    glBindVertexArray(line_vao)
    glBindBuffer(GL_ARRAY_BUFFER, line_vbo)
    glBufferData(GL_ARRAY_BUFFER, MAX_STRIPS * TRACE_N * 2 * 4, None, GL_DYNAMIC_DRAW)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, None)
    glEnableVertexAttribArray(0)
    glBindVertexArray(0)

    # Ribbon geometry for the actual trace: filled triangle-strip quads
    # (pos + per-vertex color + cross-ribbon edge coord for AA), not
    # GL_LINE_STRIP + glLineWidth. Core-profile GL deprecated wide lines,
    # and NVIDIA's Linux driver in particular commonly clamps
    # GL_SMOOTH_LINE_WIDTH_RANGE to [1,1] regardless of what glLineWidth
    # requests — building the width as real geometry works identically on
    # every driver, and per-vertex width lets beam-realism make the trace
    # physically thicker where it dwells, not just brighter. Drawn with
    # ribbon_prog (RIBBON_VS/FS). Sized for the worst case (kaleidoscope's
    # MAX_STRIPS copies, each strip -> 2*TRACE_N ribbon vertices, 7 floats
    # each); smaller-strip-count modes just use a prefix.
    ribbon_vbo = glGenBuffers(1)
    ribbon_vao = glGenVertexArrays(1)
    ribbon_capacity = MAX_STRIPS * (2 * TRACE_N) * 28
    glBindVertexArray(ribbon_vao)
    glBindBuffer(GL_ARRAY_BUFFER, ribbon_vbo)
    glBufferData(GL_ARRAY_BUFFER, ribbon_capacity, None, GL_DYNAMIC_DRAW)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 28, ctypes.c_void_p(0))
    glEnableVertexAttribArray(0)
    glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, 28, ctypes.c_void_p(8))
    glEnableVertexAttribArray(1)
    glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, 28, ctypes.c_void_p(24))
    glEnableVertexAttribArray(2)
    glBindVertexArray(0)

    # Combined UI buffer for both the VU meters and the spectrum bars (drawn
    # in one pass since they share the same simple colored-quad shader).
    ui_vbo = glGenBuffers(1)
    ui_vao = glGenVertexArrays(1)
    vu_capacity = NUM_SEGMENTS * 2 * 6 * 6 * 4
    spectrum_capacity = N_BANDS * 6 * 6 * 4
    ui_capacity = vu_capacity + spectrum_capacity
    glBindVertexArray(ui_vao)
    glBindBuffer(GL_ARRAY_BUFFER, ui_vbo)
    glBufferData(GL_ARRAY_BUFFER, ui_capacity, None, GL_DYNAMIC_DRAW)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
    glEnableVertexAttribArray(0)
    glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(8))
    glEnableVertexAttribArray(1)
    glBindVertexArray(0)

    osd = TextOSD(anchor="bottom-left")
    mpris_osd = TextOSD(anchor="bottom-right", hold=4.0, fade=1.2, font_size=26)
    bpm_osd = TextOSD(anchor="top-right", persistent=True, font_size=24)

    cap = AudioCapture(src)
    print(f"capture rate: {cap.rate}Hz (matches PipeWire's graph clock — avoids resampling this stream)")
    now_playing = NowPlaying()
    last_np_text = None

    def current_mode2():
        return MODES[(MODES.index(state["mode"]) + 1) % len(MODES)]

    def osd_refresh():
        color_label = "PRISM" if state["prism"] else state["color"].upper()
        extra = ""
        if state["split"]:
            extra = f" · SPLIT {state['mode'].upper()}+{current_mode2().upper()}"
        elif state["kaleido"]:
            extra = f" · KALEIDO x{KALEIDO_FOLDS}"
        if state["beam"]:
            extra += " · BEAM"
        if state["rainbow"]:
            extra += " · RAINBOW"
        if state["freeze"]:
            extra += " · FROZEN"
        if state["xy_swap"] or state["xy_inv_x"] or state["xy_inv_y"]:
            flags = "".join([
                "S" if state["xy_swap"] else "",
                "X" if state["xy_inv_x"] else "",
                "Y" if state["xy_inv_y"] else "",
            ])
            extra += f" · FIX-{flags}"
        osd.set_text(
            f"{state['mode'].upper()} · {color_label} · "
            f"ZOOM {state['zoom']:.2f}x · PERSIST {state['decay']:.2f}{extra}",
            W, H,
        )

    osd_refresh()

    # Aspect-ratio correction for every genuinely-XY/geometric mode (polar,
    # lissajous, lissajous_xy, phase, wire3d, kaleido of any of those): NDC
    # is -1..1 on both axes regardless of the screen's actual pixel
    # dimensions, so with no correction a mathematically perfect circle
    # (e.g. L/R sine at 90 degrees phase) renders as an ellipse on any
    # non-square screen, and kaleidoscope's fold rotations — only true
    # mirror/rotate symmetry in an isotropic coordinate system — end up
    # visibly sheared. One axis is always 1.0 and the other shrinks to
    # match, so content always fits an inscribed square regardless of
    # whether the screen is wider or taller. W/H are fixed for the life of
    # the window (no resize handling), so this is computed once here rather
    # than every frame. Deliberately NOT applied to mono/dual (time-domain:
    # X is time, not a spatial partner to Y) or split (each half-width pane
    # is already intentionally non-square by construction).
    ISO_ASPECT = (min(1.0, H / W), min(1.0, W / H))

    t_start = time.time()
    cur = 0
    clock = pygame.time.Clock()
    running = True
    frames = 0
    t_fps = time.time()
    resolve_smooth = 0.0
    frozen = None  # cached (pts, strip_count, draw_as_lines) while state["freeze"] is on
    xy_autoscale = 1.0  # lissajous_xy-only: smoothed auto-normalization, see below
    xy_extent_smooth = None
    xy_cycle_smooth = None  # smoothed lissajous_xy window length, see below
    xy_cycle_history = []  # last ~10 raw (unsmoothed) cycle_len estimates, see below
    xy_cycle_misses = 0    # consecutive frames with no usable estimate, see XY_MISS_GRACE
    prev_elapsed = 0.0
    hue_clock = 0.0  # prism/rainbow hue phase — advances at an audio-reactive
                      # rate (see below), not a fixed elapsed*const, so color
                      # cycling actually responds to the music instead of
                      # rotating at the same robotic pace regardless of what's
                      # playing
    color_smooth = None  # eased RGB actually used for rendering, see below
    take_screenshot = False
    screenshot_dir = os.path.expanduser("~/Pictures/stylus")
    # Conferir isto de fora sempre foi frágil: o SDL não põe _NET_WM_PID na
    # janela, então `xdotool search --pid` não acha nada, e o i3 pode abrir a
    # janela num espaço de trabalho que não está à vista - aí o `maim` de tela
    # cheia fotografa o papel de parede e parece que o programa não desenhou.
    # Com isto o próprio programa tira a foto na hora combinada, sem depender
    # de tecla nem de gerenciador de janela:
    #   STYLUS_DECK_SHOT_AFTER=8  STYLUS_DECK_SHOT_QUIT=1  stylus scope
    #
    # Aceita VÁRIOS instantes separados por vírgula, e o QUIT sai depois do
    # último. Uma foto só não serve para conferir uma CERIMÔNIA: a subida do
    # prato, o cue, a descida da agulha, o meio do lado e o fim do disco são
    # momentos diferentes do mesmo programa, e conferir cada um dava uma
    # tomada de tela inteira por vez.
    #   STYLUS_DECK_SHOT_AFTER=6,9,12  STYLUS_DECK_SHOT_QUIT=1  stylus deck ...
    _shots = []
    for _piece in (os.environ.get("STYLUS_DECK_SHOT_AFTER", "") or "").split(","):
        try:
            _v = float(_piece)
        except ValueError:
            continue
        if _v > 0:
            _shots.append(_v)
    _shots.sort()
    _shot_after = _shots[0] if _shots else 0.0
    _shot_quit = os.environ.get("STYLUS_DECK_SHOT_QUIT") == "1"
    _shot_done = False
    shutdown_t = None  # time.time() a quit was requested, see SHUTDOWN_DURATION below
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if shutdown_t is None:
                    shutdown_t = time.time()
            elif ev.type == pygame.KEYDOWN:
                changed = True
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    if shutdown_t is None:
                        shutdown_t = time.time()
                    changed = False
                elif ev.key == pygame.K_1:
                    state["mode"] = "polar"
                elif ev.key == pygame.K_2:
                    state["mode"] = "lissajous"
                elif ev.key == pygame.K_3:
                    state["mode"] = "lissajous_xy"
                elif ev.key == pygame.K_4:
                    state["mode"] = "mono"
                elif ev.key == pygame.K_5:
                    state["mode"] = "dual"
                elif ev.key == pygame.K_6:
                    state["mode"] = "wire3d"
                elif ev.key == pygame.K_7:
                    state["mode"] = "phase"
                elif ev.key == pygame.K_8:
                    state["mode"] = "waterfall"
                elif ev.key == pygame.K_v:
                    state["beam"] = not state["beam"]
                elif ev.key == pygame.K_y:
                    state["true_scope"] = not state["true_scope"]
                elif ev.key == pygame.K_o:
                    state["groove"] = not state["groove"]
                elif ev.key == pygame.K_r:
                    state["rainbow"] = not state["rainbow"]
                elif ev.key == pygame.K_g:
                    state["color"] = "green"
                    state["prism"] = False
                elif ev.key == pygame.K_a:
                    state["color"] = "amber"
                    state["prism"] = False
                elif ev.key == pygame.K_n:
                    state["color"] = "neon"
                    state["prism"] = False
                elif ev.key == pygame.K_w:
                    state["color"] = "white"
                    state["prism"] = False
                elif ev.key == pygame.K_b:
                    state["color"] = "blue"
                    state["prism"] = False
                elif ev.key == pygame.K_c:
                    state["color"] = "cyan"
                    state["prism"] = False
                elif ev.key == pygame.K_y:
                    state["color"] = "yellow"
                    state["prism"] = False
                elif ev.key == pygame.K_o:
                    state["color"] = "orange"
                    state["prism"] = False
                elif ev.key == pygame.K_d:
                    state["color"] = "red"
                    state["prism"] = False
                elif ev.key == pygame.K_u:
                    state["color"] = "purple"
                    state["prism"] = False
                elif ev.key == pygame.K_h:
                    state["color"] = "custom"
                    state["prism"] = False
                elif ev.key == pygame.K_COMMA:
                    state["color"] = "custom"
                    state["prism"] = False
                    state["custom_hue"] = (state["custom_hue"] - 0.025) % 1.0
                elif ev.key == pygame.K_PERIOD:
                    state["color"] = "custom"
                    state["prism"] = False
                    state["custom_hue"] = (state["custom_hue"] + 0.025) % 1.0
                elif ev.key == pygame.K_i:
                    state["bloom"] = min(2.5, state["bloom"] + 0.15)
                elif ev.key == pygame.K_j:
                    state["bloom"] = max(0.0, state["bloom"] - 0.15)
                elif ev.key == pygame.K_9:
                    state["line_w"] = max(0.3, state["line_w"] - 0.15)
                elif ev.key == pygame.K_0:
                    state["line_w"] = min(4.0, state["line_w"] + 0.15)
                elif ev.key == pygame.K_z:
                    state["freeze"] = not state["freeze"]
                elif ev.key == pygame.K_x:
                    state["xy_swap"] = not state["xy_swap"]
                elif ev.key == pygame.K_l:
                    state["xy_inv_x"] = not state["xy_inv_x"]
                elif ev.key == pygame.K_t:
                    state["xy_inv_y"] = not state["xy_inv_y"]
                elif ev.key == pygame.K_s:
                    take_screenshot = True
                    changed = False
                elif ev.key == pygame.K_p:
                    state["prism"] = not state["prism"]
                elif ev.key == pygame.K_m:
                    state["split"] = not state["split"]
                    if state["split"]:
                        state["kaleido"] = False
                elif ev.key == pygame.K_k:
                    state["kaleido"] = not state["kaleido"]
                    if state["kaleido"]:
                        state["split"] = False
                elif ev.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    state["zoom"] = min(4.0, state["zoom"] * 1.1)
                elif ev.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    state["zoom"] = max(0.2, state["zoom"] / 1.1)
                elif ev.key == pygame.K_LEFTBRACKET:
                    state["decay"] = max(0.5, state["decay"] - 0.03)
                elif ev.key == pygame.K_RIGHTBRACKET:
                    state["decay"] = min(0.97, state["decay"] + 0.03)
                elif ev.key in (pygame.K_f, pygame.K_F11):
                    pygame.display.toggle_fullscreen()
                    changed = False
                else:
                    changed = False
                if changed:
                    osd_refresh()

        elapsed = time.time() - t_start
        buf = cap.snapshot()
        XY_FIX = (state["xy_swap"], state["xy_inv_x"], state["xy_inv_y"])

        # CRT power-off collapse, in progress once a quit was requested (see
        # shutdown_t above) — see SHUTDOWN_DURATION for the physical basis.
        # y_collapse rushes to 0 over the first ~30% of the animation
        # (vertical deflection collapses -> horizontal line), x_collapse
        # holds until then and rushes to 0 over the remaining ~45%
        # (horizontal deflection collapses -> the line shrinks to a point),
        # shutdown_flash spikes right as that collapse-to-a-point happens,
        # and overall brightness (power_mult, replacing the plain power-on
        # curve as u_power below) fades out over the tail so the final dot
        # fades rather than hard-cutting.
        y_collapse = x_collapse = 1.0
        shutdown_flash = 0.0
        power_mult = power_on_curve(elapsed)
        if shutdown_t is not None:
            sd = (time.time() - shutdown_t) / SHUTDOWN_DURATION
            if sd >= 1.0:
                running = False
            y_collapse = max(0.0, min(1.0, 1.0 - sd / 0.30))
            x_collapse = 1.0 if sd < 0.30 else max(0.0, min(1.0, 1.0 - (sd - 0.30) / 0.45))
            shutdown_flash = math.exp(-((sd - 0.72) ** 2) / 0.0025) * 2.5
            if sd > 0.75:
                power_mult *= max(0.0, 1.0 - (sd - 0.75) / 0.25)

        draw_as_lines = False  # GL_LINES (disconnected segments) instead of GL_LINE_STRIP
        is_waterfall = state["mode"] == "waterfall"
        if state["freeze"] and frozen is not None and not is_waterfall:
            # Hold the trace's shape exactly as last computed — brightness,
            # color, zoom, and bloom below still all use live audio/state,
            # so a frozen shape still visibly breathes with the music, only
            # its geometry is locked. Doesn't apply to the waterfall (there's
            # no single 'shape' to hold, it's a continuous scroll).
            pts, strip_count, draw_as_lines = frozen
        elif is_waterfall:
            # No XY points at all — the waterfall draws a new spectrogram
            # column each frame instead of a trace (see the shift-based
            # scrolling logic further down).
            pts = np.zeros((0, 2), dtype=np.float32)
            strip_count = 0
        elif state["mode"] == "wire3d":
            pts = wire3d_points(elapsed, cap.bass, cap.treble, cap.beat_pulse, iso=ISO_ASPECT)
            strip_count = 0
            draw_as_lines = True
        elif state["mode"] == "dual":
            pts = dual_points(cap.trig_snapshot(), TRACE_N, xy_fix=XY_FIX)
            strip_count = 2
        elif state["split"]:
            pts = split_points(buf, state["mode"], current_mode2(), TRACE_N)
            strip_count = 2
        elif state["kaleido"]:
            pts = kaleido_points(buf, state["mode"], TRACE_N, KALEIDO_FOLDS, iso=ISO_ASPECT, xy_fix=XY_FIX)
            strip_count = KALEIDO_FOLDS
        elif state["mode"] == "lissajous_xy":
            # lissajous_xy plots raw L/R straight as X/Y — the actual
            # encoding real oscilloscope-music pictures use — so it alone
            # gets the longer XY_BUF_N window (long enough to hold a full
            # image cycle even at a low fundamental) instead of the short
            # TRACE_N one every other mode uses. Beam-realism's speed-based
            # dimming already keeps fast motion from reading as a tangled
            # scribble more accurately than the low-pass filter does (it
            # fades fast segments instead of removing the frequency content
            # that makes them fast), so beam mode reads the fully unfiltered
            # buffer here; otherwise the lightly-filtered one.
            src_buf = cap.raw_snapshot() if state["beam"] else cap.xy_snapshot()
            # "true scope" fidelity mode (key: y). A real instrument in XY
            # mode does NOT do either of the two things below — it deflects
            # the beam directly from X and Y over whatever time window the
            # timebase is set to, and the picture appears purely because the
            # signal repeats faster than the phosphor decays. Both the
            # autocorrelation-based window trimming here and the autoscale
            # further down are non-physical helpers: they make engineered
            # oscilloscope-music crisper, at the cost of showing something an
            # actual scope would not show. With true_scope on, the raw
            # fixed-length window is used exactly as captured.
            if not state["true_scope"]:
                cycle_len = estimate_xy_cycle_len((src_buf[:, 0] + src_buf[:, 1]) * 0.5, rate=cap.rate)
                # None (nothing periodic enough this frame) is handled inside
                # advance_xy_window, which coasts on the last good window
                # through short dropouts instead of discarding the smoothing
                # state — see XY_MISS_GRACE.
                xy_cycle_smooth, xy_cycle_history, window_len, xy_cycle_misses = advance_xy_window(
                    cycle_len, xy_cycle_smooth, xy_cycle_history, xy_cycle_misses)
                if window_len is not None:
                    src_buf = src_buf[-window_len:]
            else:
                xy_cycle_smooth, xy_cycle_history, xy_cycle_misses = None, [], 0
            pts = to_points(src_buf, "lissajous_xy", XY_TRACE_N, iso=ISO_ASPECT, xy_fix=XY_FIX)
            strip_count = 1
        else:
            # Every other single-strip mode (including the mid-side
            # "lissajous" swirl, which isn't how oscilloscope-music pictures
            # are actually encoded) keeps the short, snappier TRACE_N window
            # exactly as before — beam-realism can still apply its
            # brightness/width effect here if toggled, just without the
            # longer-window/full-fidelity upgrade meant for real XY pictures.
            src_for_mode = cap.trig_snapshot() if state["mode"] == "mono" else buf
            pts = to_points(src_for_mode, state["mode"], TRACE_N, iso=ISO_ASPECT, xy_fix=XY_FIX)
            strip_count = 1

        if not is_waterfall:
            frozen = (pts, strip_count, draw_as_lines)

        if shutdown_t is not None and not is_waterfall and len(pts):
            # Applied after freeze-caching (so a frozen shape's true
            # geometry is what gets cached, not a mid-collapse one) but
            # before everything downstream that uses `pts` — a single,
            # mode-agnostic transform works here because by this point
            # `pts` already holds whichever mode's finished flat point
            # array (single/dual/kaleido/split/wire3d all funnel through
            # this same shape), so scaling its X/Y columns is correct
            # regardless of which branch produced it.
            pts = pts.copy()
            pts[:, 0] *= x_collapse
            pts[:, 1] *= y_collapse

        if (state["mode"] == "lissajous_xy" and strip_count == 1
                and len(pts) > 1 and not state["true_scope"]):
            # Auto-normalize the picture's size instead of leaving it purely
            # up to manual zoom — different oscilloscope-music tracks are
            # mastered at wildly different levels, so a fixed zoom means
            # some look tiny (wasting screen space) and others clip against
            # the edges. Two-stage, AGC-style smoothing:
            #   1) smooth the raw per-frame extent measurement itself
            #      (a single frame's 90th-percentile point spread is noisy —
            #      feeding that straight into the scale, even smoothed
            #      afterward, still visibly wobbled/pumped with the music);
            #   2) derive a target scale from the smoothed extent and ease
            #      toward it.
            # Both stages react FAST when content just got louder/bigger
            # (shrink quickly, avoid clipping against the edges) and SLOW
            # when it got quieter (grow gently — a fast grow reads as a
            # jumpy zoom-in every time there's a brief lull, which is what
            # 'not smooth or natural' was actually describing: the original
            # version had this backwards, fast on grow and slow on shrink).
            raw_extent = float(np.percentile(np.abs(pts), 90)) + 1e-4
            if xy_extent_smooth is None:
                xy_extent_smooth = raw_extent
            elif raw_extent > xy_extent_smooth:
                xy_extent_smooth += 0.05 * (raw_extent - xy_extent_smooth)
            else:
                xy_extent_smooth += 0.006 * (raw_extent - xy_extent_smooth)
            target_scale = float(np.clip(0.8 / xy_extent_smooth, 0.3, 6.0))
            if target_scale < xy_autoscale:
                xy_autoscale += 0.08 * (target_scale - xy_autoscale)
            else:
                xy_autoscale += 0.02 * (target_scale - xy_autoscale)
        # A subtle bass-driven size pulse for modes that otherwise have zero
        # scale reactivity at all (only manual zoom) — lissajous_xy already
        # has its own dynamic autoscale and wire3d already pulses its own
        # scale on the beat, so this is just for the ones left completely
        # static: polar/lissajous/mono/dual/phase. Deliberately small (max
        # ~7%) — a 'breathing' quality, not a visible bounce.
        breathe = 1.0
        if state["mode"] not in ("lissajous_xy", "wire3d"):
            breathe = 1.0 + min(1.5, cap.bass) * 0.05
        # true_scope holds the auto-normalisation at unity: a real
        # instrument has a fixed volts/div, it does not rescale itself
        # to fit whatever is on screen. Without this the last computed
        # autoscale value would simply persist while the mode is on.
        xy_gain = 1.0 if state["true_scope"] else xy_autoscale
        effective_zoom = state["zoom"] * breathe * (xy_gain if state["mode"] == "lissajous_xy" else 1.0)

        # Beam-realism only makes sense for XY content — dual/wire3d/polar
        # keep the uniform-brightness line. Kaleido and split get their own
        # per-strip variant further down (each strip may be a different
        # mode, e.g. split combining lissajous_xy with mono — beam only
        # applies to whichever strip(s) are actually lissajous-family).
        use_beam = (
            state["beam"] and strip_count == 1
            and state["mode"] in ("lissajous", "lissajous_xy")
        )

        # Coherence is measured on the canonical single-mode trace regardless
        # of split/kaleido display, so the "locked-in" glow lift reflects the
        # actual audio character, not an artifact of the duplicated geometry.
        # Skip the resample entirely for modes trace_coherence ignores
        # anyway (wire3d/waterfall/dual/mono/polar) — wasted work otherwise.
        if state["mode"] not in ("lissajous", "lissajous_xy", "phase"):
            raw_coh = 0.0
        else:
            base_for_coherence = pts if strip_count == 1 else to_points(buf, state["mode"], TRACE_N, iso=ISO_ASPECT, xy_fix=XY_FIX)
            raw_coh = trace_coherence(base_for_coherence, state["mode"])
        coh_atk, coh_rel = 0.18, 0.04
        if raw_coh > resolve_smooth:
            resolve_smooth += coh_atk * (raw_coh - resolve_smooth)
        else:
            resolve_smooth += coh_rel * (raw_coh - resolve_smooth)

        # Advance the shared hue clock at an audio-reactive rate instead of
        # a fixed elapsed*const — a robotic fixed-rate hue rotation is about
        # as undynamic as color cycling can get; tying its speed to bass
        # and onset energy makes it actually respond to the music, speeding
        # up through energetic passages and settling during quiet ones.
        frame_dt = max(0.0, elapsed - prev_elapsed)
        prev_elapsed = elapsed

        # Ritual mode's clock. Advanced every frame even while the geometry
        # is not being drawn yet, so the platter is already at 33 1/3 and the
        # ceremony is in the right phase by the time the album resolves.
        hue_clock += (0.10 + min(1.5, cap.bass) * 0.22 + min(1.5, cap.onset) * 0.12) * frame_dt

        if state["prism"]:
            hue = hue_clock % 1.0
            color_target = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
        elif state["color"] == "custom":
            color_target = colorsys.hsv_to_rgb(state["custom_hue"], 0.9, 1.0)
        else:
            color_target = COLORS[state["color"]]
        # Cross-fade to a newly selected color instead of snapping to it
        # instantly — an instant color swap on a keypress reads as
        # mechanical; a ~0.3s ease reads as an actual color change
        # happening, and costs nothing when the target isn't moving (prism
        # already changes every frame, so this just adds a slight, pleasant
        # trailing quality there rather than altering it structurally).
        if color_smooth is None:
            color_smooth = color_target
        else:
            color_smooth = tuple(
                color_smooth[i] + 0.15 * (color_target[i] - color_smooth[i]) for i in range(3)
            )
        color = color_smooth
        onset = min(cap.onset, 1.5)

        boost = 1.0 + onset * 1.2

        nxt = 1 - cur
        glBindFramebuffer(GL_FRAMEBUFFER, hist_fbo[nxt][0])
        glViewport(0, 0, W, H)
        glDisable(GL_BLEND)
        glUseProgram(decay_prog)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, hist_fbo[cur][1])
        glUniform1i(glGetUniformLocation(decay_prog, "hist"), 0)
        if is_waterfall:
            # Spectrogram waterfall: scroll the whole history left every
            # frame (shift) instead of fading it (near-1.0 decay — old data
            # should scroll off-screen, not fade out, that's the whole point
            # of a waterfall). WATERFALL_SCROLL_SECONDS to fully traverse the
            # screen, independent of resolution since shift is a UV fraction
            # — the original 2.2px/frame constant was only ~14.5s to cross a
            # 1920px screen and read as basically not moving at all. Reuses
            # the exact same ping-pong history buffer every other mode's
            # persistence trail lives in, just with different shader
            # behavior.
            glUniform1f(glGetUniformLocation(decay_prog, "decay"), 0.999)
            glUniform1f(glGetUniformLocation(decay_prog, "shift"), 1.0 / (WATERFALL_SCROLL_SECONDS * 60.0))
        else:
            # Ritual mode draws a large STATIC shape every frame. Phosphor
            # persistence is built for a moving beam, so re-adding the same
            # dark disc frame after frame accumulates additively until the
            # black plastic saturates to white — which is exactly what it
            # did. The record supplies its own trail anyway: live_groove
            # already fades an arc behind the stylus.
            glUniform1f(glGetUniformLocation(decay_prog, "decay"),
                        state["decay"])
            glUniform1f(glGetUniformLocation(decay_prog, "shift"), 0.0)
        draw_quad(quad_vao)

        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE)

        # half-width in pixels for the trace ribbon; onset punches it wider
        # on a hit, same as the old glLineWidth-based thickness did.
        half_w_px = state["line_w"] * (1.0 + onset * 1.8) / 2.0

        if is_waterfall:
            # New spectrogram column drawn additively into the just-shifted
            # history buffer — reuses the VU/spectrum-bar quad geometry
            # machinery (ui_prog/ui_vbo/ui_vao), just with different source
            # geometry, since it's the exact same 'pos + per-vertex color
            # filled triangles' shape those already use. Everything after
            # this block (head-dot check, bloom, composite) runs exactly
            # once regardless of mode, same as every other mode — no need
            # to duplicate any of that here.
            col_verts = np.array(
                build_waterfall_column(W, H, cap.spectrum_db, color), dtype=np.float32
            )
            if len(col_verts):
                glUseProgram(ui_prog)
                glBindBuffer(GL_ARRAY_BUFFER, ui_vbo)
                glBufferSubData(GL_ARRAY_BUFFER, 0, col_verts.nbytes, col_verts)
                glBindVertexArray(ui_vao)
                glDrawArrays(GL_TRIANGLES, 0, len(col_verts) // 6)
                glBindVertexArray(0)
        else:
            glUseProgram(ribbon_prog)
            glBindVertexArray(ribbon_vao)
            glBindBuffer(GL_ARRAY_BUFFER, ribbon_vbo)

            if draw_as_lines:
                k = len(pts) // 2
                if state["rainbow"]:
                    seg_rgb = rainbow_colors(k, hue_offset=hue_clock * 1.2) * boost
                    seg_color = np.empty((k, 4), dtype=np.float32)
                    seg_color[:, 0:3] = seg_rgb
                    seg_color[:, 3] = 1.0
                else:
                    r, g, bl = color
                    seg_color = (r * boost, g * boost, bl * boost, 1.0)
                verts = build_ribbon_segments(pts * effective_zoom, half_w_px, W, H, seg_color)
                if len(verts):
                    glBufferSubData(GL_ARRAY_BUFFER, 0, verts.nbytes, verts)
                    glDrawArrays(GL_TRIANGLES, 0, len(verts))
            elif use_beam:
                zpts = pts * effective_zoom
                vb = compute_beam_brightness(pts)  # scale-invariant: raw or zoomed, same result
                b = vb * boost
                if state["rainbow"]:
                    rgb = rainbow_colors(len(pts), hue_offset=hue_clock * 1.2)
                else:
                    rgb = np.tile(np.array(color, dtype=np.float32), (len(pts), 1))
                colors = np.empty((len(pts), 4), dtype=np.float32)
                colors[:, 0:3] = rgb * b[:, None]
                colors[:, 3] = 1.0
                # the beam is physically wider where it dwells (slow/bright),
                # not just brighter — real CRT beams do both together. Same
                # reasoning as the brightness floor above: a flyback segment
                # was still rendering at over half its normal width even
                # fully dimmed, which alone was enough to read as a visible
                # connecting line regardless of how dark it was.
                widths = half_w_px * (0.08 + 0.92 * np.clip(vb / 2.2, 0.0, 1.0))
                verts = build_ribbon_strip(zpts, widths, W, H, colors)
                if len(verts):
                    glBufferSubData(GL_ARRAY_BUFFER, 0, verts.nbytes, verts)
                    glDrawArrays(GL_TRIANGLE_STRIP, 0, len(verts))
            else:
                zpts = pts * effective_zoom
                r, g, bl = color
                uniform_color = np.array([r * boost, g * boost, bl * boost, 1.0], dtype=np.float32)
                strips = []
                for i in range(strip_count):
                    if strip_count == 1:
                        # A lone strip IS the whole array — don't assume its
                        # length is TRACE_N (lissajous_xy uses a different,
                        # larger point count; slicing by TRACE_N here would
                        # silently truncate it).
                        strip_pts = zpts
                    else:
                        strip_pts = zpts[i * TRACE_N:(i + 1) * TRACE_N]
                    n_s = len(strip_pts)

                    # Which mode is this particular strip actually showing?
                    # Kaleido: every fold is the same mode. Split: strip 0
                    # is the current mode, strip 1 is current_mode2()'s
                    # partner — the two halves can be genuinely different
                    # modes, so beam only applies to whichever is actually
                    # lissajous-family.
                    if state["kaleido"]:
                        strip_mode = state["mode"]
                    elif state["split"]:
                        strip_mode = state["mode"] if i == 0 else current_mode2()
                    else:
                        strip_mode = None
                    strip_use_beam = state["beam"] and strip_mode in ("lissajous", "lissajous_xy")

                    # Second channel/pane gets a hue-shifted variant of the
                    # base color instead of the exact same flat color — a
                    # real dual-trace scope color-codes its channels the
                    # same way, and it's the only thing (besides screen
                    # position) telling L from R, or the two split panes
                    # apart, at a glance. Applies whether or not this strip
                    # also gets beam modulation, so a beam-eligible second
                    # pane still reads as visually distinct.
                    if i == 1 and (state["mode"] == "dual" or state["split"]):
                        base_rgb = shift_hue_rgb(color, 0.42)
                    else:
                        base_rgb = color

                    if strip_use_beam:
                        # Same speed-based brightness/width modulation as
                        # the single-strip beam path, computed per strip —
                        # for kaleido, every fold is a mirrored/rotated copy
                        # of the same source trace, so this reads as a
                        # symmetric, beam-accurate kaleidoscope of an actual
                        # drawn picture instead of a uniform-brightness one.
                        strip_pts_raw = pts if strip_count == 1 else pts[i * TRACE_N:(i + 1) * TRACE_N]
                        vb = compute_beam_brightness(strip_pts_raw)
                        b = vb * boost
                        if state["rainbow"]:
                            rgb = rainbow_colors(n_s, hue_offset=hue_clock * 1.2 + i * 0.5)
                        else:
                            rgb = np.tile(np.array(base_rgb, dtype=np.float32), (n_s, 1))
                        strip_colors = np.empty((n_s, 4), dtype=np.float32)
                        strip_colors[:, 0:3] = rgb * b[:, None]
                        strip_colors[:, 3] = 1.0
                        strip_widths = half_w_px * (0.08 + 0.92 * np.clip(vb / 2.2, 0.0, 1.0))
                        strips.append(build_ribbon_strip(strip_pts, strip_widths, W, H, strip_colors))
                        continue

                    if state["rainbow"]:
                        strip_colors = np.empty((n_s, 4), dtype=np.float32)
                        strip_colors[:, 0:3] = rainbow_colors(n_s, hue_offset=hue_clock * 1.2 + i * 0.5) * boost
                        strip_colors[:, 3] = 1.0
                    elif i == 1 and (state["mode"] == "dual" or state["split"]):
                        r2, g2, b2 = base_rgb
                        strip_color2 = np.array([r2 * boost, g2 * boost, b2 * boost, 1.0], dtype=np.float32)
                        strip_colors = np.tile(strip_color2, (n_s, 1))
                    else:
                        strip_colors = np.tile(uniform_color, (n_s, 1))
                    strip_w = half_w_px
                    if n_s >= 2:
                        # Gentle, always-on version of the same dwell-time
                        # physics the strong 'v' beam-realism toggle uses
                        # above (see compute_beam_brightness) — real Z-axis
                        # modulation isn't an optional mode on an actual
                        # scope, it's just what an electron beam always
                        # does. Brightness-only, no width modulation: width
                        # varying along a already-dense real-music trace
                        # (lots of direction changes packed close together)
                        # reads as a rippling/corrugated "extra waves"
                        # texture on the line itself, not a subtle glow —
                        # reported directly and it tracks with what varying
                        # width along a busy path would look like. Tighter
                        # floor/ceiling than the strong toggle. A real
                        # flyback cutoff IS included here now (much looser
                        # than the strong toggle's 4.5x) — without any hard
                        # cutoff, this path drew a plain connected line
                        # across every jump no matter how large, including
                        # genuine flyback-scale jumps between unrelated
                        # parts of a trace, which read directly as "edges
                        # connecting that shouldn't be" — that blanking
                        # shouldn't be exclusive to the strong beam toggle,
                        # a real beam never draws the flyback either way.
                        # cutoff_mult was 7.0, which measured as blanking
                        # almost nothing: on real music only 0.12% of
                        # segments exceed 7x the median spacing, while the
                        # 99.9th percentile is 8.5x. Genuine flyback jumps
                        # live in the 3-7x band and were all being drawn as
                        # bright connecting lines — exactly the "edges
                        # connecting that shouldn't be" complaint. 3.5x
                        # blanks ~0.5% of segments, which is where the real
                        # jumps are, while normal stroke variation (the bulk
                        # of the distribution, well under 3x) is untouched.
                        gentle = compute_beam_brightness(
                            strip_pts, floor=0.8, ceiling=1.2, exponent=0.9, cutoff_mult=3.5
                        )
                        strip_colors[:, 0:3] *= gentle[:, None]
                    strips.append(build_ribbon_strip(strip_pts, strip_w, W, H, strip_colors))

                # Groove ring last, so it sits over the trace rather than
                # under it, and outside the freeze/beam logic entirely — it
                # tracks the record, not the signal. Off in ritual mode: the
                # tonearm already says where in the side we are, and better.
                if state["groove"]:
                    _el, _tot = now_playing.progress()
                    _ring = groove_ring(_el, _tot, iso=ISO_ASPECT)
                    if _ring is not None:
                        _rpts, _rcols = _ring
                        strips.append(build_ribbon_strip(_rpts, 1.1, W, H, _rcols))
                if strips:
                    combined = np.concatenate(strips, axis=0)
                    if len(combined):
                        glBufferSubData(GL_ARRAY_BUFFER, 0, combined.nbytes, combined)
                        off = 0
                        for s in strips:
                            if len(s):
                                glDrawArrays(GL_TRIANGLE_STRIP, off, len(s))
                            off += len(s)
        glBindVertexArray(0)

        # Bright "electron beam" head at the newest sample — a real scope's
        # trace is a single moving dot, and this comet-head sells that even
        # though we're actually drawing a whole strip per frame. Single-strip
        # modes only (ambiguous which strip is "the" beam otherwise), and
        # skipped under beam-realism (the speed-modulated line already ends
        # brightly wherever the beam actually dwells).
        if strip_count == 1 and not use_beam and len(pts) > 0:
            head = (pts[-1:] * effective_zoom).astype(np.float32)
            glUseProgram(line_prog)
            glBindBuffer(GL_ARRAY_BUFFER, line_vbo)
            glBufferSubData(GL_ARRAY_BUFFER, 0, head.nbytes, head)
            if state["rainbow"]:
                # match the exact hue the trace's own last vertex carries,
                # not the flat base color — otherwise the head-dot looks
                # like a leftover mono-color artifact on an otherwise
                # multicolor trace.
                tip_hue = (hue_clock * 1.2 + (len(pts) - 1) / len(pts)) % 1.0
                head_rgb = hsv_to_rgb_np(tip_hue, 0.85, 1.0)
            else:
                head_rgb = np.array(color, dtype=np.float32)
            glUniform3f(
                glGetUniformLocation(line_prog, "color"),
                head_rgb[0] * boost * 1.8, head_rgb[1] * boost * 1.8, head_rgb[2] * boost * 1.8,
            )
            glUniform1f(glGetUniformLocation(line_prog, "zoom"), 1.0)
            glPointSize(4.0 + onset * 3.0)
            glBindVertexArray(line_vao)
            glDrawArrays(GL_POINTS, 0, 1)
            glBindVertexArray(0)

        glDisable(GL_BLEND)
        cur = nxt

        glBindFramebuffer(GL_FRAMEBUFFER, bright_fbo)
        glViewport(0, 0, bloom_w, bloom_h)
        glUseProgram(bright_prog)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, hist_fbo[cur][1])
        glUniform1i(glGetUniformLocation(bright_prog, "src"), 0)
        draw_quad(quad_vao)

        src_tex = bright_tex
        for i in range(3):
            for pass_i, (dx, dy) in enumerate(((1, 0), (0, 1))):
                dst = blur_fbo[pass_i][0]
                glBindFramebuffer(GL_FRAMEBUFFER, dst)
                glViewport(0, 0, bloom_w, bloom_h)
                glUseProgram(blur_prog)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, src_tex)
                glUniform1i(glGetUniformLocation(blur_prog, "src"), 0)
                glUniform2f(glGetUniformLocation(blur_prog, "texel"), 1.0 / bloom_w, 1.0 / bloom_h)
                glUniform2f(glGetUniformLocation(blur_prog, "dir"), dx, dy)
                draw_quad(quad_vao)
                src_tex = blur_fbo[pass_i][1]

        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, W, H)
        glUseProgram(comp_prog)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, hist_fbo[cur][1])
        glUniform1i(glGetUniformLocation(comp_prog, "base"), 0)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, src_tex)
        glUniform1i(glGetUniformLocation(comp_prog, "glow"), 1)
        glUniform1f(glGetUniformLocation(comp_prog, "u_time"), elapsed)
        glUniform1f(glGetUniformLocation(comp_prog, "u_power"), power_mult)
        glUniform1f(glGetUniformLocation(comp_prog, "u_loud"), min(1.5, (cap.level_l + cap.level_r) * 3.0))
        glUniform1f(glGetUniformLocation(comp_prog, "u_bass"), min(1.5, cap.bass))
        glUniform1f(glGetUniformLocation(comp_prog, "u_treble"), min(1.5, cap.treble))
        glUniform1f(glGetUniformLocation(comp_prog, "u_beat"), min(1.2, cap.beat_pulse))
        glUniform1f(glGetUniformLocation(comp_prog, "u_resolve"), min(1.0, resolve_smooth))
        glUniform1f(glGetUniformLocation(comp_prog, "u_bloom"), state["bloom"])
        glUniform1f(glGetUniformLocation(comp_prog, "u_flat"), 1.0 if is_waterfall else 0.0)
        glUniform1f(glGetUniformLocation(comp_prog, "u_flash"), shutdown_flash)
        draw_quad(quad_vao)

        ui_verts = build_vu_geometry(W, H, cap.level_l, cap.level_r,
                                           cap.peak_l, cap.peak_r)
        ui_arr = np.array(ui_verts, dtype=np.float32)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glUseProgram(ui_prog)
        glBindBuffer(GL_ARRAY_BUFFER, ui_vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, ui_arr.nbytes, ui_arr)
        glBindVertexArray(ui_vao)
        glDrawArrays(GL_TRIANGLES, 0, len(ui_arr) // 6)
        glBindVertexArray(0)

        # Now-playing overlay: small corner text, fades in on track change,
        # hidden entirely when nothing's playing. Truncated to fit whatever
        # room actually remains next to the main OSD's own current text
        # (only reserved while that text is actually visible, via
        # osd.alpha() — it fades on its own timer independent of this) —
        # a fixed character cap still let a long track title overlap a
        # long OSD string (e.g. several FIX-flags active) even at 1400x900,
        # since neither text knew anything about the other's actual width.
        np_artist, np_title = now_playing.snapshot()
        if np_artist and np_title:
            osd_reserved = osd.w if osd.alpha() > 0 else 0
            char_w = mpris_osd.font.size("M")[0] or 1
            max_chars = max(6, int((W - 72 - osd_reserved - 30) / char_w))
            np_text = f"{np_artist} - {np_title}"[:max_chars]
        else:
            np_text = None
        if np_text != last_np_text:
            mpris_osd.set_text(np_text, W, H)
            mpris_osd.hold_open()
            last_np_text = np_text

        # Sample rate always shown (real test gear convention — a scope's
        # own readout tells you your actual sample rate/timebase), BPM
        # appended only once a beat's actually been detected.
        rate_khz = cap.rate / 1000.0
        if cap.bpm > 30:
            bpm_osd.set_text(f"{rate_khz:g}kHz · BPM ~{int(round(cap.bpm))}", W, H)
        else:
            bpm_osd.set_text(f"{rate_khz:g}kHz", W, H)

        osd.draw(text_prog, color)
        mpris_osd.draw(text_prog, color)
        bpm_osd.draw(text_prog, color)
        glDisable(GL_BLEND)

        if _shot_after and not _shot_done and elapsed >= _shot_after:
            take_screenshot = True
            _shots.pop(0)
            if _shots:
                _shot_after = _shots[0]
            else:
                _shot_done = True

        if take_screenshot:
            take_screenshot = False
            try:
                # Read the default framebuffer now, after compositing but
                # before the double-buffer swap below — it holds exactly
                # this frame's final on-screen image. glReadPixels rows run
                # bottom-to-top (GL's origin convention); flipped=True in
                # fromstring corrects that back to normal top-to-bottom.
                raw = glReadPixels(0, 0, W, H, GL_RGB, GL_UNSIGNED_BYTE)
                img = pygame.image.fromstring(raw, (W, H), "RGB", True)
                os.makedirs(screenshot_dir, exist_ok=True)
                fname = os.path.join(screenshot_dir, f"scope-{time.strftime('%Y%m%d-%H%M%S')}.png")
                pygame.image.save(img, fname)
                print(f"saved screenshot: {fname}")
                if _shot_quit and _shot_done:
                    running = False
            except Exception as e:
                print(f"screenshot failed: {e}")

        pygame.display.flip()
        clock.tick(60)
        frames += 1
        if time.time() - t_fps > 5:
            print(f"fps~{frames / (time.time() - t_fps):.1f} mode={state['mode']} color={state['color']}")
            frames = 0
            t_fps = time.time()

    save_state(state)
    now_playing.close()
    cap.close()
    pygame.quit()


if __name__ == "__main__":
    main()
