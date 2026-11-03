"""REAL AI generation (Qwen2.5-1.5B-Instruct GGUF, local) through the real pipeline; the platform send endpoint is still a local mock.
Skipped when llama_cpp or the model file is unavailable. Run with the venv that has llama-cpp-python."""
import os, unittest, sys
sys.path.insert(0, os.path.dirname(__file__))
MODEL = os.environ.get("SRG_MODEL", "models/q15.gguf")
try: import llama_cpp; OK = os.path.exists(MODEL)
except ImportError: OK = False
from test_e2e import Store, Mock, Pipeline, make_adapters, CFG, fb_comment, fb_sig
OLD = "營業時間：每天 10:00-20:00（含週末）\n地址：台北市信義區\n包場：可預約，請私訊日期與人數，由店長確認\n付款方式：未提供資訊"
@unittest.skipUnless(OK, "local model not available")
class RealLLM(unittest.TestCase):
    def setUp(s):
        s.st = Store(); s.st.add_rules({"kb_entries": [{"id": 5, "title": "包場預約", "examples": ["可以包場嗎", "怎麼預約包場"], "answer": "可預約包場，請私訊日期與人數，由店長確認。"}, {"id": 3, "title": "營業時間", "examples": ["週末有開嗎"], "answer": "每天 10:00-20:00 營業。"}]}); s.mock = Mock()
        s.pipe = Pipeline(s.st, make_adapters(CFG), {"facebook": s.mock.url}, llm={"provider": "llama_cpp", "model_path": MODEL})
    def run_one(s, cid, text):
        b = fb_comment(cid, text); c, ids = s.pipe.ingest("facebook", fb_sig(b), b); s.pipe.process(ids[0]); return s.st.rows("select * from events where id=?", (ids[0],))[0]
    def test_grounded_reply_sent(s):
        ev = s.run_one("r1", "可以包場嗎"); print("\n[real LLM]", ev["status"], ev["decided_by"], ev["reply"])
        s.assertEqual(ev["status"], "sent"); s.assertTrue(ev["decided_by"].startswith("local:")); s.assertEqual(ev["reply"], "可預約包場，請私訊日期與人數，由店長確認。")
    def test_unknown_goes_handoff(s):
        for i, q in enumerate(["你們老闆幾歲", "可以刷卡嗎？", "我要退款"]):
            ev = s.run_one(f"h{i}", q); print("[real LLM]", q, ev["status"]); s.assertEqual(ev["status"], "handoff")
        s.assertEqual(s.mock.calls, [])
if __name__ == "__main__": unittest.main()
