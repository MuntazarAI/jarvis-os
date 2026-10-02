"""Tests for the God's Eye View application lifecycle manager."""

from jarvis.geospatial.application import GodsEyeApplication, GodsEyeApplicationConfig


def test_application_defaults_to_jarvis_home(tmp_path):
    app = GodsEyeApplication(home=tmp_path)
    assert app.workspace == tmp_path / "apps" / "gods-eye-view"
    assert app.url == "http://127.0.0.1:4173"
    assert app.status()["installed"] is False
    assert app.status()["running"] is False


def test_start_requires_install(tmp_path):
    app = GodsEyeApplication(home=tmp_path)
    try:
        app.start()
        raise AssertionError("start must require an installed checkout")
    except RuntimeError as exc:
        assert "not installed" in str(exc)


def test_nonempty_workspace_is_not_overwritten(tmp_path):
    workspace = tmp_path / "gev"
    workspace.mkdir()
    (workspace / "important.txt").write_text("keep me", encoding="utf-8")
    app = GodsEyeApplication(
        home=tmp_path,
        config=GodsEyeApplicationConfig(workspace=str(workspace)),
    )
    try:
        app.install()
        raise AssertionError("install must refuse a non-empty non-git directory")
    except RuntimeError as exc:
        assert "not an empty git checkout" in str(exc)


def test_status_exposes_local_metadata(tmp_path):
    app = GodsEyeApplication(home=tmp_path)
    status = app.status()
    assert status["repo"].endswith("gods-eye-view.git")
    assert status["workspace"] == str(tmp_path / "apps" / "gods-eye-view")
    assert status["log"].endswith("gods-eye-view.log")
