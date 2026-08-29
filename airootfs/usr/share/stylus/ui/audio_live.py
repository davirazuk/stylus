#!/usr/bin/env python3
"""O som que toca agora, em três números para a tela.

POR QUE ISTO EXISTE
-------------------
A AGORA e o deck respiram com a música — e para respirar com a música é
preciso saber o SOM, não o botão de volume. A primeira versão do brilho leu
o `wpctl get-volume`: aquilo é o GANHO do sink, não a música. Subir 1% no
volume iluminava a capa mais do que uma bateria entrando, e cada leitura
pagava um processo novo de cinco em cinco quadros. O que o scope do deck já
fazia desde sempre (ler o monitor do PipeWire pelo PortAudio) era o dado
certo; faltava uma versão pequena sem GL para a interface de tela cheia.

O que esta thread mantém pronto:
    level     o nível suavizado, 0..1 — para o brilho e o giro
    spectrum  N_BANDS faixas logarítmicas — para a coluna ao lado da capa
    wave      os últimos ~1000 samples monofônicos — para o sulco vivo

Tudo é calculado no fundo; o desenho só lê. Numa máquina sem PortAudio ou
sem monitor ativo não há o que ler: o módulo vira um monte de zeros e a
tela fica parada, que é melhor do que quebrar.
"""
import math
import os
import subprocess
import threading
import time

try:
    import numpy as np
    import pyaudio
except Exception:                       # noqa: BLE001 — sem PortAudio/numpy
    np = pyaudio = None

RATE = 48000
BLOCK = 512
WAVE_N = 1024          # samples de onda guardados (~21 ms)
SPEC_FFT_N = 1024      # tamanho da FFT do espectro
N_BANDS = 24           # faixas logarítmicas desenhadas
SPEC_MIN_HZ = 60.0
SPEC_MAX_HZ = 16000.0
# Suavização do nível: sobe quase na hora (vem da bateria), desce devagar
# (o olho carrega o brilho). Nada de respondência rápida nas duas pontas —
# piscaria.
ATK, REL = 0.45, 0.10


def _zeros(n):
    """`n` zeros — matriz se houver numpy, lista se não houver.

    Sem numpy ninguém vai desenhar com eles (o monitor nasce morto), mas os
    campos têm que EXISTIR: quem pergunta o tamanho da onda não pode receber
    None.
    """
    return np.zeros(n, dtype=np.float32) if np is not None else [0.0] * n


def find_monitor_source():
    """O monitor que está com som agora, ou o primeiro que houver.

    O mesmo critério do deck (scope.py): um sink com o monitor RUNNING é o
    que alguém está ouvindo. SOURCE_RUNNING no pactl é o campo 3.
    """
    forced = os.environ.get("STYLUS_DECK_SOURCE")
    if forced:
        return forced
    try:
        out = subprocess.run(["pactl", "list", "sources", "short"],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception:                   # noqa: BLE001
        return None
    for linha in out.splitlines():
        col = linha.split()
        # pactl list sources short: INDEX NAME DRIVER SAMPLE_SPEC STATE
        if len(col) >= 5 and ".monitor" in col[1]:
            if col[4] == "RUNNING":
                return col[1]
    for linha in out.splitlines():
        col = linha.split()
        if len(col) >= 2 and ".monitor" in col[1]:
            return col[1]
    return None


class AudioMonitor:
    """Lê o monitor numa thread de fundo; expõe level, spectrum, wave."""

    def __init__(self):
        self.ok = False
        self.level = 0.0
        # A ORDEM aqui é o conserto: o guarda do numpy vem ANTES de qualquer
        # `np.`. Estas duas linhas eram `np.zeros(...)` DUAS linhas acima do
        # `if np is None`, e numa máquina sem python-pyaudio (que derruba o
        # import inteiro deste módulo para `np = pyaudio = None`) o que o
        # docstring promete — "vira um monte de zeros e a tela fica parada" —
        # virava `AttributeError: 'NoneType' object has no attribute 'zeros'`
        # subindo pelo `get_monitor()` até o `audio_level()`, que é chamado
        # em TODO quadro da AGORA. Ou seja: faltar um pacote de áudio não
        # apagava o brilho, apagava a interface.
        self.wave = _zeros(WAVE_N)
        self.spectrum = _zeros(N_BANDS)
        self._last_block = 0.0
        self._lock = threading.Lock()
        if np is None or pyaudio is None:
            return
        src = find_monitor_source()
        if not src:
            return
        try:
            os.environ["PULSE_SOURCE"] = src
            self._p = pyaudio.PyAudio()
            dev = self._find_pulse_device()
            self._stream = self._p.open(
                format=pyaudio.paInt16, channels=2, rate=RATE, input=True,
                input_device_index=dev, frames_per_buffer=BLOCK)
        except Exception:               # noqa: BLE001 — dispositivo ocupado
            return
        # Janela de FFT e as máscaras das faixas, pré-calculadas uma vez.
        self._hann = np.hanning(SPEC_FFT_N).astype(np.float32)
        freqs = np.fft.rfftfreq(SPEC_FFT_N, 1.0 / RATE)
        edges = np.logspace(math.log10(SPEC_MIN_HZ),
                            math.log10(SPEC_MAX_HZ), N_BANDS + 1)
        self._masks = [(freqs >= edges[i]) & (freqs < edges[i + 1])
                       for i in range(N_BANDS)]
        for i, m in enumerate(self._masks):
            if not m.any():
                idx = int(np.argmin(np.abs(freqs - edges[i])))
                m[idx] = True
        self._spec_buf = np.zeros(SPEC_FFT_N, dtype=np.float32)
        self._stop = False
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()
        self.ok = True

    def close(self):
        """Parada suave — e só isto, de propósito.

        Nada de `stream.close()`/`p.terminate()`: no teardown do PortAudio a
        ponte de PulseAudio aborta com core dump numa corrida de contexto
        (pa_context_get_state, ref ≤ 0) — e este módulo só fecha na saída do
        processo, onde o sistema operacional recolhe tudo de qualquer jeito.
        Parar a thread basta para não deixar leitura ativa."""
        self._stop = True
        try:
            self._th.join(timeout=1.0)
        except Exception:               # noqa: BLE001 — alvo morto não causa
            pass

    def _find_pulse_device(self):
        """O dispositivo 'pulse' do PortAudio, se existir.

        Mesmo critério do deck (scope.py): sem o PULSE_SOURCE que apontamos
        ali em cima, abrir o dispositivo padrão pega um hardware que pode não
        dar dois canais — o 'pulse' sabem routing e respeitam o source.
        """
        for i in range(self._p.get_device_count()):
            info = self._p.get_device_info_by_index(i)
            if info["name"] == "pulse" and info["maxInputChannels"] > 0:
                return i
        return None  # cai no dispositivo padrão, melhor que nenhum

    def _run(self):
        try:
            while not self._stop:
                dados = self._stream.read(BLOCK, exception_on_overflow=False)
                a = np.frombuffer(dados, dtype=np.int16).astype(np.float32)
                a = a.reshape(-1, 2).mean(axis=1) / 32768.0
                self._process(a)
                self._last_block = time.time()
        except Exception:               # noqa: BLE001 — fio morto não derruba
            pass

    def _process(self, a):
        # Nível: RMS do bloco, suavizado com ataque rápido, queda lenta.
        rms = float(np.sqrt(np.mean(np.square(a)))) * 3.0
        rms = min(1.0, rms)
        if rms >= self.level:
            self.level += ATK * (rms - self.level)
        else:
            self.level += REL * (rms - self.level)

        # Onda: o sulco desenha o que aconteceu nos últimos ~21 ms — não
        # mais: mais comprido vira borrão na largura da tela.
        with self._lock:
            self.wave = np.roll(self.wave, -len(a))
            self.wave[-len(a):] = a

        # Espectro: FFT pequena num buffer rolante, faixas logarítmicas,
        # alisadas para subir com o som e descer devagar.
        with self._lock:
            self._spec_buf = np.roll(self._spec_buf, -len(a))
            self._spec_buf[-len(a):] = a
        env = np.abs(np.fft.rfft(self._spec_buf * self._hann))
        bands = np.array([float(env[m].mean()) for m in self._masks])
        bands = np.clip(np.log1p(bands * 40.0) / 4.0, 0.0, 1.0)
        with self._lock:
            self.spectrum += ATK * (bands - self.spectrum)
            self.spectrum = np.clip(self.spectrum, 0.0, 1.0)

    def snapshot(self):
        """(level, wave, spectrum) prontos para desenhar.

        `wave` e `spectrum` são cópias: o fio está reescrevendo os próprios
        buffers em velocidade de áudio, e ler sem copiar daria um meio-quadro
        com uma faixa pela metade.
        """
        with self._lock:
            wave = self.wave.copy()
            spec = self.spectrum.copy()
        stale = time.time() - self._last_block
        level = self.level
        if stale > 0.6:
            # Sem música (pausado, sink suspenso), nível E onda escorrem para
            # o zero — uma sessão congelada não pode deixar o brilho aceso nem
            # o sulco desenhando o último instante para sempre. A onda
            # ressurge inteira na primeira leitura depois do som voltar.
            decai = max(0.0, 1.0 - (stale - 0.6) * 2.2)
            level *= decai
            wave *= decai
        return level, wave, spec


_monitor = None
_monitor_failed = False


def get_monitor():
    """A instância única. Fracassos não são repetidos a cada quadro."""
    global _monitor, _monitor_failed
    if _monitor is None and not _monitor_failed:
        try:
            _monitor = AudioMonitor()
        except Exception:               # noqa: BLE001
            # Quem chama isto desenha um quadro. Nenhuma surpresa de máquina
            # (biblioteca faltando, PortAudio estranho, dispositivo sumido)
            # pode virar tela preta: sem monitor, a tela só não respira.
            _monitor, _monitor_failed = None, True
            return None
        if not _monitor.ok:
            _monitor = None
            _monitor_failed = True
    return _monitor


def close_monitor():
    global _monitor
    if _monitor is not None:
        try:
            _monitor.close()
        except Exception:               # noqa: BLE001
            pass
        _monitor = None