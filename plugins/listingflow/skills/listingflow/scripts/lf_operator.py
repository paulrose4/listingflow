"""Operator workbook views. Full machine checks remain in export.json."""

from collections import Counter

from lf_experience import field_label, label
from lf_rules import content_blocks
from lf_checklist import ITEMS, tables as checklist_tables


NAMES = {"PASS": "已核对", "FAIL": "需修改", "NEEDS_REVIEW": "待核实",
         "NOT_CHECKED": "未检查", "NOT_APPLICABLE": "不适用"}


def configuration(item):
    return item["id"] == "bundle.approval" or (
        item["id"].startswith("R-") and item["status"] == "NEEDS_REVIEW" and item["path"] == "rules")


def tables(request, metadata):
    content = request["content"]
    blocks = dict(content_blocks(content))
    results = request["checks"]["results"]
    review = request.get("review") or {}
    source_index = {u["id"]: (s, u) for s in request["sources"] for u in s["units"]}
    facts = {f["id"]: f for f in request["facts"]["facts"]}
    ledger = request["facts"].get("reconciliation", [])

    def locations(ids):
        return "\n".join(dict.fromkeys(
            f"{source_index[sid][0]['name']} · {source_index[sid][1]['locator'].removeprefix('sheet:')}"
            for sid in ids if sid in source_index))

    def block_sources(block):
        return locations([sid for fid in block.get("fact_ids", []) for sid in facts[fid]["sources"]])

    unresolved = [r for r in results if r["status"] not in {"PASS", "NOT_APPLICABLE"}]
    config = [r for r in unresolved if configuration(r)]
    local = [r for r in unresolved if not configuration(r) and r["severity"] == "blocking"]
    stage = ("已审核版本，按已批准范围使用" if request["mode"] == "final" else
             "草稿，内容仍需完善" if local else
             "草稿，待公司规则确认" if config else "草稿，待运营确认")
    action_rows = [
        ["交付状态", stage, f"SKU {request['sku']} · {request['site']} · 第{request['version']}版",
         ("按本版已确认的适用范围使用，新增资料须重新核对。" if request["mode"] == "final" else
          "先看本页的产品与文案事项。草稿不能冒充正式批准版。"), "运营", "", "", ""],
        ["核对范围", "有边界", "依据本次快照与公司规则进行核对；未全面核验平台政策、法律或实时关键词。",
         "词库未命中不代表文案质量、侵权或医疗宣称全面通过。", "信息说明", "", "", ""],
        ["反馈方式", "可选填写", "后面三列供运营记录处理意见；填写不会自动修改任务或批准文案。",
         "可直接在对话中按事项回复确认结果，由助手重新核对并导出新版本。", "运营", "", "", ""],
    ]
    for row in ledger:
        if row["status"] == "adopted":
            continue
        finding = row["reason"]
        if row["candidates"]:
            finding += "\n" + "\n".join(
                f"{c['value']}（{locations([c['source_id']])}）" for c in row["candidates"])
        action_rows.append([row.get("label", field_label(row["field"])), "本版已不采用" if row["status"] == "omitted" else "待核实，本版不写",
                            finding, row["action"], row["owner"], "", "", ""])
    for item in unresolved:
        if configuration(item) or item["id"].startswith("reliability.field.") or item["severity"] == "info":
            continue
        path = item["path"]
        block = blocks.get(path.removesuffix(".name"))
        finding = item["reason"]
        if block:
            finding += "\n当前原句：" + block["text"]
        owner = "文案助手"
        action = ("根据现有来源修正并复核；无需运营重新整理资料。" if item["status"] == "FAIL" else
                  "先核对具体来源与适用条件；仅把资料无法回答的问题交运营确认。")
        checklist_key = item["id"].removeprefix("checklist.")
        if checklist_key in ITEMS:
            action = review.get("operator_checklist", {}).get(checklist_key, {}).get("action") or action
            if checklist_key == "ip.visual":
                owner = "运营/权利负责人"
        action_rows.append([ITEMS[checklist_key][1] if checklist_key in ITEMS else label(path),
                            NAMES[item["status"]], finding, action, owner, "", "", ""])
    if config:
        action_rows.append(["公司规则确认", "配置待确认，不等于文案违规",
                            f"{len(config)}条配置或适用范围检查尚待确认，完整范围见“规则与范围”。",
                            "由规则负责人统一处理；不要求每个SKU重复上传词库。", "规则负责人", "", "", ""])
    if len(action_rows) == 3:
        action_rows.append(["本次检查", "无未处理行动项", "仅表示本次已执行检查未发现待办，不作全面质量保证。",
                            "审阅文案并明确确认后，才可申请正式版。", "运营", "", "", ""])

    content_rows = []
    for path, block in blocks.items():
        problems = [r for r in unresolved if r["path"] in {path, path + ".name"} and r["severity"] != "info"]
        for result in unresolved:
            key = result["id"].removeprefix("checklist.")
            entry = (review.get("operator_checklist") or {}).get(key, {})
            if result["severity"] == "info":
                continue
            affected = ([e["path"] for e in entry.get("examples", [])] if result["status"] == "FAIL"
                        else entry.get("paths", []))
            if {path, path + ".name"} & set(affected):
                problems.append(result)
        item = review.get("blocks", {}).get(path)
        status = ("需修改" if any(r["status"] == "FAIL" for r in problems) else "待核实" if problems else
                  NAMES[item["status"]] if item else "未检查")
        reasons = list(dict.fromkeys(r["reason"] for r in problems))
        if not reasons:
            reasons = [item["reason"] if item else "尚无本版逐条声明审核记录。"]
        content_rows.append([label(path), block["text"], status, "\n".join(reasons), block_sources(block)])
    for key, item in review.get("quality", {}).items():
        labels = {"differentiation": "五点是否互补", "buyer_usefulness": "是否回答购买疑问",
                  "naturalness": "表达是否自然", "conciseness": "是否重复堆砌",
                  "keyword_fit": "核心词是否相关", "conditions": "使用条件是否完整"}
        content_rows.append([labels.get(key, key), "\n".join(e["quote"] for e in item.get("examples", [])),
                             NAMES[item["status"]], item["reason"], "本版文案表达审核，不是产品事实来源"])

    evidence_rows = []
    for row in ledger:
        value = "\n".join(facts[fid]["value"] for fid in row["fact_ids"]) or "本版不采用"
        for entry in row["candidates"]:
            evidence_rows.append([row.get("label", field_label(row["field"])), value, entry["value"], locations([entry["source_id"]]),
                                  entry["quote"], row["reason"]])
        if not row["candidates"]:
            evidence_rows.append([row.get("label", field_label(row["field"])), value, "", "未取得可用依据", "", row["reason"]])
    new_layout = request.get("report_layout") in {"four-checklists-v1", "operator-overview-v1"}
    clean_terms = sum(r["id"].startswith("R-") and r["status"] == "PASS"
                      and (not new_layout or r.get("method") != "explicit_rule_review") for r in results)
    manual_rules = sum(r.get("method") == "explicit_rule_review" for r in results) if new_layout else 0
    scope_rows = [
        ["精确风险词扫描", "已执行", f"{clean_terms}条规则未命中精确短语；不计为{clean_terms}项文案质量通过。"],
        ["实际风险词命中", "见内容检查", str(sum(r["id"].startswith("R-") and r["status"] == "FAIL"
                                               and (not new_layout or r.get("method") != "explicit_rule_review")
                                               for r in results)) + "条命中记录"],
        ["公司规则配置", "待确认" if config else "已检查", f"{len(config)}条配置检查待处理，未自动批准或跳过。"],
        ["技术审计记录", "保留", "同批export.json保留完整检查、来源与版本；运营无需读取。"],
        ["审核身份", {"assistant": "助手审核", "human": "人工审核"}.get(review.get("reviewer_kind"), "未审核"),
         review.get("reviewer", "") + "；助手审核不等于独立人工审核或公司批准。"],
    ]
    if manual_rules:
        scope_rows.append(["专项规则核验", "已记录", f"{manual_rules}条专项规则审核，与精确词扫描分开统计。"])
    for reason, count in Counter(r["reason"] for r in config).items():
        scope_rows.append(["规则配置事项", f"{count}条待确认", reason])
    for item in unresolved:
        if item["severity"] == "info" and not item["id"].startswith("reliability.field."):
            scope_rows.append([label(item["path"]), NAMES[item["status"]], item["reason"]])
    for source in request["sources"]:
        selected = request["facts"]["selection"][source["id"]]
        checked = request["facts"].get("source_review", {}).get(source["id"], {})
        status = {"SUCCESS": "文字提取完成", "PARTIAL": "部分内容需另行查看", "FAILED": "提取失败",
                  "unsupported": "格式暂不支持", "excluded": "已排除", "over_limit": "超出处理限额"}.get(source["status"], source["status"])
        dispositions = Counter(
            ("已记录检查" if request["facts"]["coverage"].get(gap["id"], {}).get("action") == "inspected" else "未作为事实依据")
            for gap in source["gaps"])
        scope_rows.append([source["name"], "参与核对" if selected["action"] == "use" else "未作为事实来源",
                           selected["reason"] + "\n阅读范围：" + checked.get("reason", "未记录")
                           + f"\n提取状态：{status}；覆盖缺口{len(source['gaps'])}处。"
                           + " ".join(f"{name}{count}处。" for name, count in dispositions.items())])

    copy_rows = [["交付状态", stage], ["SKU", request["sku"]], ["站点", request["site"]]]
    for path, block in blocks.items():
        copy_rows.append([label(path) + ("：" + block["name"] if path.startswith("specs.") else ""), block["text"]])
    metadata = [[{"mode": "导出状态", "batch": "导出批次", "site": "站点", "language": "语言",
                  "version": "文案版本", "created_utc": "导出时间UTC", "rule_scope": "审核范围"}.get(k, k), v]
                for k, v in metadata]
    result = {
        "文案": [("文案", ["栏目", "可复制内容"], copy_rows, [27, 104]),
                 ("版本", ["记录项", "值"], metadata, [26, 96])],
        "自查": (checklist_tables(request) if new_layout else []) + [
            ("处理清单", ["事项", "当前判断", "具体发现", "下一步", "负责方", "处理意见", "确认人", "处理结果"],
             action_rows, [18, 22, 44, 38, 14, 24, 12, 18]),
            ("内容检查", ["文案位置", "当前原句", "核对结果", "判断与修改理由", "来源文件及位置"],
             content_rows, [20, 62, 14, 44, 40]),
            ("来源依据", ["产品字段", "本版采用值", "来源中的候选值", "文件及位置", "来源原文", "采用或不采用的原因"],
             evidence_rows, [20, 28, 30, 38, 50, 40]),
            ("规则与范围", ["事项或文件", "状态", "核对范围与说明"], scope_rows, [44, 28, 112]),
            ("版本", ["记录项", "值"], metadata, [26, 96]),
        ],
    }
    if request.get("report_layout") == "operator-overview-v1":
        from lf_overview import tables as overview_tables
        overview, actions, handled = overview_tables(request)
        result["自查"] = [overview, *result["自查"][:4], actions, handled, *result["自查"][5:]]
    return result
