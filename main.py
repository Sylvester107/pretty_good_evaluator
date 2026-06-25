import os
import logging
import threading
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from app.recorder.pipeline import init_pipeline
from app.telephony.twilio_client import make_twilio_call
from app.telephony.twilio_handler import TwilioHandler

load_dotenv(override=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)
app = FastAPI()


gemini_api_key = os.environ.get("GEMINI_API_KEY")
if not gemini_api_key:
    raise RuntimeError("GEMINI_API_KEY environment variable is required")

gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-live-preview")
telephony_handler = TwilioHandler(gemini_api_key=gemini_api_key, model=gemini_model)

# expose call to start a call to a phone number using Twilio API
@app.post("/twilio/call")
async def twilio_call(request: Request):
    data = await request.json()
    to_number = data.get("to_number")
    from_number = data.get("from_number")
    if not to_number or not from_number:
        return {"error": "Missing 'to_number' or 'from_number' in request data"}
    call_sid = make_twilio_call(to_number, from_number)
    return {"status": "ok", "call_sid": call_sid}

@app.websocket("/twilio/media")
async def twilio_media(websocket: WebSocket):
    await websocket.accept()
    try:
        await telephony_handler.handle_media_stream(websocket)
    except WebSocketDisconnect:
        logger.info("Twilio media websocket disconnected")


@app.on_event("startup")
async def startup_event():
    """Optionally initiate an outgoing call on startup when AUTO_CALL is set.

    Set `AUTO_CALL=true`, `TWILIO_TO_NUMBER` and `TWILIO_FROM_NUMBER` to enable.
    If ENABLE_NGROK=true, start an ngrok tunnel and update TWILIO_MEDIA_WS_URL.
    The actual call is run in a background thread because `make_twilio_call` is blocking.
    """
    def parse_env_flag(name: str) -> bool:
        value = os.environ.get(name, "")
        value = value.split("#", 1)[0].strip().lower()
        return value in ("1", "true", "yes")

    enable_ngrok = parse_env_flag("ENABLE_NGROK")
    if enable_ngrok:
        from app.services.ws_server import start_ngrok_tunnel
        server_port = int(os.environ.get("SERVER_PORT", "80"))
        public_url = start_ngrok_tunnel(port=server_port)
        ws_base = public_url.replace("http://", "wss://").replace("https://", "wss://")
        media_ws_url = f"{ws_base}/twilio/media"
        os.environ["TWILIO_MEDIA_WS_URL"] = media_ws_url
        logger.info(f"Ngrok started for AUTO_CALL with Twilio Media URL: {media_ws_url}")
        print(f"Ngrok started for AUTO_CALL with Twilio Media URL: {media_ws_url}")

    init_pipeline()
    auto_call = parse_env_flag("AUTO_CALL")
    to_number = os.environ.get("TWILIO_TO_NUMBER")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    if auto_call:
        if not to_number or not from_number:
            logger.warning("AUTO_CALL set but TWILIO_TO_NUMBER/TWILIO_FROM_NUMBER not provided")
        else:
            def _call():
                try:
                    logger.info(f"Initiating AUTO_CALL to {to_number}")
                    make_twilio_call(to_number, from_number)
                except Exception as e:
                    logger.exception("AUTO_CALL failed", exc_info=e)

            threading.Thread(target=_call, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80)
