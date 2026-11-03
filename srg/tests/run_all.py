"""Runs all tests and writes verification.json from REAL results only. Layer A (real platform) is never written here: it stays 'untested'."""
import unittest, json, time, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import test_e2e
res = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(test_e2e))
def result_of(*names):
    """pass only if every named test ran and passed"""
    ran = {t for t in unittest.defaultTestLoader.getTestCaseNames(getattr(test_e2e, "Base")) } 
    failed = {t.id().split(".")[-1] for t, _ in res.failures + res.errors}
    allnames = {}
    for cname in dir(test_e2e):
        c = getattr(test_e2e, cname)
        if isinstance(c, type) and issubclass(c, unittest.TestCase) and c is not unittest.TestCase:
            for n in unittest.defaultTestLoader.getTestCaseNames(c): allnames[n] = cname
    missing = [n for n in names if n not in allnames]
    if missing: return "untested (no test: %s)" % ",".join(missing)
    bad = [n for n in names if n in failed]
    return "FAILING: " + ",".join(bad) if bad else "mock-tests-pass"
M = {
 "facebook": {"comment_receive": ["test_fb_comment_to_sent_and_traceable", "test_fb_own_page_comment_does_not_loop", "test_fb_non_comment_feed_items_dropped", "test_fb_duplicate_delivery_single_reply", "test_fb_bad_signature_rejected_and_logged"],
              "comment_thread_reply": ["test_fb_comment_reply_disabled_by_default", "test_fb_unverified_flag_refused_for_non_loopback_target"], "dm": ["test_fb_dm_send_unsupported_goes_failed_config_not_guessed_endpoint"]},
 "instagram": {"comment_receive": ["test_ig_comment_reply_uses_replies_endpoint", "test_ig_comment_without_from_is_visible_not_silent"], "comment_reply": ["test_ig_comment_reply_uses_replies_endpoint"],
               "dm_receive_reply": ["test_ig_dm_endpoint_bearer_header_no_token_in_body", "test_ig_echo_and_self_messages_dropped"], "private_reply": ["test_not_implemented"]},
 "line": {"dm_receive_reply": ["test_line_reply_uses_token", "test_line_bad_signature", "test_line_dedupe_by_webhook_event_id_and_missing_userid", "test_line_without_reply_token_never_pushes", "test_line_non_text_recorded_not_replied"],
          "group_reply": ["test_line_group_not_answered_by_default_but_recorded"], "push_fallback": ["test_line_without_reply_token_never_pushes"]},
 "tiktok": {"comment_reply": ["test_tiktok_signature_t_s_and_stale_rejected", "test_tiktok_reply_shape"]}}
out = {"_ts": time.strftime("%Y-%m-%d %H:%M:%S"), "_total": res.testsRun, "_ok": res.wasSuccessful()}
for p, caps in M.items(): out[p] = {c: result_of(*ns) for c, ns in caps.items()}
json.dump(out, open(os.path.join(os.path.dirname(__file__), "..", "verification.json"), "w"), indent=1, ensure_ascii=False)
sys.exit(0 if res.wasSuccessful() else 1)
