"""automine command-line interface."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, config, hardware, miners, profit, tweaks


def _threads(hw: hardware.Hardware, pct: int) -> int:
    return max(1, hw.cpu_threads * pct // 100)


def cmd_scan(args) -> int:
    hw = hardware.detect()
    cfg = config.load() or config.Config()
    if args.json:
        print(json.dumps(hw.to_dict(), indent=2))
        return 0
    print(f"OS:   {hw.os} ({hw.arch})")
    print(f"CPU:  {hw.cpu_name} ({hw.cpu_threads} threads)")
    print(f"RAM:  {hw.ram_mb} MB")
    for g in hw.gpus or []:
        print(f"GPU:  {g.name} [{g.vendor}]" + (f" {g.vram_mb} MB" if g.vram_mb else ""))
    if not hw.gpus:
        print("GPU:  none detected")
    print("\nTweaks:")
    for t in tweaks.status(_threads(hw, cfg.max_threads_percent)):
        mark = "ok " if t.enabled else ("n/a" if not t.supported else "off")
        print(f"  [{mark}] {t.name}: {t.detail}")
    print("\nMining plan:")
    print("  CPU -> XMRig / Monero (RandomX)" if hw.os != "darwin" or hw.arch in ("arm64", "x86_64") else "  CPU -> unsupported")
    if hw.gpus:
        print("  GPU -> not automated yet in this version (Monero RandomX is CPU-oriented; GPU algorithms are on the roadmap)")
    if hw.os == "darwin":
        print("  note: macOS has no huge pages and XMRig cannot use Apple GPUs; expect modest CPU hashrate")
    return 0


def cmd_setup(args) -> int:
    cfg = config.load() or config.Config()
    print("automine setup. Nothing is sent anywhere except your wallet address as the pool username.")
    while True:
        wallet = args.wallet or input("Monero (XMR) wallet address: ").strip()
        cfg.wallet = wallet
        if config.valid_wallet("XMR", wallet):
            break
        print("That doesn't look like a valid Monero address (95 characters, starts with 4 or 8). Try again.")
        if args.wallet:
            return 1
    cfg.pool = args.pool or cfg.pool
    cfg.worker = args.worker or cfg.worker or hardware.platform.node()[:32]
    if args.max_threads:
        cfg.max_threads_percent = args.max_threads
    err = cfg.validate()
    if err:
        print(err)
        return 1
    print(f"Saved to {config.save(cfg)}")
    print("Next: 'automine scan', then 'automine tweak' (as admin), 'automine install', 'automine start'.")
    return 0


def cmd_tweak(args) -> int:
    hw = hardware.detect()
    cfg = config.load() or config.Config()
    n = _threads(hw, cfg.max_threads_percent)
    if args.revert:
        return 0 if tweaks.revert() else 1
    print("Planned changes:")
    for step in tweaks.plan(n):
        print(f"  - {step}")
    if not args.apply:
        print("\nDry run. Re-run with --apply (as admin/root) to make these changes. Undo with --revert.")
        return 0
    return 0 if tweaks.apply(n) else 1


def cmd_install(args) -> int:
    try:
        miners.install(hardware.platform.machine().lower())
    except Exception as e:  # noqa: BLE001 - surface any download/verify problem plainly
        print(f"Install failed: {e}")
        return 1
    return 0


def cmd_start(args) -> int:
    cfg = config.load()
    if not cfg:
        print("No config yet. Run 'automine setup' first.")
        return 1
    err = cfg.validate()
    if err:
        print(err)
        return 1
    binary = miners.find_binary()
    if not binary:
        print("XMRig not installed. Run 'automine install' first.")
        return 1
    return miners.run(cfg, binary)


def cmd_estimate(args) -> int:
    rev = profit.xmr_revenue_per_day(args.hashrate, args.network_hashrate, args.block_reward, args.xmr_usd)
    opt = profit.Option("xmr", rev, args.watts)
    print(f"Revenue: ${rev:.2f}/day  Power: ${profit.daily_cost(args.watts, args.kwh):.2f}/day  "
          f"Profit: ${profit.daily_profit(opt, args.kwh):.2f}/day (before pool fees)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="automine", description="Transparent miner setup tool")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="detect hardware and tweak status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("setup", help="save wallet and settings")
    s.add_argument("--wallet")
    s.add_argument("--pool")
    s.add_argument("--worker")
    s.add_argument("--max-threads", type=int, help="percent of CPU threads to use (10-100)")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("tweak", help="huge pages etc. (dry run unless --apply)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--revert", action="store_true")
    s.set_defaults(fn=cmd_tweak)

    s = sub.add_parser("install", help="download and checksum-verify XMRig")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("start", help="run the miner in the foreground")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("estimate", help="profit estimate from numbers you supply")
    s.add_argument("--hashrate", type=float, required=True, help="H/s")
    s.add_argument("--network-hashrate", type=float, required=True, help="H/s, see a Monero explorer")
    s.add_argument("--block-reward", type=float, default=0.6, help="XMR per block (tail emission ~0.6)")
    s.add_argument("--xmr-usd", type=float, required=True)
    s.add_argument("--watts", type=float, required=True)
    s.add_argument("--kwh", type=float, required=True, help="electricity price per kWh")
    s.set_defaults(fn=cmd_estimate)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
