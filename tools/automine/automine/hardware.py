"""Hardware detection using only the standard library and OS tools."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Gpu:
    name: str
    vendor: str  # nvidia | amd | intel | apple | unknown
    vram_mb: Optional[int] = None


@dataclass
class Hardware:
    os: str
    arch: str
    cpu_name: str
    cpu_threads: int
    ram_mb: int
    gpus: List[Gpu] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: List[str], timeout: int = 15) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _powershell(script: str) -> str:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return ""
    return _run([exe, "-NoProfile", "-NonInteractive", "-Command", script])


def classify_vendor(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "quadro" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n or "advanced micro" in n or "ati " in n:
        return "amd"
    if "intel" in n:
        return "intel"
    if "apple" in n:
        return "apple"
    return "unknown"


def _cpu_name() -> str:
    if sys.platform == "linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif sys.platform == "darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if name:
            return name
    elif sys.platform == "win32":
        name = _powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name").strip()
        if name:
            return name
    return platform.processor() or "unknown"


def _ram_mb() -> int:
    try:
        if sys.platform == "linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        elif sys.platform == "darwin":
            return int(_run(["sysctl", "-n", "hw.memsize"]).strip()) // (1024 * 1024)
        elif sys.platform == "win32":
            out = _powershell("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory").strip()
            return int(out) // (1024 * 1024)
    except (OSError, ValueError):
        pass
    return 0


def parse_nvidia_smi(text: str) -> List[Gpu]:
    gpus = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        vram = None
        if len(parts) > 1:
            m = re.search(r"(\d+)", parts[1])
            vram = int(m.group(1)) if m else None
        gpus.append(Gpu(parts[0], "nvidia", vram))
    return gpus


def parse_lspci(text: str) -> List[Gpu]:
    gpus = []
    for line in text.splitlines():
        if re.search(r"VGA compatible controller|3D controller|Display controller", line):
            name = line.split(": ", 1)[-1].strip()
            gpus.append(Gpu(name, classify_vendor(name)))
    return gpus


def _detect_gpus() -> List[Gpu]:
    gpus: List[Gpu] = []
    if sys.platform == "darwin":
        out = _run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=30)
        try:
            for d in json.loads(out).get("SPDisplaysDataType", []):
                name = d.get("sppci_model", "unknown")
                gpus.append(Gpu(name, classify_vendor(name)))
        except (ValueError, AttributeError):
            pass
        return gpus
    if sys.platform == "win32":
        out = _powershell(
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
        )
        try:
            data = json.loads(out) if out.strip() else []
            if isinstance(data, dict):
                data = [data]
            for d in data:
                name = d.get("Name") or "unknown"
                ram = d.get("AdapterRAM")
                # AdapterRAM is a 32-bit field and under-reports cards above 4 GB.
                vram = int(ram) // (1024 * 1024) if isinstance(ram, int) and ram > 0 else None
                gpus.append(Gpu(name, classify_vendor(name), vram))
        except ValueError:
            pass
    else:
        gpus.extend(parse_lspci(_run(["lspci"])))
    # nvidia-smi gives accurate VRAM for NVIDIA cards on any OS; prefer it.
    smi = shutil.which("nvidia-smi")
    if smi:
        nv = parse_nvidia_smi(
            _run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"])
        )
        if nv:
            gpus = [g for g in gpus if g.vendor != "nvidia"] + nv
    return gpus


def detect() -> Hardware:
    return Hardware(
        os=sys.platform,
        arch=platform.machine().lower(),
        cpu_name=_cpu_name(),
        cpu_threads=os.cpu_count() or 1,
        ram_mb=_ram_mb(),
        gpus=_detect_gpus(),
    )
