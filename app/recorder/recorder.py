"""
call_recorder/recorder.py

Records a Twilio <Connect><Stream> call as a single interleaved/mixed WAV file.

Design (v3 — fixes long pauses, echo/garbling, caller-side static, AND the
agent cursor going stale across both barge-in interrupts and normal turn ends):
- The original version placed every chunk at `time.monotonic() - start_time`,
  i.e. whenever your server happened to get around to processing it. Any
  processing delay (async scheduling, Gemini API latency, event-loop jitter)
  got baked into the recording as extra silence -> long pauses that didn't
  really happen on the call. Under load, two chunks could also race to compute
  their position and land at overlapping/out-of-order offsets -> echo/garbling
  and crackly static.
- Fix (v2): stop using wall-clock arrival time for POSITIONING audio.
    * Caller audio: Twilio sends an authoritative `timestamp` field (ms since
      stream start) on every `media` event. We use THAT as the write position,
      not whenever our code happens to run. This is immune to server-side delay.
    * Agent audio: this is audio *we* generate/stream, so there's no Twilio
      timestamp for it. Position is tracked as cumulative playback time: each
      chunk is placed immediately after the previous agent chunk ends, based
      on the chunk's own decoded duration. Bursty delivery from Gemini can't
      cause overlapping writes, because position comes from audio content,
      not from when the network/event loop delivered it.
- Fix (v3): the agent cursor still needs to "catch up" to the caller's timeline
  at the START of every new agent turn -- not just after a barge-in interrupt.
  v2 only resynced the cursor when an explicit interrupt callback fired, which
  missed the much more common case: Gemini finishes a turn normally
  (turn_complete, no interrupt), there's a multi-second gap while the caller
  talks and Gemini is silent, and then Gemini's NEXT turn starts. With no
  interrupt to trigger a resync, the cursor just resumed from where the
  previous (fully-played) turn ended -- ignoring however much real time had
  passed while only the caller was talking. That produced agent audio that
  sounded continuous/never-stopping in the recording, overlapping the
  caller's speech, because there was no per-turn boundary to anchor against.
    * Fix: detect a new agent turn automatically, by tracking how long it's
      been (wall-clock) since the last agent chunk was written. If a gap of
      AGENT_TURN_GAP_SECONDS or more has elapsed, treat the next agent chunk
      as the start of a new turn and resync the cursor to the latest known
      caller timestamp before placing it. This covers BOTH a barge-in
      interrupt AND a normal turn_complete-then-silence-then-next-turn cycle,
      since both look identical from the recorder's point of view: a gap in
      agent audio delivery, of unknown cause, followed by new agent audio.
      interrupt_agent_audio() is kept as an optional immediate signal (skips
      waiting for the gap timer), but the gap-based detection is now the
      primary mechanism and works correctly even if no interrupt ever fires.
- Overlapping audio (both talking at once) is summed with clipping -> a true mix.
- At the end of the call we write the buffer to a WAV file. WAV is a playable,
  self-describing container and avoids MP3 extension/codec mismatches.

REQUIRES: none beyond Python stdlib audio support for WAV.

Usage:
    recorder = CallRecorder(call_sid="CAxxxx")
    recorder.start()
    ...
    # twilio_timestamp_ms comes from msg["media"]["timestamp"] in the Twilio event
    recorder.add_caller_audio(mulaw_bytes, twilio_timestamp_ms)
    recorder.add_agent_audio(mulaw_bytes)
    ...
    path = recorder.finalize()                  # returns path to the WAV file
"""

import audioop
import io
import time
import wave
import os
import numpy as np
from threading import Lock

# Project-local default output folder for recordings.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "data", "recordings")

SAMPLE_RATE = 8000          # Twilio Media Streams default
SAMPLE_WIDTH = 2            # PCM16 = 2 bytes/sample
BYTES_PER_SECOND = SAMPLE_RATE * SAMPLE_WIDTH

# How far ahead of the current write position we pre-allocate the buffer,
# to avoid resizing the numpy array on every single chunk.
PREALLOC_SECONDS = 30

# If this many seconds pass with no agent audio written, the next agent chunk
# is treated as the start of a new turn and the cursor resyncs to the latest
# known caller timestamp. Real agent chunks normally arrive every 20-200ms
# while a turn is actively streaming, so a gap this long reliably means the
# previous turn ended (interrupted or naturally) and silence followed.
AGENT_TURN_GAP_SECONDS = 1.0


class CallRecorder:
    def __init__(self, call_sid: str, output_dir: str = DEFAULT_OUTPUT_DIR):
        self.call_sid = call_sid
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self._lock = Lock()
        self._started = False

        # Caller audio position is driven directly by Twilio's own timestamp,
        # so there's no "start time" to track for it -- timestamp=0 IS sample 0.
        # Agent audio position is driven by cumulative duration of agent chunks
        # written so far (no Twilio timestamp exists for audio we generate).
        self._agent_cursor_sample = 0
        self._agent_cursor_needs_resync = True  # True until the first chunk anchors it
        self._last_agent_write_wallclock = None  # None until the first agent chunk arrives

        # Tracks the most recent Twilio caller timestamp we've seen, in samples.
        # This is the only trustworthy "now" in the system (Twilio-authoritative),
        # and is what the agent cursor resyncs against at the start of each turn.
        self._latest_caller_sample = 0

        # int32 buffer to avoid clipping artifacts mid-sum; we clip down to int16 at the end.
        self._buffer = np.zeros(SAMPLE_RATE * PREALLOC_SECONDS, dtype=np.int32)
        self._max_sample_written = 0  # high-water mark, in samples

    def start(self):
        """Call this the moment the Twilio `start` event arrives."""
        self._started = True

    def _ensure_capacity(self, end_sample: int):
        """Grow the buffer if this chunk would write past the current allocation."""
        if end_sample <= len(self._buffer):
            return
        new_size = max(end_sample, len(self._buffer) * 2)
        grown = np.zeros(new_size, dtype=np.int32)
        grown[: len(self._buffer)] = self._buffer
        self._buffer = grown

    def _write_at(self, start_sample: int, samples: np.ndarray):
        """Atomically grow-and-sum samples into the buffer at an exact sample offset."""
        if start_sample < 0:
            start_sample = 0
        end_sample = start_sample + len(samples)

        with self._lock:
            self._ensure_capacity(end_sample)
            self._buffer[start_sample:end_sample] += samples
            self._max_sample_written = max(self._max_sample_written, end_sample)

    def add_caller_audio(self, mulaw_bytes: bytes, twilio_timestamp_ms: int):
        """
        Feed raw mulaw bytes from a Twilio inbound `media` event, placed using
        Twilio's own `timestamp` field (ms since stream start) -- NOT wall-clock
        arrival time. This is what makes the recording immune to your server's
        own processing delay.

        twilio_timestamp_ms: the value of msg["media"]["timestamp"], as an int.
        """
        pcm16 = audioop.ulaw2lin(mulaw_bytes, SAMPLE_WIDTH)
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.int32)

        start_sample = int(twilio_timestamp_ms * SAMPLE_RATE / 1000)

        with self._lock:
            self._latest_caller_sample = max(self._latest_caller_sample, start_sample + len(samples))

        self._write_at(start_sample, samples)

    def add_agent_audio(self, mulaw_bytes: bytes):
        """
        Feed raw mulaw bytes for audio sent back to Twilio (Gemini's voice).
        There's no Twilio timestamp for outbound audio we generate ourselves,
        so position is tracked as cumulative playback time: each chunk is
        placed immediately after the previous agent chunk ends, based on the
        chunk's own duration.

        At the start of each new agent turn (detected either by an explicit
        interrupt_agent_audio() call, or automatically by a gap of
        AGENT_TURN_GAP_SECONDS+ since the last agent chunk -- which covers
        normal turn_complete-then-silence cycles too, not just barge-in), the
        cursor resyncs to the latest known caller timestamp before placing
        this chunk. This is what prevents a new agent turn from being placed
        too early and overlapping caller speech that happened while the agent
        was silent.
        """
        pcm16 = audioop.ulaw2lin(mulaw_bytes, SAMPLE_WIDTH)
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.int32)

        now = time.monotonic()

        with self._lock:
            gap_detected = (
                self._last_agent_write_wallclock is not None
                and (now - self._last_agent_write_wallclock) >= AGENT_TURN_GAP_SECONDS
            )
            if self._agent_cursor_needs_resync or gap_detected:
                self._agent_cursor_sample = max(self._agent_cursor_sample, self._latest_caller_sample)
                self._agent_cursor_needs_resync = False

            self._last_agent_write_wallclock = now
            start_sample = self._agent_cursor_sample
            self._agent_cursor_sample += len(samples)

        self._write_at(start_sample, samples)

    def interrupt_agent_audio(self):
        """
        Optional: call this when Gemini's speech is interrupted/barged-in on
        (i.e. whenever your audio_interrupt_callback fires), to flag a resync
        immediately rather than waiting for the AGENT_TURN_GAP_SECONDS timer.
        Not required for correctness -- add_agent_audio's gap detection will
        catch a stale cursor on its own either way -- but calling this makes
        the resync happen on the very next chunk rather than after a short
        delay, which matters if the agent resumes speaking almost immediately
        after being interrupted.
        """
        with self._lock:
            self._agent_cursor_needs_resync = True

    def finalize(self) -> str:
        """Clip, write a WAV file, and return the file path. Call once, when the call ends."""
        with self._lock:
            trimmed = self._buffer[: self._max_sample_written]
            # Clip int32 sums back into int16 range to prevent wraparound distortion
            # if both sides happen to peak at the same instant.
            clipped = np.clip(trimmed, -32768, 32767).astype(np.int16)

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(clipped.tobytes())
        wav_buffer.seek(0)

        wav_path = os.path.join(self.output_dir, f"{self.call_sid}.wav")
        with open(wav_path, "wb") as f:
            f.write(wav_buffer.getvalue())

        return wav_path