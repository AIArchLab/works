import json, os, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def run(cfg):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); json.dump(cfg, f); f.close()
    try: return subprocess.run([sys.executable, "-m", "srg"], cwd=ROOT, env=dict(os.environ, SRG_CONFIG=f.name), capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired: return None   # server started = accepted
class T(unittest.TestCase):
    def rejected(self, cfg, word):
        r = run(cfg); self.assertIsNotNone(r, "server started with bad config"); self.assertNotEqual(r.returncode, 0); self.assertIn(word, r.stderr)
    def test_placeholder_admin(self): self.rejected({"admin_token": "CHANGE_ME", "platforms": {}}, "admin_token")
    def test_placeholder_verify(self): self.rejected({"admin_token": "a"*24, "verify_token": "CHANGE_ME", "platforms": {}}, "verify_token")
    def test_placeholder_platform(self): self.rejected({"admin_token": "a"*24, "platforms": {"line": {"channel_secret": "CHANGE_ME_secret"}}}, "placeholder")
    def test_missing_admin(self): self.rejected({"platforms": {}}, "admin_token")
    def test_example_rejected(self):
        r = subprocess.run([sys.executable, "-m", "srg"], cwd=ROOT, env=dict(os.environ, SRG_CONFIG=os.path.join(ROOT, "config.example.json")), capture_output=True, text=True, timeout=5); self.assertNotEqual(r.returncode, 0)
if __name__ == "__main__": unittest.main()
