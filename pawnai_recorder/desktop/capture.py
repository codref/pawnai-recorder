"""Capture one screen to a PNG.

Backend choice:

* Wayland with ``grim`` on ``PATH`` — ``grim -o <output>``. A numeric output
  is mapped through ``swaymsg`` when that tool is available.
* Wayland without ``grim`` — ``xdg-desktop-portal`` Screenshot. The portal
  does not take a monitor name; the first call may ask for permission.
  Install ``grim`` to pin a specific output.
* X11 (``DISPLAY`` set, no ``WAYLAND_DISPLAY``) — ``mss``, by monitor index
  starting at 0.

``region`` is not captured yet. Callers keep the field and leave it empty.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import unquote, urlparse

from loguru import logger


class CaptureError(RuntimeError):
    """The selected backend could not write a screenshot."""


def select_backend(
    environ: Optional[Mapping[str, str]] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> str:
    """Return ``grim``, ``portal``, ``mss``, or ``none``."""
    env = os.environ if environ is None else environ
    if env.get("WAYLAND_DISPLAY"):
        if which("grim"):
            return "grim"
        return "portal"
    if env.get("DISPLAY"):
        return "mss"
    return "none"


def capture_to(
    dest: Path,
    output: str,
    backend: Optional[str] = None,
) -> Path:
    """Write a PNG of *output* to *dest* and return that path."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    chosen = backend or select_backend()
    if chosen == "grim":
        _capture_grim(dest, output)
    elif chosen == "portal":
        _capture_portal(dest, output)
    elif chosen == "mss":
        _capture_mss(dest, output)
    else:
        raise CaptureError(
            "No display session found (set WAYLAND_DISPLAY or DISPLAY)"
        )
    if not dest.is_file() or dest.stat().st_size == 0:
        raise CaptureError(f"{chosen} did not write {dest}")
    return dest


def _sway_output_names() -> Optional[list]:
    try:
        result = subprocess.run(
            ["swaymsg", "-t", "get_outputs", "-r"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    names = [item.get("name") for item in payload if isinstance(item, dict) and item.get("name")]
    return names or None


def _resolve_grim_output(output: str) -> str:
    if not output.isdigit():
        return output
    names = _sway_output_names()
    if names is None:
        return output
    index = int(output)
    if index < 0 or index >= len(names):
        found = ", ".join(names)
        raise CaptureError(
            f"monitor index {index} is out of range; sway outputs: {found}"
        )
    return names[index]


def _capture_grim(dest: Path, output: str) -> None:
    target = _resolve_grim_output(output)
    result = subprocess.run(
        ["grim", "-o", target, str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CaptureError(detail or f"grim exited {result.returncode}")


_portal_output_warned = False


def _capture_portal(dest: Path, output: str) -> None:
    global _portal_output_warned
    if output and not _portal_output_warned:
        _portal_output_warned = True
        logger.warning(
            "xdg-desktop-portal captures the default screen; "
            "install grim to select output {!r}",
            output,
        )
    try:
        from jeepney import DBusAddress, HeaderFields, MessageType, new_method_call
        from jeepney.bus_messages import MatchRule
        from jeepney.io.blocking import open_dbus_connection
    except ImportError as exc:
        raise CaptureError(
            "Wayland screenshot without grim needs jeepney "
            "(pip install 'pawnai-recorder[ui]')"
        ) from exc

    token = "pawnai" + uuid.uuid4().hex[:12]
    conn = open_dbus_connection(bus="SESSION")
    try:
        rule = MatchRule(
            type="signal",
            sender="org.freedesktop.portal.Desktop",
            interface="org.freedesktop.portal.Request",
            member="Response",
        )
        conn.send_and_get_reply(rule.add_match())
        addr = DBusAddress(
            "/org/freedesktop/portal/desktop",
            bus_name="org.freedesktop.portal.Desktop",
            interface="org.freedesktop.portal.Screenshot",
        )
        options = [
            ("interactive", ("b", False)),
            ("handle_token", ("s", token)),
        ]
        msg = new_method_call(addr, "Screenshot", "sa{sv}", ("", options))
        reply = conn.send_and_get_reply(msg, timeout=15)
        if reply.header.message_type == MessageType.error:
            raise CaptureError(f"portal error: {reply.body}")
        request_path = reply.body[0]
        deadline = time.time() + 30
        while time.time() < deadline:
            incoming = conn.receive(timeout=1)
            if incoming is None or incoming.header.message_type != MessageType.signal:
                continue
            path = incoming.header.fields.get(HeaderFields.path)
            if path != request_path:
                continue
            code, results = incoming.body
            if code != 0:
                raise CaptureError(f"portal screenshot declined (code {code})")
            uri = _as_dict(results).get("uri")
            if not uri:
                raise CaptureError("portal returned no image uri")
            _copy_file_uri(str(uri), dest)
            return
        raise CaptureError("portal screenshot timed out")
    finally:
        conn.close()


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    mapped = {}
    for item in value:
        key, raw = item[0], item[1]
        if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], str):
            raw = raw[1]
        mapped[str(key)] = raw
    return mapped


def _copy_file_uri(uri: str, dest: Path) -> None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise CaptureError(f"portal returned unsupported uri {uri}")
    source = Path(unquote(parsed.path))
    shutil.copyfile(source, dest)


def _capture_mss(dest: Path, output: str) -> None:
    try:
        import mss
        import mss.tools
    except ImportError as exc:
        raise CaptureError(
            "X11 capture needs the mss package (pip install 'pawnai-recorder[ui]')"
        ) from exc
    if not str(output).isdigit():
        raise CaptureError(f"X11 capture expects a monitor index, got {output!r}")
    index = int(output)
    with mss.mss() as sct:
        real = list(sct.monitors[1:])
        if index < 0 or index >= len(real):
            raise CaptureError(
                f"monitor index {index} is out of range (found {len(real)})"
            )
        shot = sct.grab(real[index])
        mss.tools.to_png(shot.rgb, shot.size, output=str(dest))
