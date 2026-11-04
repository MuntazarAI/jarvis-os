"""Doctor output semantics: only required gaps are failures."""

from jarvis.cli import _doctor_mark
from jarvis.core.service import EXPECTED_OLLAMA_MODELS, HealthCheck
from jarvis.models.ollama import OllamaConfig


def test_required_failure_is_fail():
    check = HealthCheck("python", False, "missing", required=True)
    assert _doctor_mark(check) == "FAIL"


def test_optional_gap_is_warn_not_fail():
    check = HealthCheck("bin:tesseract", False, "missing", required=False)
    assert _doctor_mark(check) == "WARN"


def test_passing_check_is_ok_even_if_required():
    check = HealthCheck("python", True, "3.12", required=True)
    assert _doctor_mark(check) == "ok "


def test_expected_vision_model_is_qwen3_vl_2b():
    assert "qwen3-vl:2b" in EXPECTED_OLLAMA_MODELS
    assert not any("minicpm" in model for model in EXPECTED_OLLAMA_MODELS)
    assert OllamaConfig().vision_model == "qwen3-vl:2b"
