# automine

A transparent, open-source setup tool for CPU mining Monero with XMRig. Cross-platform (Windows, macOS, Linux), Python 3.9+, standard library only.

It never runs hidden, never starts at boot, and only sends your wallet address to the pool you choose.

## Install

```
pip install .          # or: pipx install .
```

## Use

```
automine scan                 # detect CPU/RAM/GPU and show tweak status
automine setup                # asks for your XMR wallet, saves it locally
sudo automine tweak           # dry run: shows what would change
sudo automine tweak --apply   # huge pages (Linux), 'Lock pages in memory' (Windows; run as Administrator)
sudo automine tweak --revert
automine install              # downloads XMRig, verifies SHA-256 against the release's SHA256SUMS
automine start                # runs the miner in the foreground (Ctrl+C stops it)
automine estimate --hashrate 17000 --network-hashrate 3.5e9 --xmr-usd 150 --watts 150 --kwh 0.15
```

## What it tunes

| OS      | Tweak |
|---------|-------|
| Linux   | `vm.nr_hugepages` (runtime + `/etc/sysctl.d/90-automine.conf`), `msr` module |
| Windows | Grants "Lock pages in memory" via `secedit` (sign out/in afterwards) |
| macOS   | Nothing is available to tune; XMRig runs CPU-only |

## Limits (v0.1)

- CPU/XMRig only. GPU mining and automatic algorithm switching are not wired up yet; `profit.py` has the tested switching logic for it.
- Wallet validation checks format only, not the checksum.
- The checksum comes from the same GitHub release as the binary. It catches corruption, not a compromised release.
- Windows and macOS paths are unit-tested only for their pure logic; the OS calls need a run on real machines.
- No temperature monitoring yet. Watch temps on laptops.

Tests: `python -m unittest discover -s tests`
