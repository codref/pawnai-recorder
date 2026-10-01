"""Linux status-bar icon for an open recording session.

This is a StatusNotifierItem on the session bus, which is what KDE, waybar,
and GNOME's AppIndicator host actually display. The pictures are the desktop icon theme's play and pause symbols
(``media-playback-start`` while idle, ``media-playback-pause`` while recording).

Left click (Activate) toggles recording. Right click opens the menu.
The listener thread is a daemon, so Ctrl+C is not held up by the icon.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from loguru import logger

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/StatusNotifierItem/Menu"
WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
INTROSPECT_IFACE = "org.freedesktop.DBus.Introspectable"


def desktop_session_present() -> bool:
    """True when a Linux graphical session is likely available."""
    return bool(
        os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("DISPLAY")
    )


def icon_name(recording: bool) -> str:
    """Freedesktop icon-theme name for the current recording state.

    Pause while a take is running (click stops it). Play while idle (click starts one).
    """
    return "media-playback-pause" if recording else "media-playback-start"


def build_menu_actions(session) -> list:
    """Describe the status-bar menu. Tested without opening a real tray."""
    recording = bool(session.is_recording)
    shots = bool(session.screenshots_enabled)
    return [
        {
            "id": "toggle",
            "label": "Toggle recording",
            "enabled": True,
            "default": True,
            "visible": False,
        },
        {"id": "start", "label": "Start", "enabled": not recording},
        {"id": "stop", "label": "Stop", "enabled": recording},
        {"id": "flush", "label": "Force upload chunk", "enabled": recording},
        {"id": "shot", "label": "Take screenshot", "enabled": shots},
        {"id": "quit", "label": "Quit", "enabled": True},
    ]


def dispatch_menu(session, action_id: str) -> None:
    """Run one menu action against *session*."""
    if action_id == "toggle":
        session.toggle()
    elif action_id == "start":
        session.start()
    elif action_id == "stop":
        session.stop()
    elif action_id == "flush":
        session.force_flush()
    elif action_id == "shot":
        session.take_screenshot()
    elif action_id == "quit":
        session.quit()
    else:
        raise ValueError(f"unknown tray action {action_id!r}")


def visible_menu_actions(session) -> list:
    """Menu rows the desktop should show (the hidden toggle is left-click only)."""
    return [row for row in build_menu_actions(session) if row.get("visible", True)]


def menu_layout(actions: list) -> tuple:
    """Build a DBusMenu layout node ``(id, props, children)``."""
    children = []
    for index, row in enumerate(actions, start=1):
        children.append(_menu_node(
            index,
            [
                ("type", "s", "standard"),
                ("label", "s", row["label"]),
                ("enabled", "b", bool(row.get("enabled", True))),
                ("visible", "b", True),
            ],
            [],
        ))
    return _menu_node(0, [("children-display", "s", "submenu")], children)


def menu_action_ids(actions: list) -> dict:
    """Map DBusMenu item ids to action ids. The root is 0 and is not clickable."""
    return {index: row["id"] for index, row in enumerate(actions, start=1)}


def _menu_node(item_id: int, props: list, children: list) -> tuple:
    encoded = [(key, (sig, value)) for key, sig, value in props]
    variants = [("(ia{sv}av)", child) for child in children]
    return (item_id, encoded, variants)


class TrayIcon:
    """A running StatusNotifierItem. ``stop`` does not block process exit."""

    def __init__(self, thread: threading.Thread, connection) -> None:
        self._thread = thread
        self._connection = connection

    def stop(self) -> None:
        try:
            self._connection.interrupt()
        except Exception as exc:
            logger.debug(f"Tray stop failed: {exc}")

    def refresh(self) -> None:
        return None


def start_tray(session) -> Optional[TrayIcon]:
    """Show the status icon, or return ``None`` when the desktop cannot host it."""
    if not desktop_session_present():
        logger.warning("Status bar icon skipped: no desktop session detected")
        return None
    try:
        from jeepney.io.threading import ReceiveStopped, open_dbus_connection
    except ImportError:
        logger.warning(
            "Status bar icon skipped: install jeepney "
            "(pip install 'pawnai-recorder[ui]')"
        )
        return None

    try:
        connection = open_dbus_connection(bus="SESSION")
    except Exception as exc:
        logger.warning(f"Status bar icon skipped: {exc}")
        return None

    service = _Notifier(session, connection)
    try:
        service.register()
    except Exception as exc:
        logger.warning(f"Status bar icon skipped: {exc}")
        try:
            connection.close()
        except Exception:
            pass
        return None

    thread = threading.Thread(
        target=service.serve,
        name="pawnai-tray",
        daemon=True,
        kwargs={"receive_stopped": ReceiveStopped},
    )
    session.subscribe(service.mark_dirty)
    thread.start()
    return TrayIcon(thread, connection)


class _Notifier:
    """One StatusNotifierItem plus its DBus menu."""

    def __init__(self, session, connection) -> None:
        self._session = session
        self._conn = connection
        self._revision = 1
        self._dirty = threading.Event()
        self._name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"

    def mark_dirty(self) -> None:
        self._dirty.set()

    def register(self) -> None:
        from jeepney import DBusAddress, new_method_call
        from jeepney.bus_messages import message_bus
        from jeepney.io.threading import DBusRouter

        watcher = DBusAddress(
            "/StatusNotifierWatcher",
            bus_name=WATCHER,
            interface=WATCHER,
        )
        with DBusRouter(self._conn) as router:
            reply = router.send_and_get_reply(
                message_bus.RequestName(self._name, 0),
                timeout=5,
            )
            self._raise_on_error(reply, f"could not own {self._name}")
            reply = router.send_and_get_reply(
                new_method_call(watcher, "RegisterStatusNotifierItem", "s", (self._name,)),
                timeout=5,
            )
            self._raise_on_error(reply, "status notifier watcher rejected the icon")

    @staticmethod
    def _raise_on_error(reply, prefix: str) -> None:
        if reply.header.message_type.name == "error":
            raise RuntimeError(f"{prefix}: {reply.body}")

    def serve(self, receive_stopped) -> None:
        while True:
            try:
                message = self._conn.receive(timeout=0.4)
            except TimeoutError:
                self._flush_dirty()
                continue
            except receive_stopped:
                break
            except Exception as exc:
                logger.debug(f"Tray listener stopped: {exc}")
                break
            try:
                self._dispatch(message)
            except Exception as exc:
                logger.warning(f"Tray message failed: {exc}")
            self._flush_dirty()

    def _flush_dirty(self) -> None:
        if not self._dirty.is_set():
            return
        self._dirty.clear()
        self._revision += 1
        self._emit(ITEM_PATH, ITEM_IFACE, "NewIcon")
        self._emit(ITEM_PATH, ITEM_IFACE, "NewTitle")
        self._emit(MENU_PATH, MENU_IFACE, "LayoutUpdated", "ui", (self._revision, 0))

    def _dispatch(self, message) -> None:
        from jeepney import HeaderFields, MessageFlag, MessageType, new_error, new_method_return

        if message.header.message_type != MessageType.method_call:
            return
        fields = message.header.fields
        path = fields.get(HeaderFields.path, "")
        interface = fields.get(HeaderFields.interface, "")
        member = fields.get(HeaderFields.member, "")
        flags = message.header.flags
        no_reply = bool(flags & MessageFlag.no_reply_expected)

        try:
            signature, body = self._call(path, interface, member, message.body)
        except Exception as exc:
            if not no_reply:
                self._conn.send(new_error(message, "org.freedesktop.DBus.Error.Failed", "s", (str(exc),)))
            return
        if signature is None or no_reply:
            if not no_reply and signature is None:
                self._conn.send(new_method_return(message))
            return
        self._conn.send(new_method_return(message, signature, body))

    def _call(self, path, interface, member, body):
        if member == "Introspect" and interface in ("", INTROSPECT_IFACE):
            return "s", (INTROSPECT_XML,)
        if path == ITEM_PATH:
            return self._item_call(interface, member, body)
        if path == MENU_PATH:
            return self._menu_call(interface, member, body)
        raise RuntimeError(f"unknown tray object {path}")

    def _item_call(self, interface, member, body):
        if member == "Activate" or member == "SecondaryActivate":
            self._run("toggle")
            return None, ()
        if member == "ContextMenu":
            return None, ()
        if member == "Scroll":
            return None, ()
        if interface == PROPS_IFACE and member == "Get":
            _iface, prop = body
            return "v", (self._item_property(prop),)
        if interface == PROPS_IFACE and member == "GetAll":
            return "a{sv}", (self._item_properties(),)
        raise RuntimeError(f"unknown tray method {interface}.{member}")

    def _menu_call(self, interface, member, body):
        actions = visible_menu_actions(self._session)
        if member == "GetLayout":
            _parent, _depth, names = body
            node = _filter_layout(menu_layout(actions), names)
            return "u(ia{sv}av)", (self._revision, node)
        if member == "GetGroupProperties":
            ids, names = body
            return "a(ia{sv})", (self._group_properties(actions, ids, names),)
        if member == "GetProperty":
            item_id, name = body
            value = self._item_menu_property(actions, item_id, name)
            return "v", (value,)
        if member == "Event":
            item_id, event_id = body[0], body[1]
            if event_id == "clicked":
                action = menu_action_ids(actions).get(int(item_id))
                if action:
                    self._run(action)
            return None, ()
        if member == "AboutToShow":
            return "b", (False,)
        if interface == PROPS_IFACE and member == "GetAll":
            return "a{sv}", ([
                ("Version", ("u", 3)),
                ("Status", ("s", "normal")),
            ],)
        raise RuntimeError(f"unknown menu method {interface}.{member}")

    def _run(self, action_id: str) -> None:
        """Run the action off the bus thread so a flush/upload cannot drop the icon."""
        threading.Thread(
            target=self._execute,
            args=(action_id,),
            name="pawnai-tray-action",
            daemon=True,
        ).start()

    def _execute(self, action_id: str) -> None:
        try:
            dispatch_menu(self._session, action_id)
        except Exception as exc:
            logger.warning(f"Tray action {action_id} failed: {exc}")
            setter = getattr(self._session, "set_error", None)
            if setter is not None:
                setter(str(exc))
        self.mark_dirty()

    def _item_property(self, name: str):
        props = dict(self._item_properties())
        if name not in props:
            raise RuntimeError(f"unknown property {name}")
        return props[name]

    def _item_properties(self) -> list:
        recording = bool(self._session.is_recording)
        title = "PawnAI Recorder — recording" if recording else "PawnAI Recorder"
        return [
            ("Category", ("s", "ApplicationStatus")),
            ("Id", ("s", "pawnai-recorder")),
            ("Title", ("s", title)),
            ("Status", ("s", "Active")),
            ("IconName", ("s", icon_name(recording))),
            ("ItemIsMenu", ("b", False)),
            ("Menu", ("o", MENU_PATH)),
        ]

    def _group_properties(self, actions, ids, names) -> list:
        layout = {node[0]: node for node in _walk(menu_layout(actions))}
        rows = []
        for item_id in ids:
            node = layout.get(int(item_id))
            if node is None:
                continue
            props = _filter_props(node[1], names)
            rows.append((int(item_id), props))
        return rows

    def _item_menu_property(self, actions, item_id, name):
        for node in _walk(menu_layout(actions)):
            if node[0] != int(item_id):
                continue
            for key, value in node[1]:
                if key == name:
                    return value
        raise RuntimeError(f"unknown menu property {name}")

    def _emit(self, path, interface, member, signature=None, body=()) -> None:
        from jeepney import HeaderFields, Message, MessageType
        from jeepney.wrappers import new_header

        header = new_header(MessageType.signal)
        header.fields[HeaderFields.path] = path
        header.fields[HeaderFields.interface] = interface
        header.fields[HeaderFields.member] = member
        if signature:
            header.fields[HeaderFields.signature] = signature
        try:
            self._conn.send(Message(header, body))
        except Exception as exc:
            logger.debug(f"Tray signal {member} failed: {exc}")


def _filter_layout(node, names):
    item_id, props, children = node
    return (item_id, _filter_props(props, names), children)


def _filter_props(props, names):
    if not names:
        return props
    wanted = set(names)
    return [entry for entry in props if entry[0] in wanted]


def _walk(node):
    yield node
    for _sig, child in node[2]:
        yield from _walk(child)


INTROSPECT_XML = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <property name="IconName" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
  </interface>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg type="i" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="as" direction="in"/>
      <arg type="u" direction="out"/>
      <arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="v" direction="in"/>
      <arg type="u" direction="in"/>
    </method>
  </interface>
</node>
"""
