import os
import sys
from dotenv import load_dotenv


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    load_dotenv()
    from app.services.ws_server import run_server

    enable_ngrok = os.getenv("ENABLE_NGROK", "false").lower() in ("1", "true", "yes")
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    print(f"Starting FastAPI server on {host}:{port} (ngrok enabled={enable_ngrok})")
    run_server(host=host, port=port, enable_ngrok=enable_ngrok)


if __name__ == "__main__":
    main()
