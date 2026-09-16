"""Compact operator-facing task summaries without hiding check coverage."""

import re
from collections import Counter


def label(path):
    if path in {"title", "keywords", "content", "brief", "evidence", "quality", "rules"}:
        return {"title": "标题", "keywords": "关键词", "content": "整篇文案", "brief": "写作规划",
                "evidence": "事实依据", "quality": "写作质量", "rules": "规则配置"}[path]
    match = re.fullmatch(r"(bullets|specs|description)\.(\d+)(\.name)?", path)
    if match:
        group = {"bullets": "五点", "specs": "规格", "description": "详情段落"}[match[1]]
        return f"{group}第 {int(match[2]) + 1} 项" + ("名称" if match[3] else "")
    match = re.fullmatch(r"qa\.(\d+)\.(question|answer)", path)
    if match:
        return f"问答第 {int(match[1]) + 1} 组" + ("问题" if match[2] == "question" else "回答")
    return path


def field_label(field):
    return {
        "product_name": "产品名称", "product_type": "产品类型", "core_function": "核心功能",
        "color": "颜色", "materials": "材质", "material": "材质", "input_power": "输入电源",
        "power_method": "供电方式", "battery_configuration": "电池配置", "rated_power": "额定功率",
        "heating_levels": "加热档位", "vibration_levels": "振动档位", "timer": "计时方式",
        "cleaning": "清洁方式", "care": "清洁保养", "controller_cable": "控制器线长",
        "product_size": "产品尺寸", "dimensions": "尺寸", "package_contents": "包装内容",
        "fit_and_use": "佩戴与使用", "compartments": "分区数量", "open_tops": "开口结构",
        "net_weight": "净重", "weight": "重量", "manual": "说明书", "independent_controls": "独立控制",
    }.get(field, field)


def issue_groups(checks):
    groups = {}
    for item in checks["results"]:
        if item["status"] in {"PASS", "NOT_APPLICABLE"}:
            continue
        identifier = item["id"]
        if identifier == "bundle.approval" or identifier.startswith("R-") and item["status"] == "NEEDS_REVIEW":
            key, owner, action = "business_rules", "规则负责人", "一次性确认规则的适用范围和处置；运营可继续审阅草稿。"
        elif item["status"] == "FAIL" and not identifier.startswith("editorial.review."):
            key, owner, action = "fix_copy", "文案助手", "根据现有事实修改命中段落，再重新检查。"
        elif identifier.startswith("reliability.field."):
            key, owner, action = "product_facts", "运营/产品负责人", "仅确认资料仍有差异的字段；已不采用的可选项不阻断本版草稿。"
        elif identifier.startswith(("semantic.", "review.", "editorial.", "reliability.")):
            key, owner, action = "review_copy", "文案助手", "完成来源核对和语言审核；只有无法从资料解决的问题才询问运营。"
        elif identifier == "keywords.live_data" or identifier.startswith("research."):
            key, owner, action = "keyword_data", "文案助手", "按各来源采集结果处理；缺失调研由助手补做，店铺登录问题才交运营。"
        else:
            key, owner, action = "other", "文案助手", "查看具体依据后处理，不能把未检查改成通过。"
        group = groups.setdefault(key, {"group": key, "owner": owner, "action": action, "count": 0,
                                        "blocking": 0, "warnings": 0, "examples": [], "ids": []})
        group["count"] += 1
        group["blocking"] += item["severity"] == "blocking"
        group["warnings"] += item["severity"] == "warning"
        group["ids"].append(identifier)
        if len(group["examples"]) < 3:
            group["examples"].append({"path": label(item["path"]), "status": item["status"], "reason": item["reason"]})
    order = {"product_facts": 0, "fix_copy": 1, "review_copy": 2, "business_rules": 3, "other": 4, "keyword_data": 5}
    return sorted(groups.values(), key=lambda g: order[g["group"]])


def dashboard(state, checks=None):
    if not state["sources"]:
        stage, owner, next_action = "等待产品资料", "运营", "提供本次 SKU 的产品资料文件或已授权目录。"
    elif not state.get("facts"):
        stage, owner, next_action = "整理资料与核对事实", "文案助手", "核对 SKU、版本和关键事实，汇总仍需确认的问题；不要索要非必需英文稿。"
    elif state.get("research_version") and not state.get("research"):
        stage, owner, next_action = "调研关键词", "文案助手", "自动采集本站点下拉建议、相关竞品标题与PLA推荐词，逐项记录结果和限制。"
    elif state.get("workflow_version", 1) >= 2 and not state.get("brief"):
        stage, owner, next_action = "规划卖点", "文案助手", "根据已冻结事实组织卖点与购买疑问，运营无需填写技术表。"
    elif not state["contents"]:
        stage, owner, next_action = "可以生成初稿", "文案助手", "按写作规划生成完整文案，再做程序与语义审核。"
    else:
        local = [r for r in checks["results"] if r["severity"] == "blocking"
                 and r["status"] not in {"PASS", "NOT_APPLICABLE"}
                 and r["id"] != "bundle.approval"
                 and not (r["id"].startswith("R-") and r["status"] == "NEEDS_REVIEW")]
        if local:
            stage, owner, next_action = "文案待完善", "文案助手", "先处理可自行解决的文案和审核问题，再向运营展示结果。"
        elif checks["blocking_count"]:
            stage, owner, next_action = "草稿可审阅，正式导出受阻", "规则负责人", "文案已完成当前检查；处理规则或适用性问题，或按用户要求导出带问题的草稿。"
        elif not state["contents"][-1].get("approval"):
            stage, owner, next_action = "等待运营确认", "运营", "审阅当前文案，确认后才能正式导出。"
        else:
            stage, owner, next_action = "可正式导出", "文案助手", "按运营指示导出当前内容版本及对应自查报告。"
    gaps = [{"source": s["id"], "file": s["name"], "gap": g["id"], "reason": g["reason"]}
            for s in state["sources"] for g in s["gaps"]]
    return {"task_id": state["id"], "sku": state["sku"], "site": state["site"], "language": state["language"],
            "stage": stage, "next_owner": owner, "next_action": next_action,
            "workflow_version": state.get("workflow_version", 1), "revision": state.get("revision"),
            "locked_blocks": [label(p) for p in state.get("locked_blocks", [])],
            "content_version": state["contents"][-1]["version"] if state["contents"] else None,
            "file_states": dict(Counter(s["status"] for s in state["sources"])),
            "coverage": {"recorded_gaps": len(gaps), "examples": gaps[:5], "more": max(0, len(gaps) - 5),
                         "note": "原始缺口始终保留；采用/排除与观察处置另见冻结事实。"},
            "issues": issue_groups(checks) if checks else [], "checks_total": len(checks["results"]) if checks else 0,
            "export_batches": len(state.get("exports", []))}
