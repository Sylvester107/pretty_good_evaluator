"""
call_recorder/pipeline.py

Orchestrates the full per-call lifecycle:

    CallRecorder (mixed MP3)
        -> transcribe_call()   [Gemini: audio in, speaker-labeled transcript text out]
        -> analyze_call()      [Gemini: transcript text in, structured bug report out]

Each stage writes its output to disk immediately, so if a later stage fails you
still have the artifacts from earlier stages to inspect/retry.

Wiring:
- `init_pipeline()` is called once at FastAPI startup (see main.py's lifespan hook).
  It just validates config and ensures directories exist -- there's no global
  "recorder" singleton, since a CallRecorder is inherently scoped to one call.
- `run_pipeline_for_call(call_sid, audio_path)` is called once per call, right after
  `CallRecorder.finalize()` returns. It's fired as a background asyncio task from
  the WebSocket handler so the handler can close out the connection immediately
  without blocking on transcription/analysis.

REQUIRES: GEMINI_API_KEY environment variable set.
          pip install google-genai
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from google import genai
from google.genai import types

logger = logging.getLogger("call_pipeline")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "data", "transcripts")
ANALYSIS_DIR = os.path.join(BASE_DIR, "data", "bug_reports")

# Model choice: a current Gemini model with native audio understanding.
# Swap this string if you're targeting a different Gemini version.
TRANSCRIPTION_MODEL = "gemini-2.5-flash"
ANALYSIS_MODEL = "gemini-2.5-flash"

_client = None  # initialized in init_pipeline()


def init_pipeline():
    """
    Call once at server startup (FastAPI lifespan). Validates that everything
    the pipeline needs is in place BEFORE the server starts accepting calls,
    so misconfiguration fails fast and loud instead of silently dropping the
    transcription/analysis step after the first real call.
    """
    global _client

    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    os.makedirs(ANALYSIS_DIR, exist_ok=True)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. The pipeline needs "
            "this to call Gemini for transcription and bug analysis."
        )

    _client = genai.Client(api_key=api_key)
    logger.info("Pipeline initialized. Transcripts -> %s, Analysis -> %s", TRANSCRIPTS_DIR, ANALYSIS_DIR)


def _get_client() -> genai.Client:
    if _client is None:
        raise RuntimeError(
            "Pipeline not initialized. Call init_pipeline() at server startup before any calls come in."
        )
    return _client


# ---------------------------------------------------------------------------
# Stage 1: Transcription
# ---------------------------------------------------------------------------

TRANSCRIPTION_PROMPT = """\
This audio is a single mixed-channel recording of a phone call between a human \
caller and an AI voice agent. Both speakers' audio is combined into one track.

Produce a speaker-labeled transcript. Use "Caller:" for the human and "Agent:" \
for the AI voice agent. Start a new line for each speaker turn. Include a \
timestamp in [MM:SS] format at the start of each turn, estimated from the audio.

If a turn is inaudible or unclear, write "[inaudible]" rather than guessing.
Do not add commentary, summaries, or analysis -- transcript text only.
"""


async def transcribe_call(call_sid: str, audio_path: str) -> str:
    """
    Uploads the call audio file to Gemini and returns a speaker-labeled transcript.
    Writes the transcript to TRANSCRIPTS_DIR/{call_sid}.txt and returns that path.
    """
    client = _get_client()

    def _do_transcription() -> str:
        # File upload + generate_content are synchronous in google-genai;
        # run in a thread so we don't block the event loop.
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file does not exist: {audio_file}")

        with audio_file.open("rb") as file_obj:
            uploaded_file = client.files.upload(
                file=file_obj,
                config=types.UploadFileConfig(
                    mime_type="audio/wav",
                    display_name=audio_file.name,
                ),
            )

        # Gemini processes uploaded files asynchronously (state starts as
        # PROCESSING). Poll until ACTIVE before referencing it in generate_content,
        # otherwise the call can fail or be rejected on a file that isn't ready yet.
        while uploaded_file.state and uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state and uploaded_file.state.name == "FAILED":
            raise RuntimeError(f"Gemini file processing failed for {audio_path}")

        response = client.models.generate_content(
            model=TRANSCRIPTION_MODEL,
            contents=[uploaded_file, TRANSCRIPTION_PROMPT],
        )
        return response.text

    transcript_text = await asyncio.to_thread(_do_transcription)

    transcript_path = os.path.join(TRANSCRIPTS_DIR, f"{call_sid}.txt")
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript_text)

    logger.info("Transcript written for call %s -> %s", call_sid, transcript_path)
    return transcript_path


# ---------------------------------------------------------------------------
# Stage 2: Bug analysis
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT_TEMPLATE = """\
You are reviewing a transcript of a phone call between a human caller and an AI \
voice agent, to identify bugs or failures in the agent's behavior.

Look specifically for:
- The agent misunderstanding or misinterpreting what the caller said
- The agent repeating itself or getting stuck in a loop
- Long unexplained silences or the agent failing to respond
- The agent interrupting the caller or talking over them
- The agent giving an answer that doesn't match the caller's actual question
- The agent abruptly ending the conversation or the call dropping unexpectedly
- Any other behavior that would frustrate or confuse a real caller

For each issue found, cite the approximate timestamp and quote the relevant \
turn(s). If no issues are found in a category, do not mention that category.

Respond in this structure:
1. Summary (2-3 sentences on overall call quality)
2. Issues Found (numbered list, each with: timestamp, description, severity [low/medium/high])
3. Overall Verdict (one of: "No issues", "Minor issues", "Significant issues")

Transcript:
---
{transcript}
---
"""


async def analyze_call(call_sid: str, transcript_path: str) -> str:
    """
    Reads the transcript and asks Gemini to analyze it for bugs.
    Writes the analysis to ANALYSIS_DIR/{call_sid}.txt and returns that path.
    """
    client = _get_client()

    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript_text = f.read()

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(transcript=transcript_text)

    def _do_analysis() -> str:
        response = client.models.generate_content(
            model=ANALYSIS_MODEL,
            contents=[prompt],
        )
        return response.text

    analysis_text = await asyncio.to_thread(_do_analysis)

    analysis_path = os.path.join(ANALYSIS_DIR, f"{call_sid}.txt")
    with open(analysis_path, "w", encoding="utf-8") as f:
        f.write(analysis_text)

    logger.info("Bug analysis written for call %s -> %s", call_sid, analysis_path)
    return analysis_path


# ---------------------------------------------------------------------------
# Orchestration entry point
# ---------------------------------------------------------------------------

async def run_pipeline_for_call(call_sid: str, audio_path: str):
    """
    Runs transcription then bug analysis for a single finished call.
    Each stage is wrapped so a failure in one is logged clearly and doesn't
    silently swallow the call_sid -- you can always find it in the logs and
    re-run the missing stage manually using the files already on disk.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    logger.info("Pipeline started for call %s at %s", call_sid, started_at)

    try:
        transcript_path = await transcribe_call(call_sid, audio_path)
    except Exception:
        logger.exception("Transcription failed for call %s (recording preserved at %s)", call_sid, audio_path)
        return

    try:
        await analyze_call(call_sid, transcript_path)
    except Exception:
        logger.exception(
            "Bug analysis failed for call %s (transcript preserved at %s)", call_sid, transcript_path
        )
        return

    logger.info("Pipeline complete for call %s", call_sid)


def launch_pipeline_for_call(call_sid: str, audio_path: str):
    """
    Fire-and-forget entry point for the WebSocket handler to call right after
    CallRecorder.finalize(). Schedules the pipeline as a background asyncio
    task so the handler returns immediately instead of blocking on Gemini calls.
    """
    asyncio.create_task(run_pipeline_for_call(call_sid, audio_path))