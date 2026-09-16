"""Decision summary regressions; synthetic states do not approve real copy."""

import copy
import unittest

import test_listingflow as base
from lf_checklist import ITEMS
from lf_overview import decision, tables
from lf_rules import content_blocks, digest


def request_fixture():
    content = base.fixture_content()
    checks = [{"id": "bundle.approval", "status": "PASS", "severity": "blocking",
               "path": "rules", "reason": "Synthetic approval."}]
    checks += [{"id": "semantic." + p, "status": "PASS", "severity": "blocking",
                "path": p, "reason": "Synthetic semantic review."} for p, _ in content_blocks(content)]
    checks += [{"id": "checklist." + key, "status": "PASS", "severity": severity,
                "path": "checklist." + key, "reason": "Synthetic checklist."}
               for key, (_, _, severity) in ITEMS.items()]
    return {"content": content, "content_hash": digest(content), "bundle_hash": "bundle",
            "brief_hash": "brief", "sku": "000123", "site": "US", "language": "en", "version": 1,
            "mode": "draft", "created": "2026-09-16T00:00:00+00:00", "approval": None,
            "checks": {"content_hash": digest(content), "bundle_hash": "bundle", "results": checks},
            "review": {"content_hash": digest(content), "brief_hash": "brief", "operator_checklist": {}},
            "facts": {"facts": [], "reconciliation": []}, "rule_catalog": []}


class OverviewCase(unittest.TestCase):
    def setUp(self):
        self.request = request_fixture()

    def change(self, key, status, reason="Synthetic changed result."):
        item = next(r for r in self.request["checks"]["results"] if r["id"] == key)
        item.update(status=status, reason=reason)
        return item

    def omitted(self, critical=False):
        self.request["facts"]["reconciliation"].append({
            "field": "net_weight", "label": "净重", "status": "pending", "critical": critical,
            "fact_ids": [], "reason": "Synthetic 57g/58g conflict, not written.",
            "action": "Confirm if needed.", "owner": "产品负责人"})
        self.request["checks"]["results"].append({
            "id": "reliability.field.net_weight", "status": "NEEDS_REVIEW",
            "severity": "warning", "path": "content", "reason": "Synthetic conflict."})

    def test_clean_copy_is_not_release_approval(self):
        result = decision(self.request)
        self.assertEqual(result["copy_status"], "本轮未发现必须修改项")
        self.assertFalse(result["formal"])
        self.assertIn("草稿", result["publish_status"])
        self.assertTrue(any(a["kind"] == "approval" for a in result["actions"]))

    def test_configuration_grouped_without_copy_failure(self):
        self.change("bundle.approval", "NEEDS_REVIEW")
        self.request["checks"]["results"] += [
            {"id": "R-" + str(i), "path": "rules", "status": "NEEDS_REVIEW", "severity": "blocking",
             "reason": "Synthetic unknown scope."} for i in range(26)]
        result = decision(self.request)
        grouped = [a for a in result["actions"] if a["kind"] == "config"]
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(grouped[0]["ids"]), 27)
        self.assertEqual(result["copy_status"], "本轮未发现必须修改项")
        self.assertIn("规则", result["publish_status"])

    def test_omitted_noncritical_field_is_not_a_current_todo(self):
        self.omitted()
        result = decision(self.request)
        self.assertEqual(result["handled_fields"], ["net_weight"])
        self.assertFalse(any(a["title"] == "净重" for a in result["actions"]))
        self.assertIn("57g/58g", result["handled"][0][2])

    def test_critical_conflict_never_hidden(self):
        self.omitted(critical=True)
        result = decision(self.request)
        self.assertFalse(result["handled"])
        self.assertTrue(any(a["title"] == "净重" for a in result["actions"]))
        self.assertNotEqual(result["copy_status"], "本轮未发现必须修改项")

    def test_adopted_conflicting_field_never_hidden(self):
        self.omitted()
        self.request["facts"]["facts"].append({"field": "net_weight", "id": "F9", "value": "57g"})
        self.assertFalse(decision(self.request)["handled"])

    def test_unchecked_copy_cannot_close_omission(self):
        self.omitted()
        self.change("semantic.title", "NOT_CHECKED")
        self.assertFalse(decision(self.request)["handled"])

    def test_stale_review_cannot_show_clean_conclusion(self):
        self.request["review"]["content_hash"] = "old"
        self.assertEqual(decision(self.request)["copy_status"], "审核未完成")

    def test_missing_check_cannot_show_clean_conclusion(self):
        self.request["checks"]["results"] = [r for r in self.request["checks"]["results"]
                                              if r["id"] != "checklist.compliance.medical"]
        result = decision(self.request)
        self.assertEqual(result["copy_status"], "审核未完成")
        self.assertIn("checklist.compliance.medical", result["missing_checks"])

    def test_missing_checks_do_not_disappear_under_zero_count(self):
        self.request["checks"]["results"] = []
        self.assertNotEqual(decision(self.request)["copy_status"], "本轮未发现必须修改项")

    def test_changed_text_with_old_hash_is_not_current(self):
        self.request["content"]["title"]["text"] = "Changed title"
        self.assertFalse(decision(self.request)["current"])

    def test_explicit_field_failure_never_hidden_by_omission(self):
        self.omitted()
        self.change("reliability.field.net_weight", "FAIL")["severity"] = "blocking"
        result = decision(self.request)
        self.assertFalse(result["handled"])
        self.assertEqual(result["copy_status"], "需修改")
        self.assertTrue(any(a["title"] == "净重" for a in result["actions"]))

    def test_blocking_field_uncertainty_not_auto_closed(self):
        self.omitted()
        self.change("reliability.field.net_weight", "NEEDS_REVIEW")["severity"] = "blocking"
        self.assertFalse(decision(self.request)["handled"])

    def test_all_compliance_prerequisites_reach_category_summary(self):
        for identifier in ("keywords.prefix", "keywords.title_repetition", "review.claims", "review.keywords"):
            with self.subTest(identifier=identifier):
                request = copy.deepcopy(self.request)
                request["checks"]["results"].append({
                    "id": identifier, "status": "FAIL", "severity": "blocking",
                    "path": "title", "reason": "Synthetic prerequisite failed."})
                self.assertEqual(decision(request)["categories"][3][1], "需修改")

    def test_explicit_image_rule_failure_is_not_a_copy_keyword_hit(self):
        self.request["rule_catalog"] = [{"id": "R-IMAGE", "raw": "Image origin", "kind": "image_source", "group": "ebay_ip"}]
        self.request["checks"]["results"].append({
            "id": "R-IMAGE", "status": "FAIL", "severity": "blocking", "path": "rules",
            "reason": "Synthetic missing image rights.", "method": "explicit_rule_review"})
        result = decision(self.request)
        self.assertEqual(result["copy_status"], "本轮未发现必须修改项")
        self.assertIn("素材", result["publish_status"])
        self.assertIn("素材待处理", result["categories"][1][1])
        self.assertTrue(any(a["kind"] == "asset" and "R-IMAGE" in a["ids"] for a in result["actions"]))

    def test_stale_review_loses_checkmarks_in_new_detail_layout(self):
        from lf_checklist import tables as checklist_tables
        self.request["report_layout"] = "operator-overview-v1"
        self.request["review"]["content_hash"] = "old"
        sheets = checklist_tables(self.request)
        self.assertEqual(sheets[0][2][1][1], "审核过期，需重查")
        self.assertNotIn("✓", sheets[0][2][1][1])

    def test_optional_keyword_checks_merged_and_not_mandatory(self):
        self.change("checklist.local.search_data", "NOT_CHECKED")
        self.request["checks"]["results"].append({
            "id": "keywords.live_data", "status": "NOT_CHECKED", "severity": "info",
            "path": "keywords", "reason": "No live data."})
        result = decision(self.request)
        self.assertEqual(len(result["optional"]), 1)
        self.assertFalse(any(a["kind"] == "review" for a in result["actions"]))

    def test_image_rights_separate_from_copy_status(self):
        self.change("checklist.ip.visual", "NEEDS_REVIEW")
        result = decision(self.request)
        self.assertTrue(any(a["kind"] == "asset" for a in result["actions"]))
        self.assertEqual(result["copy_status"], "本轮未发现必须修改项")
        self.assertIn("图片", result["categories"][1][2])

    def test_required_failure_overrides_successful_category_review(self):
        self.request["checks"]["results"].append({
            "id": "length.title", "status": "FAIL", "severity": "blocking",
            "path": "title", "reason": "Title too long."})
        result = decision(self.request)
        self.assertEqual(result["copy_status"], "需修改")
        self.assertEqual(result["categories"][3][1], "需修改")
        self.assertIn(self.request["content"]["title"]["text"], result["actions"][0]["finding"])

    def test_dictionary_hit_not_hidden_in_configuration(self):
        self.request["checks"]["results"].append({
            "id": "R-1", "status": "FAIL", "severity": "blocking", "path": "specs.0.name",
            "reason": "Synthetic rule hit."})
        self.request["rule_catalog"] = [{"id": "R-1", "group": "general_banned", "raw": "Compartments"}]
        result = decision(self.request)
        self.assertEqual(result["categories"][0][1], "需修改")
        self.assertIn("Compartments", result["actions"][0]["finding"])

    def test_unknown_field_warning_not_discarded(self):
        self.request["checks"]["results"].append({
            "id": "reliability.field.unknown", "status": "NEEDS_REVIEW", "severity": "blocking",
            "path": "content", "reason": "Unknown field discrepancy."})
        self.assertTrue(any("Unknown field" in a["finding"] for a in decision(self.request)["actions"]))

    def test_formal_status_requires_current_approval(self):
        self.request["mode"] = "final"
        self.assertFalse(decision(self.request)["formal"])
        self.request["approval"] = {"content_hash": self.request["content_hash"],
                                     "checks_hash": digest(self.request["checks"])}
        self.assertTrue(decision(self.request)["formal"])
        self.change("semantic.title", "FAIL")
        self.assertFalse(decision(self.request)["formal"])

    def test_model_does_not_mutate_audit(self):
        before = copy.deepcopy(self.request)
        tables(self.request)
        self.assertEqual(before, self.request)

    def test_overflow_todos_remain_in_full_list(self):
        for key in ("semantic.title", "checklist.banned.context", "checklist.compliance.medical",
                    "checklist.local.units", "checklist.ip.brand"):
            self.change(key, "FAIL")
        views = tables(self.request)
        self.assertTrue(any(row[0] == "其余待办" for row in views[0][2]))
        self.assertEqual(len(views[1][2]) - 1, len(decision(self.request)["actions"]))

    def test_feedback_blank_and_not_fabricated_approval(self):
        views = tables(self.request)
        self.assertTrue(all(row[5:] == ["", "", "", ""] for row in views[1][2]))

    def test_missing_dictionary_not_presented_as_zero_hits(self):
        result = decision(self.request)
        self.assertIn("当前无词库扫描记录", result["categories"][0][2])
        self.assertIn("词库待确认", result["categories"][0][1])
