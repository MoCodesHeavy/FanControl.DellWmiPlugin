import hashlib
import tempfile
import unittest
from pathlib import Path

from automine import config, hardware, miners, profit, tweaks

XMR = "4" + "A" * 94
XMR_BAD = "4" + "0" * 94  # '0' is not base58


class WalletTests(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertTrue(config.valid_wallet("XMR", XMR))
        self.assertFalse(config.valid_wallet("XMR", XMR_BAD))
        self.assertFalse(config.valid_wallet("XMR", XMR[:-1]))
        self.assertTrue(config.valid_wallet("BTC", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"))
        self.assertFalse(config.valid_wallet("DOGE", "x"))

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            c = config.Config(wallet=XMR, worker="w")
            config.save(c, p)
            self.assertEqual(config.load(p), c)


class TweakTests(unittest.TestCase):
    def test_required_pages(self):
        self.assertEqual(tweaks.required_hugepages(24), 1168 + 24)

    def test_privilege_existing_line(self):
        inf = "[Privilege Rights]\nSeLockMemoryPrivilege = *S-1-5-32-544\nSeOther = *S-1-1-0\n"
        out = tweaks.add_sid_to_privilege(inf, "S-1-5-21-1")
        self.assertIn("SeLockMemoryPrivilege = *S-1-5-32-544,*S-1-5-21-1", out)
        self.assertEqual(out.count("S-1-5-21-1"), 1)
        self.assertEqual(tweaks.add_sid_to_privilege(out, "S-1-5-21-1"), out)

    def test_privilege_missing_line(self):
        out = tweaks.add_sid_to_privilege("[Unicode]\nUnicode=yes\n[Privilege Rights]\nSeX = *S-1-1-0\n", "S-1-5-21-1")
        self.assertIn("SeLockMemoryPrivilege = *S-1-5-21-1", out)

    def test_privilege_no_section(self):
        out = tweaks.add_sid_to_privilege("[Unicode]\nUnicode=yes\n", "S-1-5-21-1")
        self.assertIn("[Privilege Rights]\nSeLockMemoryPrivilege = *S-1-5-21-1", out)


class MinerTests(unittest.TestCase):
    NAMES = [
        "SHA256SUMS", "xmrig-6.22.2-linux-static-x64.tar.gz", "xmrig-6.22.2-macos-arm64.tar.gz",
        "xmrig-6.22.2-macos-x64.tar.gz", "xmrig-6.22.2-msvc-win64.zip", "xmrig-6.22.2-gcc-win64.zip",
    ]

    def test_pick_asset(self):
        self.assertEqual(miners.pick_asset(self.NAMES, "linux", "x86_64"), "xmrig-6.22.2-linux-static-x64.tar.gz")
        self.assertEqual(miners.pick_asset(self.NAMES, "darwin", "arm64"), "xmrig-6.22.2-macos-arm64.tar.gz")
        self.assertEqual(miners.pick_asset(self.NAMES, "darwin", "x86_64"), "xmrig-6.22.2-macos-x64.tar.gz")
        self.assertEqual(miners.pick_asset(self.NAMES, "win32", "amd64"), "xmrig-6.22.2-msvc-win64.zip")
        self.assertIsNone(miners.pick_asset(self.NAMES, "linux", "aarch64"))

    def test_expected_hash(self):
        text = "ABC123  a.zip\ndef456 *b.tar.gz\n"
        self.assertEqual(miners.expected_hash(text, "a.zip"), "abc123")
        self.assertEqual(miners.expected_hash(text, "b.tar.gz"), "def456")
        self.assertIsNone(miners.expected_hash(text, "c"))

    def test_sha256(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "f"
            p.write_bytes(b"hello")
            self.assertEqual(miners.sha256_of(p), hashlib.sha256(b"hello").hexdigest())

    def test_build_config(self):
        c = miners.build_config(config.Config(wallet=XMR, worker="rig1", max_threads_percent=50))
        self.assertEqual(c["pools"][0]["user"], XMR)
        self.assertEqual(c["pools"][0]["pass"], "rig1")
        self.assertEqual(c["cpu"]["max-threads-hint"], 50)
        self.assertEqual(c["http"]["host"], "127.0.0.1")


class HardwareTests(unittest.TestCase):
    def test_parsers(self):
        g = hardware.parse_nvidia_smi("NVIDIA GeForce RTX 4070, 12282 MiB\n")
        self.assertEqual((g[0].vendor, g[0].vram_mb), ("nvidia", 12282))
        out = hardware.parse_lspci("03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 48\n00:00.0 Host bridge: x\n")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].vendor, "amd")

    def test_detect_runs(self):
        hw = hardware.detect()
        self.assertGreaterEqual(hw.cpu_threads, 1)


class ProfitTests(unittest.TestCase):
    def test_math(self):
        self.assertAlmostEqual(profit.daily_cost(1000, 0.10), 2.4)
        opt = profit.Option("a", 3.0, 1000)
        self.assertAlmostEqual(profit.daily_profit(opt, 0.10), 0.6)
        self.assertEqual(profit.xmr_revenue_per_day(1, 0, 0.6, 100), 0.0)

    def test_switcher_hysteresis(self):
        a, b = profit.Option("a", 5, 100), profit.Option("b", 5.2, 100)
        sw = profit.Switcher(margin=0.10, hold=3)
        self.assertEqual(sw.update({"a": a, "b": a}, 0.1), "a")
        # b is only ~4% better: never switches
        for _ in range(5):
            self.assertEqual(sw.update({"a": a, "b": b}, 0.1), "a")
        big = profit.Option("b", 8, 100)
        self.assertEqual(sw.update({"a": a, "b": big}, 0.1), "a")
        self.assertEqual(sw.update({"a": a, "b": big}, 0.1), "a")
        self.assertEqual(sw.update({"a": a, "b": big}, 0.1), "b")


if __name__ == "__main__":
    unittest.main()
