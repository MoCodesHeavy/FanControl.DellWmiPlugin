"""OS tweaks that raise RandomX (CPU) hashrate. Every change is explicit, reversible and opt-in."""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

SYSCTL_FILE = Path("/etc/sysctl.d/90-automine.conf")
# RandomX: ~2080 MB dataset + 256 MB cache = ~1168 x 2 MB pages, plus 1 page per mining thread.
BASE_HUGEPAGES = 1168
PRIV = "SeLockMemoryPrivilege"


@dataclass
class TweakStatus:
    name: str
    supported: bool
    enabled: bool
    detail: str
    needs_admin: bool = True


def required_hugepages(threads: int) -> int:
    return BASE_HUGEPAGES + max(1, threads)


def is_admin() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


# ---------------------------------------------------------------- Linux

def _linux_hugepages_total() -> Optional[int]:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("HugePages_Total:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def _linux_msr_loaded() -> bool:
    return Path("/dev/cpu/0/msr").exists()


# -------------------------------------------------------------- Windows

def _win_has_lock_privilege() -> bool:
    try:
        out = subprocess.run(["whoami", "/priv"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return PRIV in out


def add_sid_to_privilege(inf_text: str, sid: str, privilege: str = PRIV) -> str:
    """Return secedit INF text with `sid` granted `privilege`. Pure function (tested)."""
    entry = f"*{sid}"
    lines = inf_text.splitlines()
    pat = re.compile(rf"^\s*{privilege}\s*=\s*(.*)$", re.IGNORECASE)
    for i, line in enumerate(lines):
        m = pat.match(line)
        if m:
            current = [x.strip() for x in m.group(1).split(",") if x.strip()]
            if entry not in current:
                current.append(entry)
            lines[i] = f"{privilege} = {','.join(current)}"
            return "\n".join(lines) + "\n"
    for i, line in enumerate(lines):
        if line.strip().lower() == "[privilege rights]":
            lines.insert(i + 1, f"{privilege} = {entry}")
            return "\n".join(lines) + "\n"
    lines += ["[Privilege Rights]", f"{privilege} = {entry}"]
    return "\n".join(lines) + "\n"


def _win_current_sid() -> str:
    out = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True).stdout
    return out.strip().split(",")[1].strip().strip('"')


def _win_grant_lock_privilege() -> None:
    sid = _win_current_sid()
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "export.inf"
        db = Path(td) / "automine.sdb"
        subprocess.run(["secedit", "/export", "/cfg", str(cfg), "/areas", "USER_RIGHTS"], check=True, capture_output=True)
        text = cfg.read_text(encoding="utf-16")
        cfg.write_text(add_sid_to_privilege(text, sid), encoding="utf-16")
        subprocess.run(
            ["secedit", "/configure", "/db", str(db), "/cfg", str(cfg), "/areas", "USER_RIGHTS"],
            check=True, capture_output=True,
        )


# ------------------------------------------------------------ public API

def status(threads: int) -> List[TweakStatus]:
    need = required_hugepages(threads)
    if sys.platform == "linux":
        total = _linux_hugepages_total()
        hp = TweakStatus(
            "huge-pages", True, total is not None and total >= need,
            f"{total if total is not None else '?'} pages allocated, {need} needed (2 MB each)",
        )
        msr = TweakStatus("msr", True, _linux_msr_loaded(), "msr kernel module (lets XMRig apply its CPU boost when run as root)")
        return [hp, msr]
    if sys.platform == "win32":
        ok = _win_has_lock_privilege()
        hp = TweakStatus(
            "huge-pages", True, ok,
            "'Lock pages in memory' is active for this session" if ok
            else "'Lock pages in memory' not active (grant it, then sign out and back in)",
        )
        return [hp]
    if sys.platform == "darwin":
        return [TweakStatus("huge-pages", False, False, "not supported by macOS; nothing to tune", needs_admin=False)]
    return [TweakStatus("huge-pages", False, False, f"unsupported OS: {sys.platform}", needs_admin=False)]


def plan(threads: int) -> List[str]:
    """Human-readable list of what `apply` would do."""
    need = required_hugepages(threads)
    if sys.platform == "linux":
        return [
            f"sysctl -w vm.nr_hugepages={need}",
            f"write 'vm.nr_hugepages={need}' to {SYSCTL_FILE} (persists across reboots)",
            "modprobe msr",
        ]
    if sys.platform == "win32":
        return [
            f"grant '{PRIV}' (Lock pages in memory) to the current user via secedit",
            "you must sign out and back in afterwards for it to take effect",
        ]
    return ["nothing to do on this OS"]


def apply(threads: int, log: Callable[[str], None] = print) -> bool:
    if not is_admin():
        log("Administrator/root rights are required. Re-run from an elevated shell (sudo / 'Run as administrator').")
        return False
    need = required_hugepages(threads)
    try:
        if sys.platform == "linux":
            subprocess.run(["sysctl", "-w", f"vm.nr_hugepages={need}"], check=True)
            SYSCTL_FILE.write_text(f"# managed by automine\nvm.nr_hugepages={need}\n")
            subprocess.run(["modprobe", "msr"], check=False)
            log(f"Huge pages set to {need}. Allocation can fall short on a fragmented system; a reboot fixes that.")
            return True
        if sys.platform == "win32":
            _win_grant_lock_privilege()
            log("Granted 'Lock pages in memory'. Sign out and back in (or reboot) for it to apply.")
            return True
    except (OSError, subprocess.SubprocessError) as e:
        log(f"Failed: {e}")
        return False
    log("Nothing to apply on this OS.")
    return False


def revert(log: Callable[[str], None] = print) -> bool:
    if not is_admin():
        log("Administrator/root rights are required.")
        return False
    if sys.platform == "linux":
        try:
            if SYSCTL_FILE.exists():
                SYSCTL_FILE.unlink()
            subprocess.run(["sysctl", "-w", "vm.nr_hugepages=0"], check=True)
            log("Huge pages reset to 0 and persistent file removed.")
            return True
        except (OSError, subprocess.SubprocessError) as e:
            log(f"Failed: {e}")
            return False
    log("On Windows, remove your user from 'Lock pages in memory' in secpol.msc > Local Policies > User Rights Assignment.")
    return False
