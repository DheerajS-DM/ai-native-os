"""Unit tests for Nexus modules."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import safeguard
from safeguard import Verdict, SafeguardState
import context
import stats
import agent

class TestSafeguard(unittest.TestCase):
    def setUp(self):
        self.state = SafeguardState()

    def test_read_only_allowed(self):
        allowed = ["ls", "cat /home/user/file.txt", "uptime", "free -m", "ps aux", "grep 'foo' bar.txt"]
        for cmd in allowed:
            v, reason = safeguard.check(cmd, self.state)
            self.assertEqual(v, Verdict.ALLOW, f"Failed on {cmd}: {reason}")

    def test_always_blocked(self):
        blocked = [
            "rm -rf /",
            "rm -fr /home/user",
            "rm --recursive /",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "fdisk /dev/sdb",
            "shutdown -h now",
            "reboot",
            "iptables -F",
            "chmod 777 /",
        ]
        for cmd in blocked:
            state = SafeguardState()
            v, reason = safeguard.check(cmd, state)
            self.assertEqual(v, Verdict.BLOCK, f"Failed on {cmd}: {reason}")

    def test_system_path_blocked(self):
        sys_blocked = [
            "touch /etc/passwd",
            "rm /usr/bin/python3",
            "cp myfile /boot/vmlinuz",
            "mkdir /var/test",
        ]
        for cmd in sys_blocked:
            state = SafeguardState()
            v, reason = safeguard.check(cmd, state)
            self.assertEqual(v, Verdict.BLOCK, f"Failed on {cmd}: {reason}")

    def test_redirect_to_system_path_blocked(self):
        sys_redirects = [
            "echo 'hacked' > /etc/shadow",
            "echo 'evil' >> /usr/lib/test",
        ]
        for cmd in sys_redirects:
            state = SafeguardState()
            v, reason = safeguard.check(cmd, state)
            self.assertIn(v, (Verdict.BLOCK, Verdict.CONFIRM), f"Failed on {cmd}: {reason}")

    def test_write_commands_require_confirm(self):
        user_writes = [
            "touch ~/myfile.txt",
            "rm ~/temp.log",
            "mkdir ~/newdir",
            "cp ~/a ~/b",
        ]
        for cmd in user_writes:
            v, reason = safeguard.check(cmd, self.state)
            self.assertEqual(v, Verdict.CONFIRM, f"Failed on {cmd}: {reason}")

    def test_lockout_after_violations(self):
        for i in range(5):
            safeguard.check("rm -rf /", self.state)
        self.assertTrue(self.state.is_locked())
        v, _ = safeguard.check("ls", self.state)
        self.assertEqual(v, Verdict.LOCKED)
        self.state.reset()
        self.assertFalse(self.state.is_locked())
        v, _ = safeguard.check("ls", self.state)
        self.assertEqual(v, Verdict.ALLOW)

class TestContext(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_context.db"
        self.orig_db_path = context.DB_PATH
        context.DB_PATH = self.db_path

    def tearDown(self):
        context.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    def test_seed_and_instructions(self):
        context.seed_instructions()
        instr = context.get_instructions()
        self.assertGreater(len(instr), 0)
        self.assertEqual(instr[0]["role"], "system")

    def test_messages(self):
        context.append("user", "Hello agent")
        context.append("assistant", "Hello user")
        recent = context.get_recent(10)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["role"], "user")
        self.assertEqual(recent[0]["content"], "Hello agent")
        self.assertEqual(recent[1]["role"], "assistant")
        self.assertEqual(recent[1]["content"], "Hello user")

        context.clear_conversation()
        self.assertEqual(len(context.get_recent(10)), 0)

    def test_assistant_identity_nexus(self):
        context.seed_instructions()
        instr = context.get_instructions()
        self.assertTrue(any("Nexus" in i["content"] for i in instr))

class TestStats(unittest.TestCase):
    def test_snapshot_structure(self):
        snap = stats.snapshot()
        self.assertIn("ram_current_mb", snap)
        self.assertIn("ram_max_mb", snap)
        self.assertIn("vram_used_mb", snap)
        self.assertIn("gpu_temp_c", snap)
        self.assertIn("cpu_temp_c", snap)
        self.assertIn("tokens_total", snap)

class TestAgentExtraction(unittest.TestCase):
    def test_extract_command(self):
        reply1 = "I will check the files: <cmd>ls -la</cmd>"
        cmd, confirm = agent._extract_command(reply1)
        self.assertEqual(cmd, "ls -la")
        self.assertFalse(confirm)

        reply2 = "I need to remove the temp file: <cmd confirm>rm ~/temp.txt</cmd>"
        cmd, confirm = agent._extract_command(reply2)
        self.assertEqual(cmd, "rm ~/temp.txt")
        self.assertTrue(confirm)

        reply3 = "No command here."
        cmd, confirm = agent._extract_command(reply3)
        self.assertIsNone(cmd)
        self.assertFalse(confirm)

if __name__ == "__main__":
    unittest.main()
