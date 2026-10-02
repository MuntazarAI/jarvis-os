"""Minimal JARVIS-OS plugin example."""

from jarvis.plugins import Plugin, PluginRequest, PluginResponse


class HelloPlugin(Plugin):
    name = "hello"
    version = "0.1.0"
    description = "A minimal example plugin."
    capabilities = ("hello.greet",)

    def health(self) -> dict[str, str]:
        return {"status": "ok", "plugin": self.name}

    def handle(self, request: PluginRequest) -> PluginResponse:
        if request.operation != "hello.greet":
            return PluginResponse(ok=False, error="unsupported operation")
        name = str(request.payload.get("name", "JARVIS"))
        return PluginResponse(ok=True, data={"message": f"Hello, {name}!"})
