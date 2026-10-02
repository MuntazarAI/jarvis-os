from examples.plugins.hello_plugin import HelloPlugin
from jarvis.plugins import PluginRequest


def test_plugin_health():
    assert HelloPlugin().health() == {"status": "ok", "plugin": "hello"}


def test_plugin_handles_typed_operation():
    response = HelloPlugin().handle(
        PluginRequest(operation="hello.greet", payload={"name": "JARVIS"})
    )
    assert response.ok
    assert response.data["message"] == "Hello, JARVIS!"


def test_plugin_rejects_unknown_operation():
    response = HelloPlugin().handle(PluginRequest(operation="shell.exec"))
    assert not response.ok
