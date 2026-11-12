"""Assemble the final tutorial: clips + crossfades + voiceover + captions + ducked music -> MP4.
Usage: python edit.py <output.mp4>"""
import json
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).parent
FF = imageio_ffmpeg.get_ffmpeg_exe()
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "Analytivest_Tutorial.mp4"
XF = 0.3          # crossfade length between scenes (s)
VOICE_IN = 0.2    # voice starts this long after a scene begins
PAD = 0.6         # scene length = narration + PAD
END_HOLD = 1.6    # extra hold on the final card

timings = json.loads((HERE / "timings.json").read_text(encoding="utf-8"))
clips = json.loads((HERE / "clips.json").read_text())

# ---------------- timeline ----------------
scenes, t = [], 0.0
for k, tm in enumerate(timings):
    length = tm["duration"] + PAD + (END_HOLD if k == len(timings) - 1 else 0)
    scenes.append({"id": tm["id"], "start": t, "len": length, "lead": clips[tm["id"]]["lead"], "dur": tm["duration"],
                   "cues": tm["cues"]})
    t += length - XF
total = scenes[-1]["start"] + scenes[-1]["len"]
print(f"total video length {total:.1f}s ({total / 60:.2f} min)")
assert total <= 240, "video must not exceed 4 minutes"

# ---------------- captions (ASS) ----------------
def ts(x):
    h, x = divmod(x, 3600)
    m, s = divmod(x, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def chunks(text, limit=58):
    words, out, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > limit:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out


events, srt = [], []
for sc in scenes:
    base = sc["start"] + VOICE_IN
    for c in sc["cues"]:
        parts = chunks(c["text"])
        span = c["end"] - c["start"]
        total_chars = sum(len(p) for p in parts)
        t0 = c["start"]
        for p in parts:
            d = span * len(p) / total_chars
            events.append((base + t0, base + t0 + d, p))
            t0 += d
ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "",
       "[V4+ Styles]",
       "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
       "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
       "Style: Cap,Segoe UI Semibold,46,&H00FFFFFF,&H00FFFFFF,&H28101010,&H28101010,0,0,0,0,100,100,0,0,3,14,0,2,120,120,46,1",
       "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
for k, (a, b, p) in enumerate(events):
    ass.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{p}")
    srt.append(f"{k + 1}\n{ts(a).replace('.', ',')}0 --> {ts(b).replace('.', ',')}0\n{p}\n")
(HERE / "captions.ass").write_text("\n".join(ass), encoding="utf-8")
(OUT.with_suffix(".srt")).write_text("\n".join(srt), encoding="utf-8")

# ---------------- video ----------------
args = [FF, "-y", "-loglevel", "error", "-stats"]
for sc in scenes:
    args += ["-i", str(HERE / "clips" / f"{sc['id']}.webm")]
vf = []
for k, sc in enumerate(scenes):
    # trim lead-in, hold last frame if the clip is short, normalise
    vf.append(f"[{k}:v]trim=start={sc['lead']:.3f},setpts=PTS-STARTPTS,fps=30,scale=1920:1080:flags=lanczos,"
              f"tpad=stop_mode=clone:stop_duration=3,trim=duration={sc["len"]:.3f},setpts=PTS-STARTPTS,fps=30,settb=1/30,format=yuv420p[v{k}]")
prev, acc = "v0", scenes[0]["len"]
for k in range(1, len(scenes)):
    off = acc - XF
    vf.append(f"[{prev}][v{k}]xfade=transition=fade:duration={XF}:offset={off:.3f}[x{k}]")
    prev, acc = f"x{k}", off + scenes[k]["len"]
vf.append(f"[{prev}]ass=captions.ass,fade=t=in:st=0:d=0.4,fade=t=out:st={total - 0.8:.3f}:d=0.8[vout]")

# ---------------- audio ----------------
n = len(scenes)
for sc in scenes:
    args += ["-i", str(HERE / "voice" / f"{sc['id']}.wav")]
args += ["-i", str(HERE / "music.wav")]
af = []
for k, sc in enumerate(scenes):
    ms = int((sc["start"] + VOICE_IN) * 1000)
    af.append(f"[{n + k}:a]adelay={ms}|{ms},volume=1.0[a{k}]")
af.append("".join(f"[a{k}]" for k in range(n)) + f"amix=inputs={n}:normalize=0,apad=whole_dur={total:.3f}[voice]")
af.append("[voice]asplit=2[vmix][vkey]")
af.append(f"[{2 * n}:a]atrim=duration={total:.3f},volume=0.30,afade=t=out:st={total - 3:.3f}:d=3[mus]")
af.append("[mus][vkey]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=450:makeup=1[duck]")
af.append("[vmix][duck]amix=inputs=2:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000[aout]")

args += ["-filter_complex", ";".join(vf + af), "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", str(OUT)]
subprocess.run(args, check=True, cwd=HERE)
print("wrote", OUT)
