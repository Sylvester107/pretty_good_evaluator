"""
This module is responsible for connecting to Gemini Live API and sending 
requests to it. It uses the requests library to send HTTP requests to the 
API endpoints and returns the responses. 
It also handles errors and exceptions that may occur during the requests. """

import asyncio
from google import genai
from google.genai import types

client = genai.Client(api_key="YOUR_API_KEY")

model = "gemini-3.1-flash-live-preview"
config = {"response_modalities": ["AUDIO"]}

#chunk(raw PCM audio bytes)
chunk = b"..."  # Replace with actual audio data

async def main():
    async with client.aio.live.connect(model=model, config=config) as session:
        print("Session started")
        # send audio data to the session, this audio data comes from the twilio call that is connected to 
        # the websocket server that is handling the audio data(from their support AI).
    await session.send_realtime_input(
    audio=types.Blob(
        data=chunk,
        mime_type="audio/pcm;rate=16000"
    )
)

if __name__ == "__main__":
    asyncio.run(main())