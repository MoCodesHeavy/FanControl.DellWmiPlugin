"""Config storage and wallet-address validation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

from .paths import config_dir

B58 = "1-9A-HJ-NP-Za-km-z"
# One address format per coin. Format checks only (no checksum): they catch a truncated or
# wrong-coin paste, not every bad address.
COINS = {
    "XMR": re.compile(rf"^[48][{B58}]{{94}}$|^4[{B58}]{{105}}$"),
    "BTC": re.compile(r"^(bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$"),
    "ETC": re.compile(r"^0x[0-9a-fA-F]{40}$"),
    "RVN": re.compile(rf"^R[{B58}]{{33}}$"),
    "VRSC": re.compile(rf"^R[{B58}]{{33}}$"),
    "ERG": re.compile(rf"^9[{B58}]{{50}}$"),
    "KAS": re.compile(r"^kaspa:[qp][a-z0-9]{55,70}$"),
}


def valid_wallet(coin: str, address: str) -> bool:
    pattern = COINS.get(coin.upper())
    return bool(pattern and pattern.match(address.strip()))


@dataclass
class Config:
    wallets: Dict[str, str] = field(default_factory=dict)  # coin -> address
    pool: str = "pool.supportxmr.com:443"
    tls: bool = True
    worker: str = ""
    max_threads_percent: int = 75
    power_cost_kwh: float = 0.15

    def validate(self) -> Optional[str]:
        if not self.wallets:
            return "no wallets configured"
        for coin, addr in self.wallets.items():
            if not valid_wallet(coin, addr):
                return f"'{addr}' does not look like a valid {coin} address"
        if not 10 <= self.max_threads_percent <= 100:
            return "max_threads_percent must be between 10 and 100"
        return None


def config_path() -> Path:
    return config_dir() / "config.json"


def load(path: Optional[Path] = None) -> Optional[Config]:
    p = path or config_path()
    try:
        data = json.loads(p.read_text())
        if "wallet" in data:  # v0.1 single-wallet format
            data.setdefault("wallets", {})[data.pop("coin", "XMR")] = data.pop("wallet")
        data.pop("coin", None)
        return Config(**data)
    except (OSError, ValueError, TypeError):
        return None


def save(cfg: Config, path: Optional[Path] = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2))
    return p
