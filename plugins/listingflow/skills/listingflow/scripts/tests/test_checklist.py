"""Checklist scope, honest statuses, and rule-to-row traceability."""

import copy
import unittest

import test_listingflow as base
import lf_checklist as checklist


class ChecklistCase(unittest.TestCase):
    def setUp(self):
        self.content = base.fixture_content()
        self.paths = list(checklist.content_texts(self.content))
        self.review = {"operator_checklist": checklist.template()}
        for item in self.review["operator_checklist"].values():
            item.update(reason="测试：本项尚未检查。", action="先检查。")

    def complete(self, key):
        self.review["operator_checklist"][key].update(
            status="PASS", paths=self.paths,
            examples=[{"path": "title", "quote": self.content["title"]["text"]}],
            reason="合成用例的当前原句核对记录。", action="无待办。")

    def request(self):
        checks = checklist.checks({"workflow_version": 3}, {"review": self.review, "content": self.content})
        return {"content": self.content, "checks": {"results": checks}, "review": self.review,
                "sku": "000123", "site": "US", "language": "en", "rule_catalog": []}

    def test_legacy_review_is_not_implicitly_passed(self):
        checks = checklist.checks({"workflow_version": 3, "checklist_version": 1},
                                 {"content": self.content, "review": {}})
        self.assertEqual(len(checks), len(checklist.ITEMS))
        self.assertTrue(all(r["status"] == "NOT_CHECKED" for r in checks))
        self.assertTrue(any(r["severity"] == "blocking" for r in checks))

    def test_old_workflow_unchanged(self):
        self.assertEqual(checklist.checks({"workflow_version": 2}, {}), [])

    def test_template_never_fills_pass(self):
        self.assertTrue(all(i["status"] == "NOT_CHECKED" for i in checklist.template().values()))

    def test_null_rejected_without_crashing_checks_or_report(self):
        self.review["operator_checklist"] = None
        with self.assertRaisesRegex(ValueError, "all four"):
            checklist.validate(self.review, self.content)
        request = self.request()
        self.assertTrue(all(r["status"] == "NOT_CHECKED" for r in request["checks"]["results"]))
        self.assertTrue(checklist.tables(request))

    def test_external_pass_needs_source_not_copy(self):
        for key in ("ip.visual", "local.search_data"):
            with self.subTest(key=key):
                self.complete(key)
                with self.assertRaisesRegex(ValueError, "actual source evidence"):
                    checklist.validate(self.review, self.content)
                self.review["operator_checklist"][key]["status"] = "NOT_CHECKED"

    def test_external_evidence_quote_must_exist(self):
        self.complete("local.search_data")
        state = {"sources": [{"units": [{"id": "S1:U1", "text": "Search term sample", "kind": "cell"}]}]}
        item = self.review["operator_checklist"]["local.search_data"]
        item["evidence"] = [{"source_id": "S1:U1", "quote": "invented metrics", "scope": "US sample only"}]
        with self.assertRaisesRegex(ValueError, "does not exist"):
            checklist.validate(self.review, self.content, state)
        item["evidence"][0]["quote"] = "Search term sample"
        checklist.validate(self.review, self.content, state)

    def test_specification_name_can_be_reviewed_and_displayed(self):
        self.content["specs"][0]["name"] = "luxury"
        self.complete("compliance.superlative")
        item = self.review["operator_checklist"]["compliance.superlative"]
        item.update(status="FAIL", examples=[{"path": "specs.0.name", "quote": "luxury"}])
        checklist.validate(self.review, self.content)
        request = self.request()
        request["rule_catalog"] = [{"id": "R-2", "raw": "luxury", "group": "general_banned", "sources": []}]
        request["checks"]["results"].append(
            {"id": "R-2", "status": "FAIL", "path": "specs.0.name", "excerpt": "luxury", "reason": "Hit"})
        rows = next(s[2] for s in checklist.tables(request) if s[0] == "违禁词自查表")
        row = next(r for r in rows if r[0] == "luxury")
        self.assertEqual(row[3], "命中：luxury\nluxury")
        self.assertIn("名称", row[2])

    def test_manual_review_keeps_its_scope(self):
        request = self.request()
        request["rule_catalog"] = [{"id": "R-3", "raw": "Image check", "group": "ebay_ip", "sources": []}]
        request["checks"]["results"].append(
            {"id": "R-3", "status": "PASS", "path": "rules", "reason": "Image scope only",
             "method": "explicit_rule_review"})
        rows = next(s[2] for s in checklist.tables(request) if s[0] == "侵权词自查表")
        row = next(r for r in rows if r[0] == "Image check")
        self.assertNotIn("精确匹配", row[1])
        self.assertNotIn("全部成品", row[2])
        self.assertIn("Image scope only", row[4])

    def test_missing_specific_review_rejected(self):
        del self.review["operator_checklist"]["ip.event"]
        with self.assertRaisesRegex(ValueError, "all four"):
            checklist.validate(self.review, self.content)

    def test_fabricated_quote_rejected(self):
        self.complete("local.title")
        self.review["operator_checklist"]["local.title"]["examples"][0]["quote"] = "Invented claim"
        with self.assertRaisesRegex(ValueError, "quote current"):
            checklist.validate(self.review, self.content)

    def test_title_only_cannot_pass_full_compliance(self):
        self.complete("compliance.medical")
        self.review["operator_checklist"]["compliance.medical"]["paths"] = ["title"]
        with self.assertRaisesRegex(ValueError, "required content scope"):
            checklist.validate(self.review, self.content)

    def test_example_outside_review_scope_rejected(self):
        self.complete("local.bullets")
        self.review["operator_checklist"]["local.bullets"]["paths"] = [p for p in self.paths if p.startswith("bullets.")]
        with self.assertRaisesRegex(ValueError, "within its scope"):
            checklist.validate(self.review, self.content)

    def test_no_evidence_cannot_pass(self):
        self.complete("ip.brand")
        self.review["operator_checklist"]["ip.brand"]["examples"] = []
        with self.assertRaisesRegex(ValueError, "actual text"):
            checklist.validate(self.review, self.content)

    def test_live_search_unchecked_is_not_a_text_failure(self):
        result = next(r for r in self.request()["checks"]["results"] if r["id"] == "checklist.local.search_data")
        self.assertEqual(result["status"], "NOT_CHECKED")
        self.assertEqual(result["severity"], "info")

    def test_visual_rights_not_inferred_from_word_scan(self):
        request = self.request()
        rows = next(s[2] for s in checklist.tables(request) if s[0] == "侵权词自查表")
        self.assertEqual(next(r[1] for r in rows if r[0] == "图片与外观授权范围"), "未检查")

    def test_rule_statuses_and_sources_remain_distinct(self):
        request = self.request()
        rule = {"id": "R-1", "raw": "Example Brand", "group": "general_ip",
                "sources": [{"file": "词库.xlsx", "locator": "Sheet1!A2"}]}
        request["rule_catalog"] = [rule]
        request["checks"]["results"].append(
            {"id": "R-1", "status": "PASS", "path": "content", "reason": "Exact scan"})
        rows = next(s[2] for s in checklist.tables(request) if s[0] == "侵权词自查表")
        row = next(r for r in rows if r[0] == "Example Brand")
        self.assertIn("未命中（精确匹配）", row[1])
        self.assertIn("Sheet1!A2", row[4])
        request["checks"]["results"][-1].update(status="NEEDS_REVIEW", path="rules")
        row = next(r for s in checklist.tables(request) if s[0] == "侵权词自查表" for r in s[2] if r[0] == "Example Brand")
        self.assertEqual(row[1], "待确认")
        self.assertNotIn("✓", row[1])

    def test_each_hit_keeps_its_location(self):
        request = self.request()
        request["rule_catalog"] = [{"id": "R-2", "raw": "desk", "group": "general_banned", "sources": []}]
        for path in ("title", "bullets.0"):
            request["checks"]["results"].append(
                {"id": "R-2", "status": "FAIL", "path": path, "excerpt": "desk", "reason": "Hit"})
        rows = next(s[2] for s in checklist.tables(request) if s[0] == "违禁词自查表")
        hits = [r for r in rows if r[0] == "desk"]
        self.assertEqual(len(hits), 2)
        self.assertNotEqual(hits[0][2], hits[1][2])
        self.assertTrue(all(r[1] == "✗ 需修改" for r in hits))

    def test_missing_catalog_does_not_look_like_zero_risk(self):
        sheets = checklist.tables(self.request())
        self.assertTrue(all(any(r[0] == "词库逐项检查" and r[1] == "未检查" for r in s[2]) for s in sheets[:2]))

    def test_frequency_does_not_depend_on_manual_claim(self):
        content = copy.deepcopy(self.content)
        content["title"]["text"] = "Mask mask MASK"
        content["bullets"][0]["text"] = "Mask"
        self.assertIn("mask: 标题3 / 五点1", checklist.word_counts(content))

    def test_fail_survives_report_projection(self):
        self.complete("compliance.superlative")
        self.review["operator_checklist"]["compliance.superlative"]["status"] = "FAIL"
        rows = next(s[2] for s in checklist.tables(self.request()) if s[0] == "文案合规自查表")
        self.assertEqual(next(r[1] for r in rows if r[0] == "夸大词与绝对承诺"), "✗ 需修改")
