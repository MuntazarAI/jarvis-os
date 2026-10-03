"""Persistent Chatterbox worker (5.2). Runs under the DEDICATED Python
3.12 interpreter — never system Python:

    chatterbox-venv/bin/python -m jarvis.voice.tts_worker \\
        --workdir DIR --model chatterbox-turbo --reference REF.flac

Authority is intentionally tiny: read one JSON request line on stdin,
run Chatterbox, validate the wav, write ONE JSON response line on
stdout. stdout carries protocol lines ONLY (diagnostics go to stderr).

The worker never: executes shell, imports by request, touches the
network deliberately, reads files outside --workdir + --reference,
writes outside --workdir, or spawns anything. Options are validated
numbers/strings from a closed set — never behavior switches.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
from pathlib import Path

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 64 * 1024
MAX_TEXT_CHARS = 2000
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_AUDIO_S = 120.0
KNOWN_MODELS = ("chatterbox", "chatterbox-turbo")
ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def _valid_id(value: object) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 64
            and all(c in ID_CHARS for c in value))


def _error(request_id: str, error: str, state: str) -> dict:
    return {"v": PROTOCOL_VERSION, "id": request_id, "status": "error",
            "error": str(error)[:300], "worker_state": state}


def _rss_kb() -> int:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


class Worker:
    def __init__(self, workdir: Path, model: str, reference: str,
                 device: str = "cpu") -> None:
        self.workdir = workdir
        self.model = model
        self.reference = reference
        self.device = device
        self.state = "STARTING"
        self.engine: object = None
        self.sample_rate = 24000
        self.load_count = 0
        self.started_at = time.monotonic()
        self.ok_count = 0
        self.fail_count = 0

    def load(self) -> None:
        self.state = "LOADING"
        if "turbo" in self.model:
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            cls = ChatterboxTurboTTS
        elif self.model == "chatterbox":
            from chatterbox.tts import ChatterboxTTS
            cls = ChatterboxTTS
        else:
            raise ValueError(f"unknown model: {self.model}")
        try:
            self.engine = cls.from_pretrained(device=self.device)
        except TypeError:
            self.engine = cls.from_pretrained()
        generate = getattr(self.engine, "generate", None)
        self._params = (set(inspect.signature(generate).parameters)
                        if generate is not None else set())
        self.sample_rate = int(getattr(self.engine, "sr", 24000))
        self.load_count += 1
        self.state = "READY"

    def _validate_request(self, raw: object) -> tuple[dict | None, dict]:
        if not isinstance(raw, dict):
            return None, _error("", "request must be an object",
                                self.state)
        if raw.get("v") != PROTOCOL_VERSION:
            return None, _error(str(raw.get("id", ""))[:64],
                                 "unknown protocol version", self.state)
        request_id = raw.get("id", "")
        if not _valid_id(request_id):
            return None, _error("", "invalid request id", self.state)
        op = raw.get("op", "")
        if op not in ("synthesize", "health", "shutdown"):
            return None, _error(request_id, "unknown operation",
                                self.state)
        return {"id": request_id, "op": op,
                "payload": raw}, {"v": PROTOCOL_VERSION}

    def _synthesize(self, request_id: str, payload: dict) -> dict:
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip() \
                or len(text) > MAX_TEXT_CHARS:
            return _error(request_id, "text empty or too long",
                          self.state)
        try:
            exaggeration = float(payload.get("exaggeration", 0.5))
            temperature = float(payload.get("temperature", 0.8))
            cfg_weight = float(payload.get("cfg_weight", 0.5))
        except (TypeError, ValueError):
            return _error(request_id, "invalid numeric options",
                          self.state)
        if not (0.0 <= exaggeration <= 1.0
                and 0.0 <= temperature <= 2.0
                and 0.0 <= cfg_weight <= 1.0):
            return _error(request_id, "options out of range",
                          self.state)
        self.state = "BUSY"
        started = time.perf_counter()
        try:
            candidates = {
                "audio_prompt_path": self.reference,
                "reference_audio": self.reference,
                "exaggeration": exaggeration,
                "temperature": temperature,
                "cfg_weight": cfg_weight,
                "cfg": cfg_weight,
            }
            kwargs = {k: v for k, v in candidates.items()
                      if k in self._params}
            # Third-party code prints banners/progress to stdout
            # (perth, S3 tokenizers). The pipe carries protocol lines
            # only, so stdout stays suppressed for the whole call.
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                wav = self.engine.generate(text, **kwargs)
            latency_ms = round(
                (time.perf_counter() - started) * 1000.0, 2)
            import numpy as _np
            arr = _np.asarray(wav.cpu().numpy()
                              if hasattr(wav, "cpu") else wav)
            duration = float(arr.size / max(self.sample_rate, 1))
            if arr.size == 0 or duration <= 0.0 \
                    or duration > MAX_AUDIO_S:
                return _error(request_id, "invalid audio produced",
                              self.state)
            out_path = self.workdir / f"req-{request_id}.wav"
            try:
                import torch
                import torchaudio
                torchaudio.save(str(out_path), wav.cpu()
                                if hasattr(wav, "cpu") else wav,
                                self.sample_rate)
            except Exception:
                import wave
                with wave.open(str(out_path), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(self.sample_rate)
                    handle.writeframes(
                        (arr * 32767).astype("<i2").tobytes())
            size = out_path.stat().st_size
            if size <= 0 or size > MAX_AUDIO_BYTES:
                try:
                    out_path.unlink()
                except OSError:
                    pass
                return _error(request_id, "invalid audio file",
                              self.state)
            self.ok_count += 1
            return {"v": PROTOCOL_VERSION, "id": request_id,
                    "status": "ok", "audio_path": str(out_path),
                    "audio_bytes": size,
                    "duration_s": round(duration, 3),
                    "sample_rate": self.sample_rate,
                    "latency_ms": latency_ms,
                    "worker_state": "READY"}
        except Exception as exc:
            self.fail_count += 1
            return _error(request_id,
                          f"{type(exc).__name__}: {exc}", self.state)
        finally:
            if self.state == "BUSY":
                self.state = "READY"

    def _health(self, request_id: str) -> dict:
        return {"v": PROTOCOL_VERSION, "id": request_id, "status": "ok",
                "worker_state": self.state, "model": self.model,
                "protocol": PROTOCOL_VERSION,
                "load_count": self.load_count,
                "ok_count": self.ok_count,
                "fail_count": self.fail_count,
                "uptime_s": round(time.monotonic() - self.started_at, 1),
                "rss_kb": _rss_kb()}

    def handle_line(self, line: bytes) -> dict | None:
        """Process one request line. Returns response dict, or None to
        signal the worker should exit (shutdown op)."""
        if len(line) > MAX_LINE_BYTES:
            return _error("", "request too large", self.state)
        try:
            raw = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _error("", "malformed request", self.state)
        parsed, marker = self._validate_request(raw)
        if parsed is None:
            return marker
        request_id = parsed["id"]
        op = parsed["op"]
        if op == "shutdown":
            return None
        if op == "health":
            return self._health(request_id)
        return self._synthesize(request_id, parsed["payload"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tts_worker")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--model", default="chatterbox-turbo")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir)
    if not workdir.is_dir():
        print(json.dumps(_error("", "workdir missing", "FAILED")),
              flush=True)
        return 2
    if args.model not in KNOWN_MODELS:
        print(json.dumps(_error("", "unknown model", "FAILED")),
              flush=True)
        return 2
    reference = str(Path(args.reference).expanduser())
    if not Path(reference).exists():
        print(json.dumps(_error("", "reference voice missing; run: "
                                    "jarvis voice setup", "FAILED")),
              flush=True)
        return 2
    worker = Worker(workdir, args.model, reference, args.device)
    try:
        # Third-party libraries (perth, diffusers) print banners to
        # stdout on import. Swallow stdout during load so the boot
        # line is the first protocol line on the pipe; stderr is
        # untouched for real diagnostics.
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            worker.load()
    except Exception as exc:
        print(json.dumps(_error(
            "", f"model load failed: {type(exc).__name__}",
            "FAILED")), flush=True)
        return 3
    print(json.dumps({"v": PROTOCOL_VERSION, "id": "boot",
                      "status": "ready",
                      "worker_state": worker.state,
                      "model": worker.model,
                      "protocol": PROTOCOL_VERSION,
                      "load_count": worker.load_count}), flush=True)
    stdin = sys.stdin.buffer
    while True:
        line = stdin.readline(MAX_LINE_BYTES + 4096)
        if not line:
            return 0  # EOF: graceful exit
        response = worker.handle_line(line.strip())
        if response is None:
            print(json.dumps({"v": PROTOCOL_VERSION, "id": "bye",
                              "status": "ok",
                              "worker_state": "SHUTDOWN"}), flush=True)
            return 0
        print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
