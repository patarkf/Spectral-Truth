"""App config: paths, allowed formats, server port."""
import os

# Where to store SQLite DB (default: project data dir)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "audio_analyzer.db")

# Allowed extensions (WAV, FLAC, AIFF)
ALLOWED_EXTENSIONS = {".wav", ".flac", ".aiff", ".aif"}

# Server
HOST = "127.0.0.1"
PORT = 8765

# Lexicon Local API (enable in Lexicon: Settings → Integrations)
LEXICON_API_BASE_URL = os.environ.get("LEXICON_API_BASE_URL", "http://localhost:48624")
