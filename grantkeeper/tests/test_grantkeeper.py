import json
import tempfile
import unittest
from datetime import date, timedelta

import grantkeeper as gk


class StatusTests(unittest.TestCase):
    ref = date(2026, 10, 24)

    def make(self, **kw):
        grant = {"remind_days_before": 7}
        grant.update(kw)
        return grant

    def test_expired(self):
        self.assertEqual(gk.compute_status(self.make(expires_at="2026-10-23"), self.ref), "expired")

    def test_expiring_inside_window(self):
        self.assertEqual(gk.compute_status(self.make(expires_at="2026-10-29"), self.ref), "expiring")

    def test_valid_outside_window(self):
        self.assertEqual(gk.compute_status(self.make(expires_at="2026-11-23"), self.ref), "valid")

    def test_boundary_exactly_remind_days(self):
        # 7 days left equals remind window -> still valid (>= remind stays valid)
        self.assertEqual(gk.compute_status(self.make(expires_at="2026-10-31"), self.ref), "valid")

    def test_long_lived_is_unknown(self):
        self.assertEqual(gk.compute_status(self.make(expires_at=None), self.ref), "unknown")

    def test_revoked_wins(self):
        self.assertEqual(
            gk.compute_status(self.make(expires_at="2027-01-01", status="revoked"), self.ref), "revoked"
        )

    def test_stored_status_never_trusted(self):
        grant = self.make(expires_at="2026-10-23", status="valid")
        self.assertEqual(gk.compute_status(grant, self.ref), "expired")


class CliTests(unittest.TestCase):
    def run_cli(self, data_path, *argv):
        return gk.main(["--data", data_path] + list(argv))

    def test_add_scan_list_renew_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/credentials.json"
            self.run_cli(path, "add", "Sample git-host deploy token", "--provider", "git-host",
                         "--owner", "Sample CI", "--expires-at", (date.today() + timedelta(days=5)).isoformat(),
                         "--renewal-method", "rotate in provider settings")
            self.run_cli(path, "scan")
            with open(path) as fh: data = json.load(fh)
            self.assertEqual(len(data["grants"]), 1)
            self.assertEqual(data["grants"][0]["status"], "expiring")
            self.assertIsNotNone(data["grants"][0]["last_checked"])
            self.run_cli(path, "renew", "Sample git-host deploy token",
                         "--new-expires", (date.today() + timedelta(days=90)).isoformat(),
                         "--by", "Sample operator")
            with open(path) as fh: data = json.load(fh)
            self.assertEqual(data["grants"][0]["status"], "valid")
            self.assertEqual(data["grants"][0]["grant_date"], date.today().isoformat())
            self.assertEqual(len(data["renewals"]), 1)
            self.assertEqual(data["renewals"][0]["renewed_by"], "Sample operator")

    def test_add_duplicate_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/credentials.json"
            self.run_cli(path, "add", "dup", "--expires-at", "2026-12-01")
            with self.assertRaises(SystemExit):
                self.run_cli(path, "add", "dup", "--expires-at", "2026-12-01")

    def test_corrupt_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/credentials.json"
            with open(path, "w") as fh: fh.write("{not json")
            with self.assertRaises(SystemExit):
                gk.load_data(path)

    def test_invalid_date_fails_closed_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/credentials.json"
            with self.assertRaises(SystemExit) as cm:
                self.run_cli(path, "add", "bad-date grant", "--expires-at", "not-a-date")
            self.assertIn("YYYY-MM-DD", str(cm.exception))
            data = gk.load_data(path)
            self.assertEqual(data["grants"], [])  # nothing written

    def test_invalid_renew_date_fails_closed_and_logs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/credentials.json"
            self.run_cli(path, "add", "grant", "--expires-at", (date.today() + timedelta(days=30)).isoformat())
            with self.assertRaises(SystemExit):
                self.run_cli(path, "renew", "grant", "--new-expires", "31-12-2026")
            with open(path) as fh:
                after = json.load(fh)
            self.assertEqual(after["renewals"], [])  # ledger untouched
            self.assertEqual(after["grants"][0]["grant_date"], date.today().isoformat())  # grant untouched

    def test_renew_missing_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/credentials.json"
            with self.assertRaises(SystemExit):
                self.run_cli(path, "renew", "ghost")


if __name__ == "__main__":
    unittest.main()
