"""Synthetic editorial fixtures; not business-approved product copy."""

import test_listingflow as base
import listingflow as lf


def brief(state):
    angle_facts = [["F2", "F3"], ["F4"], ["F5"], ["F6"], ["F7"]]
    labels = ["Organizing items", "Checking desk fit", "Accessing items", "Material identification", "Cleaning"]
    result = {"schema": 1, "facts_hash": state["facts_hash"], "sku": state["sku"], "site": state["site"],
            "language": state["language"], "audience": "People organizing a desk",
            "audience_basis": "editorial_hypothesis", "tone": "clear_practical",
            "primary_keyword": base.fixture_content()["keywords"], "critical_fact_ids": ["F7"],
            "avoid": ["No unverified waterproof claims"],
            "angles": [{"label": name, "buyer_need": name, "benefit": "State the supported feature and practical use",
                        "fact_ids": refs, "caveat": ""} for name, refs in zip(labels, angle_facts)],
            "questions": [{"intent": qa["question"]["text"], "fact_ids": qa["question"]["fact_ids"]}
                          for qa in base.fixture_content()["qa"]]}
    if state.get("research_version"):
        result["research_hash"] = state.get("research_hash")
    return result


def research(state):
    from lf_research import template
    result = template(state)
    for key in result["channels"]:
        result["channels"][key] = [{
            "status": "blocked", "observed_at": lf.now(), "url": "https://www.ebay.com/",
            "query": "Desk Organizer", "method": "browser",
            "evidence_text": "SYNTHETIC TEST: network access is intentionally unavailable in fixture.",
            "reason": "合成测试限制，不代表真实站点访问状态。", "items": []}]
    return result


def ready_content(flow):
    flow.ingested()
    flow.command("freeze", "--json", flow.payload(flow.facts_payload()))
    flow.command("brief", "--json", flow.payload(brief(lf.current(flow.task))))
    return flow.command("save-content", "--json", flow.payload(base.fixture_content()))


def review(state):
    result = base.fixture_review(state)
    record = state["contents"][-1]
    result["brief_hash"] = record["brief_hash"]
    if state.get("research_version"):
        result["research_hash"] = record.get("research_hash")
    facts = {f["id"]: f for f in state["facts"]["facts"]}
    units = {u["id"]: u for s in state["sources"] for u in s["units"]}
    used = {fid for b in result["blocks"].values() for fid in b["fact_ids"]}
    result["fact_evidence"] = {
        fid: [{"source_id": facts[fid]["sources"][0], "quote": units[facts[fid]["sources"][0]]["text"]}]
        for fid in used}
    paths = {
        "differentiation": "bullets.0", "buyer_usefulness": "qa.2.answer",
        "naturalness": "title", "conciseness": "bullets.4",
        "keyword_fit": "title", "conditions": "bullets.4",
    }
    blocks = dict(lf.content_blocks(record["content"]))
    result["quality"] = {key: {"status": "PASS", "reason": f"Synthetic fixture check: {key}",
                               "examples": [{"path": path, "quote": blocks[path]["text"]}]}
                         for key, path in paths.items()}
    return result
