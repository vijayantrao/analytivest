# Tutorial video source

Rebuild `../Analytivest_Tutorial.mp4` (needs the app running at http://127.0.0.1:8000):

```powershell
py -m venv v; v\Scripts\pip install playwright edge-tts imageio-ffmpeg numpy scipy pillow; v\Scripts\python -m playwright install chromium
v\Scripts\python tts.py en-IN-PrabhatNeural   # voiceover (Microsoft neural en-IN voice via edge-tts) -> voice/, timings.json
v\Scripts\python record.py                    # screen-records each scene -> clips/, clips.json
v\Scripts\python music.py 240                 # original synthesised background music -> music.wav
v\Scripts\python edit.py Analytivest_Tutorial.mp4
```

Edit narration in `script.json`. Use a short folder path on Windows. `record.py` uploads the fictional sample RHP,
which creates one IPO record; delete it afterwards from the IPOs page.
