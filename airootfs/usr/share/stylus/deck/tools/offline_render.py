#!/usr/bin/env python3
"""
Render the visualiser's geometry to PNG files WITHOUT the GUI.

Why this exists
---------------
Every change to the lissajous_xy pipeline so far had to be evaluated by
launching the app and looking at it. That has two problems: it needs Davi
physically present, and "does this look better" is not measurable, so several
rounds of fixes shipped unverified and the reported problem persisted.

This drives the REAL functions from scope.py (estimate_xy_cycle_len,
advance_xy_window, to_points) over a chosen audio source and draws the
resulting point array with PIL. No OpenGL, no audio device, no window. That
makes two things possible:

  1. Look at what the geometry actually is, frame by frame, on demand.
  2. Measure stability numerically (see --stats) rather than by eye.

It deliberately reuses scope.py's own functions rather than reimplementing
them — an earlier ad-hoc test reimplemented estimate_xy_cycle_len, which
risks the test and the app drifting apart and measuring different things.

What it does NOT reproduce: the GPU shading (beam brightness, Gaussian trace
cross-section, glow, persistence). This is about geometry — is the shape
right, is it stable — not about how pretty the beam looks.

Usage
-----
  # synthetic signals with known-correct answers
  ./venv/bin/python tools/offline_render.py --signal circle --frames 6
  ./venv/bin/python tools/offline_render.py --signal lissajous-3-2
  ./venv/bin/python tools/offline_render.py --signal polyphonic --stats

  # a real file (any format ffmpeg can read)
  ./venv/bin/python tools/offline_render.py --file ~/Music/…/some.flac \\
      --start 30 --frames 8

Output goes to tools/offline-out/ as frame_NN.png plus a filmstrip.png
contact sheet, which is the useful one: frame-to-frame drift is obvious in a
strip and invisible in a single frame.
"""
import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# scope.py parses argv at import, so hide ours from it — but restore
# afterwards, or this script's own flags are silently swallowed and every run
# quietly uses defaults (which is exactly what happened the first time).
_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
import scope                       # noqa: E402
sys.argv = _argv

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offline-out")


# ── audio sources ────────────────────────────────────────────────────────────

def synth(kind, rate, seconds):
    """Signals whose correct rendering is known in advance, so a wrong
    result is unambiguous rather than a matter of taste."""
    t = np.arange(int(rate * seconds)) / rate
    if kind == "circle":
        # 90-degree phase pair: must render as a perfect circle.
        L, R = np.sin(2 * np.pi * 440 * t), np.cos(2 * np.pi * 440 * t)
    elif kind.startswith("lissajous-"):
        a, b = (int(x) for x in kind.split("-")[1:3])
        L, R = np.sin(2 * np.pi * 220 * a * t), np.sin(2 * np.pi * 220 * b * t)
    elif kind == "line":
        # identical channels: must collapse to a 45-degree diagonal line.
        L = R = np.sin(2 * np.pi * 300 * t)
    elif kind == "polyphonic":
        # NOT a pure tone — a fundamental plus inharmonic partials with
        # independently drifting amplitudes, approximating ordinary music.
        # This is the case the visualiser is reportedly bad at.
        rng = np.random.default_rng(0)
        L = np.sin(2 * np.pi * 110 * t)
        for f, amp, am in [(163.0, 0.6, 0.7), (271.0, 0.4, 1.3), (398.0, 0.25, 2.1)]:
            env = 0.5 + 0.5 * np.sin(2 * np.pi * am * t + rng.uniform(0, 6.28))
            L += amp * env * np.sin(2 * np.pi * f * t)
        R = np.roll(L, 37) * 0.9      # slight decorrelation between channels
        L += 0.03 * rng.standard_normal(len(t))
        R += 0.03 * rng.standard_normal(len(t))
    else:
        raise SystemExit(f"unknown --signal: {kind}")
    peak = max(np.max(np.abs(L)), np.max(np.abs(R)), 1e-9)
    return np.stack([L / peak, R / peak], axis=1).astype(np.float32)


def from_file(path, rate, start, seconds):
    """Decode via ffmpeg to raw float32 stereo at the app's own rate."""
    cmd = [
        "ffmpeg", "-v", "error", "-ss", str(start), "-t", str(seconds),
        "-i", os.path.expanduser(path),
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-ar", str(rate), "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    buf = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
    peak = max(np.max(np.abs(buf)), 1e-9)
    return (buf / peak).astype(np.float32)


# ── rendering ────────────────────────────────────────────────────────────────

def draw(pts, size, zoom, bright=None):
    """Draw the point array the way the GPU connects it: as a polyline.

    `bright` is the per-vertex brightness from compute_beam_brightness. When
    supplied, segments are drawn per-pair at their real brightness, so
    flyback blanking (brightness 0) is actually visible as a GAP — which is
    the whole point when the complaint is "edges connecting that shouldn't
    be". Without it every segment draws at full brightness and blanking is
    invisible here even when the app is doing it correctly.
    """
    img = Image.new("RGB", (size, size), (4, 6, 10))
    d = ImageDraw.Draw(img)
    half = size / 2
    d.line([(half, 0), (half, size)], fill=(20, 26, 34))
    d.line([(0, half), (size, half)], fill=(20, 26, 34))
    if len(pts) > 1:
        xy = [(half + p[0] * half * zoom, half - p[1] * half * zoom) for p in pts]
        if bright is None:
            d.line(xy, fill=(190, 226, 250), width=1)
        else:
            for i in range(len(xy) - 1):
                b = min(bright[i], bright[i + 1])
                if b <= 0.001:
                    continue                      # blanked — leave a real gap
                c = (int(190 * b), int(226 * b), int(250 * b))
                d.line([xy[i], xy[i + 1]], fill=c, width=1)
    return img


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--signal", default="circle",
                     help="circle | line | lissajous-A-B | polyphonic")
    src.add_argument("--file", help="audio file to decode with ffmpeg")
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--start", type=float, default=0.0, help="--file offset, seconds")
    ap.add_argument("--size", type=int, default=420)
    ap.add_argument("--zoom", type=float, default=0.9)
    ap.add_argument("--mode", default="lissajous_xy")
    ap.add_argument("--stats", action="store_true",
                    help="print window-length stability numbers")
    ap.add_argument("--beam", action="store_true",
                    help="apply the app's beam brightness + flyback blanking,\nso blanked segments show as real gaps")
    ap.add_argument("--cutoff", type=float, default=3.5,
                    help="flyback blanking threshold for --beam")
    ap.add_argument("--true-scope", dest="true_scope", action="store_true",
                    help="fidelity mode: no adaptive window, no autoscale —\nwhat a real instrument shows (matches the app's y key)")
    ap.add_argument("--raw", action="store_true",
                    help="skip the XY low-pass the app applies (debug only)")
    ap.add_argument("--lpf", type=float, default=None,
                    help="override XY_LPF_CUTOFF_HZ for the input filter")
    ap.add_argument("--grace", type=int, default=None,
                    help="override XY_MISS_GRACE (0 = the old discard-state-on-\nevery-dropout behaviour). Lets you A/B a change rather than trusting it.")
    args = ap.parse_args()
    if args.grace is not None:
        scope.XY_MISS_GRACE = args.grace

    seconds = args.start + (args.frames / args.fps) + 0.5
    if args.file:
        audio = from_file(args.file, args.rate, args.start, seconds)
        label = os.path.basename(args.file)
    else:
        audio = synth(args.signal, args.rate, seconds)
        label = args.signal

    # The app does NOT feed raw audio to lissajous_xy — AudioCapture runs it
    # through a one-pole low-pass first (XY_LPF_CUTOFF_HZ, currently 6kHz)
    # via xy_snapshot(), or leaves it raw only under the beam toggle which
    # has its own 14kHz anti-alias stage. An earlier version of this harness
    # skipped that entirely and so measured noisier data than the app ever
    # sees, which inflates both the dropout count and the instability
    # numbers. Apply the same filter here so measurements are comparable.
    if not args.raw:
        cutoff = args.lpf if args.lpf is not None else scope.XY_LPF_CUTOFF_HZ
        audio = scope.OnePoleLPF(cutoff, args.rate).apply(audio)

    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.endswith(".png"):
            os.remove(os.path.join(OUT_DIR, f))

    advance = args.rate // args.fps
    smooth, history = None, []
    frames, windows = [], []
    # one-element lists so the autoscale block below can mutate them in place
    autoscale, extent_smooth = [1.0], [None]
    misses, raw_misses = 0, 0

    pos = scope.XY_BUF_N
    for i in range(args.frames):
        if pos > len(audio):
            print(f"ran out of audio at frame {i}")
            break
        src_buf = audio[pos - scope.XY_BUF_N:pos]

        if args.mode == "lissajous_xy" and not args.true_scope:
            mono = (src_buf[:, 0] + src_buf[:, 1]) * 0.5
            cycle_len = scope.estimate_xy_cycle_len(mono, rate=args.rate)
            smooth, history, window_len, misses = scope.advance_xy_window(
                cycle_len, smooth, history, misses)
            if window_len is not None:
                src_buf = src_buf[-window_len:]
            windows.append(window_len)
            if cycle_len is None:
                raw_misses += 1
            n = scope.XY_TRACE_N
        elif args.mode == "lissajous_xy":
            # true scope: full fixed window, no trimming, no autoscale
            windows.append(len(src_buf))
            n = scope.XY_TRACE_N
        else:
            n = scope.TRACE_N

        pts = scope.to_points(src_buf, args.mode, n)

        # Reproduce main()'s AGC-style auto-normalisation. Without it the
        # trace renders at whatever raw level the material happens to sit at,
        # which is NOT what ends up on screen — an early version of this tool
        # omitted it and made real music look far smaller and more off-centre
        # than it actually appears in the app.
        if args.mode == "lissajous_xy" and len(pts) > 1 and not args.true_scope:
            raw_extent = float(np.percentile(np.abs(pts), 90)) + 1e-4
            if extent_smooth[0] is None:
                extent_smooth[0] = raw_extent
            elif raw_extent > extent_smooth[0]:
                extent_smooth[0] += 0.05 * (raw_extent - extent_smooth[0])
            else:
                extent_smooth[0] += 0.006 * (raw_extent - extent_smooth[0])
            target = float(np.clip(0.8 / extent_smooth[0], 0.3, 6.0))
            if target < autoscale[0]:
                autoscale[0] += 0.08 * (target - autoscale[0])
            else:
                autoscale[0] += 0.02 * (target - autoscale[0])

        b = None
        if args.beam and len(pts) > 1:
            b = scope.compute_beam_brightness(pts, floor=0.8, ceiling=1.2,
                                              exponent=0.9, cutoff_mult=args.cutoff)
        frames.append(draw(pts, args.size, args.zoom * autoscale[0], b))
        pos += advance

    for i, img in enumerate(frames):
        img.save(os.path.join(OUT_DIR, f"frame_{i:02d}.png"))

    if frames:
        strip = Image.new("RGB", (args.size * len(frames), args.size), (4, 6, 10))
        for i, img in enumerate(frames):
            strip.paste(img, (i * args.size, 0))
        strip.save(os.path.join(OUT_DIR, "filmstrip.png"))
        print(f"wrote {len(frames)} frames + filmstrip.png to {OUT_DIR}  [{label}]")

    if args.stats and windows:
        vals = [w for w in windows if w]
        if vals:
            a = np.array(vals, dtype=float)
            d = np.abs(np.diff(a)) if len(a) > 1 else np.array([0.0])
            print(f"window_len: mean={a.mean():.0f} min={a.min():.0f} "
                  f"max={a.max():.0f} spread={a.max()/max(a.min(),1):.2f}x")
            print(f"frame-to-frame |delta|: mean={d.mean():.1f} max={d.max():.1f}")
            print(f"frames with no raw estimate: {raw_misses}/{len(windows)}")
            print(f"frames with no usable window: {len(windows) - len(vals)}/{len(windows)}")


if __name__ == "__main__":
    main()
