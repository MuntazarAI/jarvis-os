"""Model-free screen reader: bounds, password skip, scrubbing, opt-in OCR."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.computer.computer import ComputerController, computer_tools  # noqa: E402
from jarvis.computer.screen_reader import ScreenReader  # noqa: E402
from jarvis.core.types import RiskLevel  # noqa: E402


class _State:
    def __init__(self, *flags):
        self.flags = set(flags)

    def contains(self, flag):
        return flag in self.flags


class _Text:
    def __init__(self, text):
        self._text = text
        self.characterCount = len(text)

    def getText(self, start, end):
        return self._text[start:end]


class FakeNode:
    def __init__(self, role, name="", text="", children=None, *,
                 attributes=None, value=None):
        self.role = role
        self.name = name
        self._text = text
        self._children = list(children or [])
        self.childCount = len(self._children)
        self._attributes = attributes or {}
        self._value = value
        self._state = _State()

    def getRoleName(self):
        return self.role

    def getChildAtIndex(self, index):
        return self._children[index]

    def queryText(self):
        return _Text(self._text) if self._text else None

    def queryValue(self):
        return type("Value", (), {"currentValue": self._value})()

    def getAttributes(self):
        return self._attributes

    def getState(self):
        return self._state


class FakeDesktop:
    def __init__(self, apps):
        self.apps = list(apps)
        self.childCount = len(self.apps)

    def getChildAtIndex(self, index):
        return self.apps[index]


def _demo_app():
    return FakeNode(
        "application", "demo", children=[
            FakeNode("frame", "Demo — Editor", children=[
                FakeNode("terminal", "Terminal", text="hello\nworld"),
                FakeNode("button", "Save"),
                FakeNode("entry", "Search", text="visible query"),
                FakeNode("password text", "Password", text="hunter2"),
            ]),
        ])


def test_read_collects_roles_text_and_windows():
    reader = ScreenReader(desktop=FakeDesktop([_demo_app()]))
    out = reader.read()
    assert out["ok"] and out["untrusted"]
    app = out["apps"][0]
    assert app["name"] == "demo"
    assert app["windows"] == ["Demo — Editor"]
    by_role = {}
    for element in app["elements"]:
        by_role.setdefault(element["role"], []).append(element)
    assert by_role["terminal"][0]["text"] == "hello\nworld"
    assert by_role["button"][0]["name"] == "Save"
    assert by_role["entry"][0]["text"] == "visible query"
    assert out["stats"]["passwords_skipped"] == 1


def test_password_content_never_leaves_reader():
    reader = ScreenReader(desktop=FakeDesktop([_demo_app()]))
    dumped = json.dumps(reader.read())
    assert "hunter2" not in dumped
    assert "password field" in dumped


def test_password_attribute_also_skips_content():
    node = FakeNode("entry", "PIN", text="1234",
                    attributes={"text-input-type": "password"})
    reader = ScreenReader(desktop=FakeDesktop([
        FakeNode("application", "demo", children=[node])]))
    dumped = json.dumps(reader.read())
    assert "1234" not in dumped
    assert "password field" in dumped


def test_secret_shapes_are_scrubbed():
    app = FakeNode("application", "demo", children=[
        FakeNode("label", "credentials", text="token=abc123 api_key=sk-xyz"),
    ])
    reader = ScreenReader(desktop=FakeDesktop([app]))
    dumped = json.dumps(reader.read())
    assert "abc123" not in dumped
    assert "sk-xyz" not in dumped
    assert "[redacted]" in dumped


def test_ocr_is_opt_in_and_scrubbed():
    class Capture:
        def capture(self, path):
            return {"ok": True, "path": path, "scope": "test"}

    class OCR:
        def read(self, path):
            return {"ok": True, "text": "screen token=abc123", "backend": "fake"}

    reader = ScreenReader(desktop=FakeDesktop([_demo_app()]),
                          capture=Capture(), ocr=OCR())
    assert reader.read()["ocr"]["requested"] is False
    ocr = reader.read(include_ocr=True)["ocr"]
    assert ocr["ok"] and "screen" in ocr["text"]
    assert "abc123" not in ocr["text"]


def test_bounds_stop_runaway_tree():
    deep = FakeNode("text", "leaf", text="x" * 500)
    for index in range(20):
        deep = FakeNode("panel", children=[
            FakeNode("label", f"label-{index}"),
            deep,
        ])
    app = FakeNode("application", "demo", children=[deep])
    reader = ScreenReader(desktop=FakeDesktop([app]))
    reader.max_depth = 3
    reader.max_elements_per_app = 2
    reader.max_nodes_per_app = 5
    out = reader.read()
    assert out["stats"]["truncated"]
    assert out["stats"]["nodes"] <= 5
    assert len(out["apps"][0]["elements"]) <= 2


def test_infra_apps_are_excluded_by_default():
    apps = [
        FakeNode("application", "gnome-shell", children=[
            FakeNode("window", "Main stage", children=[FakeNode("label", "Clock")])]),
        _demo_app(),
    ]
    reader = ScreenReader(desktop=FakeDesktop(apps))
    assert [app["name"] for app in reader.read()["apps"]] == ["demo"]
    names = [app["name"] for app in reader.read(include_system_ui=True)["apps"]]
    assert names == ["gnome-shell", "demo"]


def test_unavailable_atspi_is_reported():
    reader = ScreenReader(desktop=FakeDesktop([]))
    with patch.object(ScreenReader, "_apps", side_effect=RuntimeError("no bus")):
        out = reader.read()
    assert not out["ok"]
    assert "AT-SPI unavailable" in out["error"]


def test_summary_is_bounded_and_readable():
    reader = ScreenReader(desktop=FakeDesktop([_demo_app()]))
    text = reader.summary(reader.read())
    assert "demo — Demo — Editor" in text
    assert "terminal: hello" in text


def test_screen_understand_tool_is_registered_and_read_only():
    tools = {tool.spec.name: tool for tool in computer_tools()}
    spec = tools["screen_understand"].spec
    assert spec.risk == RiskLevel.SAFE
    assert "desktop.accessibility" in spec.required_permissions
    status = ComputerController().status()
    assert "accessibility" in status
