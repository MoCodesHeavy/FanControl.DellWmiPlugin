"""Config storage and wallet-address validation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .paths import config_dir

XMR_RE = re.compile(r"^[48][1-9A-HJ-NP-Za-km-z]{94}$|^4[1-9A-HJ-NP-Za-km-z]{105}$")
BTC_RE = re.compile(r"^(bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")


def valid_wallet(coin: str, address: str) -> bool:
    """Format check only (no checksum): catches typos like a truncated paste, not every bad address."""
    pattern = {"XMR": XMR_RE, "BTC": BTC_RE}.get(coin.upper())
    return bool(pattern and pattern.match(address.strip()))


@dataclass
class Config:
    coin: str = "XMR"
    wallet: str = ""
    pool: str = "pool.supportxmr.com:443"
    tls: bool = True
    worker: str = ""
    max_threads_percent: int = 75
    power_cost_kwh: float = 0.15

    def validate(self) -> Optional[str]:
        if not valid_wallet(self.coin, self.wallet):
            return f"'{self.wallet}' does not look like a valid {self.coin} address"
        if not 10 <= self.max_threads_percent <= 100:
            return "max_threads_percent must be between 10 and 100"
        return None


def config_path() -> Path:
    return config_dir() / "config.json"


def load(path: Optional[Path] = None) -> Optional[Config]:
    p = path or config_path()
    try:
        return Config(**json.loads(p.read_text()))
    except (OSError, ValueError, TypeError):
        return None


def save(cfg: Config, path: Optional[Path] = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2))
    return p
