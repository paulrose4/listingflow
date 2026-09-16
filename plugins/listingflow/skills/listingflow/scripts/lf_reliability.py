"""V3 evidence contracts and targeted regressions, not a semantic proof engine."""

import re

from lf_rules import content_blocks
from lf_experience import field_label


def active(state):
    return state.get("workflow_version", 1) >= 3


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Nonempty text required: {name}")


def excerpt(entry, state):
    units = {u["id"]: u for s in state["sources"] for u in s["units"]}
    sid = entry.get("source_id")
    if sid not in units:
        raise ValueError("Evidence source does not exist")
    unit = units[sid]
    original = unit["text"]
    oid = entry.get("observation_id")
    if oid:
        observation = next((o for o in state.get("observations", []) if o["id"] == oid), None)
        if not observation or observation["unit_id"] != sid:
            raise ValueError("Observation must match evidence source")
        original = observation["text"]
    if unit["kind"] in {"image", "pdf_page"} and not oid:
        raise ValueError("Visual evidence requires a recorded observation")
    text(entry.get("quote"), "evidence quote")
    if entry["quote"] not in original:
        raise ValueError("Evidence quote does not exist in source")
    return sid


def validate_facts(payload, state):
    if not active(state):
        return
    reviews = payload.get("source_review", {})
    if set(reviews) != {s["id"] for s in state["sources"]}:
        raise ValueError("V3 requires source_review for every inventoried source")
    observations = {o["unit_id"] for o in state.get("observations", []) if o["method"] == "visual"}
    for source in state["sources"]:
        item = reviews[source["id"]]
        if item.get("role") not in {"primary", "manual", "image", "reference", "irrelevant"}:
            raise ValueError("Source role must distinguish primary/manual/image/reference/irrelevant")
        if type(item.get("reviewed")) is not bool:
            raise ValueError("Source reviewed must be boolean")
        text(item.get("reason"), "source review reason")
        used = payload["selection"][source["id"]]["action"] == "use"
        if (used or item["role"] == "manual") and not item["reviewed"]:
            raise ValueError("Used sources and applicable manuals must be reviewed before freeze")
        if item["role"] == "manual":
            visual = [u["id"] for u in source["units"] if u["kind"] in {"image", "pdf_page"}]
            if any(uid not in observations for uid in visual):
                raise ValueError("Manual visual pages require recorded visual observations")
        if used and item["role"] == "irrelevant":
            raise ValueError("Irrelevant sources cannot supply product facts")
    ledger = payload.get("reconciliation")
    if not isinstance(ledger, list) or not ledger:
        raise ValueError("V3 requires a field-level reconciliation ledger")
    facts = {f["id"]: f for f in payload["facts"]}
    fields, covered = set(), []
    for row in ledger:
        field = row.get("field")
        text(field, "reconciliation field")
        if "label" in row:
            text(row["label"], "operator field label")
        if not re.search(r"[\u4e00-\u9fff]", row.get("label", field_label(field))):
            raise ValueError("Custom fields require a Chinese operator label")
        if field in fields:
            raise ValueError("Duplicate reconciliation field")
        fields.add(field)
        if row.get("status") not in {"adopted", "omitted", "pending"}:
            raise ValueError("Reconciliation status must be adopted/omitted/pending")
        if type(row.get("critical")) is not bool:
            raise ValueError("Reconciliation critical must be boolean")
        for key in ("reason", "action", "owner"):
            text(row.get(key), f"reconciliation {key}")
        ids = row.get("fact_ids")
        if not isinstance(ids, list) or any(fid not in facts for fid in ids):
            raise ValueError("Reconciliation fact references invalid")
        if row["status"] == "adopted":
            if not ids or any(facts[fid]["field"] != field for fid in ids):
                raise ValueError("Adopted field must map to its own confirmed facts")
        elif ids or field in {f["field"] for f in facts.values()}:
            raise ValueError("Unresolved or omitted fields cannot enter confirmed facts")
        if row["critical"] and row["status"] != "adopted":
            raise ValueError("Unresolved critical field requires clarification before freeze")
        candidates = row.get("candidates")
        if not isinstance(candidates, list) or (row["status"] == "adopted" and not candidates):
            raise ValueError("Adopted fields require original candidate evidence")
        cited = set()
        for entry in candidates:
            text(entry.get("value"), "candidate value")
            cited.add(excerpt(entry, state))
        for fid in ids:
            if not set(facts[fid]["sources"]).issubset(cited):
                raise ValueError("Reconciliation must cover all adopted fact sources")
        covered.extend(ids)
    if set(covered) != set(facts) or len(covered) != len(set(covered)):
        raise ValueError("Every confirmed fact must appear exactly once in reconciliation")


def validate_review(review, state, record):
    if not active(state):
        return
    blocks = dict(content_blocks(record["content"]))
    for path, block in blocks.items():
        item = review["blocks"][path]
        claims = item.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError(f"V3 requires claim-level review at {path}")
        coverage = set()
        referenced = set()
        for claim in claims:
            quote = claim.get("text")
            text(quote, "current claim")
            if quote not in block["text"]:
                raise ValueError("Claim must quote current content")
            start = block["text"].find(quote)
            coverage.update(range(start, start + len(quote)))
            ids = claim.get("fact_ids")
            if not isinstance(ids, list) or not ids or not set(ids).issubset(block["fact_ids"]):
                raise ValueError("Claim references must be a nonempty subset of block facts")
            referenced.update(ids)
            if claim.get("status") not in {"PASS", "FAIL", "NEEDS_REVIEW", "NOT_CHECKED"}:
                raise ValueError("Invalid claim review status")
            text(claim.get("reason"), "claim support explanation")
            if item["status"] == "PASS" and claim["status"] != "PASS":
                raise ValueError("Block cannot pass with unchecked or unsupported claims")
        if any(c.isalnum() and i not in coverage for i, c in enumerate(block["text"])):
            raise ValueError("Claim review leaves current text uncovered")
        if referenced != set(block["fact_ids"]):
            raise ValueError("Claim review must explain every referenced fact")
    conditions = review.get("conditions")
    critical = set(record["brief"]["critical_fact_ids"])
    if not isinstance(conditions, dict) or set(conditions) != critical:
        raise ValueError("Critical conditions require explicit content coverage")
    for fid, item in conditions.items():
        path = item.get("path")
        text(item.get("quote"), "condition content quote")
        text(item.get("reason"), "condition support reason")
        if path not in blocks or fid not in blocks[path]["fact_ids"] or item["quote"] not in blocks[path]["text"]:
            raise ValueError("Condition must quote current supported content")
    for entries in review["fact_evidence"].values():
        for entry in entries:
            excerpt(entry, state)
    images = review["categories"].get("images", {})
    units = {u["id"]: u for s in state["sources"] for u in s["units"]}
    visual_refs = {entry["source_id"] for row in state["facts"]["reconciliation"]
                   for entry in row["candidates"] if units[entry["source_id"]]["kind"] in {"image", "pdf_page"}}
    if visual_refs and images.get("status") == "NOT_APPLICABLE":
        raise ValueError("Visual reconciliation evidence requires image review")
    if images.get("status") == "PASS":
        ids = images.get("observation_ids", [])
        observed = {o["id"]: o["unit_id"] for o in state.get("observations", []) if o["method"] == "visual"}
        if not ids or not set(ids).issubset(observed):
            raise ValueError("Image PASS requires source-specific visual observations")
        if not visual_refs.issubset({observed[oid] for oid in ids}):
            raise ValueError("Image review observations must cover visual reconciliation sources")


# Narrow linguistic guards flag evidence gaps; passing them is not entailment proof.
GUARDS = [
    ("battery", r"\bno (?:built[- ]in |internal )?batter(?:y|ies)\b|\bwithout (?:a )?batter|不带电池|无内置电池|ohne (?:eingebauten? )?(?:Akku|Batterie)",
     r"不带电池|无(?:内置)?电池|不含电池|no (?:built[- ]in |internal )?batter|without (?:a )?batter|ohne (?:eingebauten? )?(?:Akku|Batterie)",
     "不带电池", "电压、接口和线长不能证明没有电池；请引用明确说明电池配置的资料。"),
    ("strap", r"adjustable (?:head)?(?:strap|band)|可调(?:节)?绑带|verstellbare[ nr]* (?:Band|Gurt)",
     r"可调(?:节)?.{0,8}(?:绑带|头带|松紧带)|(?:绑带|头带|松紧带).{0,8}可调|(?:绑带|头带|松紧带)可通过(?:滑扣|调节扣)调节长度|adjustable.{0,12}(?:strap|band)|verstellbar",
     "可调绑带", "贴合或遮光不能证明绑带可调；需结构说明或对应实物观察。"),
    ("independent", r"(?:heat|heating|vibration).{0,80}(?:separately|independently)|(?:separately|independently).{0,80}(?:heat|vibration)|分别调节|独立调节",
     r"独立|分别|单独|separately|independen|heat(?:ing)? button.{0,300}vibration button|加热.{0,40}按[键钮].{0,80}振动.{0,40}按[键钮]",
     "独立调节", "分别调节的说法需控制方式依据，“未夸大医疗效果”不能回答这个问题。"),
]


def checks(state, record):
    if not active(state):
        return []
    result = []

    def add(key, status, path, reason, severity="blocking"):
        result.append({"id": "reliability." + key, "status": status, "severity": severity,
                       "path": path, "reason": reason, "method": "targeted-evidence-guard-v3"})

    review = record.get("review")
    valid = False
    if review:
        try:
            validate_review(review, state, record)
            valid = True
        except (ValueError, KeyError, TypeError):
            pass
    add("claim_review", "PASS" if valid else "NOT_CHECKED", "evidence",
        "逐条声明、关键条件及视觉记录已登记；仍依赖实际语义核对。" if valid else "尚未完成逐条声明、关键条件及视觉记录核对。")
    for row in state["facts"].get("reconciliation", []):
        if row["status"] != "adopted":
            add("field." + row["field"], "NEEDS_REVIEW", "content",
                f"{row['field']}：{row['reason']}；本版不采用。{row['action']}", "info" if row["status"] == "omitted" else "warning")
    if not review:
        return result
    evidence = review.get("fact_evidence", {})
    facts = {f["id"]: f for f in state["facts"]["facts"]}
    units = {u["id"]: u for s in state["sources"] for u in s["units"]}
    for path, block in content_blocks(record["content"]):
        for index, claim in enumerate(review["blocks"][path].get("claims", [])):
            support = "\n".join(e["quote"] for fid in claim["fact_ids"] for e in evidence.get(fid, []))
            for key, pattern, required, title, reason in GUARDS:
                if re.search(pattern, claim["text"], re.I | re.S) and not re.search(required, support, re.I | re.S):
                    add(f"{key}.{path}.{index}", "NEEDS_REVIEW", path, f"{title}：{reason}")
                if key == "independent" and re.search(pattern, claim["text"], re.I | re.S):
                    explanation = claim["reason"]
                    if re.search(r"医疗|medical", explanation, re.I) and not re.search(
                            r"独立|分别|单独|按键|按钮|separat|independen|button|control", explanation, re.I):
                        add(f"rationale.{path}.{index}", "NEEDS_REVIEW", path,
                            "审核理由只谈医疗宣称，未解释控制是否独立；请补充对应来源与支持关系。")
        support = "\n".join(e["quote"] for fid in block["fact_ids"] for e in evidence.get(fid, []))
        fields = {facts[fid]["field"] for fid in block["fact_ids"]}
        candidates = "\n".join(c["quote"] for row in state["facts"]["reconciliation"] if row["field"] in fields
                               for c in row["candidates"])
        originals = "\n".join(units[sid]["text"] for fid in block["fact_ids"] for sid in facts[fid]["sources"])
        if re.search(r"15.{0,12}min|15\s*分钟", block["text"], re.I):
            if re.search(r"重[置新].{0,12}计时|计时.{0,12}重[置新]|reset|last.{0,15}(?:button|press)",
                         "\n".join((support, candidates, originals)), re.I):
                if not re.search(r"reset|restart|last.{0,15}(?:button|press)|重置|最后一次|neu gestartet", block["text"], re.I):
                    add("timer." + path, "NEEDS_REVIEW", path, "来源包含按键重置计时条件，此处的15分钟说法需同步保留条件。")
        if re.search(r"(?:package|include|box).{0,100}(?:multilingual|multi-language).{0,20}manual", block["text"], re.I | re.S):
            package_evidence = "\n".join((support, candidates))
            if re.search(r"电子|digital|electronic", package_evidence, re.I) and re.search(r"英文实物|physical.{0,20}English|English.{0,20}physical", package_evidence, re.I):
                add("package." + path, "NEEDS_REVIEW", path, "来源区分英文实物说明书与多语言电子说明书，不能合并成包内多语言实物。")
        if re.search(r"°F", block["text"]) and re.search(r"±\s*\d+(?:\.\d+)?\s*°C", block["text"]):
            if not re.search(r"±\s*\d+(?:\.\d+)?\s*°F", block["text"]):
                add("units." + path, "NEEDS_REVIEW", path, "华氏主温度配摄氏公差不便阅读；温差换算乘9/5，不加32。", "warning")
    return result
