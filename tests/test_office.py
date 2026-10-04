"""Office floor page: MD design tokens, live data, honesty mapping."""

from types import SimpleNamespace

from jarvis.api.office_page import OFFICE_HTML
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


def test_office_route_is_public_shell():
    api = _api(token="tok")
    code, payload = api.handle("GET", "/office", b"", {})
    assert code == 200
    assert payload["__html__"].startswith("<!DOCTYPE html>")


def test_office_design_tokens_and_honesty():
    for token in ("#FFF8E7", "#1A1320", "#FFD93D", "#4ECDC4",
                  "Press Start 2P", "Pixelify Sans", "VT323"):
        assert token in OFFICE_HTML, token
    assert "HONESTY MAPPING" in OFFICE_HTML
    assert "api/experience" in OFFICE_HTML
    assert "sessionStorage" in OFFICE_HTML


def test_office_hygiene():
    lowered = OFFICE_HTML.lower()
    assert "src=\"http" not in lowered
    # Sole external exception: MD-spec Google Fonts, with system
    # fallbacks so the page works fully offline.
    hrefs = [line for line in lowered.splitlines()
             if "href=\"http" in line]
    assert hrefs and all("fonts.g" in line for line in hrefs), hrefs
    assert "system-ui" in lowered and "monospace" in lowered
    assert "token_hint" not in OFFICE_HTML  # pasted only, never shown
    assert "alert(" not in lowered  # no demo popups


def test_office_post_has_no_route():
    api = _api()
    code, _ = api.handle("POST", "/office", b"{}", {})
    assert code == 404


def test_pending_endpoint_gated_and_shaped():
    from jarvis.api.server import JarvisAPI as API
    from types import SimpleNamespace as NS

    policy = NS(approvals={
        "appr-full-secret-1": {"actor": "computer", "action": "restart",
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


def test_office_has_approval_modal():
    from jarvis.api.office_page import OFFICE_HTML
    assert "appr-modal" in OFFICE_HTML
    assert "api/approvals/pending" in OFFICE_HTML
    assert "api/approvals/decision" in OFFICE_HTML
