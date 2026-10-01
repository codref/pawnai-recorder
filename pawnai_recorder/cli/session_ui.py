"""Textual window for a live recording session.

The note field stays available while audio is captured. Keys:

* ``s`` start / stop
* ``u`` force-upload the current chunk
* ``c`` screenshot (when ``--screenshot-output`` is set)
* ``q`` quit
"""

from __future__ import annotations

from typing import Optional


def run_session_ui(session, duration: Optional[float] = None) -> None:
    """Block on the session window until the user quits or *duration* elapses."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal
    from textual.widgets import Footer, Header, Input, Static

    class SessionApp(App):
        TITLE = "PawnAI Recorder"
        CSS = """
        Screen { layout: vertical; }
        #status { height: 2; padding: 0 1; }
        #error { height: auto; max-height: 4; padding: 0 1; color: $error; display: none; }
        #body { height: 1fr; }
        #chunks { width: 1fr; height: 1fr; padding: 0 1; border: solid $primary; }
        #notes { width: 1fr; height: 1fr; padding: 0 1; border: solid $accent; }
        #note { height: 3; margin: 0 1; }
        """
        BINDINGS = [
            Binding("s", "toggle", "Start/Stop"),
            Binding("u", "flush", "Force upload"),
            Binding("c", "shot", "Screenshot"),
            Binding("q", "quit_session", "Quit"),
            Binding("ctrl+c", "quit_session", "Quit", show=False),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._session = session
            self._duration = duration

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="status")
            yield Static("", id="error")
            with Horizontal(id="body"):
                yield Static("", id="chunks")
                yield Static("", id="notes")
            yield Input(placeholder="Note — Enter to attach it to this take", id="note")
            yield Footer()

        def on_mount(self) -> None:
            self.set_interval(0.2, self._tick)
            if not self._session.is_recording:
                try:
                    self._session.start()
                except Exception as exc:
                    self._set_error(str(exc))
            self._render()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value
            event.input.value = ""
            try:
                self._session.add_note(text)
            except Exception as exc:
                self._set_error(str(exc))
            self._render()

        def action_toggle(self) -> None:
            try:
                self._session.toggle()
            except Exception as exc:
                self._set_error(str(exc))
            self._render()

        def action_flush(self) -> None:
            try:
                flushed = self._session.force_flush()
                if not flushed and self._session.is_recording:
                    self._set_error("nothing buffered to upload yet")
            except Exception as exc:
                self._set_error(str(exc))
            self._render()

        def action_shot(self) -> None:
            if not self._session.screenshots_enabled:
                self._set_error("pass --screenshot-output to enable capture")
                self._render()
                return
            try:
                self._session.take_screenshot()
            except Exception as exc:
                self._set_error(str(exc))
            self._render()

        def action_quit_session(self) -> None:
            if self._session.is_recording:
                self._session.stop()
            self.exit()

        def _set_error(self, message: str) -> None:
            self._session.set_error(message)

        def _tick(self) -> None:
            self._session.drain_audio_ops()
            if (
                self._duration
                and self._session.is_recording
                and self._session.elapsed_sec() >= self._duration
            ):
                self._session.stop()
                self.exit()
                return
            self._render()

        def _render(self) -> None:
            snap = self._session.snapshot()
            state = "REC" if snap["recording"] else "IDLE"
            elapsed = _clock(snap["elapsed_sec"])
            db = snap["db"]
            bar = _bar(db)
            device = snap["device_name"] or ""
            self.query_one("#status", Static).update(
                f"{state}  {snap['session_label'] or '—'}  {elapsed}  {snap['diarize_mode']}"
                f"  {bar} {db:5.1f} dB  {device}"
            )
            error = self.query_one("#error", Static)
            if snap["last_error"]:
                error.update(snap["last_error"])
                error.display = True
            else:
                error.update("")
                error.display = False

            if snap["chunks"]:
                chunk_lines = ["Chunks"]
                for chunk in reversed(snap["chunks"]):
                    dur = chunk.get("duration_sec") or 0
                    chunk_lines.append(
                        f"#{chunk['index']:02d}  {chunk['status']}  {dur:.1f}s  {chunk['file_path']}"
                    )
            else:
                chunk_lines = ["Chunks", "No chunks yet"]
            self.query_one("#chunks", Static).update("\n".join(chunk_lines))

            note_lines = ["Notes"]
            if snap["notes"]:
                for note in snap["notes"]:
                    note_lines.append(f"{note['at']}  {note['text']}")
            else:
                note_lines.append("Type a note and press Enter")
            if snap["screenshots"]:
                note_lines.append("")
                note_lines.append("Screenshots")
                for shot in snap["screenshots"]:
                    note_lines.append(f"{shot['at']}  {shot['output']}  {shot['s3_uri'] or 'local'}")
            self.query_one("#notes", Static).update("\n".join(note_lines))

    app = SessionApp()

    def _quit_from_tray() -> None:
        app.call_from_thread(app.action_quit_session)

    session.request_quit = _quit_from_tray
    app.run()


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _bar(db: float, width: int = 24) -> str:
    filled = int(max(0.0, min(120.0, db)) / 120.0 * width)
    return "█" * filled + "░" * (width - filled)
