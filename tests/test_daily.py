"""Daily-driver workflow tests."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.loop import Jarvis  # noqa: E402
from jarvis.workflows.daily import (  # noqa: E402
    continue_project,
    explain_error,
    remember_this,
    run_tests,
    what_am_i_working_on,
    what_changed_since,
)


def _jarvis():
    return Jarvis(home=tempfile.mkdtemp())


def test_status_and_continue():
    j = _jarvis()
    try:
        j.cycle_once("remember my editor is helix")
        j.cycle_once("working on voice loop today")
        status = j.cycle_once("what am i working on?")
        assert "voice" in status.response.lower() or "helix" in status.response.lower()
        assert "cycle 3" not in status.response
        cont = j.cycle_once("continue my project")
        assert "helix" in cont.response.lower() or "voice" in cont.response.lower()
    finally:
        j.close()


def test_changes_and_explain():
    j = _jarvis()
    try:
        j.cycle_once("remember deploy key rotates monthly")
        changes = what_changed_since(j, hours=1.0)
        assert changes["memory_events"]
        report = explain_error(j, "permission denied writing log")
        assert report["likely_cause"] == "permission"
        assert report["suggested_fix"]
        via_loop = j.cycle_once("explain this error: permission denied writing log")
        assert "permission" in via_loop.response.lower()
    finally:
        j.close()


def test_remember_and_continue_api():
    j = _jarvis()
    try:
        stored = remember_this(j, "staging deploys on fridays")
        assert stored["ok"] and stored["room"] == "Knowledge Library"
        state = continue_project(j, "staging")
        assert state["recent_work"] or state["decisions"]
        status = what_am_i_working_on(j)
        assert status["summary"]
    finally:
        j.close()


def test_run_tests_policy_gated():
    j = _jarvis()
    try:
        report = run_tests(j, ".")
        # Either runs (ok) or asks approval — never executes blind.
        assert report.get("ok") in (True, False)
        if report.get("ok"):
            assert "passed" in report
        else:
            assert report.get("needs_approval") or report.get("error")
    finally:
        j.close()
