"""Chatterbox out-of-process bridge (5.1).

Run under the dedicated Chatterbox interpreter
(`~/.config/jarvis/chatterbox-venv/bin/python`), NOT system Python:

    chatterbox-venv/bin/python -m jarvis.voice.chatterbox_bridge \\
        request.json out.wav

Reads the JSON request, synthesizes with the local Chatterbox model
+ reference voice, writes the wav, prints ONE JSON result line on
stdout (warnings stay on stderr). The caller (`ChatterboxTTSProvider`)
enforces timeouts and bounds; this helper never executes anything but
synthesis.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from pathlib import Path

MAX_TEXT_CHARS = 2000


def _fail(request_id: str, error: str) -> dict:
    return {"request_id": request_id, "status": "failed",
            "error": error[:300]}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(json.dumps(_fail("", "usage: chatterbox_bridge "
                                  "request.json out.wav")))
        return 2
    try:
        request = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps(_fail("", f"bad request: {exc}")))
        return 2
    request_id = str(request.get("request_id", ""))
    text = str(request.get("text", ""))
    if not text.strip() or len(text) > MAX_TEXT_CHARS:
        print(json.dumps(_fail(request_id, "text empty or too long")))
        return 2
    ref = str(request.get("reference_audio", ""))
    if not ref or not Path(ref).expanduser().exists():
        print(json.dumps(_fail(
            request_id, "reference voice missing; run: "
                        "jarvis voice setup")))
        return 0
    out_path = Path(argv[2])
    started = time.perf_counter()
    try:
        model_name = str(request.get("model", "chatterbox"))
        if "turbo" in model_name.lower():
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            cls = ChatterboxTurboTTS
        else:
            from chatterbox.tts import ChatterboxTTS
            cls = ChatterboxTTS
        device = str(request.get("device", "cpu"))
        try:
            engine = cls.from_pretrained(device=device)
        except TypeError:
            engine = cls.from_pretrained()
        params = set(inspect.signature(engine.generate).parameters)
        candidates = {
            "audio_prompt_path": str(Path(ref).expanduser()),
            "reference_audio": str(Path(ref).expanduser()),
            "exaggeration": float(request.get("exaggeration", 0.5)),
            "temperature": float(request.get("temperature", 0.8)),
            "cfg_weight": float(request.get("cfg_weight", 0.5)),
            "cfg": float(request.get("cfg_weight", 0.5)),
        }
        kwargs = {k: v for k, v in candidates.items() if k in params}
        wav = engine.generate(text, **kwargs)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        rate = int(getattr(engine, "sr", 24000))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import torch
            import torchaudio
            torchaudio.save(str(out_path), wav.cpu()
                            if hasattr(wav, "cpu") else wav, rate)
        except Exception:
            import wave
            import numpy as np
            arr = np.asarray(
                wav.cpu().numpy() if hasattr(wav, "cpu") else wav)
            with wave.open(str(out_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes((arr * 32767).astype("<i2").tobytes())
        import numpy as _np
        arr = _np.asarray(wav.cpu().numpy()
                          if hasattr(wav, "cpu") else wav)
        duration = round(float(arr.size / max(rate, 1)), 3)
        print(json.dumps({
            "request_id": request_id, "status": "success",
            "audio_path": str(out_path), "audio_bytes": int(arr.nbytes),
            "duration_s": duration, "sample_rate": rate,
            "latency_ms": latency_ms,
            "metadata": {"model": model_name, "local": True,
                         "mode": "bridge"}}))
        return 0
    except Exception as exc:
        print(json.dumps(_fail(
            request_id, f"{type(exc).__name__}: {exc}")))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
