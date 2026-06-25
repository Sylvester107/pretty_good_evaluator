import os
import logging
import uvicorn
from pyngrok import ngrok
logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 80


def _configure_ngrok_auth_token(auth_token: str | None):
    if auth_token:
        ngrok.set_auth_token(auth_token)
        logger.info("Configured ngrok auth token")


def start_ngrok_tunnel(port: int = DEFAULT_PORT, auth_token: str | None = None) -> str:
    _configure_ngrok_auth_token(auth_token or os.environ.get("NGROK_AUTH_TOKEN"))
    tunnel = ngrok.connect(port, "http")
    public_url = tunnel.public_url
    logger.info("Started ngrok tunnel", extra={"public_url": public_url, "port": port})
    return public_url


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, enable_ngrok: bool = False) -> None:
    if enable_ngrok:
        public_url = start_ngrok_tunnel(port=port)
        websocket_scheme = "wss://"
        ws_base = public_url.replace("http://", websocket_scheme).replace("https://", websocket_scheme)
        media_ws_url = f"{ws_base}/twilio/media"
        print(f"ngrok public URL: {public_url}")
        print(f"Twilio Media WebSocket URL: {media_ws_url}")

    from main import app as fastapi_app
    uvicorn.run(fastapi_app, host=host, port=port)
