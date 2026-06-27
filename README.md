# pretty_good_evaluator

A full-stack voice AI evaluation prototype that connects Twilio phone calls to Gemini Live, records the conversation, transcribes the mixed audio, and generates structured bug reports for agent behavior analysis.

## What this project does

This repository demonstrates a complete pipeline for evaluating a voice assistant in a realistic phone-call setting:

- Accepts inbound or outbound Twilio media streams over WebSocket
- Connects the stream to Gemini Live for conversational AI responses
- Records the full mixed audio call locally and encodes it with ffmpeg
- Supports selecting a patient scenario from the command line (for example, billing issues, accent testing, or emergency cases)
- Transcribes the conversation into a speaker-labeled transcript
- Analyzes the transcript for issues such as misunderstanding, looping, poor timing, or abrupt failures
- Writes outputs into the data folder for later review and debugging

## Architecture at a glance

- app/main entrypoint: FastAPI app exposing the Twilio webhook and media websocket
- app/telephony: Twilio call initiation and media stream handling
- app/llm: Gemini Live client for real-time audio conversation
- app/agents: patient/customer persona prompts for realistic call simulation
- app/recorder: call recording and post-call pipeline orchestration
- app/services: websocket server and ngrok tunnel support

## Features

- Real-time Twilio media streaming support
- Gemini Live voice conversation integration
- Automatic call recording with mixed audio timing fixes
- Command-line scenario selection for patient personas
- Automatic call shutdown after roughly 3 minutes of conversation
- Transcript generation with speaker labels and timestamps
- Structured bug analysis from call transcripts
- Optional automatic outbound calls via Twilio on startup
- Optional ngrok tunnel support for public webhook exposure

## Prerequisites

- Python 3.10+
- A Gemini API key
- A Twilio account and phone number (if you want to place or receive live calls)
- FFmpeg binaries installed and available on your PATH for audio encoding
- Optional: ngrok account token for public tunneling

## Installation

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use .venv\Scripts\activate
pip install -r requirments.txt
```

Install FFmpeg so the recorder can encode audio files correctly:

Windows (Chocolatey):

```powershell
choco install ffmpeg
```

macOS (Homebrew):

```bash
brew install ffmpeg
```

macOS (MacPorts):

```bash
sudo port install ffmpeg
```

After installation, verify that the `ffmpeg` command is available:

```bash
ffmpeg -version
```

## Environment configuration

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Required variables:

```env
GEMINI_API_KEY=your_gemini_api_key
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=+15551234567
TWILIO_TO_NUMBER=+15557654321
TWILIO_MEDIA_WS_URL=ws://your-server/twilio/media
```

Optional variables:

```env
GEMINI_MODEL=gemini-3.1-flash-live-preview
AUTO_CALL=false
ENABLE_NGROK=false
NGROK_AUTH_TOKEN=your_ngrok_token
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

## Running the app locally

Start the server:

```bash
python scripts/start_server.py
python main.py
```

You can also choose a specific patient scenario from the command line:

```bash
python main.py billing_issue
# or
python main.py --scenario heavy_accent
```

Supported scenario names:

- billing_issue
- account_issue
- clinic_location
- checkin_process
- heavy_accent
- broken_english
- spanish_patient
- confused_patient
- multiple_questions
- memory_test
- poor_call_quality
- frustrated_patient
- medical_emergency

The Twilio connection will automatically end after roughly 3 minutes of conversation unless the stream is stopped earlier.

This launches the FastAPI app and exposes:

- WebSocket endpoint: /twilio/media
- Twilio call endpoint: /twilio/call

If ENABLE_NGROK=true, the app will also create a public ngrok tunnel and update the Twilio media WebSocket URL automatically.

## Making a Twilio call

You can trigger an outbound call through the API:

```bash
curl -X POST http://localhost:8000/twilio/call \
  -H "Content-Type: application/json" \
  -d '{"to_number":"+15551234567","from_number":"+15557654321"}'
```

The response includes a Twilio call SID.

## Generated outputs

After a completed call, the pipeline writes artifacts into:

- data/recordings/: recorded mixed-call WAV files
- data/transcripts/: speaker-labeled transcripts
- data/bug_reports/: structured bug analysis reports

## Project structure

```text
app/
  agents/        Patient persona scenarios
  core/          Shared configuration
  llm/           Gemini Live client
  recorder/      Audio recording and pipeline orchestration
  services/      WebSocket server and ngrok helpers
  telephony/     Twilio client and handlers
scripts/         Startup scripts
tests/          Example and integration tests
```

## Debugging and troubleshooting

- Ensure GEMINI_API_KEY is set before starting the app.
- If Twilio audio is not flowing correctly, verify the media WebSocket URL matches the public endpoint.
- If ngrok fails, confirm NGROK_AUTH_TOKEN is configured and the tunnel port is reachable.
- If ffmpeg is missing, install the binary and ensure `ffmpeg` is on your PATH.
- If the pipeline fails after recording, inspect the generated transcript or bug report files in the data folder.

## Notes

This project is intended as a practical reference implementation for voice AI evaluation. It is suitable for prototyping, lab testing, and debugging conversational agent behavior in a realistic telephony context.
