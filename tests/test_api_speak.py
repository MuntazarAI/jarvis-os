"""The speak and approval endpoints.

The office page is gone; these APIs are what an interface would use.
"""

import json
from types import SimpleNamespace

from jarvis.api.server import JarvisAPI


class _Bus:
    def subscribe(self, *a, **k):
        return True


def _api(token=""):
    fake = SimpleNamespace(
        bus=_Bus(), cycle=0,
        config=SimpleNamespace(
            paths=SimpleNamespace(home=""),
            voice=SimpleNamespace(), world=None))
    return JarvisAPI(fake, token=token)


def test_speak_endpoint():
    from types import SimpleNamespace as NS
    from jarvis.api.server import JarvisAPI as API
    fake = NS(bus=_Bus(), cycle=0,
              config=NS(paths=NS(home=""),
                        voice=NS(tts_provider="fake", language="en",
                                 reference_audio="", sample_rate=24000),
                        world=None))
    api = API(fake, token="tok")
    code, _ = api.handle("POST", "/api/speak",
                         json.dumps({"text": "hi"}).encode(), {})
    assert code == 401
    auth = {"authorization": "Bearer tok"}
    code, _ = api.handle("POST", "/api/speak", b"{}", auth)
    assert code == 400  # missing text
    code, _ = api.handle("POST", "/api/speak", b"nope", auth)
    assert code == 400
    code, out = api.handle(
        "POST", "/api/speak",
        json.dumps({"text": "hello there"}).encode(), auth)
    assert code == 200
    assert out["ctype"] == "audio/wav"
    assert out["__audio__"][:4] == b"RIFF"  # real wav bytes
    code, _ = api.handle(
        "POST", "/api/speak",
        json.dumps({"text": "x" * 501}).encode(), auth)
    assert code == 400  # bounded input


def test_speak_audio_over_http():
    import urllib.request
    from types import SimpleNamespace as NS
    from jarvis.api.server import JarvisAPI as API
    fake = NS(bus=_Bus(), cycle=0,
              config=NS(paths=NS(home=""),
                        voice=NS(tts_provider="fake", language="en",
                                 reference_audio="", sample_rate=24000),
                        world=None))
    api = API(fake, host="127.0.0.1", port=0, token="")
    api.serve_forever()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{api.port}/api/speak",
            data=json.dumps({"text": "hi"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "audio/wav"
            assert resp.read(4) == b"RIFF"
    finally:
        api.shutdown()


def test_pending_endpoint_gated_and_shaped():
    from jarvis.api.server import JarvisAPI as API
    from types import SimpleNamespace as NS

    policy = NS(approvals={
        "appr-full-secret-1": {"actor": "computer", "action": "restart",
                               "args": {"service": "camera",
                                        "token": "never-show",
                                        "command": "restart --password=hunter2"},
                               "risk": 0.8, "requested_at": 1.0,
                               "status": "pending"},
        "appr-old": {"actor": "x", "action": "y",
                     "status": "approved"}})
    fake = NS(bus=_Bus(), cycle=0,
              config=NS(paths=NS(home=""), voice=NS(), world=None),
              policy=policy,
              events=NS(record=lambda *a, **k: None))
    api = API(fake, token="tok")
    code, _ = api.handle("GET", "/api/approvals/pending", b"", {})
    assert code == 401  # bearer gate holds: no leak, ever
    code, out = api.handle("GET", "/api/approvals/pending", b"", {
        "authorization": "Bearer tok"})
    assert code == 200
    assert len(out["approvals"]) == 1  # only pending
    assert out["approvals"][0]["token"] == "appr-full-secret-1"
    assert out["approvals"][0]["action"] == "restart"
    args = out["approvals"][0]["args"]
    assert args["service"] == "camera"
    assert args["token"] == "[redacted]"
    assert "hunter2" not in args["command"]


