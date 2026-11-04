# Optional Host Capabilities

JARVIS treats host-level input injection and neural TTS as **optional
capabilities**. Missing either one is a `WARN` in `jarvis doctor`, never
a required failure. The core CLI, screen reader, memory, policy engine,
and tests run without them.

| Capability | Doctor check | Default | Why it is optional |
| --- | --- | --- | --- |
| `ydotoold` | `computer:input` | off | needs write access to `/dev/uinput` |
| Chatterbox TTS | `voice:chatterbox` | off | ~8 GiB disk and slow CPU inference |

Neither capability bypasses policy. Screen text and model output remain
untrusted, and every input action is still a HIGH-risk, approval-gated
tool call.

---

## Input automation: `ydotoold` and `/dev/uinput`

`ydotool` needs a running `ydotoold` daemon, and the daemon needs write
access to `/dev/uinput`. On many distributions that device is root-only
(`crw------- root root`), so the daemon cannot start as your user.

Check the current state:

```bash
ls -l /dev/uinput
pgrep -af ydotoold || true
jarvis doctor | grep computer:input
```

### Root setup once

Use a **dedicated group** rather than the broad `input` group. Write
access to `/dev/uinput` allows arbitrary keyboard and mouse injection;
only accounts that need automation should be members.

```bash
# 1. Dedicated group and udev rule (root).
sudo groupadd --system uinput 2>/dev/null || true
sudo usermod -aG uinput "$USER"
sudo tee /etc/udev/rules.d/60-uinput.rules >/dev/null <<'EOF'
KERNEL=="uinput", GROUP="uinput", MODE="0660", OPTIONS+="static_node=uinput"
EOF

# 2. Load the module and re-apply the rule.
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput

# 3. Verify: crw-rw---- root uinput
ls -l /dev/uinput
```

Group membership only applies to new sessions. Log out and back in, or
start a temporary shell with `newgrp uinput`, before starting the daemon.

### Run the daemon as your user

`ydotoold` defaults to `$XDG_RUNTIME_DIR/.ydotool_socket`, which is also
what `ydotool` looks for. Do **not** enable the packaged system-wide
`ydotool.service`: it runs as root and creates a socket your user cannot
reach.

Foreground test:

```bash
ydotoold --socket-path="$XDG_RUNTIME_DIR/.ydotool_socket" \
         --socket-own="$(id -u):$(id -g)" &
ydotool type "hello"
```

Persistent systemd user unit:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/ydotoold.service <<'EOF'
[Unit]
Description=ydotool input daemon
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=/usr/bin/ydotoold --socket-path=%t/.ydotool_socket --socket-own=%U:%G
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service
systemctl --user status ydotoold.service --no-pager
jarvis doctor | grep computer:input
```

`%t` is the user runtime directory, so the socket matches ydotool's
default. Keep the socket at mode `0600` (the default); do not make it
world-writable.

### Revoke

```bash
systemctl --user disable --now ydotoold.service
sudo rm /etc/udev/rules.d/60-uinput.rules
sudo udevadm control --reload-rules
sudo gpasswd -d "$USER" uinput
```

If you do not need input automation, leaving this capability off is the
safer default. JARVIS reports it as an optional `WARN`.

---

## Chatterbox TTS

Chatterbox is a local neural voice. It is not installed by default
because it needs an isolated Python 3.12 runtime, CPU PyTorch, and
several gigabytes of cached model weights. On the reference 8 GB
CPU-only laptop, a short utterance can take tens of seconds.

The fallback chain is:

```
Chatterbox (persistent or bridge) → espeak/piper → text-only
```

### Install

`uv` is the recommended way to keep this out of the project `.venv` and
the system Python:

```bash
# User-space uv install, no root.
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Isolated runtime.
uv venv ~/.config/jarvis/chatterbox-venv --python 3.12
uv pip install --torch-backend cpu \
  --python ~/.config/jarvis/chatterbox-venv/bin/python chatterbox-tts

# Runtime fix: perth imports pkg_resources.
uv pip install --python ~/.config/jarvis/chatterbox-venv/bin/python \
  "setuptools<81"
```

Fetch the reference voice and verify the bridge:

```bash
jarvis voice setup
jarvis voice status
jarvis say "Voice online"
jarvis doctor | grep voice:chatterbox
```

The first synthesis may download model weights (roughly 6 GiB) and load
the model before speaking. JARVIS reports `direct`, `bridge`, or
`unavailable` honestly; it never silently switches voices or crashes
when the runtime is missing.

Override the interpreter path if you installed elsewhere:

```bash
export JARVIS_CHATTERBOX_PYTHON="$HOME/.config/jarvis/chatterbox-venv/bin/python"
```

### Remove

```bash
rm -rf ~/.config/jarvis/chatterbox-venv
# Optional: remove cached weights.
rm -rf ~/.cache/huggingface/hub/models--resemble-ai--chatterbox
jarvis doctor
```

### Safety

- TTS synthesizes validated text only. It cannot execute tools, devices,
  or memory operations.
- Reference audio and generated WAVs are local; no cloud TTS is used.
- Transcripts remain untrusted input. Speaking a transcript is not
  authorization to act on it.
- Keep the runtime isolated. Do not install PyTorch or Chatterbox into
  the project `.venv` or the system Python.
