# Screen Understanding (No Model Required)

JARVIS can answer "what is on my screen right now?" without a vision
model. The fast path reads the desktop's **accessibility tree** through
AT-SPI, adds X11 window metadata when available, and optionally runs
Tesseract OCR. A vision model remains optional for semantic scene
description; it is not required to read labels, buttons, terminal text,
or the focused control.

## Quick use

```bash
jarvis screen                 # compact, human-readable snapshot
jarvis screen --json          # full structured snapshot
jarvis screen --ocr           # also OCR a screenshot
jarvis screen --system-ui     # include GNOME Shell / portal trees
```

The same capability is exposed to agents as the read-only
`screen_understand` tool:

```json
{"tool": "screen_understand", "args": {"include_ocr": false}}
```

Required permission: `desktop.accessibility`. Risk: **SAFE** (read-only,
no input, no focus changes). It is granted to the `computer` actor and
to the front-door `jarvis` actor; it never authorizes clicks or typing.

## What it reads

| Source | Data |
| --- | --- |
| AT-SPI | application names, windows, roles, labels, buttons, entry text, terminal viewport text, focused element |
| `wmctrl` | X11/XWayland window ids, desktops, titles (empty on native Wayland) |
| Tesseract (opt-in) | pixel text from a screenshot, including apps that expose no accessibility tree |

The reader walks each application tree depth-first. Infrastructure apps
(`gnome-shell`, IBus, desktop portals) are skipped by default because
they add clock/panel noise; use `--system-ui` to include them.

## Safety and privacy

- **Password fields are never read.** A password role or a
  `text-input-type=password` attribute is replaced with
  `[password field]`, and traversal stops at that node.
- **Credential-shaped text is scrubbed** with the same secret-span
  scrubbing used by security findings (`token=...`, `api_key=...`,
  bearer tokens, URL userinfo, PEM/AWS/GitHub/Slack spans).
- **Everything is bounded**: 12 apps, depth 24, 600 nodes per app,
  1500 nodes total, 240 elements total, 400 characters per node,
  8000 characters total, and a 2.5 s time budget. Hitting a bound sets
  `stats.truncated` or `stats.timed_out`; it never silently grows.
- **OCR screenshots are deleted immediately** after text extraction; no
  image is retained by this path.
- **Screen text is untrusted input.** It is evidence about what is
  visible, never an instruction and never permission to act. Any action
  derived from it still goes through intent → policy → approval →
  the existing command path.

## Limits

- AT-SPI only sees applications that expose an accessibility tree.
  Electron/Chromium apps may need accessibility enabled; games and
  custom canvases usually expose nothing.
- Terminal text is the visible viewport, not scrollback.
- Native Wayland windows are not listed by `wmctrl`; AT-SPI is the
  primary source there.
- Screenshot OCR on GNOME/Wayland uses the XWayland layer unless a
  portal grants full-desktop capture. The result reports that scope
  honestly instead of pretending it saw the whole compositor.
- There is no scene graph, object detection, or visual reasoning in this
  path. Those are optional model capabilities.

## Optional vision model

The local vision default is **`qwen3-vl:2b`** (about 1.9 GB), chosen for
an 8 GB CPU-only laptop. It adds semantic scene description on top of
the deterministic reader:

```bash
ollama pull qwen3-vl:2b
jarvis see screen            # OCR + scene description
jarvis see screen --fast     # OCR only, no scene model
```

The model is never required for `jarvis screen`, `screen_understand`,
or the accessibility/OCR fast paths.

On this 8 GB CPU-only laptop, a 640x240 probe with a one-sentence
answer took about **105 seconds** with `qwen3-vl:2b`. Use `jarvis screen`
or `jarvis see screen --fast` when latency matters; reserve the scene
model for explicit semantic questions.
