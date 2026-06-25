# WebSocket Server with ngrok Setup

## Overview

The WebSocket server setup provides:
- **FastAPI-based WebSocket server** for Twilio media streaming (`/twilio/media`)
- **ngrok integration** for exposing local server with a public URL
- **Configurable startup script** for easy server management

## Quick Start

### 1. Set Environment Variables

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Required variables:
```env
GEMINI_API_KEY=your_key_here
TWILIO_ACCOUNT_SID=your_sid_here
TWILIO_AUTH_TOKEN=your_token_here
TWILIO_FROM_NUMBER=+1234567890
TWILIO_TO_NUMBER=+0987654321
TWILIO_MEDIA_WS_URL=ws://your_server_url/twilio/media
```

Optional variables for ngrok:
```env
ENABLE_NGROK=true          # Enable automatic ngrok tunnel
SERVER_HOST=0.0.0.0        # Server bind address (default: 0.0.0.0)
SERVER_PORT=8000           # Server port (default: 8000)
NGROK_AUTH_TOKEN=your_token_here  # ngrok auth token for stable URLs
```

### 2. Run the Server

#### Without ngrok (local development):
```bash
python scripts/start_server.py
```
Server runs on `http://localhost:8000`

#### With ngrok (expose publicly):
Set `ENABLE_NGROK=true` in `.env`, then:
```bash
python scripts/start_server.py
```
Output shows:
```
ngrok public URL: https://abc123xyz.ngrok.io
WebSocket endpoint: https://abc123xyz.ngrok.io/twilio/media
```

Use the WebSocket endpoint to configure Twilio media stream webhook.

### 3. Update Twilio Configuration

Set `TWILIO_MEDIA_WS_URL` to the ngrok WebSocket endpoint, then update your Twilio call configuration to use that URL.

## API Endpoints

### POST `/twilio/call`
Initiate an outbound call to a phone number.

**Request:**
```json
{
  "to_number": "+1234567890",
  "from_number": "+0987654321"
}
```

**Response:**
```json
{
  "status": "ok",
  "call_sid": "CA1234567890abcdef"
}
```

### WebSocket `/twilio/media`
Bidirectional media stream with Twilio. Automatically connects to Gemini Live for AI conversation.

## Service Modules

### `app.services.ws_server`

Core module providing:
- `run_server(host, port, enable_ngrok)` — Start FastAPI server with optional ngrok tunnel
- `start_ngrok_tunnel(port, auth_token)` — Manually start ngrok tunnel and return public URL

**Usage:**
```python
from app.services.ws_server import run_server, start_ngrok_tunnel

# Start server with ngrok
run_server(host="0.0.0.0", port=8000, enable_ngrok=True)

# Or manually create tunnel
public_url = start_ngrok_tunnel(port=8000)
print(f"Exposed at: {public_url}")
```

## Dependencies

The following packages are required:
- `fastapi` — Web framework
- `uvicorn` — ASGI server
- `pyngrok` — ngrok Python integration
- `python-dotenv` — Environment variable management
- `twilio` — Twilio SDK
- `google-genai` — Gemini LLM integration

Install all:
```bash
pip install -r requirments.txt
```

## Troubleshooting

### ngrok tunnel fails to connect
- Verify `NGROK_AUTH_TOKEN` is set (required for reliable tunnels)
- Check ngrok account limits: https://dashboard.ngrok.com

### WebSocket connection fails
- Verify `TWILIO_MEDIA_WS_URL` matches the actual ngrok URL
- Check firewall and port forwarding settings
- Ensure server is running: `python scripts/start_server.py`

### Twilio media stream error
- Ensure `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` are valid
- Check `TWILIO_FROM_NUMBER` is a valid Twilio-managed number
- Verify phone number formats include country code (+1 for US)
