import asyncio
import base64
import json
import logging
import os
import audioop
import time
from app.llm.gemini_client import GeminiLive
from app.agents.patient_agent import get_patient_scenario
from app.recorder.recorder import CallRecorder
from app.recorder.pipeline import launch_pipeline_for_call

logger = logging.getLogger(__name__)

class TwilioHandler:
    def __init__(self, gemini_api_key, model, default_scenario: str | None = None):
        self.gemini_client = GeminiLive(
            api_key=gemini_api_key,
            model=model,
            input_sample_rate=16000
        )
        self.stream_sid = None
        self.default_scenario = default_scenario or os.environ.get("PATIENT_SCENARIO", "heavy_accent")
        logger.info(f"TwilioHandler initialized with model={model} and scenario={self.default_scenario}")

    async def handle_media_stream(self, websocket):
        """Processes the Twilio Media Stream."""
        audio_input_queue = asyncio.Queue()
        recorder = None

        # Buffer for accumulating output audio before sending to Twilio
        # Twilio works best with consistent 20ms frames (160 bytes of mulaw at 8kHz)
        MULAW_FRAME_SIZE = 160  # 20ms at 8kHz, 1 byte per sample (mulaw)
        output_buffer = bytearray()

        # Keep resampling state between chunks for cleaner audio
        resample_state_8_to_16 = None
        resample_state_24_to_16 = None
        resample_state_16_to_8 = None
        conversation_timeout_seconds = 180
        conversation_started_at = None
        last_activity_at = None
        
        # Initialize patient scenario (will be updated when stream starts)
        patient_scenario = get_patient_scenario(self.default_scenario)
        system_prompt = patient_scenario.system_prompt
        scenario_issue=patient_scenario.issue

        async def send_buffered_audio(websocket, stream_sid, flush: bool = False):
            """Send buffered audio in consistent 160-byte (20ms) mulaw frames."""
            nonlocal output_buffer
            while len(output_buffer) >= MULAW_FRAME_SIZE:
                frame = bytes(output_buffer[:MULAW_FRAME_SIZE])
                del output_buffer[:MULAW_FRAME_SIZE]
                payload = base64.b64encode(frame).decode("utf-8")
                message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload},
                }
                logger.debug(f"Sending Twilio media frame size={len(frame)} bytes")
                await websocket.send_text(json.dumps(message))

            if flush and output_buffer:
                # If the stream is ending, pad the remaining audio to a full frame
                frame = bytes(output_buffer)
                remaining = MULAW_FRAME_SIZE - len(frame)
                if remaining > 0:
                    frame += bytes([0xFF] * remaining)
                output_buffer.clear()
                payload = base64.b64encode(frame).decode("utf-8")
                message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload},
                }
                logger.debug(f"Flushing Twilio media frame size={len(frame)} bytes")
                await websocket.send_text(json.dumps(message))

        async def audio_output_callback(data):
            """Callback for Gemini audio output."""
            nonlocal output_buffer
            logger.info(f"[{time.time():.3f}] audio_output_callback chunk size={len(data)} bytes")
            if not self.stream_sid:
                # This used to fail silently, which made it impossible to tell
                # "Gemini never sent audio" apart from "Gemini sent audio before
                # the Twilio 'start' event set stream_sid". Now it's logged.
                logger.warning(
                    "Dropping Gemini audio chunk: stream_sid not set yet "
                    f"(chunk size={len(data)} bytes)"
                )
                return

            logger.debug(f"Gemini output chunk size={len(data)} bytes")
            # Gemini sends 24kHz 16-bit PCM. Twilio expects 8kHz mulaw.
            # Two-step resampling for better quality: 24kHz → 16kHz → 8kHz
            nonlocal resample_state_24_to_16, resample_state_16_to_8
            try:
                # Step 1: 24kHz → 16kHz (3:2 ratio)
                intermediate, resample_state_24_to_16 = audioop.ratecv(
                    data, 2, 1, 24000, 16000, resample_state_24_to_16
                )
                # Step 2: 16kHz → 8kHz (2:1 ratio)
                resampled_data, resample_state_16_to_8 = audioop.ratecv(
                    intermediate, 2, 1, 16000, 8000, resample_state_16_to_8
                )
                # Convert PCM to mulaw
                mulaw_data = audioop.lin2ulaw(resampled_data, 2)

                logger.debug(f"Converted Gemini output to {len(mulaw_data)} bytes of mulaw")
                if recorder:
                    recorder.add_agent_audio(mulaw_data)
                # Buffer and send in consistent frame sizes
                output_buffer.extend(mulaw_data)
                await send_buffered_audio(websocket, self.stream_sid)
            except Exception as e:
                logger.error(f"Error sending audio to Twilio: {e}", exc_info=True)

        async def audio_interrupt_callback():
            """Callback for Gemini audio interruption."""
            nonlocal output_buffer
            output_buffer.clear()  # Discard buffered audio
            logger.info(f"[{time.time():.3f}] Gemini audio interrupted; cleared output buffer")
            if recorder:
                recorder.interrupt_agent_audio()
            if self.stream_sid:
                # Clear Twilio's buffer
                await websocket.send_text(json.dumps({
                    "event": "clear",
                    "streamSid": self.stream_sid
                }))

        gemini_task = None

        async def start_gemini_session_if_needed():
            nonlocal gemini_task
            if gemini_task is None:
                logger.info("Starting Gemini session task for Twilio call...")
                gemini_task = asyncio.create_task(self._run_gemini_session(
                    audio_input_queue,
                    audio_output_callback,
                    audio_interrupt_callback,
                    system_prompt=system_prompt,
                    initial_text=patient_scenario.opening_statement,
                ))

        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)
                event = data.get("event")

                if event == "start":
                    self.stream_sid = data["start"]["streamSid"]
                    call_sid = data["start"].get("callSid", "unknown")
                    recorder = CallRecorder(call_sid=call_sid, scenario_issue=scenario_issue)
                    recorder.start()
                    conversation_started_at = time.time()
                    last_activity_at = conversation_started_at
                    logger.info(f"Twilio Stream started — streamSid={self.stream_sid}, callSid={call_sid}")
                    logger.info(f"Stream metadata: {json.dumps(data['start'], indent=2)}")
                    logger.info(f"Patient scenario active: {patient_scenario.scenario_type}")
                    await start_gemini_session_if_needed()
                elif event == "media":
                    now = time.time()
                    if conversation_started_at is not None and (now - conversation_started_at) >= conversation_timeout_seconds:
                        logger.info("Conversation reached %s seconds; ending Twilio stream", conversation_timeout_seconds)
                        await send_buffered_audio(websocket, self.stream_sid, flush=True)
                        break

                    payload = data["media"]["payload"]
                    mulaw_data = base64.b64decode(payload)
                    track = data["media"].get("track", "").lower()
                    if recorder and track and "outbound" in track:
                        logger.debug(f"Skipping Twilio outbound audio track {track} in recorder")
                    elif recorder:
                        recorder.add_caller_audio(mulaw_data, int(data["media"]["timestamp"]))

                    # Convert mulaw to PCM (8kHz)
                    pcm_data = audioop.ulaw2lin(mulaw_data, 2)
                    # Two-step resampling: 8kHz → 16kHz (clean 1:2 ratio)
                    resampled_data, resample_state_8_to_16 = audioop.ratecv(
                        pcm_data, 2, 1, 8000, 16000, resample_state_8_to_16
                    )
                    last_activity_at = now
                    await audio_input_queue.put(resampled_data)
                elif event == "stop":
                    logger.info(f"Twilio Stream stopped: {self.stream_sid}")
                    await send_buffered_audio(websocket, self.stream_sid, flush=True)
                    break
        except Exception as e:
            logger.error(f"Error in Twilio media stream: {e}", exc_info=True)
        finally:
            # gemini_task can still be None here if the websocket never got a
            # 'start' event before disconnecting/erroring out.
            if gemini_task is not None:
                if gemini_task.done() and not gemini_task.cancelled():
                    exc = gemini_task.exception()
                    if exc:
                        logger.error(f"Gemini task failed with exception: {exc}", exc_info=exc)
                gemini_task.cancel()
            if recorder:
                try:
                    audio_path = recorder.finalize()
                    launch_pipeline_for_call(recorder.call_sid, audio_path)
                    logger.info("Call %s recording saved to %s", recorder.call_sid, audio_path)
                except Exception:
                    logger.exception("Failed to finalize or launch pipeline for call %s", recorder.call_sid)
            logger.info("Twilio handler finished — cleaning up")

    async def _run_gemini_session(self, audio_input_queue, output_callback, interrupt_callback, system_prompt=None, initial_text=None):
        try:
            logger.info("Gemini session connecting...")
            # Prepare session config with system prompt and optional seed text
            session_config = {
                "audio_input_queue": audio_input_queue,
                "audio_output_callback": output_callback,
                "audio_interrupt_callback": interrupt_callback,
            }
            if system_prompt:
                session_config["system_prompt"] = system_prompt
                logger.info(f"Using system prompt: {system_prompt[:100]}...")
            if initial_text:
                session_config["initial_text"] = initial_text
                logger.info(f"Sending initial hidden prompt to Gemini: {initial_text[:100]}...")
            
            async for event in self.gemini_client.start_session(**session_config):
                if event:
                    event_type = event.get("type", "unknown") if isinstance(event, dict) else type(event).__name__
                    logger.info(f"Gemini event: {event_type}")
                    if isinstance(event, dict) and event.get("type") == "error":
                        logger.error(f"Gemini returned error event: {event}")
            logger.info("Gemini session ended normally")
        except asyncio.CancelledError:
            logger.info("Gemini session cancelled (expected on call end)")
        except Exception as e:
            logger.error(f"Error in Gemini session (Twilio): {e}", exc_info=True)