"""
call_recorder/integration_example.py

Shows where CallRecorder and the pipeline hook into your existing Twilio <-> Gemini
relay. This is NOT a full app -- merge the marked sections into your existing
FastAPI app and WebSocket handler that already proxies audio between Twilio and Gemini.
"""

import base64
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from recorder import CallRecorder
from pipeline import init_pipeline, launch_pipeline_for_call

logging.basicConfig(level=logging.INFO)


# --- STARTUP: this is the "called when the server starts" hook. ---
# init_pipeline() validates GEMINI_API_KEY and creates the transcripts/analysis
# directories BEFORE the server accepts any calls, so a misconfiguration (e.g.
# missing API key, missing ffmpeg) fails immediately on `python main.py`
# instead of silently failing after your first real phone call.
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pipeline()
    yield
    # (no teardown needed currently)


app = FastAPI(lifespan=lifespan)


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()

    recorder = None  # created once we know the call_sid, in the `start` event

    # --- your existing Gemini Live session setup goes here ---
    # gemini_session = await connect_to_gemini_live(...)

    try:
        async for raw_message in websocket.iter_text():
            msg = json.loads(raw_message)
            event = msg.get("event")

            if event == "start":
                call_sid = msg["start"]["callSid"]
                recorder = CallRecorder(call_sid=call_sid)
                recorder.start()

            elif event == "media":
                # --- INBOUND: caller audio from Twilio ---
                mulaw_bytes = base64.b64decode(msg["media"]["payload"])

                if recorder:
                    recorder.add_caller_audio(mulaw_bytes, twilio_timestamp_ms=msg["media"]["timestamp"])

                # --- your existing forward-to-Gemini code goes here ---
                # await gemini_session.send_audio(mulaw_bytes)

            elif event == "stop":
                if recorder:
                    mp3_path = recorder.finalize()
                    # Fire-and-forget: schedules transcription + bug analysis as a
                    # background task. Doesn't block closing out this connection.
                    launch_pipeline_for_call(recorder.call_sid, mp3_path)
                    logging.info("Call %s ended, recording saved to %s", recorder.call_sid, mp3_path)
                break

    except WebSocketDisconnect:
        if recorder:
            mp3_path = recorder.finalize()
            launch_pipeline_for_call(recorder.call_sid, mp3_path)
            logging.info("Call %s disconnected early, partial recording saved to %s", recorder.call_sid, mp3_path)


# --- Wherever you currently receive audio chunks BACK from Gemini and send
#     them to Twilio, mirror them into the recorder too. E.g. inside whatever
#     callback/loop handles Gemini's streamed response audio:
#
#     async def on_gemini_audio_chunk(mulaw_bytes: bytes):
#         if recorder:
#             recorder.add_agent_audio(mulaw_bytes)
#         await websocket.send_text(json.dumps({
#             "event": "media",
#             "streamSid": stream_sid,
#             "media": {"payload": base64.b64encode(mulaw_bytes).decode()}
#         }))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

