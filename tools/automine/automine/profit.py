"""Profit math and a switching rule that avoids flapping. Pure functions, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Option:
    name: str
    revenue_per_day: float  # USD/day at the device's measured hashrate
    power_watts: float


def daily_cost(power_watts: float, price_per_kwh: float) -> float:
    return power_watts / 1000.0 * 24.0 * price_per_kwh


def daily_profit(opt: Option, price_per_kwh: float) -> float:
    return opt.revenue_per_day - daily_cost(opt.power_watts, price_per_kwh)


def xmr_revenue_per_day(hashrate_hs: float, network_hashrate_hs: float, block_reward_xmr: float,
                        xmr_usd: float, blocks_per_day: float = 720.0) -> float:
    """Expected earnings before pool fees: your share of network hashrate times daily emission."""
    if network_hashrate_hs <= 0:
        return 0.0
    return hashrate_hs / network_hashrate_hs * block_reward_xmr * blocks_per_day * xmr_usd


def best(options: Dict[str, Option], price_per_kwh: float) -> Optional[str]:
    if not options:
        return None
    return max(options, key=lambda k: daily_profit(options[k], price_per_kwh))


class Switcher:
    """Only change algorithm if the challenger beats the incumbent by `margin` for `hold` consecutive checks."""

    def __init__(self, margin: float = 0.10, hold: int = 3):
        self.margin, self.hold = margin, hold
        self.current: Optional[str] = None
        self._challenger: Optional[str] = None
        self._count = 0

    def update(self, options: Dict[str, Option], price_per_kwh: float) -> Optional[str]:
        top = best(options, price_per_kwh)
        if top is None:
            return self.current
        if self.current is None or self.current not in options:
            self.current, self._challenger, self._count = top, None, 0
            return self.current
        cur_p = daily_profit(options[self.current], price_per_kwh)
        top_p = daily_profit(options[top], price_per_kwh)
        better = top != self.current and top_p > cur_p + abs(cur_p) * self.margin and top_p > cur_p
        if better:
            self._count = self._count + 1 if self._challenger == top else 1
            self._challenger = top
            if self._count >= self.hold:
                self.current, self._challenger, self._count = top, None, 0
        else:
            self._challenger, self._count = None, 0
        return self.current
