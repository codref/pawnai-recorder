"""pawn_recorder_droid.audio.mic_source — superseded by flet-audio-recorder.

This module previously wrapped the Kivy ``audiostream`` library with a
hand-rolled chunked-PCM pipeline.  The Flet rewrite replaced it entirely:

* Mic access is now handled by ``flet_audio_recorder.AudioRecorder`` — a
  Flet Service that works on Android, iOS, Windows, macOS, Linux, and web.
* Chunked recording is implemented directly in
  ``pawn_recorder_droid.screens.recorder_screen.build_recorder_view`` via an
  ``asyncio`` timed loop (start → sleep → stop → upload).

Migration guide
───────────────
If you had code that imported ``AndroidMicSource`` directly, migrate to the
pattern used in ``recorder_screen.py``::

    import flet_audio_recorder as far

    recorder = far.AudioRecorder(
        configuration=far.AudioRecorderConfiguration(encoder=far.AudioEncoder.WAV),
    )
    page.services.append(recorder)

    # start a chunk
    await recorder.start_recording(output_path="/path/to/chunk.wav")
    await asyncio.sleep(60)          # record for 60 s
    path = await recorder.stop_recording()  # → "/path/to/chunk.wav"

No AudioStream, SDL, or Cython required.
"""
