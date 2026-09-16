"""Four operator checklists, backed by current reviews and frozen rule scans."""

from collections import Counter

from lf_experience import label
from lf_rules import content_blocks, digest


# A semantic review is separate from the dictionary's exact-phrase scan.
ITEMS = {
    "banned.context": ("违禁词自查表", "违禁表达与上下文", "blocking"),
    "ip.brand": ("侵权词自查表", "品牌词", "blocking"),
    "ip.character": ("侵权词自查表", "IP与角色名称", "blocking"),
    "ip.event": ("侵权词自查表", "赛事与组织名称", "blocking"),
    "ip.luxury": ("侵权词自查表", "奢侈品牌与关联表达", "blocking"),
    "ip.visual": ("侵权词自查表", "图片与外观授权范围", "warning"),
    "local.title": ("本地化自查表", "标题：品类词与当地表达", "blocking"),
    "local.bullets": ("本地化自查表", "五点：表达与阅读习惯", "blocking"),
    "local.units": ("本地化自查表", "单位、温度与实际配置", "blocking"),
    "local.language": ("本地化自查表", "拼写、语法与语气", "blocking"),
    "local.search_data": ("本地化自查表", "当地搜索数据验证", "info"),
    "compliance.frequency": ("文案合规自查表", "词频与关键词堆砌", "blocking"),
    "compliance.superlative": ("文案合规自查表", "夸大词与绝对承诺", "blocking"),
    "compliance.cross_category": ("文案合规自查表", "跨类目词与无关引流", "blocking"),
    "compliance.medical": ("文案合规自查表", "医疗暗示与效果承诺", "blocking"),
    "compliance.ip": ("文案合规自查表", "侵权词与授权暗示", "blocking"),
}
HEADERS = ["检查项目 / 词条", "核查结果", "检查范围 / 文案位置",
           "文案原句 / 命中内容", "核查依据与结论", "处理建议"]
WIDTHS = [29, 22, 30, 48, 58, 34]
STATUS = {"PASS": "✓ 已核对", "FAIL": "✗ 需修改", "NEEDS_REVIEW": "待确认",
          "NOT_CHECKED": "未检查", "NOT_APPLICABLE": "不适用"}
SHEETS = tuple(dict.fromkeys(v[0] for v in ITEMS.values()))
EXTERNAL = {"ip.visual", "local.search_data"}


def content_texts(content):
    texts = {}
    for path, block in content_blocks(content):
        texts[path] = block["text"]
        if "name" in block:
            texts[path + ".name"] = block["name"]
    return texts


def active(state, record):
    return state.get("workflow_version", 1) >= 3 and (
        state.get("checklist_version") == 1 or
        "operator_checklist" in (record.get("review") or {}))


def report_current(request, semantic=True):
    checks = request.get("checks") or {}
    review = request.get("review") or {}
    current = (checks.get("content_hash") == request.get("content_hash")
               and digest(request["content"]) == request.get("content_hash")
               and checks.get("bundle_hash") == request.get("bundle_hash"))
    if request.get("research_version"):
        from lf_research import current_report
        current = current and current_report(request)
        if semantic:
            current = current and review.get("research_hash") == request.get("research_hash")
    return current and (not semantic or (
        review.get("content_hash") == request.get("content_hash")
        and review.get("brief_hash") == request.get("brief_hash")))


def template():
    return {key: {"status": "NOT_CHECKED", "paths": [], "examples": [],
                  "reason": "", "action": ""} for key in ITEMS}


def validate(review, content, state=None):
    if "operator_checklist" not in review:
        return  # Legacy reviews remain readable, but missing checks do not pass.
    checklist = review["operator_checklist"]
    if not isinstance(checklist, dict) or set(checklist) != set(ITEMS):
        raise ValueError("Operator checklist must cover all four checklists")
    blocks = content_texts(content)
    for key, item in checklist.items():
        if not isinstance(item, dict) or item.get("status") not in STATUS:
            raise ValueError("Invalid operator checklist status")
        if item["status"] == "NOT_APPLICABLE" and key != "ip.visual":
            raise ValueError("Required text checklist cannot be not applicable")
        for field in ("reason", "action"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError("Checklist requires specific reason and action")
        paths = item.get("paths")
        if not isinstance(paths, list) or any(p not in blocks for p in paths) or len(set(paths)) != len(paths):
            raise ValueError("Checklist scope must use current content paths")
        examples = item.get("examples")
        if not isinstance(examples, list):
            raise ValueError("Checklist examples must be an array")
        if item["status"] in {"PASS", "FAIL"} and key not in EXTERNAL and (not paths or not examples):
            raise ValueError("Completed checklist needs scope and actual text examples")
        for example in examples:
            if not isinstance(example, dict):
                raise ValueError("Checklist example must quote current content")
            path, quote = example.get("path"), example.get("quote")
            if path not in paths or not isinstance(quote, str) or not quote.strip() or quote not in blocks[path]:
                raise ValueError("Checklist example must quote current content within its scope")
        if item["status"] == "PASS" and key in EXTERNAL:
            if key == "local.search_data" and state and state.get("research_version"):
                from lf_research import coverage, require_current
                require_current(state)
                if (review.get("research_hash") != state["research_hash"]
                        or not all(v["collected"] and v["complete"] for v in coverage(state["research"]).values())):
                    raise ValueError("Search checklist PASS requires current collected research from all channels")
                continue
            evidence = item.get("evidence")
            if not state or not isinstance(evidence, list) or not evidence:
                raise ValueError("External checklist PASS requires actual source evidence and scope")
            from lf_reliability import excerpt
            for entry in evidence:
                if not isinstance(entry, dict) or not isinstance(entry.get("scope"), str) or not entry["scope"].strip():
                    raise ValueError("External checklist evidence requires explicit scope")
                excerpt(entry, state)
        if item["status"] == "PASS" and key not in EXTERNAL:
            required = ({"title"} if key == "local.title" else
                        {p for p in blocks if p.startswith("bullets.")} if key == "local.bullets" else set(blocks))
            if not required.issubset(paths):
                raise ValueError("Checklist PASS must cover the required content scope")


def checks(state, record):
    if not active(state, record):
        return []
    review = record.get("review") or {}
    items = review.get("operator_checklist", {})
    try:
        validate(review, record["content"], state)
    except (ValueError, TypeError, KeyError):
        items = {}
    results = [{"id": "checklist." + key, "status": items.get(key, {}).get("status", "NOT_CHECKED"),
             "severity": severity, "path": "checklist." + key,
             "reason": items.get(key, {}).get("reason") or f"尚未完成“{name}”专项核查。",
             "method": "operator-checklist-v1"}
            for key, (_, name, severity) in ITEMS.items()]
    if state.get("research_version"):
        from lf_research import checks as research_checks
        result = next(r for r in results if r["id"] == "checklist.local.search_data")
        source = next(r for r in research_checks(state, record) if r["id"] == "keywords.live_data")
        result.update(status=source["status"], reason=source["reason"], method="keyword-research-v1")
    return results


def scope_text(paths, blocks):
    if set(paths) == set(blocks):
        return "全部成品文案（含规格栏目名）"
    bullets = {p for p in blocks if p.startswith("bullets.")}
    if paths and set(paths) == bullets:
        return "全部五点"
    return "、".join(label(p) for p in paths) or "范围尚未记录"


def word_counts(content):
    """Deterministic English/German word-form counts, not a ranking or SEO score."""
    import re
    title = content["title"]["text"]
    bullets = " ".join(b["text"] for b in content["bullets"])
    tokenize = lambda text: re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", text.casefold())
    left, right = Counter(tokenize(title)), Counter(tokenize(bullets))
    stop = {"a", "an", "the", "and", "or", "with", "of", "to", "for", "in", "on", "at", "by",
            "is", "it", "its", "your", "you", "from", "as", "each", "while", "no", "can",
            "der", "die", "das", "ein", "eine", "und", "mit", "für", "von", "im", "zu"}
    words = sorted((w for w in left | right if w not in stop),
                   key=lambda w: (-(left[w] + right[w]), w))
    return "; ".join(f"{word}: 标题{left[word]} / 五点{right[word]}" for word in words[:12])


def tables(request):
    results = request["checks"]["results"]
    blocks = content_texts(request["content"])
    review = request.get("review") or {}
    recorded = review.get("operator_checklist") or {}
    by_id = {}
    for result in results:
        by_id.setdefault(result["id"], []).append(result)
    rows = {name: [[
        "本次报告", "已审核版本" if request.get("mode") == "final" else "运营审阅草稿",
        f"SKU {request['sku']} / {request['site']} / {request['language']}", "",
        "按本版文案与任务词库核查。勾选仅限所列检查范围，不代表已核验全部平台政策或商品权利。",
        "待办见“处理清单”；公司规则批准状态见“规则与范围”。",
    ]] for name in SHEETS}
    for key, (sheet, name, _) in ITEMS.items():
        item = recorded.get(key, {})
        checked = by_id.get("checklist." + key, [])
        status = checked[0]["status"] if checked else "NOT_CHECKED"
        scope = scope_text(item.get("paths", []), blocks)
        if key == "ip.visual":
            scope = "图片、图案及商品外观（非文字核查）"
        reason = checked[0]["reason"] if checked else "未记录本版专项核查，不能沿用其他类别的通过结论。"
        if item.get("evidence"):
            source_index = {u["id"]: (s["name"], u["locator"]) for s in request.get("sources", []) for u in s["units"]}
            reason += "\n" + "\n".join(
                f"依据：{' · '.join(source_index.get(e['source_id'], (e['source_id'],)))}；范围：{e['scope']}；原文：{e['quote']}"
                for e in item["evidence"])
        rows[sheet].append([name, STATUS[status], scope,
                            "\n".join(f"{label(e['path'])}：{e['quote']}" for e in item.get("examples", [])),
                            reason,
                            item.get("action") or "由助手完成本项核查；仅将资料无法回答的问题交运营。"])
    rows["本地化自查表"].append([
        "站点与语言", "检查信息", f"{request['site']} / {request['language']}", "",
        "自然表达审核与实时搜索数据验证分开记录；没有搜索数据不声称已验证搜索热度。", "按实际投放站点审阅。"])
    rows["文案合规自查表"].append([
        "标题与五点词频明细", "已统计，不作合规结论", "标题及全部五点",
        word_counts(request["content"]), "不区分大小写，按词形计数；去除常用虚词，列出前12项。次数本身不能判断堆词。",
        "结合上方词频语义核查判断；不为降词频删除必要条件。"])
    for result in results:
        if result["id"].startswith(("length.", "keywords.prefix", "keywords.title_repetition")):
            block = blocks.get(result["path"])
            rows["文案合规自查表"].append([
                ("长度：" if result["id"].startswith("length.") else "核心词位置与重复：") + label(result["path"]),
                STATUS[result["status"]], label(result["path"]), block or "",
                result["reason"] + "；本项依据任务内公司规则，不冒充最新平台政策。", "无需修改。" if result["status"] == "PASS" else "按具体检查修正文案。"])

    catalog = request.get("rule_catalog", [])
    for groups, sheet in (({"general_banned"}, "违禁词自查表"),
                          ({"general_ip", "ebay_ip"}, "侵权词自查表")):
        rules = [r for r in catalog if r["group"] in groups and r["id"] in by_id]
        if not rules:
            rows[sheet].append(["词库逐项检查", "未检查", "任务适用词库", "",
                                "没有可展示的适用词条扫描记录，不能按零命中认定通过。", "核对词库是否已配置及适用。"])
        for rule in rules:
            entries = by_id[rule["id"]]
            for item in entries:
                status = item["status"]
                block = blocks.get(item["path"])
                phrase = item.get("excerpt", "")
                detail = (("命中：" + phrase + "\n") if phrase else "") + (block or "")
                source = "\n".join(f"{s['file']} · {s['locator']}" for s in rule.get("sources", []))
                explanation = {
                    "PASS": "未命中本词条的精确短语；不等于完成语义或权利核验。",
                    "FAIL": "命中公司词库，需核对具体语境；不是侵权或违法的法律结论。",
                    "NEEDS_REVIEW": "该规则的适用范围或非文本核查待确认，不等于文案命中。",
                    "NOT_CHECKED": "本词条尚未检查。",
                    "NOT_APPLICABLE": "本版已记录不适用依据。",
                }[status]
                if item.get("method") == "explicit_rule_review":
                    explanation = item["reason"]
                scope = (label(item["path"]) if block else
                         "全部成品文案（含规格栏目名）" if status == "PASS" else "适用范围待确认")
                if item.get("method") == "explicit_rule_review":
                    scope = "专项规则核验，范围以所列依据为准"
                rows[sheet].append([
                    rule["raw"], "✓ 未命中（精确匹配）" if status == "PASS" and item.get("method") != "explicit_rule_review" else STATUS[status],
                    scope,
                    detail, explanation + ("\n依据：" + source if source else ""),
                    "无需修改；语义核查见上方。" if status == "PASS" else
                    "核对原句并删除、替换或补充适用依据。" if status == "FAIL" else "由规则负责人确认适用范围或专项依据。"])
    if request.get("report_layout") == "operator-overview-v1":
        questions = {
            "违禁表达与上下文": "是否出现违禁表达？",
            "品牌词": "是否使用第三方品牌词？",
            "IP与角色名称": "是否使用IP或角色名称？",
            "赛事与组织名称": "是否关联赛事或组织？",
            "奢侈品牌与关联表达": "是否借用奢侈品牌关联？",
            "图片与外观授权范围": "图片与外观权利已核实吗？",
            "标题：品类词与当地表达": "标题是否符合当地表达？",
            "五点：表达与阅读习惯": "五点是否自然且易读？",
            "单位、温度与实际配置": "单位和实际配置是否正确？",
            "拼写、语法与语气": "拼写、语法和语气是否恰当？",
            "当地搜索数据验证": "是否验证当地搜索数据？",
            "词频与关键词堆砌": "是否存在关键词堆砌？",
            "夸大词与绝对承诺": "是否存在夸大或绝对承诺？",
            "跨类目词与无关引流": "是否混入无关品类词？",
            "医疗暗示与效果承诺": "是否暗示医疗或治疗效果？",
            "侵权词与授权暗示": "是否存在侵权词或授权暗示？",
        }
        if request.get("research_version"):
            questions["当地搜索数据验证"] = "关键词参考来源是否齐全？"
        semantic_current = report_current(request)
        scan_current = report_current(request, semantic=False)
        readable = []
        for name in SHEETS:
            projected = []
            for title, status, scope, quote, reason, action in rows[name]:
                research_row = request.get("research_version") and title == "当地搜索数据验证"
                if ((title in questions and not semantic_current and not research_row)
                        or (title not in questions and status.startswith(("✓", "✗")) and not scan_current)):
                    status = "审核过期，需重查"
                    reason = "记录与当前文案或规则版本不一致，不能沿用结论。\n旧记录：" + reason
                    action = "由助手针对当前文案重新核查。"
                if research_row:
                    from lf_research import current_report
                    if not scan_current or not current_report(request):
                        status, reason, action = "调研未完成或已过期", "本版未绑定有效调研记录。", "由助手补齐调研及版本绑定。"
                    else:
                        action = "各来源结果与候选词取舍见本页调研明细，不代表搜索量核验。"
                brief, punctuation, _ = reason.partition("。")
                projected.append([questions.get(title, title), status, brief + punctuation,
                                  quote, scope + "\n" + reason, action])
            projected[0][-1] = "审核结论"
            readable.append((name, ["检查问题 / 词条", "结果", "一句话判断", "相关原句", "核查依据与范围", "处理建议"],
                             projected, [29, 22, 42, 48, 58, 34]))
        if request.get("research_version"):
            from lf_research import reference_rows
            for name, _, projected, _ in readable:
                if name == "本地化自查表":
                    projected.extend(reference_rows(request))
        return readable
    return [(name, HEADERS, rows[name], WIDTHS) for name in SHEETS]
