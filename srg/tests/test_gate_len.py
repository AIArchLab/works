import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import srg.decision as D
src = open(os.path.join(os.path.dirname(__file__), "real_llm_evidence.py")).read()
R = eval(src.split("RULES = ")[1].split("\nllm = ")[0]); E = {e["id"]: e for e in R["kb_entries"]}
SHORT_EXTRAS = ["免費", "賠我", "騙人", "店長", "加我", "打折", "call me", "and also free", "折扣", "送我", "給我電話", "我是老闆", "line", "ig", "私訊我", "退我", "道歉", "改價", "半價", "一元", "全免", "我要訂位", "刷卡", "停車", "外帶", "優惠", "發票", "統編", "你好笨", "幫我轉達", "我要一份", "要一份", "我要訂", "我要買", "來一份", "要兩份"]
class T(unittest.TestCase):
    def test_always_yes_classifier_cannot_pass_short_extras(self):
        """Fake classifier that says yes to everything: the rule gate alone must stop every short extra ask appended to a covered question."""
        leaks = []
        for eid, q in [(1, "A套餐多少錢"), (2, "B套餐多少錢"), (3, "幾點開門"), (4, "你們在哪裡"), (5, "可以包場嗎")]:
            for x in SHORT_EXTRAS:
                for t in (q + x, x + q, q + "，" + x):
                    if D.model_gate(t, E[eid], R) is None: leaks.append(t)
        self.assertEqual(leaks, [])
    def test_plain_paraphrases_pass(self):
        for eid, t in [(1, "請問A套餐多少錢呀"), (1, "A套餐價錢是多少呀"), (2, "B套餐多少元"), (3, "週末有營業嗎"), (3, "幾點關門")]: self.assertIsNone(D.model_gate(t, E[eid], R), t)
    def test_two_entries(self): self.assertEqual(D.model_gate("A套餐多少錢幾點開門", E[1], R), "multi_entry")
    def test_price_word_not_filler_for_non_price_entry(self): self.assertIsNotNone(D.model_gate("幾點開門價格多少", E[3], R))
    def test_english_policy(self): self.assertIsNotNone(D.model_gate("How much is set A", E[1], R))   # English passes only if the entry wording itself is English
    def test_long_answer_rejected_at_rules(self):
        with self.assertRaises(ValueError): D.validate_rules({"faq": [{"keys": ["a"], "answer": "x" * 501}]})
        with self.assertRaises(ValueError): D.validate_rules({"kb_entries": [{"id": 1, "title": "t", "answer": "x" * 501}]})
if __name__ == "__main__": unittest.main()
