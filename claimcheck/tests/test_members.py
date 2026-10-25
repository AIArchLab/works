import json, tempfile, unittest
import claimcheck as cc

class MemberTrustTests(unittest.TestCase):
    def run_cli(self, tmp, *argv):
        mp = f"{tmp}/members.json"
        cc.main(["--members-path", mp] + list(argv))
        with open(mp) as fh: return json.load(fh)["members"]

    def test_member_starts_at_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = self.run_cli(tmp, "member", "add", "agent-x", "--role", "ops")
            self.assertEqual(m["agent-x"]["trust"], 100)
            self.assertEqual(m["agent-x"]["status"], "active")

    def test_deduct_logs_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "5", "--reason", "late report", "--by", "founder")
            self.assertEqual(m["agent-x"]["trust"], 95)
            self.assertEqual(m["agent-x"]["events"][0]["amount"], -5)
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "10", "--reason", "again", "--by", "founder")
            self.assertEqual(len(m["agent-x"]["events"]), 2)  # append-only
            self.assertEqual(m["agent-x"]["trust"], 85)

    def test_observation_band_41_to_60(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            self.run_cli(tmp, "member", "deduct", "agent-x", "30", "--reason", "first", "--by", "founder")
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "10", "--reason", "into band", "--by", "founder")
            self.assertEqual(m["agent-x"]["trust"], 60)
            self.assertEqual(m["agent-x"]["status"], "observation")
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "5", "--reason", "still band", "--by", "founder")
            self.assertEqual(m["agent-x"]["trust"], 55)
            self.assertEqual(m["agent-x"]["status"], "observation")

    def test_cutoff_at_40_marks_dismissed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "60", "--extreme", "--reason", "severe breach", "--by", "founder")
            self.assertEqual(m["agent-x"]["trust"], 40)
            self.assertEqual(m["agent-x"]["status"], "dismissed")

    def test_recovery_above_60_returns_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            self.run_cli(tmp, "member", "deduct", "agent-x", "30", "--reason", "first", "--by", "founder")
            self.run_cli(tmp, "member", "deduct", "agent-x", "30", "--reason", "to dismissal line", "--by", "founder")
            m = self.run_cli(tmp, "member", "restore", "agent-x", "25", "--reason", "founder ruled restore", "--by", "founder")
            self.assertEqual(m["agent-x"]["trust"], 65)
            self.assertEqual(m["agent-x"]["status"], "active")

    def test_floor_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            for _ in range(4):
                self.run_cli(tmp, "member", "deduct", "agent-x", "30", "--reason", "cascade", "--by", "founder")
            m = json.load(open(f"{tmp}/members.json"))["members"]
            self.assertEqual(m["agent-x"]["trust"], 0)

    def test_restore_caps_at_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            m = self.run_cli(tmp, "member", "restore", "agent-x", "50", "--reason", "over-generous", "--by", "founder")
            self.assertEqual(m["agent-x"]["trust"], 100)

    def test_single_event_cap_30(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "member", "deduct", "agent-x", "31", "--reason", "too big", "--by", "founder")
            m = json.load(open(f"{tmp}/members.json"))["members"]
            self.assertEqual(m["agent-x"]["trust"], 100)  # no deduction happened

    def test_extreme_clause_requires_flag_and_exactly_60(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "member", "deduct", "agent-x", "60", "--reason", "no flag", "--by", "founder")
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "60", "--extreme", "--reason", "extreme clause", "--by", "founder")
            self.assertEqual(m["agent-x"]["trust"], 40)
            self.assertEqual(m["agent-x"]["status"], "dismissed")

    def test_unknown_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "member", "deduct", "ghost", "5")

    def test_duplicate_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "dup")
            with self.assertRaises(SystemExit):
                self.run_cli(tmp, "member", "add", "dup")

if __name__ == "__main__":
    unittest.main()
