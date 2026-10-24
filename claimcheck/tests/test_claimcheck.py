"""Offline protocol self-test: exercises the full pipeline with canned
worker/verifier responses. This validates harness logic only — it makes NO
claims about any real model's hallucination rate."""
import json, tempfile, unittest
import claimcheck as cc

CORPUS = "grantkeeper has 13 unit tests. Its scan command recomputes statuses from dates."

def patch_call(monkey, worker_reply, verifier_reply):
    calls = {"n": 0}
    def fake(model, prompt, timeout=120):
        calls["n"] += 1
        return worker_reply if calls["n"] == 1 else verifier_reply
    monkey(fake)

class LedgerTests(unittest.TestCase):
    def run_one(self, worker_reply, verifier_reply):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            led = f"{tmp}/ledger.json"
            orig = cc.call
            state = {"n": 0}
            def fake(model, prompt, timeout=120):
                state["n"] += 1
                return worker_reply if state["n"] == 1 else verifier_reply
            cc.call = fake
            try:
                res = cc.score_run("mock-model", CORPUS, "any question?", led)
            finally:
                cc.call = orig
            with open(led) as fh:
                m = json.load(fh)["models"]["mock-model"]
            return res, m

    def test_supported_answer_no_deduction(self):
        res, m = self.run_one(
            '{"answer": "grantkeeper has 13 unit tests.", "claims": ["grantkeeper has 13 unit tests."]}',
            '[{"claim": "grantkeeper has 13 unit tests.", "verdict": "supported", "quote": "grantkeeper has 13 unit tests."}]')
        self.assertEqual(res["deduction"], 0)
        self.assertEqual(m["trust"], 100)

    def test_hallucinated_answer_deducts_and_logs(self):
        res, m = self.run_one(
            '{"answer": "grantkeeper costs 20 dollars per month.", "claims": ["grantkeeper costs 20 dollars per month."]}',
            '[{"claim": "grantkeeper costs 20 dollars per month.", "verdict": "unsourced", "quote": ""}]')
        self.assertEqual(res["deduction"], cc.DEDUCT["unsourced"])
        self.assertEqual(m["trust"], 100 - cc.DEDUCT["unsourced"])
        self.assertEqual(m["unsupported"], 1)
        self.assertEqual(m["hallucinated_refusals"], 1)

    def test_correct_refusal_is_free(self):
        res, m = self.run_one(
            '{"answer": "NOT_IN_SOURCE", "claims": []}',
            '[]')
        self.assertTrue(res["refused"])
        self.assertEqual(res["deduction"], 0)
        self.assertEqual(m["correct_refusals"], 1)
        self.assertEqual(m["trust"], 100)

    def test_contradicted_costs_more_than_unsourced(self):
        res, m = self.run_one(
            '{"answer": "grantkeeper has zero tests.", "claims": ["grantkeeper has zero tests."]}',
            '[{"claim": "grantkeeper has zero tests.", "verdict": "contradicted", "quote": "grantkeeper has 13 unit tests."}]')
        self.assertEqual(m["trust"], 100 - cc.DEDUCT["contradicted"])

    def test_cutoff_flag_at_40(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = f"{tmp}/ledger.json"
            orig = cc.call
            state = {"n": 0}
            def fake(model, prompt, timeout=120):
                state["n"] += 1
                if state["n"] % 2 == 1:  # worker call
                    return '{"answer": "grantkeeper is made of cheese.", "claims": ["grantkeeper is made of cheese."]}'
                return '[{"claim": "grantkeeper is made of cheese.", "verdict": "contradicted", "quote": "grantkeeper has 13 unit tests."}]'
            cc.call = fake
            try:
                # 5 runs x -15 contradicted = -75 -> trust 25 (<40 cutoff)
                for _ in range(5):
                    cc.score_run("bad-model", CORPUS, "what is grantkeeper?", led)
            finally:
                cc.call = orig
            with open(led) as fh:
                trust = json.load(fh)["models"]["bad-model"]["trust"]
        self.assertEqual(trust, 25)
        self.assertLess(trust, cc.CUTOFF)

    def test_protocol_failure_fails_closed_with_fixed_penalty(self):
        res, m = self.run_one('garbage no json here at all', 'also garbage')
        self.assertGreaterEqual(res["deduction"], cc.DEDUCT["protocol_failure"])
        self.assertEqual(m["trust"], 100 - res["deduction"])

if __name__ == "__main__":
    unittest.main()
