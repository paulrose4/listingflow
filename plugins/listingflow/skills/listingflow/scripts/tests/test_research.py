"""Synthetic keyword research regressions, never live eBay evidence."""

import copy
from datetime import datetime, timedelta, timezone
import unittest

import test_listingflow as base
import quality_fixtures as fixture
from test_reliability import reconcile, claim_review
import listingflow as lf
import lf_research as research
from lf_overview import decision
from lf_excel import tables


def collected(state, pla=True):
    result = fixture.research(state)
    for channel in result["channels"]:
        if channel == "pla" and not pla:
            continue
        url = "https://www.ebay.com/itm/123456789012" if channel == "competitors" else "https://www.ebay.com/"
        item = {"text": "Desk Organizer", "url": url, "relevant": True,
                "reason": "合成测试：品类匹配F1，非真实推荐。"}
        result["channels"][channel][0].update(
            status="collected", evidence_text=f"SYNTHETIC TEST\nDesk Organizer\n{url}", items=[item])
    result["candidates"] = [{"term": "Desk Organizer", "decision": "use", "fact_ids": ["F1"],
                              "reason": "合成测试：采用已知品类，不扩展功能。",
                              "evidence": ["autocomplete:0:0", "competitors:0:0"]}]
    return result


class ResearchCase(unittest.TestCase):
    def setUp(self):
        self.flow = base.FlowCase()
        self.flow.use_v3 = True
        self.flow.setUp()
        self.flow.ingested()
        self.send("freeze", reconcile(self.state(), self.flow.facts_payload()))

    def tearDown(self):
        self.flow.tearDown()

    def state(self):
        return lf.current(self.flow.task)

    def send(self, name, payload):
        return self.flow.command(name, "--json", self.flow.payload(payload))

    def ready(self, payload=None):
        self.send("research", payload or collected(self.state()))
        brief = fixture.brief(self.state())
        brief["primary_keyword"].update(source="ebay_research", reference="合成测试下拉和竞品证据。")
        self.send("brief", brief)
        content = base.fixture_content()
        content["keywords"] = brief["primary_keyword"]
        self.send("save-content", content)
        self.send("review", claim_review(self.state()))

    def exported(self):
        result = self.flow.command("export", "--mode", "draft")
        from pathlib import Path
        return lf.load(Path(result["files"][0]).parent / "export.json")

    def test_new_task_cannot_skip_research(self):
        self.assertEqual(self.state()["research_version"], 1)
        with self.assertRaisesRegex(ValueError, "research before"):
            self.send("brief", fixture.brief(self.state()))
        with self.assertRaisesRegex(ValueError, "research before"):
            self.flow.command("prepare", "--kind", "brief")

    def test_unattempted_channel_cannot_be_saved(self):
        payload = fixture.research(self.state())
        payload["channels"]["pla"] = []
        with self.assertRaisesRegex(ValueError, "actual bounded attempt"):
            self.send("research", payload)

    def test_identity_and_site_must_match(self):
        for key, value in (("sku", "OTHER"), ("site", "DE"), ("language", "de"), ("facts_hash", "wrong")):
            payload = collected(self.state())
            payload[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "does not match"):
                self.send("research", payload)

    def test_foreign_or_lookalike_domain_is_not_evidence(self):
        for url in ("https://www.ebay.de/", "https://ebay.com.evil.test/", "https://user:pw@www.ebay.com/",
                    "http://www.ebay.com/", "https://www.ebay.com:444/"):
            payload = collected(self.state())
            payload["channels"]["pla"][0]["url"] = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "marketplace"):
                self.send("research", payload)

    def test_empty_result_and_fabricated_excerpt_rejected(self):
        payload = collected(self.state())
        payload["channels"]["pla"][0]["items"] = []
        with self.assertRaisesRegex(ValueError, "empty success"):
            self.send("research", payload)
        payload = collected(self.state())
        payload["channels"]["pla"][0]["evidence_text"] = "No such keyword"
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.send("research", payload)

    def test_competitor_needs_observed_item_link(self):
        payload = collected(self.state())
        payload["channels"]["competitors"][0]["items"][0]["url"] = "https://www.ebay.com/itm/999999999999"
        with self.assertRaisesRegex(ValueError, "URL must occur"):
            self.send("research", payload)

    def test_candidate_needs_phrase_and_facts(self):
        for key, value, message in (("term", "Rechargeable", "phrase"),
                                    ("fact_ids", [], "fact references"),
                                    ("evidence", ["pla:1:0"], "collected research")):
            payload = collected(self.state())
            payload["candidates"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                self.send("research", payload)

    def test_irrelevant_sources_cannot_justify_adoption(self):
        payload = collected(self.state())
        for channel in payload["channels"].values():
            channel[0]["items"][0]["relevant"] = False
        with self.assertRaisesRegex(ValueError, "irrelevant"):
            self.send("research", payload)

    def test_future_and_naive_observation_rejected(self):
        for timestamp in ("2026-09-16T01:00:00", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()):
            payload = collected(self.state())
            payload["channels"]["pla"][0]["observed_at"] = timestamp
            with self.assertRaisesRegex(ValueError, "timestamp"):
                self.send("research", payload)

    def test_optout_needs_user_instruction(self):
        payload = fixture.research(self.state())
        payload["channels"]["pla"][0]["status"] = "declined"
        with self.assertRaisesRegex(ValueError, "actual user instruction"):
            self.send("research", payload)
        payload["channels"]["pla"][0]["method"] = "user_instruction"
        self.send("research", payload)

    def test_adopted_evidence_cannot_be_ignored_in_primary(self):
        self.send("research", collected(self.state()))
        brief = fixture.brief(self.state())
        with self.assertRaisesRegex(ValueError, "silently fall back"):
            self.send("brief", brief)
        brief["primary_keyword"].update(source="ebay_research", primary="Unknown invented keyword")
        with self.assertRaisesRegex(ValueError, "adopted"):
            self.send("brief", brief)

    def test_blocked_collection_still_allows_honest_draft(self):
        self.send("research", fixture.research(self.state()))
        self.send("brief", fixture.brief(self.state()))
        self.send("save-content", base.fixture_content())
        self.send("review", claim_review(self.state()))
        request = self.exported()
        rows = {r["id"]: r for r in request["checks"]["results"]}
        self.assertEqual(rows["research.current"]["status"], "PASS")
        self.assertEqual(rows["keywords.live_data"]["status"], "NEEDS_REVIEW")
        model = decision(request)
        self.assertEqual(len([a for a in model["actions"] if a["kind"] == "research"]), 3)
        self.assertFalse(any(row[0] == "实时搜索数据" for row in model["optional"]))

    def test_partial_success_is_not_full_pass_or_all_unverified(self):
        self.ready(collected(self.state(), pla=False))
        request = self.exported()
        rows = {r["id"]: r for r in request["checks"]["results"]}
        self.assertEqual(rows["research.autocomplete"]["status"], "PASS")
        self.assertEqual(rows["research.pla"]["status"], "NEEDS_REVIEW")
        self.assertEqual(rows["checklist.local.search_data"]["status"], "NEEDS_REVIEW")
        actions = [a for a in decision(request)["actions"] if a["kind"] == "research"]
        self.assertEqual(len(actions), 1)
        self.assertIn("PLA", actions[0]["title"])
        self.assertIn("已取得", rows["keywords.live_data"]["reason"])

    def test_complete_result_used_in_context_and_report(self):
        self.ready()
        request = self.exported()
        self.assertTrue(research.current_report(request))
        self.assertEqual(request["research_hash"], self.state()["research_hash"])
        context = self.flow.command("context")
        self.assertEqual(context["research_hash"], request["research_hash"])
        rows = {r["id"]: r for r in request["checks"]["results"]}
        self.assertEqual(rows["keywords.live_data"]["status"], "PASS")
        self.assertIn("不是搜索量", rows["keywords.live_data"]["reason"])
        localization = next(s[2] for s in tables(request)["自查"] if s[0] == "本地化自查表")
        candidate = next(r for r in localization if r[0] == "候选词：Desk Organizer")
        self.assertIn("标题", candidate[3])
        self.assertIn("1/1", candidate[4])

    def test_research_refresh_invalidates_approval_brief_review(self):
        self.ready()
        state = self.state()
        old = copy.deepcopy(state["contents"][-1])
        payload = copy.deepcopy(state["research"])
        payload["channels"]["pla"][0]["reason"] += " Updated synthetic query."
        self.send("research", payload)
        checks = lf.build_checks(self.state(), self.state()["contents"][-1])
        self.assertGreater(checks["blocking_count"], 0)
        with self.assertRaisesRegex(ValueError, "Research changed"):
            self.send("save-content", old["content"])
        with self.assertRaisesRegex(ValueError, "Research changed"):
            self.send("review", old["review"])
        exported = self.exported()
        self.assertFalse(research.current_report(exported))
        self.assertIn("未完成", decision(exported)["copy_status"])

    def test_same_copy_new_research_creates_new_version(self):
        self.ready()
        state = self.state()
        payload = copy.deepcopy(state["research"])
        payload["channels"]["pla"][0]["reason"] += " Refreshed sample."
        self.send("research", payload)
        brief = copy.deepcopy(state["brief"])
        brief["research_hash"] = self.state()["research_hash"]
        self.send("brief", brief)
        result = self.send("save-content", state["contents"][-1]["content"])
        self.assertEqual(result["content_version"], 2)
        self.assertIsNone(self.state()["contents"][-1]["review"])

    def test_duplicate_listing_urls_do_not_inflate_frequency(self):
        self.ready()
        request = self.exported()
        payload = request["research"]
        attempt = payload["channels"]["competitors"][0]
        duplicate = copy.deepcopy(attempt["items"][0])
        duplicate["url"] += "?tracking=another"
        attempt["items"].append(duplicate)
        attempt["evidence_text"] += "\n" + duplicate["url"]
        self.send("research", payload)
        request["research_hash"] = lf.digest(payload)
        request["checks"]["research_hash"] = request["research_hash"]
        rows = research.reference_rows(request)
        self.assertIn("1/1", next(r[4] for r in rows if r[0].startswith("候选词：")))

    def test_old_record_does_not_gain_research_pass(self):
        state = self.state()
        state.pop("research_version")
        self.assertEqual(research.checks(state, {}), [])

    def test_unbound_competitor_label_cannot_bypass_evidence(self):
        self.send("research", fixture.research(self.state()))
        brief = fixture.brief(self.state())
        brief["primary_keyword"]["source"] = "public_competitor"
        with self.assertRaisesRegex(ValueError, "unbound public_competitor"):
            self.send("brief", brief)

    def test_retry_success_resolves_same_query_but_preserves_other_failure(self):
        payload = collected(self.state())
        failed = copy.deepcopy(payload["channels"]["pla"][0])
        failed.update(status="error", items=[], reason="Earlier synthetic error")
        payload["channels"]["pla"].insert(0, failed)
        self.ready(payload)
        request = self.exported()
        self.assertTrue(research.coverage(payload)["pla"]["complete"])
        self.assertFalse(any(a["kind"] == "research" for a in decision(request)["actions"]))
        failed["query"] = "Another query"
        payload["channels"]["pla"].append(failed)
        self.assertFalse(research.coverage(payload)["pla"]["complete"])

    def test_distinct_listings_with_same_title_remain_distinct_samples(self):
        payload = collected(self.state())
        attempt = payload["channels"]["competitors"][0]
        second = copy.deepcopy(attempt["items"][0])
        second["url"] = "https://www.ebay.com/itm/223456789012"
        attempt["items"].append(second)
        attempt["evidence_text"] += "\n" + second["url"]
        research.validate(payload, self.state())
        self.assertEqual(research.coverage(payload)["competitors"]["status"], "已取得2条")

    def test_missing_copy_review_does_not_expire_completed_research(self):
        self.ready()
        state = self.state()
        content = copy.deepcopy(state["contents"][-1]["content"])
        content["description"][0]["text"] += " Synthetic wording change."
        self.send("save-content", content)
        request = self.exported()
        local = next(s[2] for s in tables(request)["自查"] if s[0] == "本地化自查表")
        row = next(r for r in local if r[0] == "关键词参考来源是否齐全？")
        self.assertEqual(row[1], "✓ 已核对")
        self.assertFalse(decision(request)["current"])


if __name__ == "__main__":
    unittest.main()
