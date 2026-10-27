"""Consistency checks across the App / Executa config files.

Anna resolves the bundled Executa through several files that must agree; a
mismatch only shows up after publishing, as a tool the Cloud Agent cannot prepare.
Run: python tests/test_config.py
"""

import importlib.util
import json
import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXECUTA_DIR = os.path.join(ROOT, "executas", "ai-news-reporter")
PLATFORMS = {"darwin-arm64", "darwin-x86_64", "linux-x86_64", "windows-x86_64"}


def load_json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "plugin", os.path.join(EXECUTA_DIR, "ai_news_reporter_plugin.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    app = load_json("app.json")
    manifest = load_json("manifest.json")
    executa = load_json("executas", "ai-news-reporter", "executa.json")
    protocol = load_json("executas", "ai-news-reporter", "manifest.json")
    with open(os.path.join(EXECUTA_DIR, "pyproject.toml"), "rb") as f:
        pyproject = tomllib.load(f)
    plugin = load_plugin()

    # Every bundled:<handle> reference resolves to an app.json entry that exists on disk.
    handles = set(app["bundled_executas"])
    refs = {e["tool_id"].removeprefix("bundled:") for e in manifest["required_executas"]}
    assert refs == handles, (refs, handles)
    for h in handles:
        path = os.path.join(ROOT, app["bundled_executas"][h]["path"])
        assert os.path.isfile(os.path.join(path, "executa.json")), path

    # The protocol manifest the CLI syncs to the server is exactly what describe returns.
    assert protocol == plugin.MANIFEST, "run: scripts/build_binary.py --write-manifest"
    assert "llm.sample" in protocol["host_capabilities"]
    assert "llm.sample" in manifest["host_capabilities"]

    # One tool version everywhere it is written.
    versions = {
        "plugin VERSION": plugin.VERSION,
        "manifest.json": protocol["version"],
        "executa.json": executa["version"],
        "pyproject.toml": pyproject["project"]["version"],
    }
    assert len(set(versions.values())) == 1, versions

    # Local profile: `anna-app dev` runs `uv run <tool_id>`, so the script key must match.
    assert executa["tool_id"] in pyproject["project"]["scripts"], executa["tool_id"]

    # Cloud install: the binary profile is active and ships all four platforms.
    dist = executa["distribution"]
    assert dist["active"] == "binary", dist["active"]
    binary = dist["profiles"]["binary"]
    assert set(binary["binary_artifacts"]) == PLATFORMS, set(binary["binary_artifacts"])
    for key, art in binary["binary_artifacts"].items():
        exe = binary["executable_name"] + (".exe" if key.startswith("windows") else "")
        assert art["entrypoint"] == f"bin/{exe}", (key, art)
        assert art["format"] == ("zip" if key.startswith("windows") else "tar.gz"), (key, art)
        assert art["path"].endswith(f"-{{version}}-{key}.{art['format']}"), (key, art)

    print("ALL CONFIG CHECKS PASSED")


if __name__ == "__main__":
    main()
