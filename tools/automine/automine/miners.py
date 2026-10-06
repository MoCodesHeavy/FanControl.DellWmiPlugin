"""Download, configure and run XMRig (CPU RandomX miner)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from .config import Config
from .paths import data_dir

API = "https://api.github.com/repos/xmrig/xmrig/releases/latest"
API_PORT = 16000


def pick_asset(names: List[str], os_name: str, arch: str) -> Optional[str]:
    """Choose the right XMRig release file for this OS/CPU. Pure function (tested)."""
    arm = arch in ("arm64", "aarch64")
    if os_name == "win32":
        want = lambda n: "win64" in n and n.endswith(".zip") and "gcc" not in n
    elif os_name == "darwin":
        want = lambda n: ("macos-arm64" if arm else "macos-x64") in n and n.endswith(".tar.gz")
    else:
        want = lambda n: ("linux-static-arm64" if arm else "linux-static-x64") in n and n.endswith(".tar.gz")
        if arm and not any("linux-static-arm64" in n for n in names):
            return None  # XMRig publishes no official ARM Linux build; compile from source.
    for n in names:
        if want(n):
            return n
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_hash(sums_text: str, filename: str) -> Optional[str]:
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    return None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "automine"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def miner_dir() -> Path:
    return data_dir() / "xmrig"


def find_binary() -> Optional[Path]:
    exe = "xmrig.exe" if sys.platform == "win32" else "xmrig"
    d = miner_dir()
    if d.exists():
        for p in d.rglob(exe):
            return p
    found = shutil.which("xmrig")
    return Path(found) if found else None


def install(arch: str, log: Callable[[str], None] = print) -> Path:
    release = json.loads(_get(API))
    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    name = pick_asset(list(assets), sys.platform, arch)
    if not name:
        raise RuntimeError(f"No official XMRig build for {sys.platform}/{arch}; build from source.")
    sums_name = next((n for n in assets if n.upper().startswith("SHA256SUMS") and not n.endswith(".sig")), None)
    if not sums_name:
        raise RuntimeError("Release has no SHA256SUMS file; refusing to install unverified binary.")
    want = expected_hash(_get(assets[sums_name]).decode(), name)
    if not want:
        raise RuntimeError(f"No checksum listed for {name}; refusing to install.")
    d = miner_dir()
    d.mkdir(parents=True, exist_ok=True)
    archive = d / name
    log(f"Downloading {name} ({release['tag_name']})")
    archive.write_bytes(_get(assets[name]))
    got = sha256_of(archive)
    if got != want:
        archive.unlink()
        raise RuntimeError(f"Checksum mismatch for {name}: expected {want}, got {got}. File deleted.")
    log("SHA-256 verified.")
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(d)
    else:
        with tarfile.open(archive) as t:
            t.extractall(d, filter="data") if sys.version_info >= (3, 12) else t.extractall(d)
    archive.unlink()
    binary = find_binary()
    if not binary:
        raise RuntimeError("Extracted archive but could not find the xmrig binary.")
    binary.chmod(0o755)
    log(f"Installed to {binary}")
    log("Note: antivirus tools commonly flag XMRig as a 'miner'. If yours does, exclude only this folder: "
        f"{binary.parent}")
    return binary


def build_config(cfg: Config, huge_pages: bool = True) -> dict:
    return {
        "autosave": False,
        "donate-level": 1,
        "cpu": {"enabled": True, "huge-pages": huge_pages, "max-threads-hint": cfg.max_threads_percent, "yield": True},
        "opencl": {"enabled": False},
        "cuda": {"enabled": False},
        "randomx": {"mode": "auto", "1gb-pages": False, "rdmsr": True, "wrmsr": True, "numa": True},
        "http": {"enabled": True, "host": "127.0.0.1", "port": API_PORT, "access-token": None, "restricted": True},
        "pools": [{
            "url": cfg.pool,
            "user": cfg.wallets["XMR"],
            "pass": cfg.worker or "automine",
            "tls": cfg.tls,
            "keepalive": True,
        }],
    }


def summary() -> Optional[dict]:
    try:
        return json.loads(_get(f"http://127.0.0.1:{API_PORT}/2/summary"))
    except (OSError, ValueError):
        return None


def run(cfg: Config, binary: Path, log: Callable[[str], None] = print) -> int:
    conf_path = binary.parent / "automine-config.json"
    conf_path.write_text(json.dumps(build_config(cfg), indent=2))
    w = cfg.wallets["XMR"]
    log(f"Starting {binary} (Ctrl+C to stop). Mining XMR to {w[:6]}...{w[-4:]} on {cfg.pool}")
    proc = subprocess.Popen([str(binary), "--config", str(conf_path)])
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log("Stopped.")
        return 0
