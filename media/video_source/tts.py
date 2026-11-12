"""Generate the Indian-English voiceover per scene with edge-tts (Microsoft neural voice en-IN-PrabhatNeural).
Writes voice/<id>.mp3, voice/<id>.wav and timings.json (duration + sentence cues for captions)."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts
import imageio_ffmpeg

HERE = Path(__file__).parent
FF = imageio_ffmpeg.get_ffmpeg_exe()
VOICE = sys.argv[1] if len(sys.argv) > 1 else "en-IN-PrabhatNeural"
RATE = "+16%"  # slightly fast-paced


def duration(path: Path) -> float:
    out = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    t = out.split("Duration: ")[1].split(",")[0]
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


async def one(scene: dict, outdir: Path) -> dict:
    comm = edge_tts.Communicate(scene["text"], VOICE, rate=RATE, boundary="SentenceBoundary")
    mp3 = outdir / f"{scene['id']}.mp3"
    cues = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
                cues.append({"start": chunk["offset"] / 1e7, "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                             "text": chunk["text"]})
    wav = outdir / f"{scene['id']}.wav"
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "48000", "-ac", "2", str(wav)], check=True)
    return {"id": scene["id"], "duration": duration(wav), "cues": cues}


async def main():
    scenes = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    outdir = HERE / "voice"
    outdir.mkdir(exist_ok=True)
    res = []
    for s in scenes:
        r = await one(s, outdir)
        print(f"{r['id']}: {r['duration']:.1f}s, {len(r['cues'])} cues")
        res.append(r)
    total = sum(r["duration"] for r in res)
    print(f"TOTAL narration {total:.1f}s ({total / 60:.2f} min)")
    (HERE / "timings.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


asyncio.run(main())
