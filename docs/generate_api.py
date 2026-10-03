"""Deterministic API reference generator (stdlib only, offline).

Walks the boundary modules listed in MODULES, extracts public classes,
functions, and their docstring summaries, and writes sorted Markdown
into docs/api/. No timestamps, no absolute paths, no network — two runs
produce byte-identical output.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

MODULES = [
    "jarvis.cli",
    "jarvis.core.config",
    "jarvis.core.service",
    "jarvis.voice.tts",
    "jarvis.voice.speak",
    "jarvis.voice.voice_profile",
    "jarvis.neural.scale",
    "jarvis.neural.topology",
    "jarvis.neural.temporal_bench",
    "jarvis.neural.prototypes",
    "jarvis.device.fabric",
    "jarvis.policy.policy",
    "jarvis.intelligence.loop",
    "jarvis.cognition.goals",
    "jarvis.api",
]


def _summary(obj: object) -> str:
    doc = inspect.getdoc(obj) or ""
    first = doc.splitlines()[0].strip() if doc.strip() else ""
    home = os.path.expanduser("~")
    return first.replace(home, "~")


def render_module(name: str) -> str:
    module = __import__(name, fromlist=["*"])
    lines = [f"# `{name}`", ""]
    members = sorted(
        ((key, value) for key, value in vars(module).items()
         if not key.startswith("_")
         and (inspect.isclass(value) or inspect.isfunction(value))
         and getattr(value, "__module__", name) == module.__name__),
        key=lambda item: item[0])
    if not members:
        lines.append("_No public classes/functions defined here._")
        return "\n".join(lines) + "\n"
    lines.append("## Members")
    lines.append("")
    for key, value in members:
        kind = "class" if inspect.isclass(value) else "function"
        lines.append(f"### `{key}` ({kind})")
        summary = _summary(value)
        lines.append("")
        lines.append(summary if summary else "_No docstring._")
        lines.append("")
    return "\n".join(lines)


def generate(out_dir: str | Path) -> list[str]:
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in sorted(MODULES):
        try:
            text = render_module(name)
        except Exception as exc:
            text = f"# `{name}`\n\n_Undocumented: {type(exc).__name__}_\n"
        path = dest / (name + ".md")
        path.write_text(text, encoding="utf-8")
        written.append(str(path))
    index = ["# API Reference (generated)", "",
             "Deterministic output of `docs/generate_api.py`.", ""]
    for name in sorted(MODULES):
        index.append(f"- [`{name}`](./{name}.md)")
    (dest / "index.md").write_text("\n".join(index) + "\n",
                                   encoding="utf-8")
    written.append(str(dest / "index.md"))
    return sorted(written)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs" / "api"
    for path in generate(target):
        print(path)
