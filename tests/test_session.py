"""Session payload, force-flush, capture backend, and tray menu tests."""

import json

import pytest

from pawnai_recorder.core.jobs import (
    AttachmentTracker,
    ChunkPipeline,
    Shot,
    new_attachment_id,
    resolve_diarize_mode,
    with_diarize_mode,
)
from pawnai_recorder.desktop.capture import _resolve_grim_output, select_backend
from pawnai_recorder.desktop.tray import build_menu_actions, dispatch_menu


class _Producer:
    def __init__(self):
        self.messages = []

    def publish(self, payload):
        self.messages.append(payload)


def _pipeline(mode, producer, tracker):
    return ChunkPipeline(
        producer=producer,
        bucket="bucket",
        queue_job_config={
            "transcribe_diarize": {"mode": mode, "threshold": 0.2, "device": "cpu"},
            "analyze": {"mode": "summary", "model": "gpt-4o"},
            "sync_siyuan": {},
        },
        session_value=lambda: "sess",
        attachments=tracker,
    )


def test_diarize_mode_override_wins_over_yaml():
    cfg = {"transcribe_diarize": {"mode": "end_of_session", "threshold": 0.2}}
    assert resolve_diarize_mode(cfg, None) == "end_of_session"
    assert resolve_diarize_mode(cfg, "per_chunk") == "per_chunk"
    updated = with_diarize_mode(cfg, "per_chunk")
    assert updated["transcribe_diarize"]["mode"] == "per_chunk"
    assert cfg["transcribe_diarize"]["mode"] == "end_of_session"
    with pytest.raises(ValueError):
        resolve_diarize_mode(cfg, "sometimes")


def test_attachment_delta_is_published_once():
    tracker = AttachmentTracker()
    tracker.add_note("a")
    tracker.add_note("b")
    first, _shots = tracker.take_delta()
    assert [item["text"] for item in first] == ["a", "b"]
    tracker.add_note("c")
    second, _shots = tracker.take_delta()
    assert [item["text"] for item in second] == ["c"]
    third, _shots = tracker.take_delta()
    assert third == []


def test_full_set_marks_items_so_a_later_delta_is_empty():
    tracker = AttachmentTracker()
    tracker.add_note("a")
    notes, _shots = tracker.full_set()
    assert [item["text"] for item in notes] == ["a"]
    again, _shots = tracker.take_delta()
    assert again == []


def test_per_chunk_payload_carries_only_new_notes_and_screenshots():
    tracker = AttachmentTracker()
    producer = _Producer()
    pipeline = _pipeline("per_chunk", producer, tracker)

    tracker.add_note("first")
    assert pipeline.on_uploaded("a.flac") == "diarize_published"
    tracker.add_shot(Shot(
        id=new_attachment_id(),
        at="2026-10-01T22:10:05+02:00",
        s3_uri="s3://bucket/shot.png",
        output="DP-1",
        region=None,
    ))
    assert pipeline.on_uploaded("b.flac") == "diarize_published"

    assert producer.messages[0]["audio_paths"] == ["s3://bucket/a.flac"]
    assert [item["text"] for item in producer.messages[0]["annotations"]] == ["first"]
    assert "screenshots" not in producer.messages[0]

    assert producer.messages[1]["audio_paths"] == ["s3://bucket/b.flac"]
    assert "annotations" not in producer.messages[1]
    shot = producer.messages[1]["screenshots"][0]
    assert shot["s3_uri"] == "s3://bucket/shot.png"
    assert shot["output"] == "DP-1"
    assert shot["region"] is None

    pipeline.finish_transcription()
    pipeline.publish_session_close()
    assert [message["command"] for message in producer.messages[2:]] == [
        "analyze",
        "sync-siyuan",
    ]
    assert "annotations" not in producer.messages[2]
    assert "screenshots" not in producer.messages[2]


def test_end_of_session_publishes_every_path_and_the_full_attachment_set():
    tracker = AttachmentTracker()
    producer = _Producer()
    pipeline = _pipeline("end_of_session", producer, tracker)

    assert pipeline.on_uploaded("a.flac") == "accumulated"
    tracker.add_note("later")
    assert pipeline.on_uploaded("b.flac") == "accumulated"
    assert producer.messages == []

    pipeline.finish_transcription()
    pipeline.finish_transcription()
    assert len(producer.messages) == 1
    message = producer.messages[0]
    assert message["command"] == "transcribe-diarize"
    assert message["audio_paths"] == ["s3://bucket/a.flac", "s3://bucket/b.flac"]
    assert [item["text"] for item in message["annotations"]] == ["later"]

    pipeline.publish_session_close()
    assert producer.messages[1]["command"] == "analyze"
    assert "annotations" not in producer.messages[1]


def test_session_offset_is_cumulative_and_restart_keeps_notes(tmp_path):
    import time

    from pawnai_recorder.core.jobs import format_session_offset
    from pawnai_recorder.core.log import RecordingLogger
    from pawnai_recorder.core.recording import MicrophoneStream
    from pawnai_recorder.core.session import RecordingSession

    assert format_session_offset(49.2) == "00:49.20"

    stream = MicrophoneStream(
        output_dir=str(tmp_path) + "/",
        upload_enabled=False,
        initial_chunk_index=1,
    )
    calls = []
    stream._create_chunk_saving_thread = lambda frames, count: calls.append(count)
    stream._recording_frames = [b"\x00\x00"]
    assert stream.force_flush() is True
    assert calls == [2]

    live = RecordingSession(
        output_dir=str(tmp_path) + "/",
        rate=16000,
        chunk_size=2,
        file_format="flac",
        gain=1.0,
        device_id=0,
        sink=None,
        conversation_id=None,
        upload_enabled=False,
        verbose=False,
        timestamp_format="{ts}",
        datetime_format="%y%m%d%H%M%S",
        session_label="test-1001",
        recording_logger=RecordingLogger(tmp_path / "log.jsonl"),
        queue_producer=None,
        queue_job_config={},
    )
    live._running.set()
    live._take_started = time.monotonic() - 40
    live._stop_impl()
    assert live._recorded_sec >= 39
    live._attachments.add_note("keep", at="00:10.00", offset_sec=10)
    live._chunks[1] = {"index": 1, "file_path": "old_01.flac", "status": "uploaded"}
    live._chunk_count = 1

    class Backend:
        session_id = "261002000100"

        def start_recording(self):
            return {
                "session_id": self.session_id,
                "device_name": "mic",
                "device_id": 1,
                "sample_rate": 16000,
                "output_dir": str(tmp_path),
            }

        def get_current_db_level(self):
            return 0.0

    seen = {}

    def _open():
        seen["index"] = live._chunk_count
        return Backend()

    live._open_backend = _open
    live._start_impl()
    assert seen["index"] == 1
    notes, _shots = live._attachments.snapshot()
    assert [note.text for note in notes] == ["keep"]
    assert live._chunks[1]["file_path"] == "old_01.flac"
    live._take_started = time.monotonic() - 9
    fresh = live.add_note("later")
    assert fresh.at.startswith("00:4")
    assert fresh.offset_sec >= 48


def test_force_flush_emits_partial_buffer_once(tmp_path):
    from pawnai_recorder.core.recording import MicrophoneStream

    stream = MicrophoneStream(
        output_dir=str(tmp_path) + "/",
        upload_enabled=False,
        chunk_size=8,
    )
    calls = []
    stream._create_chunk_saving_thread = lambda frames, count: calls.append((count, len(frames)))
    stream._recording_frames = [b"\x00\x00", b"\x01\x00"]

    assert stream.force_flush() is True
    assert calls == [(1, 2)]
    assert stream._recording_frames == []
    assert stream.force_flush() is False
    assert calls == [(1, 2)]


def test_callback_flushes_when_the_chunk_fills(tmp_path):
    import pyaudio

    from pawnai_recorder.core.recording import MicrophoneStream

    stream = MicrophoneStream(
        output_dir=str(tmp_path) + "/",
        upload_enabled=False,
        chunk_size=2,
    )
    calls = []
    stream._create_chunk_saving_thread = lambda frames, count: calls.append((count, len(frames)))
    assert stream._fill_buffer(b"\x00\x00", 1, None, None)[1] == pyaudio.paContinue
    assert calls == []
    stream._fill_buffer(b"\x00\x00", 1, None, None)
    assert calls == [(1, 2)]
    assert stream._recording_frames == []


def test_add_note_is_logged_only_while_recording(tmp_path):
    from pawnai_recorder.core.log import RecordingLogger
    from pawnai_recorder.core.session import RecordingSession

    log_path = tmp_path / "recordings.jsonl"
    live = RecordingSession(
        output_dir=str(tmp_path) + "/",
        rate=16000,
        chunk_size=2,
        file_format="flac",
        gain=1.0,
        device_id=0,
        sink=None,
        conversation_id=None,
        upload_enabled=False,
        verbose=False,
        timestamp_format="{ts}",
        datetime_format="%y%m%d%H%M%S",
        session_label="label",
        recording_logger=RecordingLogger(log_path),
        queue_producer=None,
        queue_job_config={"transcribe_diarize": {"mode": "per_chunk"}},
    )
    with pytest.raises(RuntimeError, match="not recording"):
        live.add_note("hello")

    live._running.set()
    live._session_id = "sess"
    note = live.add_note("  hello  ")
    assert note is not None
    assert note.text == "hello"
    assert live.session_value() == "label"

    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert rows[0]["type"] == "note"
    assert rows[0]["session_id"] == "sess"
    assert rows[0]["text"] == "hello"
    assert rows[0]["id"] == note.id


def test_input_candidates_try_pulse_before_alsa_plugins():
    from pawnai_recorder.core.recording import input_candidate_order

    devices = [
        {"id": 21, "name": "default", "driver": "default", "channels": 128},
        {"id": 15, "name": "pipewire", "driver": "pulse", "channels": 128},
        {"id": 16, "name": "pulse", "driver": "pulse", "channels": 32},
        {"id": 22, "name": "Built-in Audio Analog Stereo", "driver": "default", "channels": 2},
    ]
    order = input_candidate_order(devices, preferred_id=21)
    assert order[0] == 21
    assert order.index(16) < order.index(15)
    assert order.index(16) < order.index(22)


def test_select_backend_prefers_grim_on_wayland_and_mss_on_x11():
    def nowhere(_name):
        return None

    def grim(name):
        return "/usr/bin/grim" if name == "grim" else None

    assert select_backend({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, nowhere) == "portal"
    assert select_backend({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, grim) == "grim"
    assert select_backend({"DISPLAY": ":0"}, nowhere) == "mss"
    assert select_backend({}, nowhere) == "none"


def test_grim_output_index_uses_sway_names(monkeypatch):
    monkeypatch.setattr(
        "pawnai_recorder.desktop.capture._sway_output_names",
        lambda: ["eDP-1", "DP-1"],
    )
    assert _resolve_grim_output("1") == "DP-1"
    assert _resolve_grim_output("DP-1") == "DP-1"
    with pytest.raises(Exception, match="out of range"):
        _resolve_grim_output("4")


def test_tray_audio_ops_run_on_the_main_thread(tmp_path):
    """Pause/play from the tray thread must not touch PortAudio off the main thread."""
    import threading
    import time

    from pawnai_recorder.core.log import RecordingLogger
    from pawnai_recorder.core.session import RecordingSession

    live = RecordingSession(
        output_dir=str(tmp_path) + "/",
        rate=16000,
        chunk_size=2,
        file_format="flac",
        gain=1.0,
        device_id=0,
        sink=None,
        conversation_id=None,
        upload_enabled=False,
        verbose=False,
        timestamp_format="{ts}",
        datetime_format="%y%m%d%H%M%S",
        session_label=None,
        recording_logger=RecordingLogger(tmp_path / "log.jsonl"),
        queue_producer=None,
        queue_job_config={},
    )
    seen = []

    def _impl():
        seen.append(threading.current_thread() is threading.main_thread())

    worker = threading.Thread(target=lambda: live._on_main_thread(_impl))
    worker.start()
    for _ in range(50):
        live.drain_audio_ops()
        if not worker.is_alive():
            break
        time.sleep(0.01)
    worker.join(timeout=1)
    assert seen == [True]


def test_tray_icon_uses_theme_names_and_menu_serialises():
    from jeepney import HeaderFields, Message, MessageType
    from jeepney.wrappers import new_header

    from pawnai_recorder.desktop.tray import icon_name, menu_layout, visible_menu_actions

    assert icon_name(False) == "media-playback-start"
    assert icon_name(True) == "media-playback-pause"

    class Fake:
        is_recording = True
        screenshots_enabled = False

    actions = visible_menu_actions(Fake())
    assert [row["id"] for row in actions] == ["start", "stop", "flush", "shot", "quit"]
    assert actions[1]["enabled"] is True
    message = Message(new_header(MessageType.method_return), (1, menu_layout(actions)))
    message.header.fields[HeaderFields.signature] = "u(ia{sv}av)"
    message.serialise(serial=1)


def test_tray_menu_and_dispatch():
    class Fake:
        def __init__(self):
            self.calls = []
            self.is_recording = False
            self.screenshots_enabled = False

        def toggle(self):
            self.calls.append("toggle")

        def start(self):
            self.calls.append("start")

        def stop(self):
            self.calls.append("stop")

        def force_flush(self):
            self.calls.append("flush")

        def take_screenshot(self):
            self.calls.append("shot")

        def quit(self):
            self.calls.append("quit")

    idle = Fake()
    actions = {row["id"]: row for row in build_menu_actions(idle)}
    assert actions["start"]["enabled"] is True
    assert actions["stop"]["enabled"] is False
    assert actions["flush"]["enabled"] is False
    assert actions["shot"]["enabled"] is False
    assert actions["toggle"]["default"] is True

    idle.is_recording = True
    idle.screenshots_enabled = True
    actions = {row["id"]: row for row in build_menu_actions(idle)}
    assert actions["start"]["enabled"] is False
    assert actions["stop"]["enabled"] is True
    assert actions["shot"]["enabled"] is True

    dispatch_menu(idle, "toggle")
    dispatch_menu(idle, "flush")
    dispatch_menu(idle, "shot")
    dispatch_menu(idle, "quit")
    assert idle.calls == ["toggle", "flush", "shot", "quit"]
