"""
CLI Completions — JARVIS-OS shell completion support.

Provides bash, zsh, and fish completion scripts for the jarvis CLI.
"""

from __future__ import annotations

import argparse
from typing import Any


def generate_bash_completion(parser: argparse.ArgumentParser) -> str:
    """Generate bash completion script."""
    return (
        "# JARVIS-OS CLI bash completion\n"
        "_jarvis_completion() {\n"
        "    local cur prev opts\n"
        "    COMPREPLY=()\n"
        "    cur=\"${COMP_WORDS[COMP_CWORD]}\"\n"
        "    prev=\"${COMP_WORDS[COMP_CWORD-1]}\"\n"
        "\n"
        "    opts=\"talk repl serve board remote command office status status-summary proof feedback setup gods-eye mentalist remember consolidate see screen devices experience report device-fabric device pi benchmark intelligence integration start stop restart doctor service agents dots missions task proactive say listen audio voice voice-test world grants security backup approvals autonomy stark omninet scheduler neural integrate\"\n"
        "\n"
        "    if [[ ${cur} == -* ]]; then\n"
        "        COMPREPLY=($(compgen -W \"--help --home --token --port --host --open --allow-remote --provider --lat --lon --radius-km --kind --limit --key --approve --json --cycles --neurons --room --device --name --type --reason --by --capability --args --cycle --source --path --observation --action --team --depth --task --speak --file --camera --ocr --system-ui --rooms --install --start --stop --restart --status --health --doctor --logs --run --list --add --run --enable --disable --stats --neurons --status --create --test --speak --listen --see --screen --devices --report --fabric --device --pi --benchmark --intelligence --integration --stark --omninet --scheduler --neural --integrate\" -- \"${cur}\"))\n"
        "    else\n"
        "        COMPREPLY=($(compgen -W \"${opts}\" -- \"${cur}\"))\n"
        "    fi\n"
        "    return 0\n"
        "}\n"
        "complete -F _jarvis_completion jarvis\n"
    )


def generate_zsh_completion(parser: argparse.ArgumentParser) -> str:
    """Generate zsh completion script."""
    return (
        "# JARVIS-OS CLI zsh completion\n"
        "#compdef jarvis\n"
        "\n"
        "_jarvis() {\n"
        "    local -a commands\n"
        "    commands=(\n"
        "        talk:Send one input through the loop\n"
        "        repl:Interactive prompt\n"
        "        serve:Start the HTTP + WebSocket API\n"
        "        board:Local status board URL\n"
        "        remote:Phone/local remote URL\n"
        "        command:AI command centre URL\n"
        "        office:Agent office floor URL\n"
        "        status:Print system status JSON\n"
        "        status-summary:One-line-per-system human status\n"
        "        proof:Show receipts for a claim\n"
        "        feedback:Record feedback as a memory episode\n"
        "        setup:Guided first-run checklist\n"
        "        gods-eye:Manage God's Eye View application\n"
        "        mentalist:Evidence-gated analysis\n"
        "        remember:Store a fact in the palace\n"
        "        consolidate:Run memory consolidation\n"
        "        see:Camera/screen/file observation\n"
        "        screen:Read the screen\n"
        "        devices:Capability snapshot\n"
        "        experience:Experience Layer foundation\n"
        "        report:Read-only SQL reports\n"
        "        device-fabric:Distributed device mesh\n"
        "        device:Device endpoints\n"
        "        pi:Raspberry Pi edge node\n"
        "        benchmark:Latency + resource benchmark\n"
        "        intelligence:Unified cognitive loop\n"
        "        integration:Cross-system integration test\n"
        "        start:Start the JARVIS service\n"
        "        stop:Stop the JARVIS service\n"
        "        restart:Restart the JARVIS service\n"
        "        doctor:Dependency + hardware + model health checks\n"
        "        service:24/7 background service\n"
        "        agents:Multi-agent organization\n"
        "        dots:Persistent autonomous workers\n"
        "        missions:Persistent multi-dot missions\n"
        "        task:Durable autonomous tasks\n"
        "        proactive:Proactive attention + decisions\n"
        "        say:Speak text aloud via TTS\n"
        "        listen:Voice turn: mic → STT → think → speak\n"
        "        audio:Audio perception\n"
        "        voice:JARVIS voice\n"
        "        voice-test:Deterministic voice self-test\n"
        "        world:World intelligence\n"
        "        grants:Standing grants\n"
        "        security:Security review\n"
        "        backup:State backup\n"
        "        approvals:Policy approvals\n"
        "        autonomy:Bounded autonomy\n"
        "        stark:Stark AI dispatch\n"
        "        omninet:OMNINET system status dashboard\n"
        "        scheduler:Automated scheduler management\n"
        "        neural:Neural networking management\n"
        "        integrate:Cross-system integration test\n"
        "    )\n"
        "\n"
        "    _describe -t commands \"jarvis command\" commands\n"
        "    return 0\n"
        "}\n"
    )


def generate_fish_completion(parser: argparse.ArgumentParser) -> str:
    """Generate fish completion script."""
    return (
        "# JARVIS-OS CLI fish completion\n"
        "function __fish_jarvis_using_command\n"
        "    set -l cmd (commandline -opc)\n"
        "    test (count $cmd) -eq 1\n"
        "end\n"
        "\n"
        "complete -c jarvis -f -a 'talk' -d 'Send one input through the loop'\n"
        "complete -c jarvis -f -a 'repl' -d 'Interactive prompt'\n"
        "complete -c jarvis -f -a 'serve' -d 'Start the HTTP + WebSocket API'\n"
        "complete -c jarvis -f -a 'board' -d 'Local status board URL'\n"
        "complete -c jarvis -f -a 'remote' -d 'Phone/local remote URL'\n"
        "complete -c jarvis -f -a 'command' -d 'AI command centre URL'\n"
        "complete -c jarvis -f -a 'office' -d 'Agent office floor URL'\n"
        "complete -c jarvis -f -a 'status' -d 'Print system status JSON'\n"
        "complete -c jarvis -f -a 'status-summary' -d 'One-line-per-system human status'\n"
        "complete -c jarvis -f -a 'proof' -d 'Show receipts for a claim'\n"
        "complete -c jarvis -f -a 'feedback' -d 'Record feedback as a memory episode'\n"
        "complete -c jarvis -f -a 'setup' -d 'Guided first-run checklist'\n"
        "complete -c jarvis -f -a 'gods-eye' -d 'Manage God's Eye View application'\n"
        "complete -c jarvis -f -a 'mentalist' -d 'Evidence-gated analysis'\n"
        "complete -c jarvis -f -a 'remember' -d 'Store a fact in the palace'\n"
        "complete -c jarvis -f -a 'consolidate' -d 'Run memory consolidation'\n"
        "complete -c jarvis -f -a 'see' -d 'Camera/screen/file observation'\n"
        "complete -c jarvis -f -a 'screen' -d 'Read the screen'\n"
        "complete -c jarvis -f -a 'devices' -d 'Capability snapshot'\n"
        "complete -c jarvis -f -a 'experience' -d 'Experience Layer foundation'\n"
        "complete -c jarvis -f -a 'report' -d 'Read-only SQL reports'\n"
        "complete -c jarvis -f -a 'device-fabric' -d 'Distributed device mesh'\n"
        "complete -c jarvis -f -a 'device' -d 'Device endpoints'\n"
        "complete -c jarvis -f -a 'pi' -d 'Raspberry Pi edge node'\n"
        "complete -c jarvis -f -a 'benchmark' -d 'Latency + resource benchmark'\n"
        "complete -c jarvis -f -a 'intelligence' -d 'Unified cognitive loop'\n"
        "complete -c jarvis -f -a 'integration' -d 'Cross-system integration test'\n"
        "complete -c jarvis -f -a 'start' -d 'Start the JARVIS service'\n"
        "complete -c jarvis -f -a 'stop' -d 'Stop the JARVIS service'\n"
        "complete -c jarvis -f -a 'restart' -d 'Restart the JARVIS service'\n"
        "complete -c jarvis -f -a 'doctor' -d 'Dependency + hardware + model health checks'\n"
        "complete -c jarvis -f -a 'service' -d '24/7 background service'\n"
        "complete -c jarvis -f -a 'agents' -d 'Multi-agent organization'\n"
        "complete -c jarvis -f -a 'dots' -d 'Persistent autonomous workers'\n"
        "complete -c jarvis -f -a 'missions' -d 'Persistent multi-dot missions'\n"
        "complete -c jarvis -f -a 'task' -d 'Durable autonomous tasks'\n"
        "complete -c jarvis -f -a 'proactive' -d 'Proactive attention + decisions'\n"
        "complete -c jarvis -f -a 'say' -d 'Speak text aloud via TTS'\n"
        "complete -c jarvis -f -a 'listen' -d 'Voice turn: mic → STT → think → speak'\n"
        "complete -c jarvis -f -a 'audio' -d 'Audio perception'\n"
        "complete -c jarvis -f -a 'voice' -d 'JARVIS voice'\n"
        "complete -c jarvis -f -a 'voice-test' -d 'Deterministic voice self-test'\n"
        "complete -c jarvis -f -a 'world' -d 'World intelligence'\n"
        "complete -c jarvis -f -a 'grants' -d 'Standing grants'\n"
        "complete -c jarvis -f -a 'security' -d 'Security review'\n"
        "complete -c jarvis -f -a 'backup' -d 'State backup'\n"
        "complete -c jarvis -f -a 'approvals' -d 'Policy approvals'\n"
        "complete -c jarvis -f -a 'autonomy' -d 'Bounded autonomy'\n"
        "complete -c jarvis -f -a 'stark' -d 'Stark AI dispatch'\n"
        "complete -c jarvis -f -a 'omninet' -d 'OMNINET system status dashboard'\n"
        "complete -c jarvis -f -a 'scheduler' -d 'Automated scheduler management'\n"
        "complete -c jarvis -f -a 'neural' -d 'Neural networking management'\n"
        "complete -c jarvis -f -a 'integrate' -d 'Cross-system integration test'\n"
    )


def write_completions(output_dir: str) -> dict[str, str]:
    """Write completion scripts to the output directory."""
    import os

    os.makedirs(output_dir, exist_ok=True)

    bash_path = os.path.join(output_dir, "jarvis.bash")
    zsh_path = os.path.join(output_dir, "_jarvis")
    fish_path = os.path.join(output_dir, "jarvis.fish")

    with open(bash_path, "w") as f:
        f.write(generate_bash_completion(parser=None))

    with open(zsh_path, "w") as f:
        f.write(generate_zsh_completion(parser=None))

    with open(fish_path, "w") as f:
        f.write(generate_fish_completion(parser=None))

    return {
        "bash": bash_path,
        "zsh": zsh_path,
        "fish": fish_path,
    }


__all__ = [
    "generate_bash_completion",
    "generate_zsh_completion",
    "generate_fish_completion",
    "write_completions",
]