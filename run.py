"""Launch script for Repo Graveyard."""
import sys
import subprocess
import uvicorn
import httpx
from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL

if sys.platform == "win32":
    # Enable UTF-8 mode on Windows terminal if possible
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def print_banner():
    banner = r"""
     ____                         ____                                            _ 
    |  _ \ ___ _ __   ___        / ___|_ __ __ ___   _____ _   _  __ _ _ __ __| |
    | |_) / _ \ '_ \ / _ \ _____| |  _| '__/ _` \ \ / / _ \ | | |/ _` | '__/ _` |
    |  _ <  __/ |_) | (_) |_____| |_| | | | (_| |\ V /  __/ |_| | (_| | | | (_| |
    |_| \_\___| .__/ \___/       \____|_|  \__,_| \_/ \___|\__, |\__,_|_|  \__,_|
              |_|                                          |___/                 
    """
    print(banner)
    print("=" * 75)
    print(" [*] Repo Graveyard -- Hackathon: Ghost in the Machine")
    print(" [x] 100% Local -- Zero Telemetry -- Air-Gapped Capable")
    print(f" [!] Local LLM: Ollama with '{OLLAMA_MODEL}'")
    print("=" * 75)

def check_ollama():
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        if r.status_code == 200:
            models = [m.get("name", "") for m in r.json().get("models", [])]
            target = OLLAMA_MODEL.split(":")[0]
            has_target = any(target in m for m in models)
            if has_target:
                print(f" [+] Ollama is active and model '{OLLAMA_MODEL}' is ready in VRAM.")
            else:
                print(f" [!] Warning: Ollama is running, but '{OLLAMA_MODEL}' was not found.")
                print(f"     Run: 'ollama pull {OLLAMA_MODEL}' to download the model.")
        else:
            print(f" [!] Warning: Ollama returned status code {r.status_code}.")
    except Exception as e:
        print(f" [!] Notice: Ollama not detected at {OLLAMA_BASE_URL}.")
        print("     To enable AI ghost stories and séance plans, start Ollama:")
        print("     1. Install Ollama from https://ollama.com")
        print(f"     2. Run: ollama run {OLLAMA_MODEL}")
        print("     (Graveyard scanning, fact extraction, and Demo Mode work regardless!)")
    print("=" * 75)

if __name__ == "__main__":
    print_banner()
    check_ollama()
    print(" [*] Summoning graveyard interface on: http://127.0.0.1:8000")
    print(" [*] Press Ctrl+C to terminate.")
    print("=" * 75)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
