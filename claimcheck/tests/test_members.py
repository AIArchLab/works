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
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "5", "--reason", "late report", "--by", "chair")
            self.assertEqual(m["agent-x"]["trust"], 95)
            self.assertEqual(m["agent-x"]["events"][0]["amount"], -5)
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "10", "--reason", "again", "--by", "chair")
            self.assertEqual(len(m["agent-x"]["events"]), 2)  # append-only
            self.assertEqual(m["agent-x"]["trust"], 85)

    def test_cutoff_at_40_marks_dismissed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "60", "--reason", "severe breach", "--by", "chair")
            self.assertEqual(m["agent-x"]["trust"], 40)
            self.assertEqual(m["agent-x"]["status"], "dismissed")

    def test_floor_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "member", "add", "agent-x")
            m = self.run_cli(tmp, "member", "deduct", "agent-x", "200", "--reason", "catastrophic", "--by", "chair")
            self.assertEqual(m["agent-x"]["trust"], 0)

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
