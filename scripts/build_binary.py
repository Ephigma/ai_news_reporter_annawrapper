#!/usr/bin/env python3
"""Build, package and smoke-test the Executa binary for the current platform.

Archive paths, entrypoints and formats are read from executa.json's binary
profile, so the archive built here is exactly what `anna-app apps publish`
uploads. The smoke test runs the binary extracted from the archive, not the
source file, because that is what the Cloud Agent installs.

Usage (from the repo root):
  uv run --project executas/ai-news-reporter python scripts/build_binary.py
  uv run --project executas/ai-news-reporter python scripts/build_binary.py --write-manifest
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXECUTA_DIR = ROOT / "executas" / "ai-news-reporter"
PLUGIN = EXECUTA_DIR / "ai_news_reporter_plugin.py"
PROTOCOL_MANIFEST = EXECUTA_DIR / "manifest.json"

# platform.system()/machine() -> Anna platform key
PLATFORM_KEYS = {
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x86_64",
    ("Linux", "x86_64"): "linux-x86_64",
    ("Windows", "AMD64"): "windows-x86_64",
}


def load_plugin_manifest() -> dict:
    spec = importlib.util.spec_from_file_location("plugin", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MANIFEST


def write_manifest() -> None:
    """manifest.json beside executa.json is what the CLI syncs to the server as
    the tool's capabilities; it is generated from the plugin so the two cannot drift."""
    PROTOCOL_MANIFEST.write_text(
        json.dumps(load_plugin_manifest(), indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"wrote {PROTOCOL_MANIFEST.relative_to(ROOT)}")


def host_platform() -> str:
    key = PLATFORM_KEYS.get((platform.system(), platform.machine()))
    if key is None:
        sys.exit(f"unsupported build host: {platform.system()} {platform.machine()}")
    return key


def build(platform_key: str) -> Path:
    executa = json.loads((EXECUTA_DIR / "executa.json").read_text("utf-8"))
    version = executa["version"]
    profile = executa["distribution"]["profiles"]["binary"]
    artifact = profile["binary_artifacts"][platform_key]
    entrypoint = artifact["entrypoint"]
    archive = EXECUTA_DIR / artifact["path"].replace("{version}", version)
    archive.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--onefile", "--clean", "--noupx",
             "--noconfirm", "--name", Path(entrypoint).stem,
             "--distpath", str(tmp / "dist"), "--workpath", str(tmp / "build"),
             "--specpath", str(tmp), str(PLUGIN)],
            check=True,
        )
        binary = tmp / "dist" / Path(entrypoint).name
        archive_manifest = {
            "name": profile["executable_name"],
            "version": version,
            "runtime": {"binary": {
                "entrypoint": entrypoint,
                "permissions": {entrypoint: "0o755"},
            }},
        }
        manifest_bytes = (json.dumps(archive_manifest, indent=2) + "\n").encode()

        if artifact["format"] == "zip":
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", manifest_bytes)
                info = zipfile.ZipInfo(entrypoint)
                info.external_attr = 0o755 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, binary.read_bytes())
        else:
            manifest_file = tmp / "manifest.json"
            manifest_file.write_bytes(manifest_bytes)
            binary.chmod(0o755)
            with tarfile.open(archive, "w:gz") as tf:
                tf.add(manifest_file, arcname="manifest.json")
                tf.add(binary, arcname=entrypoint)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"built {archive.relative_to(ROOT)} ({archive.stat().st_size} bytes, sha256 {digest})")
    return archive


def extract(archive: Path, dest: Path) -> dict:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
            for info in zf.infolist():
                mode = info.external_attr >> 16
                if mode:
                    (dest / info.filename).chmod(mode)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(dest, filter="data")
    return json.loads((dest / "manifest.json").read_text("utf-8"))


class Rpc:
    def __init__(self, argv: list[str], cwd: Path):
        self.p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8")

    def call(self, rid, method: str, params: dict | None = None) -> dict:
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()
        resp = json.loads(self.p.stdout.readline())
        assert resp.get("jsonrpc") == "2.0" and resp.get("id") == rid, resp
        assert ("result" in resp) != ("error" in resp), resp
        return resp

    def close(self) -> int:
        self.p.stdin.close()
        rest = self.p.stdout.read()
        assert rest == "", f"unexpected stdout after EOF: {rest!r}"
        return self.p.wait(timeout=30)


def smoke_test(archive: Path) -> None:
    """Pre-release inspection sequence, run against the binary inside the archive."""
    expected = json.loads(PROTOCOL_MANIFEST.read_text("utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive_manifest = extract(archive, tmp)
        entry = tmp / archive_manifest["runtime"]["binary"]["entrypoint"]
        assert entry.is_file(), f"entrypoint missing in archive: {entry}"
        assert archive_manifest["version"] == expected["version"], archive_manifest

        rpc = Rpc([str(entry)], cwd=tmp)
        init = rpc.call(0, "initialize", {
            "protocolVersion": "2.0", "clientInfo": {"name": "smoke", "version": "1"},
            "capabilities": {"sampling": {"modalities": ["text"]}}})
        assert init["result"]["protocolVersion"] == "2.0", init
        assert "sampling" in init["result"]["capabilities"], init
        for rid in ("describe-1", 2):
            assert rpc.call(rid, "describe")["result"] == expected, "describe != manifest.json"
        missing_key = rpc.call(3, "invoke", {
            "tool": "search_ai_news", "arguments": {}, "context": {}})["result"]
        assert missing_key["success"] is False and "TAVILY_API_KEY" in missing_key["error"]
        unknown = rpc.call(4, "invoke", {"tool": "nope", "arguments": {}, "context": {}})
        assert unknown["error"]["code"] == -32601, unknown
        assert rpc.call(5, "describe")["result"] == expected, "no recovery after error"
        assert rpc.call(6, "health")["result"]["status"] == "ready"
        code = rpc.close()
        assert code == 0, f"exit code {code}: {rpc.p.stderr.read()}"
    print(f"smoke test passed: {archive.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-manifest", action="store_true",
                    help="regenerate executas/ai-news-reporter/manifest.json and exit")
    if ap.parse_args().write_manifest:
        write_manifest()
        return
    smoke_test(build(host_platform()))


if __name__ == "__main__":
    main()
