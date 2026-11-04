"""ECC integration: curated assets stay V2-compatible and attributed.

The npm package ships a V1 plugin that OpenCode V2 cannot load, so the
repository vendors adapted Markdown assets. These tests keep the
manifest, frontmatter, attribution, and plugin decision honest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from jarvis.agents.reach import harness_inventory, registry_roster

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / ".opencode"
MANIFEST_PATH = ASSETS / "ECC_SOURCE.json"
CONFIG_PATH = ROOT / "opencode.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    assert text.startswith("---\n"), "missing frontmatter"
    end = text.index("\n---", 4)
    raw = text[4:end]
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields, raw


def _assets_of(kind: str) -> list[dict]:
    return [asset for asset in _manifest()["assets"] if asset["kind"] == kind]


def test_manifest_pins_upstream_version_and_license():
    manifest = _manifest()
    upstream = manifest["upstream"]
    assert upstream["package"] == "ecc-universal"
    assert upstream["version"] == "2.2.3"
    assert upstream["repository"] == "https://github.com/affaan-m/ECC"
    assert upstream["license"] == "MIT"
    assert "Affaan Mustafa" in upstream["copyright"]
    integration = manifest["integration"]
    assert integration["mode"] == "curated-assets"
    assert integration["plugin_loaded"] is False
    assert integration["runtime_authority"] is False
    assert "V1" in integration["reason"] and "@opencode/plugin" in integration["reason"]
    paths = [asset["path"] for asset in manifest["assets"]]
    assert len(paths) == len(set(paths)), "duplicate asset path"


def test_every_manifest_asset_exists_and_is_listed_once():
    manifest = _manifest()
    listed = set()
    for asset in manifest["assets"]:
        path = ROOT / asset["path"]
        assert path.is_file(), asset["path"]
        assert path.resolve().is_relative_to(ASSETS.resolve())
        assert asset["kind"] in {"skill", "agent"}
        assert asset["upstream"].startswith(("skills/", "agents/"))
        assert asset["adapted"] is True
        listed.add(path.resolve())
    discovered = set(ASSETS.glob("skills/*/SKILL.md")) | set(
        ASSETS.glob("agents/*.md"))
    assert discovered == listed, "unlisted or missing harness asset"


def test_skills_use_v2_frontmatter_and_credit_ecc():
    for asset in _assets_of("skill"):
        text = (ROOT / asset["path"]).read_text(encoding="utf-8")
        fields, raw = _frontmatter(text)
        assert fields.get("name"), asset["path"]
        assert len(fields.get("description", "")) > 20, asset["path"]
        assert fields.get("license") == "MIT", asset["path"]
        assert "origin: ECC" in raw, asset["path"]
        assert "upstream: ecc-universal@2.2.3" in raw, asset["path"]
        assert "https://github.com/affaan-m/ECC" in text, asset["path"]
        # Skills are guidance only; a permission declaration here would
        # be a second authority and is never allowed.
        assert "permissions:" not in raw, asset["path"]
        assert len(text.encode("utf-8")) < 100_000, asset["path"]


def test_agents_use_v2_frontmatter_without_legacy_fields():
    legacy = {"tools", "prompt", "permission", "disable", "maxsteps",
              "temperature", "top_p"}
    for asset in _assets_of("agent"):
        text = (ROOT / asset["path"]).read_text(encoding="utf-8")
        fields, raw = _frontmatter(text)
        assert len(fields.get("description", "")) > 20, asset["path"]
        assert fields.get("mode") == "subagent", asset["path"]
        keys = {key.lower() for key in fields}
        assert not keys & legacy, (asset["path"], keys & legacy)
        assert "permissions:" in raw, asset["path"]
        assert "effect:" in raw and "resource:" in raw, asset["path"]
        assert "model: sonnet" not in text, asset["path"]
        assert "ECC" in text, asset["path"]
        assert len(text.encode("utf-8")) < 100_000, asset["path"]


def test_review_agents_are_read_only_and_leaf():
    for name in ("python-reviewer", "security-reviewer"):
        text = (ROOT / ".opencode/agents" / f"{name}.md").read_text(
            encoding="utf-8")
        _, raw = _frontmatter(text)
        assert "effect: allow" not in raw, name
        for action in ("edit", "shell", "webfetch", "websearch", "subagent"):
            block = (f"  - action: {action}\n"
                     '    resource: "*"\n'
                     "    effect: deny")
            assert block in raw, (name, action)


def test_tdd_guide_is_scoped_to_tests_and_pytest():
    text = (ROOT / ".opencode/agents/tdd-guide.md").read_text(
        encoding="utf-8")
    _, raw = _frontmatter(text)
    # Broad deny first, narrow allows after: last matching rule wins.
    assert raw.index("effect: deny") < raw.index("effect: allow")
    assert 'resource: "tests/**"' in raw
    assert 'resource: "jarvis/**"' in raw
    assert 'resource: ".venv/bin/python -m pytest*"' in raw
    assert 'resource: "git push*"' not in raw
    assert "webfetch" in raw and "websearch" in raw


def test_no_v1_plugin_or_opencode_ai_dependency_is_configured():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert "plugin" not in config and "plugins" not in config
    assert not (ASSETS / "package.json").exists()
    assert not (ASSETS / "plugin").exists()
    assert not (ASSETS / "plugins").exists()
    for path in ASSETS.rglob("*"):
        if path.suffix in {".ts", ".js", ".mjs", ".cjs", ".json"} \
                and path.name != "ECC_SOURCE.json":
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "@opencode-ai/plugin" not in text, path
            assert "@opencode/plugin" not in text, path


def test_upstream_license_is_preserved():
    text = (ASSETS / "ECC_LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Copyright (c) 2026 Affaan Mustafa" in text
    assert "Permission is hereby granted" in text
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in text


def test_docs_explain_the_plugin_decision_and_link_assets():
    doc = (ROOT / "docs/ECC_INTEGRATION.md").read_text(encoding="utf-8")
    assert "https://github.com/affaan-m/ECC" in doc
    assert "ecc-universal@2.2.3" in doc
    assert "Plugin.define" in doc
    assert "do not run in v2" in doc.lower()
    index = (ROOT / "docs/index.md").read_text(encoding="utf-8")
    assert "docs/ECC_INTEGRATION.md" in index


def test_reach_inventory_discovers_assets_without_granting_reach():
    inventory = harness_inventory(ASSETS)
    assert inventory["available"] is True
    assert inventory["skill_count"] == len(_assets_of("skill"))
    assert inventory["agent_count"] == len(_assets_of("agent"))
    assert {item["id"] for item in inventory["skills"]} == {
        Path(asset["path"]).parent.name for asset in _assets_of("skill")}
    assert {item["id"] for item in inventory["agents"]} == {
        Path(asset["path"]).stem for asset in _assets_of("agent")}
    for item in inventory["skills"] + inventory["agents"]:
        assert item["source"] == "ecc"
        assert "authority" not in item and "permissions" not in item

    roster = registry_roster(query="security-review", harness_root=ASSETS)
    kinds = {row["kind"] for row in roster["harness"]}
    assert kinds == {"ecc-skill", "ecc-agent"}
    assert all("policy" not in row["dispatch"].lower()
               for row in roster["harness"])


def test_assets_contain_no_absolute_local_paths_or_private_keys():
    for asset in _manifest()["assets"]:
        text = (ROOT / asset["path"]).read_text(encoding="utf-8")
        assert "/home/" not in text, asset["path"]
        assert "PRIVATE KEY-----" not in text, asset["path"]
        assert not re.search(r"(?i)\b(?:ghp_|xoxb-|AKIA)[A-Za-z0-9]{8,}",
                             text), asset["path"]
