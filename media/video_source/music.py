"""Compose an original, royalty-free background track (synthesised from scratch, so no copyright issues).

Upbeat 'corporate tech' feel: 112 BPM, Am–F–C–G progression, four-on-the-floor kick, claps, off-beat hats,
pulsing sidechained bass and pads, and a plucked arpeggio. Sections change every 16 bars; ends with a fade.
Usage: python music.py <seconds>   ->  music.wav (48 kHz stereo)
"""
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
BPM = 112
BEAT = 60 / BPM
BAR = 4 * BEAT
rng = np.random.default_rng(7)

LEN = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
N = int(LEN * SR) + SR
L = np.zeros(N)
R = np.zeros(N)
drums = np.zeros(N)
pad_bus = np.zeros((2, N))
side = np.ones(N)  # sidechain gain envelope driven by the kick


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def lp(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi):
    return sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def add(buf, start, sig):
    # 1 ms fade-in and 6 ms fade-out on every event so notes never start or stop with a click
    sig = sig.copy()
    a, z = min(len(sig), int(0.001 * SR)), min(len(sig), int(0.006 * SR))
    sig[:a] *= np.linspace(0, 1, a)
    sig[len(sig) - z:] *= np.linspace(1, 0, z)
    i = int(start * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i]


def env(n, a=0.005, d=0.2, s=0.0, r=0.05, hold=None):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4))
    if hold is None:
        e *= np.exp(-np.maximum(0, t - a) / d) * (1 - s) + s
    else:
        e *= np.where(t < hold, 1.0, np.exp(-(t - hold) / r))
    return e


def saw(f, n, detune=0.0):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for dt in (-detune, 0, detune):
        ph = (t * f * (1 + dt) + rng.random()) % 1.0
        out += 2 * ph - 1
    return out / 3


# ---- instruments ----
def kick(t0):
    n = int(0.42 * SR)
    t = np.arange(n) / SR
    f = 46 + 95 * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    sig = np.sin(ph) * np.exp(-t / 0.16) * np.minimum(1, t / 0.0015) + lp(0.06 * np.exp(-t / 0.003) * rng.standard_normal(n), 4000)
    add(drums, t0, 0.95 * sig)
    # duck pads/bass for ~200 ms after each kick
    i = int(t0 * SR)
    m = int(0.24 * SR)
    k = np.arange(m)
    seg = 1 - 0.55 * (1 - np.exp(-k / (0.005 * SR))) * np.exp(-k / (0.07 * SR))  # 5 ms attack: no clicks
    j = min(N, i + m)
    side[i:j] = np.minimum(side[i:j], seg[: j - i])


def clap(t0):
    n = int(0.25 * SR)
    noise = rng.standard_normal(n)
    e = np.zeros(n)
    for k, off in enumerate((0, 0.011, 0.022)):
        i = int(off * SR)
        e[i:] += np.exp(-np.arange(n - i) / (0.012 * SR if k < 2 else 0.07 * SR))
    add(drums, t0, 0.32 * bp(noise * e, 900, 5200))


def hat(t0, open_=False):
    n = int((0.16 if open_ else 0.045) * SR)
    sig = hp(rng.standard_normal(n), 7000) * np.exp(-np.arange(n) / ((0.05 if open_ else 0.012) * SR))
    add(drums, t0, 0.13 * sig)


def bass(t0, note, dur):
    n = int(dur * SR)
    f = midi(note)
    t = np.arange(n) / SR
    sig = 0.6 * np.sin(2 * np.pi * f * t) + 0.35 * lp(saw(f, n), 420)
    sig *= env(n, a=0.004, hold=dur * 0.75, r=0.03)
    add(L, t0, 0.42 * sig)
    add(R, t0, 0.42 * sig)


def pad(t0, notes, dur, level=0.09):
    n = int(dur * SR)
    sig = np.zeros(n)
    for nt in notes:
        sig += saw(midi(nt), n, detune=0.004)
    sig = lp(sig, 1500)
    t = np.arange(n) / SR
    e = np.minimum(1, t / 0.35) * np.minimum(1, (dur - t) / 0.3)
    pad_bus[0, int(t0 * SR):int(t0 * SR) + n] += (level * sig * e)[: max(0, N - int(t0 * SR))]
    pad_bus[1, int(t0 * SR):int(t0 * SR) + n] += (level * 0.95 * sig * e)[: max(0, N - int(t0 * SR))]


def pluck(t0, note, pan):
    n = int(0.42 * SR)
    f = midi(note)
    t = np.arange(n) / SR
    tri = 2 * np.abs(2 * ((t * f) % 1) - 1) - 1
    sig = lp(tri + 0.3 * np.sin(2 * np.pi * 2 * f * t), 3200) * np.exp(-t / 0.11)
    add(L, t0, 0.075 * sig * (1 - pan))
    add(R, t0, 0.075 * sig * (1 + pan))
    # echo (dotted eighth) for width
    add(L, t0 + BEAT * 0.75, 0.03 * sig * (1 + pan))
    add(R, t0 + BEAT * 0.75, 0.03 * sig * (1 - pan))


# Am – F – C – G   (root for bass, chord tones for pad/arp)
PROG = [(57, [57, 60, 64, 69]), (53, [53, 57, 60, 65]), (48, [55, 60, 64, 67]), (55, [55, 59, 62, 67])]
ARP = [0, 1, 2, 3, 2, 1, 2, 3]

bars = int(LEN / BAR) + 1
for b in range(bars):
    t = b * BAR
    root, chord = PROG[b % 4]
    section = (b // 16) % 4  # 0: light, 1: full, 2: full + open hats, 3: breakdown-ish
    last = b >= bars - 3
    pad(t, [x + 12 for x in chord[:3]] + [chord[0]], BAR, level=0.07 if section == 3 else 0.085)
    drums_on = b >= 2 and not last
    for k in range(4):
        bt = t + k * BEAT
        if drums_on and not (section == 3 and k % 2 == 1):
            kick(bt)
        if drums_on and k in (1, 3) and section != 3:
            clap(bt)
        if drums_on:
            hat(bt + BEAT / 2, open_=(section == 2 and k == 3))
    if b >= 1 and not last:
        for e in range(8):  # pulsing eighth-note bass
            bass(t + e * BEAT / 2, root - 12 if e % 4 else root - 12, BEAT / 2 * 0.9)
    if section != 0 or b % 2 == 1:
        for s in range(8 if section == 3 else 16 if section else 8):
            step = BEAT / 4 if section else BEAT / 2
            note = chord[ARP[s % 8]] + 12 + (12 if (section == 2 and s % 8 == 7) else 0)
            pluck(t + s * step, note, pan=0.35 * np.sin(s))

# reverb on pads + plucks
ir_n = int(1.6 * SR)
ir = rng.standard_normal(ir_n) * np.exp(-np.arange(ir_n) / (0.45 * SR))
ir /= np.sqrt(np.sum(ir ** 2))
wetL = fftconvolve(pad_bus[0] + L * 0.3, ir)[:N] * 0.35
wetR = fftconvolve(pad_bus[1] + R * 0.3, ir[::-1].copy())[:N] * 0.35

mixL = (L + pad_bus[0]) * side + wetL * side + drums
mixR = (R + pad_bus[1]) * side + wetR * side + drums
mix = np.stack([mixL, mixR], axis=1)[: int(LEN * SR)]
# fade in/out, soft clip, normalise to -1 dBFS
n = len(mix)
fade = np.ones(n)
fi, fo = int(1.5 * SR), int(5.0 * SR)
fade[:fi] = np.linspace(0, 1, fi)
fade[-fo:] = np.linspace(1, 0, fo)
mix *= fade[:, None]
mix = np.tanh(mix * 1.2)
mix /= np.max(np.abs(mix)) / 0.89
wavfile.write("music.wav", SR, (mix * 32767).astype(np.int16))
print(f"music.wav: {n / SR:.1f}s, {bars} bars at {BPM} BPM")
