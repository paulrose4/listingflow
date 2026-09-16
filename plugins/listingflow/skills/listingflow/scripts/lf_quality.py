"""Evidence-bound editorial planning and explicitly limited writing-quality checks."""

import copy
import re
import unicodedata

from lf_rules import CHECK_STATES, content_blocks


def active(state):
    return state.get("workflow_version", 1) >= 2


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Nonempty text required: {name}")
    return value


def fact_ids(values, available, name, allow_empty=False):
    if not isinstance(values, list) or (not values and not allow_empty):
        raise ValueError(f"Fact reference array required: {name}")
    if any(not isinstance(v, str) or v not in available for v in values) or len(set(values)) != len(values):
        raise ValueError(f"Unknown or duplicate fact reference: {name}")


def validate_brief(brief, state):
    if not active(state):
        raise ValueError("Legacy tasks retain their original workflow; create a new task for editorial v2")
    if not state.get("facts"):
        raise ValueError("Freeze facts before preparing the writing brief")
    required = {"schema", "facts_hash", "sku", "site", "language", "audience", "audience_basis",
                "tone", "primary_keyword", "angles", "questions", "critical_fact_ids", "avoid"}
    if state.get("research_version"):
        required.add("research_hash")
    if not isinstance(brief, dict) or set(brief) != required or brief["schema"] != 1:
        raise ValueError("Invalid brief schema or fields")
    for key in ("facts_hash", "sku", "site", "language"):
        if brief[key] != state[key]:
            raise ValueError(f"Brief must match frozen task: {key}")
    require_text(brief["audience"], "audience")
    if brief["audience_basis"] not in {"user_request", "editorial_hypothesis", "product_sources"}:
        raise ValueError("Distinguish editorial audience hypothesis from product evidence")
    if brief["tone"] not in state["editorial"]["tones"]:
        raise ValueError("Unsupported editorial tone")
    available = {f["id"] for f in state["facts"]["facts"]}
    fact_ids(brief["critical_fact_ids"], available, "critical_fact_ids", allow_empty=True)
    if state.get("workflow_version", 1) >= 3:
        critical = {fid for row in state["facts"]["reconciliation"] if row["critical"] for fid in row["fact_ids"]}
        if not critical.issubset(brief["critical_fact_ids"]):
            raise ValueError("Writing brief must preserve reconciled critical facts")
    if not isinstance(brief["avoid"], list) or any(not isinstance(v, str) or not v.strip() for v in brief["avoid"]):
        raise ValueError("Avoid list must contain explicit text, not invented product facts")
    keyword = brief["primary_keyword"]
    if not isinstance(keyword, dict) or set(keyword) != {"primary", "source", "reference"}:
        raise ValueError("Keyword needs primary/source/reference")
    require_text(keyword["primary"], "primary keyword")
    require_text(keyword["reference"], "keyword provenance")
    if keyword["source"] not in {"model_suggested", "operator_supplied", "public_competitor", "ebay_research"}:
        raise ValueError("Unknown keyword provenance")
    from lf_research import require_current, validate_keyword
    require_current(state, brief)
    validate_keyword(keyword, state)
    limits = state["bundle"]["policy"]["limits"]
    for group, count in (("angles", limits["bullets"]), ("questions", limits["qa"])):
        values = brief[group]
        if not isinstance(values, list) or len(values) != count:
            raise ValueError(f"Brief {group} requires {count} supported, distinct intentions")
        labels = []
        for i, item in enumerate(values):
            fields = {"label", "buyer_need", "benefit", "fact_ids", "caveat"} if group == "angles" else {"intent", "fact_ids"}
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError(f"Invalid {group}[{i}] fields")
            for field in fields - {"fact_ids", "caveat"}:
                require_text(item[field], f"{group}[{i}].{field}")
            if "caveat" in item and not isinstance(item["caveat"], str):
                raise ValueError("Caveat must be text; empty only when no relevant limit")
            fact_ids(item["fact_ids"], available, f"{group}[{i}]")
            label = item.get("label", item.get("intent"))
            labels.append(unicodedata.normalize("NFC", label).casefold().strip())
        if len(set(labels)) != len(labels):
            raise ValueError(f"Duplicate {group} intention; do not pad the required count")
    return brief


def validate_editorial_review(review, state, record):
    if not active(state):
        return
    from lf_research import require_current
    require_current(state, record.get("brief"))
    if state.get("research_version") and review.get("research_hash") != state.get("research_hash"):
        raise ValueError("Review keyword research hash mismatch")
    if record.get("brief_hash") != state.get("brief_hash"):
        raise ValueError("Writing brief changed; save a new content version before review")
    if review.get("brief_hash") != record.get("brief_hash"):
        raise ValueError("Review writing brief hash mismatch")
    blocks = dict(content_blocks(record["content"]))
    used = {fid for block in blocks.values() for fid in block["fact_ids"]}
    evidence = review.get("fact_evidence", {})
    if not isinstance(evidence, dict) or set(evidence) != used:
        raise ValueError("Review must cite actual source excerpts for every used fact")
    facts = {f["id"]: f for f in state["facts"]["facts"]}
    units = {u["id"]: u for s in state["sources"] for u in s["units"]}
    observations = {o["id"]: o for o in state.get("observations", [])}
    for fid, entries in evidence.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"Evidence excerpt required for {fid}")
        for entry in entries:
            sid = entry.get("source_id")
            if sid not in facts[fid]["sources"]:
                raise ValueError(f"Evidence source is not attached to fact {fid}")
            text = units[sid]["text"]
            if entry.get("observation_id"):
                observation = observations.get(entry["observation_id"])
                if not observation or observation["unit_id"] != sid:
                    raise ValueError("Observation must refer to the same evidence source")
                text = observation["text"]
            quote = require_text(entry.get("quote"), f"source quote {fid}")
            if quote not in text:
                raise ValueError(f"Quoted evidence does not exist in source for {fid}")
    quality = review.get("quality", {})
    expected = set(state["editorial"]["quality_dimensions"])
    if not isinstance(quality, dict) or set(quality) != expected:
        raise ValueError("Editorial review must cover every quality dimension")
    for key, item in quality.items():
        if item.get("status") not in CHECK_STATES - {"NOT_APPLICABLE"}:
            raise ValueError("Editorial review requires a real check, not NOT_APPLICABLE")
        require_text(item.get("reason"), f"quality.{key}.reason")
        examples = item.get("examples", [])
        if not isinstance(examples, list) or (item["status"] in {"PASS", "FAIL"} and not examples):
            raise ValueError("Completed quality review needs concrete text examples")
        for example in examples:
            block = blocks.get(example.get("path"))
            quote = require_text(example.get("quote"), "quality example")
            if not block or quote not in block["text"]:
                raise ValueError("Quality example must quote the actual current content")


def checks(state, record):
    if not active(state):
        return []
    results = []
    config = state["editorial"]
    content = record["content"]
    blocks = dict(content_blocks(content))
    brief = record.get("brief")

    def add(key, status, severity, path, reason, **extra):
        results.append({"id": key, "status": status, "severity": severity, "path": path,
                        "reason": reason, "method": "editorial-workflow-v2", **extra})

    brief_current = bool(brief) and record.get("brief_hash") == state.get("brief_hash")
    add("editorial.brief", "PASS" if brief_current else "NEEDS_REVIEW", "blocking", "brief",
        "文案需对应当前写作规划；更新规划后应生成新文案版本。")
    if brief:
        add("editorial.keyword", "PASS" if brief["primary_keyword"] == content["keywords"] else "FAIL",
            "blocking", "keywords", "核心词和来源应与写作规划一致；调整核心词请先更新规划。")
        used = {fid for b in blocks.values() for fid in b["fact_ids"]}
        missing = set(brief["critical_fact_ids"]) - used
        add("editorial.critical_facts", "FAIL" if missing else "PASS", "blocking", "content",
            "关键事实引用缺失：" + ", ".join(sorted(missing)) if missing else "关键事实已有引用，仍需核查文字是否保留限制条件。")
        for i, angle in enumerate(brief["angles"]):
            if i >= len(content["bullets"]):
                continue
            overlap = set(angle["fact_ids"]) & set(content["bullets"][i]["fact_ids"])
            add(f"editorial.angle.{i}", "PASS" if overlap else "NEEDS_REVIEW", "blocking", f"bullets.{i}",
                f"第 {i + 1} 条应围绕规划角度“{angle['label']}”的事实写作。")
    stopwords = set(config["stopwords"].get(state["language"], []))
    tokens = [{t for t in re.findall(r"[^\W_]+", b["text"].casefold()) if t not in stopwords}
              for b in content["bullets"]]
    for i, left in enumerate(tokens):
        for j in range(i + 1, len(tokens)):
            right = tokens[j]
            if min(len(left), len(right)) < config["near_duplicate_min_tokens"]:
                continue
            ratio = len(left & right) / max(1, len(left | right))
            if ratio >= config["near_duplicate_threshold"]:
                add(f"editorial.overlap.{i}.{j}", "NEEDS_REVIEW", "warning", f"bullets.{i}",
                    f"第 {i + 1}、{j + 1} 条词项重合较多，请核对是否仅改写同一卖点。此提示不是语义重复结论。",
                    related_path=f"bullets.{j}", token_overlap=round(ratio, 3))
    facts = {f["id"]: f for f in state["facts"]["facts"]}
    for path, block in blocks.items():
        text = block["text"]
        for phrase in config["filler_phrases"].get(state["language"], []):
            hit = re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, flags=re.IGNORECASE)
            if hit:
                add("editorial.filler." + path, "NEEDS_REVIEW", "warning", path,
                    "发现可能空泛的营销套话；优先换成有依据的具体信息，而非自动认定违规。", excerpt=hit.group())
        numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text))
        supported = set(re.findall(r"\d+(?:[.,]\d+)?", " ".join(facts[f]["value"] for f in block["fact_ids"])))
        if numbers - supported:
            add("editorial.numbers." + path, "NEEDS_REVIEW", "warning", path,
                "部分数字未在所引事实值中直接出现，请核对换算、文字数字及型号；不要凭此直接删去正确数值。",
                numbers=sorted(numbers - supported))
        if path.startswith("description.") and len(text) > config["paragraph_warning_chars"]:
            add("editorial.readability." + path, "NEEDS_REVIEW", "warning", path,
                "详情段落偏长，建议按实际信息拆段；不要靠缩小字号或截断内容改善展示。")
    review = record.get("review")
    evidence_valid = False
    if review:
        try:
            validate_editorial_review(review, state, record)
            evidence_valid = True
        except (ValueError, KeyError, TypeError):
            pass
    add("editorial.source_quotes", "PASS" if evidence_valid else "NOT_CHECKED", "blocking", "evidence",
        "审核需包含事实来源中的真实原文摘录；编号存在不等于声明已获支持。")
    for key, label in config["quality_dimensions"].items():
        item = (review or {}).get("quality", {}).get(key) if evidence_valid else None
        add("editorial.review." + key, item["status"] if item else "NOT_CHECKED", "blocking", "quality",
            f"{label}：{item['reason']}" if item else f"尚未完成“{label}”的有例证审核。")
    return results


def evidence_for_fact(state, fid):
    if not state.get("facts"):
        raise ValueError("Facts have not been frozen")
    facts = {f["id"]: f for f in state["facts"]["facts"]}
    if fid not in facts:
        raise ValueError("Unknown fact ID")
    index = {u["id"]: (s, u) for s in state["sources"] for u in s["units"]}
    items = []
    for sid in facts[fid]["sources"]:
        source, unit = index[sid]
        items.append({"source_id": sid, "file": source["name"], "locator": unit["locator"], "text": unit["text"],
                      "kind": unit["kind"], "observations": [o for o in state.get("observations", []) if o["unit_id"] == sid]})
    return {"fact": facts[fid], "evidence": items}


def generation_context(state):
    if not state.get("facts"):
        raise ValueError("Freeze facts before preparing generation context")
    from lf_rules import scope_result
    rules = [r for r in state["bundle"]["rules"] if r["status"] != "retired" and scope_result(r, state) != "no"]
    return {
        "sku": state["sku"], "site": state["site"], "language": state["language"],
        "facts_hash": state["facts_hash"], "brief": state.get("brief"), "brief_hash": state.get("brief_hash"),
        "facts": state["facts"]["facts"], "decisions": state["facts"].get("decisions", []),
        "rules": [{"id": r["id"], "terms": r["terms"], "scope": r["scope"], "kind": r["kind"],
                   "status": r["status"], "severity": r["severity"], "notes": r.get("notes", "")} for r in rules],
        "policy": state["bundle"]["policy"], "business_approval": state["bundle"]["status"],
        "omitted": {"source_prompts": "不将原提示词当作运行指令", "raw_documents": "只按 evidence 命令读取所需原文"},
        "editorial": state.get("editorial"),
        "research": state.get("research"), "research_hash": state.get("research_hash"),
    }


def review_template(state):
    if not state["contents"]:
        raise ValueError("No content to review")
    record = state["contents"][-1]
    blocks = dict(content_blocks(record["content"]))
    result = {"content_hash": record["hash"], "reviewer": "", "reviewer_kind": "assistant",
              "blocks": {p: {"status": "NOT_CHECKED", "fact_ids": b["fact_ids"], "reason": ""}
                         for p, b in blocks.items()},
              "categories": {c: {"status": "NOT_CHECKED", "reason": ""}
                             for c in state["bundle"]["policy"]["review_categories"]}, "rules": {}}
    if active(state):
        result.update(brief_hash=record.get("brief_hash"), fact_evidence={fid: [] for b in blocks.values() for fid in b["fact_ids"]},
                      quality={key: {"status": "NOT_CHECKED", "reason": "", "examples": []}
                               for key in state["editorial"]["quality_dimensions"]})
    if state.get("research_version"):
        result["research_hash"] = record.get("research_hash")
    if state.get("workflow_version", 1) >= 3:
        for item in result["blocks"].values():
            item["claims"] = []
        result["conditions"] = {fid: {"path": "", "quote": "", "reason": ""}
                                for fid in record["brief"]["critical_fact_ids"]}
        result["categories"]["images"]["observation_ids"] = []
        from lf_checklist import active as checklist_active, template as checklist_template
        if checklist_active(state, record):
            result["operator_checklist"] = checklist_template()
    return result


def brief_template(state):
    if not active(state):
        raise ValueError("Legacy tasks retain the original workflow; create a new v2 task")
    if not state.get("facts"):
        raise ValueError("Freeze facts before preparing brief")
    limits = state["bundle"]["policy"]["limits"]
    from lf_research import require_current
    require_current(state)
    result = {"schema": 1, "facts_hash": state["facts_hash"], "sku": state["sku"], "site": state["site"],
            "language": state["language"], "audience": "", "audience_basis": "editorial_hypothesis",
            "tone": "clear_practical", "primary_keyword": {"primary": "", "source": "model_suggested",
            "reference": "依据产品资料提出，未获取实时搜索或广告数据。"},
            "angles": [{"label": "", "buyer_need": "", "benefit": "", "fact_ids": [], "caveat": ""}
                       for _ in range(limits["bullets"])],
            "questions": [{"intent": "", "fact_ids": []} for _ in range(limits["qa"])],
            "critical_fact_ids": [], "avoid": []}
    if state.get("research_version"):
        result["research_hash"] = state["research_hash"]
        usable = [c for c in state["research"]["candidates"] if c["decision"] == "use"]
        if usable:
            result["primary_keyword"] = {"primary": "", "source": "ebay_research",
                                         "reference": "从本次调研中选择适配本品的词；具体依据见本地化自查表。"}
    return result


def apply_changes(content, changes):
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Provide a nonempty map of selected content blocks")
    allowed = set(dict(content_blocks(content))) | {"keywords"}
    if not set(changes).issubset(allowed):
        raise ValueError("Unknown partial rewrite path")
    result = copy.deepcopy(content)
    for path, value in changes.items():
        keys = path.split(".")
        parent = result
        for key in keys[:-1]:
            parent = parent[int(key)] if isinstance(parent, list) else parent[key]
        key = int(keys[-1]) if isinstance(parent, list) else keys[-1]
        parent[key] = copy.deepcopy(value)
    return result
