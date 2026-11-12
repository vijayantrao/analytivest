"""Start the Analytivest server (API + built frontend) on http://127.0.0.1:8000.

Usage:  .venv\\Scripts\\python run.py          (add --reload while developing)
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))

if __name__ == "__main__":
    import uvicorn

    from app import config

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload="--reload" in sys.argv,
                log_level="info")
