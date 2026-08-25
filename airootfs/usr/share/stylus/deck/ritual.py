#!/usr/bin/env python3
"""GPU vinyl record player — CRT-phosphor aesthetic, live audio groove.

A standalone ritual app: the disc, the ceremony, the arm, the music.
Built on its own GL foundation, not as a mode inside the oscilloscope.
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

try:
    import vinyl
except Exception as _e:
    vinyl = None
    _VINYL_ERR = _e


RATE = 44100
BLOCK = 512
TRACE_N = 760

LPF_CUTOFF_HZ = 900.0

RITUAL_CX, RITUAL_CY, RITUAL_R = -0.10, -0.10, 0.76
RITUAL_GAIN = 1.18  # was 1.8 — bloomed everything to white with honest palette

N_BANDS = 28
SPEC_FFT_N = 2048
SPEC_MIN_HZ = 40.0
SPEC_MAX_HZ = 15000.0

STATE_PATH = os.path.expanduser("~/.local/share/stylus/ritual-state.json")
DEFAULTS = {"zoom": 1.9, "bloom": 1.0, "line_w": 1.15}


# ── shaders ──────────────────────────────────────────────────────────────

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
void main() { frag = texture(hist, uv) * decay; }
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

// Máscara do disco — separa o objeto do fundo.
uniform vec4 u_disc;

float disc_inside(vec2 p, vec4 disc) {
    if (disc.w <= 0.0) return 0.0;
    vec2 q = (p - disc.xy) / max(disc.zw, vec2(1e-5));
    // borda dura — 0.9%% anti-alias, não nuvem de 5%%
    return 1.0 - smoothstep(0.992, 1.001, length(q));
}

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }

void main() {
    // VINYL NÃO É CRT — sem curva, sem scanline. Objeto físico sob softbox.
    vec2 cuv = uv;
    vec2 d = cuv - 0.5;
    float ins = disc_inside(cuv, u_disc);

    // Aberração mínima, só fora do disco.
    vec2 ca = d * 0.0015 * (1.0 - ins);
    vec3 b = vec3(
        texture(base, cuv + ca).r,
        texture(base, cuv).g,
        texture(base, cuv - ca).b
    );
    vec3 g = vec3(
        texture(glow, cuv + ca * 1.2).r,
        texture(glow, cuv).g,
        texture(glow, cuv - ca * 1.2).b
    );
    // Dentro do disco o plástico não respira nem blooma — só o sulco vivo.
    float breathe = mix(1.0 + u_loud * 0.55, 1.0, ins);
    float bloomK = mix(u_bloom * 0.85, u_bloom * 0.18, ins);
    g *= breathe * bloomK;

    // Vinheta: disco 95%% livre, fundo suave.
    float vig = 1.0 - dot(d, d) * 0.58;
    vig = clamp(vig, 0.0, 1.0);
    vig = mix(vig, 1.0, 0.95 * ins + 0.35 * (1.0 - ins));

    // Poeira: 0.004 dentro (quase nada), 0.025 fora — honesto.
    float grain = (hash(floor(cuv * 520.0) + u_time * 41.0) - 0.5)
                  * mix(0.025, 0.004, ins) * mix(1.0, 0.55, min(1.0, u_loud * 0.5));

    // Softbox elíptico no acrílico — não diagonal pow 6 de CRT.
    vec2 glareCoord = (cuv - vec2(0.35, 0.20)) / vec2(0.55, 0.38);
    float glare = 1.0 - length(glareCoord);
    glare = pow(clamp(glare, 0.0, 1.0), 12.0) * 0.07 * (1.0 - ins * 0.3);

    // Sparkle só fora do disco — vinil não cintila.
    float sparkle = 0.0;
    if (ins < 0.5) {
        float sparkleCell = hash(floor(cuv * 280.0));
        float twinkle = 0.5 + 0.5 * sin(u_time * 38.0 + sparkleCell * 70.0);
        sparkle = step(0.9965, sparkleCell) * u_treble * twinkle;
    }

    vec3 col = (b + g) * vig;
    // plinth — warm dark wood, not scope's phosphor green
    vec3 plinth = vec3(0.06, 0.04, 0.028) * (0.9 + 0.10 * sin(cuv.x * 40.0) * sin(cuv.y * 40.0));
    col += mix(plinth, vec3(0.008, 0.011, 0.014), ins) * vig;
    col += grain * vig;
    col += glare * vig;
    col += vec3(0.90, 0.92, 1.0) * sparkle * vig;
    col *= u_power;
    // Graves/beat só fora do disco — plástico não incha com grave.
    col *= mix(1.0 + u_bass * 0.18, 1.0, ins);
    col *= mix(1.0 + u_beat * 0.10, 1.0, ins);
    col *= mix(1.0 + u_resolve * 0.20, 1.0, ins);
    frag = vec4(max(col, 0.0), 1.0);
}
"""

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
// Vinyl groove is a matte incision, not an electron beam.
// Flat profile with only 8%% core lift — reads as pencil, not phosphor.
void main() {
    float d = abs(vedge);
    float a = 1.0 - smoothstep(0.45, 1.0, d);
    a *= 0.92 + 0.08 * exp(-d * d * 8.0);
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


# ── GL utilities ─────────────────────────────────────────────────────────

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


# ── audio helpers ────────────────────────────────────────────────────────

class OnePoleLPF:
    def __init__(self, cutoff_hz, rate, channels=2):
        rc = 1.0 / (2 * np.pi * cutoff_hz)
        dt = 1.0 / rate
        self.alpha = dt / (rc + dt)
        self.y = np.zeros(channels, dtype=np.float64)

    def apply(self, block):
        out = np.empty_like(block, dtype=np.float64)
        y = self.y
        a = self.alpha
        for i in range(len(block)):
            y = y + a * (block[i].astype(np.float64) - y)
            out[i] = y
        self.y = y
        return out.astype(np.float32)


class BandFlash:
    def __init__(self, scale=16.0, decay=0.72):
        self.scale = scale
        self.decay = decay
        self.v = 0.0

    def update(self, energy, dt):
        target = energy * self.scale
        if target > self.v:
            self.v += 0.35 * (target - self.v)
        else:
            self.v *= self.decay ** (dt * 60.0)
        return self.v


def detect_graph_rate(default=RATE):
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


def find_monitor_source():
    forced = os.environ.get("STYLUS_DECK_SOURCE")
    if forced:
        return forced
    out = subprocess.run(
        ["pactl", "list", "sources", "short"], capture_output=True, text=True
    ).stdout
    lines = [l for l in out.splitlines() if ".monitor" in l]
    for l in lines:
        if "RUNNING" in l:
            return l.split()[1]
    if lines:
        return lines[0].split()[1]
    return None


# ── audio capture ────────────────────────────────────────────────────────

class AudioCapture:
    def __init__(self, source_name):
        if pyaudio is None:
            import sys
            sys.stderr.write(
                "ritual: o deck precisa do PortAudio para ler o som que está "
                "tocando, e ele não está instalado (falta python-pyaudio).\n"
                "         Rode `stylus update` para trazer a versão que o "
                "inclui.\n")
            raise SystemExit(3)
        self.buf = np.zeros((TRACE_N, 2), dtype=np.float32)
        self.rate = detect_graph_rate(default=RATE)
        self._lock = threading.Lock()
        self._stop = False
        self._lpf = OnePoleLPF(LPF_CUTOFF_HZ, self.rate)
        self._bass_lpf = OnePoleLPF(150.0, self.rate, channels=1)
        self._midhi_lpf = OnePoleLPF(2500.0, self.rate, channels=1)
        self._onset_flash = BandFlash(scale=18.0)
        self._bass_flash = BandFlash(scale=16.0, decay=0.80)
        self._treble_flash = BandFlash(scale=26.0, decay=0.68)

        self.level_l = 0.0
        self.level_r = 0.0
        self.peak_l = 0.0
        self.peak_r = 0.0
        self.onset = 0.0
        self.bass = 0.0
        self.treble = 0.0

        self._spec_buf = np.zeros(SPEC_FFT_N, dtype=np.float32)
        self._hann = np.hanning(SPEC_FFT_N).astype(np.float32)
        freqs = np.fft.rfftfreq(SPEC_FFT_N, 1.0 / self.rate)
        edges = np.logspace(np.log10(SPEC_MIN_HZ), np.log10(SPEC_MAX_HZ), N_BANDS + 1)
        self._band_masks = [
            (freqs >= edges[i]) & (freqs < edges[i + 1]) for i in range(N_BANDS)
        ]
        for i, m in enumerate(self._band_masks):
            if not m.any():
                idx = int(np.argmin(np.abs(freqs - edges[i])))
                m[idx] = True
        self.spectrum = np.zeros(N_BANDS, dtype=np.float32)

        self._bass_hist = collections.deque(maxlen=43)
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
        return None

    def _update_spectrum(self, raw):
        mono = raw.mean(axis=1)
        self._spec_buf = np.roll(self._spec_buf, -len(mono))
        self._spec_buf[-len(mono):] = mono
        if np.any(self._spec_buf):
            windowed = self._spec_buf * self._hann
        else:
            windowed = self._spec_buf
        fft = np.abs(np.fft.rfft(windowed))
        bands = np.array([fft[m].mean() if m.any() else 0.0 for m in self._band_masks])
        self.spectrum = np.clip(np.log1p(bands * 3.0) / 3.5, 0, 1).astype(np.float32)

    def _run(self):
        while not self._stop:
            try:
                data = self.stream.read(BLOCK, exception_on_overflow=False)
            except Exception:
                continue
            raw = np.frombuffer(data, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0
            filtered = self._lpf.apply(raw)
            bass_raw = np.abs(filtered[:, 0] + filtered[:, 1]) * 0.5
            midhi_raw = np.abs(filtered[:, 0] - filtered[:, 1]) * 0.5
            bass = float(self._bass_lpf.apply(bass_raw.reshape(-1, 1)).mean())
            midhi = float(self._midhi_lpf.apply(midhi_raw.reshape(-1, 1)).mean())
            now = time.time()
            level_l = float(np.sqrt(np.mean(raw[:, 0] ** 2)))
            level_r = float(np.sqrt(np.mean(raw[:, 1] ** 2)))
            onset = self._onset_flash.update(midhi, BLOCK / self.rate)
            bass_f = self._bass_flash.update(bass, BLOCK / self.rate)
            treble_f = self._treble_flash.update(midhi, BLOCK / self.rate)
            dt_beat = now - self._last_beat_t
            if bass_f > 1.8 and dt_beat > 0.18:
                if self._last_beat_t > 0:
                    self._beat_intervals.append(dt_beat)
                self._last_beat_t = now
                self.beat_pulse = 1.0
            self.beat_pulse *= 0.88
            if len(self._beat_intervals) >= 4:
                med = sorted(self._beat_intervals)[len(self._beat_intervals) // 2]
                self.bpm = 60.0 / med
            self._bass_hist.append(bass)
            self._update_spectrum(raw)
            with self._lock:
                self.buf = filtered[-TRACE_N:].copy()
                self.level_l = level_l
                self.level_r = level_r
                self.peak_l = max(self.peak_l * 0.995, level_l)
                self.peak_r = max(self.peak_r * 0.995, level_r)
                self.onset = onset
                self.bass = bass_f
                self.treble = treble_f

    def snapshot(self):
        with self._lock:
            return self.buf.copy()

    def close(self):
        self._stop = True
        try:
            self.stream.stop_stream()
            self.stream.close()
            self.p.terminate()
        except Exception:
            pass


# ── now-playing (MPRIS) ──────────────────────────────────────────────────

class NowPlaying:
    def __init__(self, poll_interval=1.0):
        self._available = shutil.which("playerctl") is not None
        self._lock = threading.Lock()
        self._artist = ""
        self._title = ""
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
                         "{{artist}}\t{{title}}"],
                        capture_output=True, text=True, timeout=2,
                    ).stdout.strip()
                    if out:
                        parts = out.split("\t")
                        if len(parts) >= 2:
                            artist, title = parts[0], parts[1]
            except Exception:
                pass
            with self._lock:
                self._artist, self._title = artist, title
            time.sleep(interval)

    def snapshot(self):
        with self._lock:
            return self._artist, self._title

    def close(self):
        self._stop = True


# ── text OSD ─────────────────────────────────────────────────────────────

class TextOSD:
    def __init__(self, anchor="bottom-left", hold=2.0, fade=0.7,
                 persistent=False, font_size=30):
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
        glBufferData(GL_ARRAY_BUFFER, 6 * 4 * 4, None, GL_DYNAMIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(8))
        glEnableVertexAttribArray(1)
        glBindVertexArray(0)
        self._text = None
        self._surfs = {}
        self._t0 = 0.0
        self.w = 0

    def set_text(self, text, W, H):
        self._text = text
        self._t0 = time.monotonic()
        self._surfs = {}
        self.w = 0
        if text:
            surf = self.font.render(text, True, (255, 255, 255))
            self._surfs[W] = surf
            self.w = surf.get_width()

    def hold_open(self):
        self._t0 = time.monotonic()

    def alpha(self):
        if self._text is None:
            return 0.0
        age = time.monotonic() - self._t0
        if self.persistent:
            return 1.0
        if age < self.hold:
            return 1.0
        fade_age = age - self.hold
        if fade_age > self.fade:
            return 0.0
        return max(0.0, 1.0 - fade_age / self.fade)

    def draw(self, prog, color):
        a = self.alpha()
        if a <= 0.0 or self._text is None:
            return
        W = pygame.display.get_surface().get_size()[0]
        surf = self._surfs.get(W)
        if surf is None:
            surf = self.font.render(self._text, True, (255, 255, 255))
            self._surfs[W] = surf
        rw, rh = surf.get_size()
        tex_data = pygame.image.tostring(surf, "RGBA", True)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, rw, rh, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, tex_data)
        m = 40
        if "right" in self.anchor:
            x0 = W - rw - m
        elif "top" in self.anchor:
            x0 = m
        else:
            x0 = m
        H = pygame.display.get_surface().get_size()[1]
        if "top" in self.anchor:
            y0 = m
        elif "bottom" in self.anchor:
            y0 = H - rh - m
        else:
            y0 = H - rh - m
        def px(x, y):
            return (x / W * 2.0 - 1.0, 1.0 - y / H * 2.0)
        p0 = px(x0, y0)
        p1 = px(x0 + rw, y0)
        p2 = px(x0 + rw, y0 + rh)
        p3 = px(x0, y0 + rh)
        arr = np.array([
            *p0, 0, 0, *p1, 1, 0, *p2, 1, 1,
            *p0, 0, 0, *p2, 1, 1, *p3, 0, 1,
        ], dtype=np.float32)
        r, g, b = color
        glUniform1i(glGetUniformLocation(prog, "tex"), 0)
        glUniform4f(glGetUniformLocation(prog, "tint"),
                    r * a * 1.8, g * a * 1.8, b * a * 1.8, a)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, arr.nbytes, arr)
        glDrawArrays(GL_TRIANGLES, 0, 6)
        glBindVertexArray(0)


# ── record label (PIL → GL texture) ─────────────────────────────────────

class RecordLabel:
    def __init__(self):
        self.tex = glGenTextures(1)
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, 6 * 4 * 4, None, GL_DYNAMIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(8))
        glEnableVertexAttribArray(1)
        glBindVertexArray(0)
        self.source = "\x00"
        self.ok = False

    def load(self, path):
        if path == self.source:
            return
        self.source = path
        self.ok = False
        if not path or not os.path.isfile(path):
            return
        try:
            from PIL import Image
            n = 512
            im = Image.open(path).convert("RGBA").resize((n, n), Image.LANCZOS)
            a = np.asarray(im).astype(np.float32).copy()
            yy, xx = np.mgrid[0:n, 0:n]
            rad = np.hypot(xx - (n - 1) / 2.0, yy - (n - 1) / 2.0) / ((n - 1) / 2.0)
            a[..., 3] *= np.clip((1.0 - rad) * (n * 0.25), 0.0, 1.0)
            hole = vinyl.R_SPINDLE / vinyl.R_LABEL
            a[..., 3] *= np.clip((rad - hole) * (n * 0.25), 0.0, 1.0)
            rim = np.clip(((rad - 0.92) * 20.0) * (1.0 - (rad - 0.92) * 20.0), 0.0, 1.0)
            a[..., 0] -= rim * a[..., 0] * 0.75
            a[..., 1] -= rim * a[..., 1] * 0.75
            a[..., 2] -= rim * a[..., 2] * 0.75
            data = a.clip(0, 255).astype(np.uint8).tobytes()
            glBindTexture(GL_TEXTURE_2D, self.tex)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, n, n, 0,
                         GL_RGBA, GL_UNSIGNED_BYTE, data)
            self.ok = True
        except Exception as e:
            print(f"ritual: capa não carregou: {type(e).__name__}: {e}")
            self.ok = False

    def draw(self, prog, rotation, iso, alpha=1.0):
        if not self.ok:
            return
        r = vinyl.R_LABEL * RITUAL_R
        c, sn = math.cos(rotation), math.sin(rotation)
        corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        arr = np.empty((4, 4), dtype=np.float32)
        for i, (u, v) in enumerate(corners):
            x = (u * c - v * sn) * r * iso[0] + RITUAL_CX
            y = (u * sn + v * c) * r * iso[1] + RITUAL_CY
            arr[i, 0] = x
            arr[i, 1] = y
            arr[i, 2] = u * 0.5 + 0.5
            arr[i, 3] = v * 0.5 + 0.5
        quad = np.array([
            *arr[0], *arr[1], *arr[2],
            *arr[0], *arr[2], *arr[3],
        ], dtype=np.float32)
        glUseProgram(prog)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glUniform1i(glGetUniformLocation(prog, "tex"), 0)
        glUniform1f(glGetUniformLocation(prog, "alpha"), alpha)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferSubData(GL_ARRAY_BUFFER, 0, quad.nbytes, quad)
        glDrawArrays(GL_TRIANGLES, 0, 6)
        glBindVertexArray(0)


# ── ribbon geometry ──────────────────────────────────────────────────────

def px_to_ndc(x, y, W, H):
    return (x / W * 2.0 - 1.0, 1.0 - y / H * 2.0)


def build_ribbon_strip(pts, half_width_px, W, H, colors):
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
    out[:, 2:6] = (np.repeat(color_arr, 6, axis=0) if color_arr.ndim == 2
                    else color_arr)
    out[0::6, 6] = 1.0
    out[1::6, 6] = -1.0
    out[2::6, 6] = 1.0
    out[3::6, 6] = -1.0
    out[4::6, 6] = -1.0
    out[5::6, 6] = 1.0
    return out


# ── power-on curve ───────────────────────────────────────────────────────

def power_on_curve(elapsed, warmup=0.6):
    if elapsed >= warmup:
        return 1.0
    base = elapsed / warmup
    flicker = 0.15 * math.sin(elapsed * 80.0) * (1 - base)
    return max(0.0, min(1.0, base + flicker))


# ── state persistence ────────────────────────────────────────────────────

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


# ── ritual scene (ceremony, album, deck) ────────────────────────────────

class RitualScene:
    def __init__(self, view=False):
        self.view = view
        self.session = vinyl.Session()
        self.deck = vinyl.Deck()
        # view mode: já está tocando, sem cerimônia — agulha direto no sulco
        if self.view:
            self.deck.phase = vinyl.PLAY
            self.deck.speed = vinyl.REV_PER_SEC
        self.album = None
        self._key = None
        self._resolving = False
        self._side = None
        self._was_paused = False
        self._rearm = False
        self._ended = False
        self._last_phase = None
        self._banner = None
        self._banner_until = 0.0
        self._last_t_abs = 0.0
        self._ti_cache = [None, 0]

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

    def _resolve(self, snap):
        try:
            folder = vinyl.resolve_album(
                snap.get("path"), snap.get("artist", ""), snap.get("album", ""))
            self.album = vinyl.Album(folder) if folder else None
            if self.album is not None:
                print(f"record: {self.album.artist} — {self.album.name} "
                      f"({len(self.album.tracks)} faixas, "
                      f"posto {self.album.plays}x)")
                self._rearm = True
            else:
                print(f"record: nenhuma pasta local para "
                      f"{snap.get('artist','?')} — {snap.get('album','?')}")
        except Exception as e:
            self.album = None
            print(f"record: falhou ao ler o álbum: {type(e).__name__}: {e}")
        finally:
            self._resolving = False

    def update(self, dt):
        snap = self.session.snapshot()
        _path = snap.get("path") or ""
        _folder = os.path.dirname(_path) if _path else ""
        key = (_folder, snap.get("artist"), snap.get("album"))
        if key != self._key and not self._resolving and any(key):
            self._key = key
            self._resolving = True
            threading.Thread(target=self._resolve, args=(snap,), daemon=True).start()
        if self._rearm:
            self._rearm = False
            self._side = None
            self._ended = False
            if self.view:
                # view não interrompe a música — agulha já no sulco
                self.deck.phase = vinyl.PLAY
                self.deck.speed = vinyl.REV_PER_SEC
                self.deck.t0 = time.monotonic()
                self.deck.crackle = 0.0
            else:
                self.deck.after_lift = vinyl.BREAK
                self.deck.go(vinyl.SPINUP)
        paused = bool(snap.get("paused", True))
        if (self._ended and not paused and self.album is not None
                and self.album.total):
            _pos, _d = self.session.position()
            if self.album.album_time(snap.get("track_index", 0) or 0,
                                     _pos) < self.album.total - 5.0:
                self._rearm = True
        if self.album is not None and self.album.total:
            pos, _dur = self.session.position()
            _ti = self._track_index(snap)
            if _ti >= len(self.album.tracks):
                if not self._ended and self.deck.phase == vinyl.PLAY:
                    self._end_of_record()
                return self._finish_update(dt, snap, paused)
            t_abs = self.album.album_time(_ti, pos)
            idx, _side = self.album.side_for(t_abs)
            if _side is not None:
                if self._side is None:
                    self._side = idx
                elif idx != self._side:
                    self._side = idx
                    if self.deck.phase == vinyl.PLAY:
                        self.deck.after_lift = vinyl.BREAK
                        self.deck.go(vinyl.LIFT)
                        self.session.pause(True)
            self._last_t_abs = t_abs
            if (not self._ended and self.deck.phase == vinyl.PLAY
                    and t_abs >= self.album.total - 0.4):
                self._end_of_record()
        if (not self._ended and self.album is not None and self.album.total
                and self.deck.phase == vinyl.PLAY
                and snap.get("source") == "none"
                and self._last_t_abs >= self.album.total - 20.0):
            self._end_of_record()
        if self._was_paused and not paused and self.deck.phase == vinyl.BREAK:
            self.deck.go(vinyl.RETURN)
        return self._finish_update(dt, snap, paused)

    def _finish_update(self, dt, snap, paused):
        self._was_paused = paused
        phase = self.deck.update(dt, playing=not paused)
        # agulha controla o som — honest, instantâneo
        if not self.view and snap.get("source") == "mpv":
            needle_down = (phase == vinyl.PLAY and self.deck.arm_lift() < 0.12)
            if needle_down and paused:
                self.session.pause(False)
            elif not needle_down and not paused and phase in (
                    vinyl.SPINUP, vinyl.CUE, vinyl.DROP, vinyl.LIFT,
                    vinyl.BREAK, vinyl.STOP, vinyl.RETURN):
                self.session.pause(True)
        if phase == vinyl.PLAY and self._last_phase == vinyl.DROP:
            self._register_play()
        self._last_phase = phase
        return snap

    def _track_index(self, snap):
        return vinyl.track_index_for(self.album, snap, self._ti_cache)

    def _end_of_record(self):
        self._ended = True
        self.deck.after_lift = vinyl.STOP
        self.deck.go(vinyl.LIFT)

    def _register_play(self):
        al = self.album
        if al is None:
            return
        try:
            n = vinyl.log_play(al.folder, al.artist, al.name)
        except Exception:
            return
        al.plays = n
        if not al.first_played:
            al.first_played = time.time()
        self._banner = vinyl.play_banner(n, al.first_played,
                                         f"{al.artist} — {al.name}")
        self._banner_until = time.monotonic() + 7.0

    def banner_text(self):
        if self._banner and time.monotonic() < self._banner_until:
            return self._banner
        return None

    def caption_is_state(self):
        return (self.deck.phase in (vinyl.BREAK, vinyl.STOP)
                or self.banner_text() is not None)

    def current_lyric(self, snap):
        if self.album is None:
            return None
        idx = self._track_index(snap)
        try:
            lines = self.album.lyrics_for(idx)
        except Exception:
            return None
        if not lines:
            return None
        pos, _dur = self.session.position()
        lo, hi = 0, len(lines)
        while lo < hi:
            mid = (lo + hi) // 2
            if lines[mid][0] <= pos:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        text = (lines[lo - 1][1] or "").strip()
        return text or None

    def build(self, snap, buf, W, H, iso):
        album = self.album
        if album is None or not album.total or snap is None:
            return [], None

        cx, cy, radius = RITUAL_CX, RITUAL_CY, RITUAL_R
        light = math.radians(-38.0)
        rot = self.deck.rotation

        pos, _dur = self.session.position()
        t_abs = album.album_time(self._track_index(snap), pos)
        side_idx, side = album.side_for(t_abs)
        if side is None:
            return [], None
        span = max(1e-6, side["end"] - side["start"])
        frac = float(np.clip((t_abs - side["start"]) / span, 0.0, 1.0))

        def _gain(v, k=RITUAL_GAIN):
            v = v.copy()
            v[:, 2:5] *= k
            return v

        strips = [_gain(v) for v in vinyl.disc_body(cx, cy, radius, iso, light)]

        tris = []
        wm = vinyl.wear_marks(cx, cy, radius, iso, rot,
                              seed=album.seed, plays=album.plays,
                              crackle=self.deck.crackle)
        if wm is not None and len(wm[0]):
            tris.append(build_ribbon_segments(wm[0], 1.2, W, H, wm[1]))

        env = album.envelope_snapshot()
        side_tracks = [album.tracks[i] for i in side.get("tracks", [])]
        played = int(frac * (vinyl.N_RINGS - 1))
        for pts, cols, wd in vinyl.groove_rings(cx, cy, radius, iso, side, env,
                                                side_tracks, light, played_ring=played):
            strips.append(_gain(build_ribbon_strip(pts, wd, W, H, cols)))
        br = vinyl.boundary_ring(cx, cy, radius, iso, side, env, frac, light)
        if br:
            strips.append(_gain(build_ribbon_strip(br[0], br[2], W, H, br[1])))

        if buf is not None and len(buf):
            mid = buf[:, 0] + buf[:, 1] if buf.ndim == 2 else buf
            sid = buf[:, 0] - buf[:, 1] if buf.ndim == 2 else np.zeros_like(mid)
            lg = vinyl.live_groove(cx, cy, radius, iso, frac, mid, sid, rot)
            if lg:
                strips.append(build_ribbon_strip(lg[0], lg[2], W, H, lg[1]))

        for pts, cols, wd in vinyl.edge_and_label_rings(cx, cy, radius, iso, light):
            strips.append(_gain(build_ribbon_strip(pts, wd, W, H, cols)))

        rest = vinyl.arm_rest(cx, cy, radius, iso)
        if rest is not None and len(rest[0]):
            tris.append(build_ribbon_segments(rest[0], 1.8, W, H, rest[1]))

        play_r = vinyl.R_PROG_OUT + (vinyl.R_PROG_IN - vinyl.R_PROG_OUT) * frac
        segs, cols, _stylus = vinyl.tonearm(
            cx, cy, radius, iso,
            self.deck.arm_target_radius(play_r), lift=self.deck.arm_lift())
        if len(segs):
            tris.append(build_ribbon_segments(segs, 2.2, W, H, cols))
        arm = np.concatenate(tris, axis=0) if tris else None
        return strips, arm


# ── main ─────────────────────────────────────────────────────────────────

def main():
    if vinyl is None:
        print(f"ritual: vinyl.py não disponível: {_VINYL_ERR}")
        raise SystemExit(1)

    loaded = load_state()

    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default=None, help="WxH")
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--view", action="store_true",
                    help="só observa — não controla o mpv, sem cerimônia")
    args = ap.parse_args()

    pygame.display.init()

    if args.res:
        W, H = (int(v) for v in args.res.split("x"))
    else:
        info = pygame.display.Info()
        W, H = info.current_w, info.current_h

    state = {
        "zoom": loaded.get("zoom", DEFAULTS["zoom"]),
        "bloom": loaded.get("bloom", DEFAULTS["bloom"]),
        "line_w": loaded.get("line_w", DEFAULTS["line_w"]),
    }

    src = find_monitor_source()
    print(f"monitor source: {src}")
    print("keys: space play/pause  ←/→ seek  +/- volume  f fullscreen  q quit  s screenshot")

    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,
                                    pygame.GL_CONTEXT_PROFILE_CORE)
    flags = pygame.OPENGL | pygame.DOUBLEBUF
    if not args.windowed:
        flags |= pygame.FULLSCREEN
    pygame.display.set_mode((W, H), flags)
    pygame.display.set_caption("STYLUS — ritual")

    decay_prog = compile_shader(QUAD_VS, DECAY_FS)
    bright_prog = compile_shader(QUAD_VS, BRIGHT_FS)
    blur_prog = compile_shader(QUAD_VS, BLUR_FS)
    comp_prog = compile_shader(QUAD_VS, COMPOSITE_FS)
    ribbon_prog = compile_shader(RIBBON_VS, RIBBON_FS)
    text_prog = compile_shader(TEXT_VS, TEXT_FS)
    label_prog = compile_shader(TEXT_VS, LABEL_FS)
    record_label = RecordLabel()

    hist_fbo = [make_fbo(W, H) for _ in range(2)]
    bloom_w, bloom_h = W // 3, H // 3
    bright_fbo, bright_tex = make_fbo(bloom_w, bloom_h)
    blur_fbo = [make_fbo(bloom_w, bloom_h) for _ in range(2)]

    quad_vao = make_quad_vao()

    ribbon_vbo = glGenBuffers(1)
    ribbon_vao = glGenVertexArrays(1)
    ribbon_capacity = 4 * 1024 * 1024
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

    osd = TextOSD(anchor="bottom-left")
    mpris_osd = TextOSD(anchor="bottom-right", hold=4.0, fade=1.2, font_size=26)
    lyric_osd = TextOSD(anchor="right", persistent=True, font_size=34)
    last_lyric = None

    cap = AudioCapture(src)
    print(f"capture rate: {cap.rate}Hz")
    now_playing = NowPlaying()
    ritual = RitualScene(view=args.view)
    last_np_text = None
    if args.view:
        print("ritual: modo view — só observando, sem controlar a agulha")

    ISO_ASPECT = (min(1.0, H / W), min(1.0, W / H))

    t_start = time.time()
    clock = pygame.time.Clock()
    running = True
    frames = 0
    t_fps = time.time()
    prev_elapsed = 0.0
    take_screenshot = False
    screenshot_dir = os.path.expanduser("~/Pictures/stylus")
    shutdown_t = None

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

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if shutdown_t is None:
                    shutdown_t = time.time()
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    if shutdown_t is None:
                        shutdown_t = time.time()
                elif ev.key == pygame.K_SPACE:
                    subprocess.Popen(["playerctl", "play-pause"])
                elif ev.key == pygame.K_LEFT:
                    subprocess.Popen(["playerctl", "position", "10-"])
                elif ev.key == pygame.K_RIGHT:
                    subprocess.Popen(["playerctl", "position", "+10"])
                elif ev.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    subprocess.Popen(["pamixer", "-i", "5"])
                elif ev.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    subprocess.Popen(["pamixer", "-d", "5"])
                elif ev.key in (pygame.K_f, pygame.K_F11):
                    pygame.display.toggle_fullscreen()
                elif ev.key == pygame.K_s:
                    take_screenshot = True

        elapsed = time.time() - t_start
        buf = cap.snapshot()

        y_collapse = x_collapse = 1.0
        shutdown_flash = 0.0
        power_mult = power_on_curve(elapsed)
        if shutdown_t is not None:
            sd = (time.time() - shutdown_t) / 0.5
            if sd >= 1.0:
                running = False
            y_collapse = max(0.0, min(1.0, 1.0 - sd / 0.30))
            x_collapse = (1.0 if sd < 0.30
                          else max(0.0, min(1.0, 1.0 - (sd - 0.30) / 0.45)))
            shutdown_flash = math.exp(-((sd - 0.72) ** 2) / 0.0025) * 2.5
            if sd > 0.75:
                power_mult *= max(0.0, 1.0 - (sd - 0.75) / 0.25)

        frame_dt = max(0.0, elapsed - prev_elapsed)
        prev_elapsed = elapsed

        _ritual_snap = ritual.update(frame_dt)

        _ritual_strips, _ritual_arm = ritual.build(
            _ritual_snap, buf, W, H, ISO_ASPECT)

        if y_collapse < 1.0 or x_collapse < 1.0:
            if _ritual_strips:
                for i, s in enumerate(_ritual_strips):
                    s = s.copy()
                    s[:, 0] *= x_collapse
                    s[:, 1] *= y_collapse
                    _ritual_strips[i] = s
            if _ritual_arm is not None and len(_ritual_arm):
                _ritual_arm = _ritual_arm.copy()
                _ritual_arm[:, 0] *= x_collapse
                _ritual_arm[:, 1] *= y_collapse

        nxt = 1
        glBindFramebuffer(GL_FRAMEBUFFER, hist_fbo[nxt][0])
        glViewport(0, 0, W, H)
        glDisable(GL_BLEND)
        glUseProgram(decay_prog)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, hist_fbo[0][1])
        glUniform1i(glGetUniformLocation(decay_prog, "hist"), 0)
        glUniform1f(glGetUniformLocation(decay_prog, "decay"), 0.0)
        draw_quad(quad_vao)

        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE)

        ribbon_capacity_local = ribbon_capacity
        if _ritual_strips:
            combined = np.concatenate(_ritual_strips, axis=0)
            if len(combined):
                glBindBuffer(GL_ARRAY_BUFFER, ribbon_vbo)
                if combined.nbytes > ribbon_capacity_local:
                    ribbon_capacity_local = int(combined.nbytes * 1.5)
                    glBufferData(GL_ARRAY_BUFFER, ribbon_capacity_local, None, GL_DYNAMIC_DRAW)
                glBufferSubData(GL_ARRAY_BUFFER, 0, combined.nbytes, combined)
                glUseProgram(ribbon_prog)
                glBindVertexArray(ribbon_vao)
                off = 0
                for _st in _ritual_strips:
                    if len(_st):
                        glDrawArrays(GL_TRIANGLE_STRIP, off, len(_st))
                    off += len(_st)
            if _ritual_arm is not None and len(_ritual_arm):
                glBindBuffer(GL_ARRAY_BUFFER, ribbon_vbo)
                if _ritual_arm.nbytes > ribbon_capacity_local:
                    ribbon_capacity_local = int(_ritual_arm.nbytes * 1.5)
                    glBufferData(GL_ARRAY_BUFFER, ribbon_capacity_local, None, GL_DYNAMIC_DRAW)
                glBufferSubData(GL_ARRAY_BUFFER, 0, _ritual_arm.nbytes, _ritual_arm)
                glUseProgram(ribbon_prog)
                glBindVertexArray(ribbon_vao)
                glDrawArrays(GL_TRIANGLES, 0, len(_ritual_arm))
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
                glUniform2f(glGetUniformLocation(blur_prog, "texel"),
                            1.0 / bloom_w, 1.0 / bloom_h)
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
        glUniform1f(glGetUniformLocation(comp_prog, "u_loud"),
                    min(1.5, (cap.level_l + cap.level_r) * 3.0))
        glUniform1f(glGetUniformLocation(comp_prog, "u_bass"), min(1.5, cap.bass))
        glUniform1f(glGetUniformLocation(comp_prog, "u_treble"), min(1.5, cap.treble))
        glUniform1f(glGetUniformLocation(comp_prog, "u_beat"), min(1.2, cap.beat_pulse))
        glUniform1f(glGetUniformLocation(comp_prog, "u_resolve"), 0.0)
        glUniform1f(glGetUniformLocation(comp_prog, "u_bloom"), state["bloom"])
        glUniform4f(glGetUniformLocation(comp_prog, "u_disc"),
                    RITUAL_CX * 0.5 + 0.5, RITUAL_CY * 0.5 + 0.5,
                    RITUAL_R * ISO_ASPECT[0] * 0.5, RITUAL_R * ISO_ASPECT[1] * 0.5)
        draw_quad(quad_vao)

        _ly = ritual.current_lyric(_ritual_snap or {})
        if _ly is not None and len(_ly) > 46:
            _ly = _ly[:45].rstrip() + "…"
        if _ly != last_lyric:
            lyric_osd.set_text(_ly, W, H)
            last_lyric = _ly

        if record_label is not None and ritual.album is not None:
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            record_label.load(ritual.album.cover)
            record_label.draw(label_prog, ritual.deck.rotation, ISO_ASPECT)

        np_artist, np_title = now_playing.snapshot()
        if ritual.album is not None:
            _al = ritual.album
            _ti = ritual._track_index(_ritual_snap or {})
            _side_i, _side = _al.side_for(
                _al.album_time(_ti, ritual.session.position()[0]))
            np_artist = _al.artist or np_artist
            if 0 <= _ti < len(_al.tracks):
                _t = _al.tracks[_ti]
                np_title = _t.get("title") or _t.get("name") or np_title
            if _side:
                np_artist = f"{np_artist} · {_side['label']}"
            if ritual.deck.phase == vinyl.BREAK:
                np_artist, np_title = "VIRE O DISCO", _side["label"] if _side else ""
            elif ritual.deck.phase == vinyl.STOP:
                np_artist, np_title = "FIM", f"{_al.artist} — {_al.name}"
            elif ritual.banner_text():
                np_artist, np_title = ritual.banner_text()
        if np_artist and np_title:
            osd_reserved = osd.w if osd.alpha() > 0 else 0
            char_w = mpris_osd.font.size("M")[0] or 1
            max_chars = max(6, int((W - 72 - osd_reserved - 30) / char_w))
            np_text = f"{np_artist} - {np_title}"[:max_chars]
        else:
            np_text = None
        if np_text != last_np_text:
            mpris_osd.set_text(np_text, W, H)
        if ritual.caption_is_state():
            mpris_osd.hold_open()
            last_np_text = np_text

        osd.set_text(
            f"RITUAL · ZOOM {state['zoom']:.2f}x", W, H)

        glUseProgram(text_prog)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        osd.draw(text_prog, (1.0, 1.0, 1.0))
        mpris_osd.draw(text_prog, (1.0, 1.0, 1.0))
        lyric_osd.draw(text_prog, (1.0, 1.0, 1.0))
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
                raw = glReadPixels(0, 0, W, H, GL_RGB, GL_UNSIGNED_BYTE)
                img = pygame.image.fromstring(raw, (W, H), "RGB", True)
                os.makedirs(screenshot_dir, exist_ok=True)
                fname = os.path.join(screenshot_dir,
                                     f"ritual-{time.strftime('%Y%m%d-%H%M%S')}.png")
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
            print(f"fps~{frames / (time.time() - t_fps):.1f}")
            frames = 0
            t_fps = time.time()

    save_state(state)
    now_playing.close()
    ritual.close()
    cap.close()
    pygame.quit()


if __name__ == "__main__":
    main()
