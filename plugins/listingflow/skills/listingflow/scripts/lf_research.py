"""Evidence-backed keyword research; collection is performed by the Codex browser/connector."""

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse

from lf_rules import content_blocks, digest, matches


CHANNELS = {"autocomplete": "eBay搜索下拉建议", "competitors": "主竞品标题样本",
            "pla": "PLA广告推荐关键词"}
STATES = {"collected": "已取得", "empty": "已查询，无结果", "blocked": "访问受限",
          "error": "采集失败", "declined": "用户要求跳过"}
DOMAINS = {"US": "ebay.com", "UK": "ebay.co.uk", "DE": "ebay.de",
           "AU": "ebay.com.au", "CA": "ebay.ca", "FR": "ebay.fr", "IT": "ebay.it", "ES": "ebay.es"}


def active(state):
    return state.get("research_version") == 1


def text(value, name, maximum=30000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Research requires nonempty bounded text: {name}")
    return value


def site_url(value, site):
    parsed = urlparse(text(value, "url", 4096))
    domain = DOMAINS.get(site)
    if (not domain or parsed.scheme != "https" or parsed.username or parsed.password
            or not parsed.hostname or not (parsed.hostname == domain or parsed.hostname.endswith("." + domain))
            or parsed.port not in {None, 443}):
        raise ValueError("Research URL must belong to the target eBay marketplace")
    return parsed


def template(state):
    if not state.get("facts"):
        raise ValueError("Freeze facts before keyword research")
    return {"schema": 1, **{k: state[k] for k in ("sku", "site", "language", "facts_hash")},
            "channels": {key: [] for key in CHANNELS}, "candidates": []}


def validate(payload, state):
    if not state.get("facts"):
        raise ValueError("Freeze facts before keyword research")
    expected = {"schema", "sku", "site", "language", "facts_hash", "channels", "candidates"}
    if not isinstance(payload, dict) or set(payload) != expected or payload["schema"] != 1:
        raise ValueError("Invalid research schema")
    for key in ("sku", "site", "language", "facts_hash"):
        if payload[key] != state[key]:
            raise ValueError(f"Research does not match frozen task: {key}")
    if not isinstance(payload["channels"], dict) or set(payload["channels"]) != set(CHANNELS):
        raise ValueError("Research must cover autocomplete, competitors and PLA separately")
    facts = {f["id"] for f in state["facts"]["facts"]}
    index = {}
    for channel, attempts in payload["channels"].items():
        if not isinstance(attempts, list) or not 1 <= len(attempts) <= 8:
            raise ValueError("Each research channel needs an actual bounded attempt or explicit user opt-out")
        for ai, attempt in enumerate(attempts):
            fields = {"status", "observed_at", "url", "query", "method", "evidence_text", "reason", "items"}
            if not isinstance(attempt, dict) or set(attempt) != fields:
                raise ValueError("Invalid research attempt fields")
            if attempt["status"] not in STATES or attempt["method"] not in {"browser", "connector", "user_instruction"}:
                raise ValueError("Invalid research outcome/method")
            for key in ("query", "evidence_text", "reason"):
                text(attempt[key], key, 30000 if key == "evidence_text" else 600)
            if (attempt["status"] == "declined") != (attempt["method"] == "user_instruction"):
                raise ValueError("Only an actual user instruction can opt out of research")
            site_url(attempt["url"], state["site"])
            observed = datetime.fromisoformat(attempt["observed_at"])
            if observed.tzinfo is None or observed > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise ValueError("Research observation needs a real timezone-aware, non-future timestamp")
            items = attempt["items"]
            if not isinstance(items, list) or len(items) > 100:
                raise ValueError("Research items must be a bounded array")
            if bool(items) != (attempt["status"] == "collected"):
                raise ValueError("Only collected research can contain items; empty success is not collected")
            for ii, item in enumerate(items):
                if not isinstance(item, dict) or set(item) != {"text", "url", "relevant", "reason"}:
                    raise ValueError("Invalid research item fields")
                text(item["text"], "item text", 500)
                text(item["reason"], "relevance reason", 600)
                if type(item["relevant"]) is not bool:
                    raise ValueError("Item relevance must be explicitly checked")
                parsed = site_url(item["url"], state["site"])
                if item["text"] not in attempt["evidence_text"]:
                    raise ValueError("Research item quote does not exist in captured evidence")
                if channel == "competitors":
                    if not re.search(r"/itm/(?:[^/]+/)?\d+(?:/|$)", parsed.path):
                        raise ValueError("Competitor requires an observed eBay item URL")
                    if item["url"] not in attempt["evidence_text"]:
                        raise ValueError("Competitor URL must occur in captured evidence")
                index[f"{channel}:{ai}:{ii}"] = item
    candidates = payload["candidates"]
    if not isinstance(candidates, list) or len(candidates) > 100:
        raise ValueError("Research candidates must be a bounded array")
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {"term", "decision", "reason", "fact_ids", "evidence"}:
            raise ValueError("Invalid keyword candidate fields")
        term = text(candidate["term"], "candidate term", 150)
        if term.casefold().strip() in seen:
            raise ValueError("Duplicate keyword candidate")
        seen.add(term.casefold().strip())
        text(candidate["reason"], "adoption reason", 600)
        if candidate["decision"] not in {"use", "avoid"}:
            raise ValueError("Candidate needs use/avoid decision")
        refs = candidate["fact_ids"]
        if (not isinstance(refs, list) or any(fid not in facts for fid in refs)
                or (candidate["decision"] == "use" and not refs)):
            raise ValueError("Adopted keyword needs frozen product fact references")
        evidence = candidate["evidence"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 12 or any(e not in index for e in evidence):
            raise ValueError("Candidate must cite collected research items")
        if any(not matches(index[e]["text"], term) for e in evidence):
            raise ValueError("Keyword phrase must occur in every cited item")
        if candidate["decision"] == "use" and not any(index[e]["relevant"] for e in evidence):
            raise ValueError("Cannot adopt a keyword supported only by irrelevant items")
    return payload


def require_current(state, brief=None):
    if not active(state):
        return
    if not state.get("research") or digest(state["research"]) != state.get("research_hash"):
        raise ValueError("Complete and save keyword research before the writing brief")
    validate(state["research"], state)
    if brief is not None and brief.get("research_hash") != state["research_hash"]:
        raise ValueError("Research changed; update the writing brief before content/review")


def validate_keyword(keyword, state):
    require_current(state)
    if not active(state):
        return
    if keyword["source"] == "public_competitor":
        raise ValueError("New tasks require evidenced ebay_research instead of unbound public_competitor")
    usable = [c for c in state["research"]["candidates"] if c["decision"] == "use"]
    if keyword["source"] == "ebay_research":
        if not any(c["term"].casefold() == keyword["primary"].casefold() for c in usable):
            raise ValueError("Research keyword must match an adopted, evidenced candidate")
    elif usable and keyword["source"] != "operator_supplied":
        raise ValueError("Use an adopted research keyword; do not silently fall back to a model suggestion")


def effective_attempts(attempts):
    """Preserve attempts for audit, but resolve the same query by its latest observation."""
    latest = {}
    for attempt in sorted(attempts, key=lambda a: datetime.fromisoformat(a["observed_at"])):
        latest[" ".join(attempt["query"].casefold().split())] = attempt
    return list(latest.values())


def coverage(research):
    result = {}
    for key, name in CHANNELS.items():
        attempts = effective_attempts(research["channels"][key])
        success = [a for a in attempts if a["status"] == "collected"]
        count = len({
            re.search(r"/itm/(?:[^/]+/)?(\d+)(?:/|$)", urlparse(i["url"]).path).group(1)
            if key == "competitors" else i["text"].casefold()
            for a in success for i in a["items"]})
        complete = all(a["status"] in {"collected", "empty"} for a in attempts)
        result[key] = {"name": name, "collected": bool(success), "complete": complete,
                       "status": ("已取得，部分查询受限" if success and not complete else
                                  f"已取得{count}条" if success else
                                  "；".join(dict.fromkeys(STATES[a["status"]] for a in attempts))),
                       "reason": "；".join(dict.fromkeys(a["reason"] for a in attempts))}
    return result


def summary(research):
    return "；".join(f"{v['name']}：{v['status']}" for v in coverage(research).values()) + "。以上不是搜索量或转化数据。"


def checks(state, record):
    if not active(state):
        return []
    valid = False
    try:
        require_current(state, record.get("brief") or {})
        valid = (record.get("research_hash") == state.get("research_hash")
                 and digest(record.get("research")) == state["research_hash"])
    except (ValueError, TypeError, KeyError):
        pass
    result = [{"id": "research.current", "status": "PASS" if valid else "NOT_CHECKED",
               "severity": "blocking", "path": "keywords",
               "reason": "文案已绑定本次关键词调研记录。" if valid else "关键词调研缺失或已更新，需完成调研并更新文案审核。"}]
    if valid:
        info = coverage(state["research"])
        result.extend({"id": "research." + key, "status": "PASS" if v["collected"] and v["complete"] else "NEEDS_REVIEW",
                       "severity": "info", "path": "keywords", "reason": v["name"] + "：" + v["status"] + "。" + v["reason"]}
                      for key, v in info.items())
        status = "PASS" if all(v["collected"] and v["complete"] for v in info.values()) else "NEEDS_REVIEW"
        reason = summary(state["research"])
    else:
        status, reason = "NOT_CHECKED", "调研未完成或与当前文案不一致，不能声称已经取得实时关键词。"
    result.append({"id": "keywords.live_data", "status": status, "severity": "info",
                   "path": "keywords", "reason": reason})
    return result


def current_report(request):
    research = request.get("research")
    return (bool(research) and digest(research) == request.get("research_hash")
            and request.get("research_hash") == request["checks"].get("research_hash")
            and any(r["id"] == "research.current" and r["status"] == "PASS"
                    for r in request["checks"]["results"]))


def reference_rows(request):
    """Six-column rows fit the existing localization checklist without an extra workbook."""
    if not request.get("research_version"):
        return []
    if not current_report(request):
        return [["关键词调研", "未完成或已过期", "需重新调研并绑定本版文案。", "", "不能借用旧采集结果。", "由助手补齐。"]]
    research = request["research"]
    rows = []
    for channel, outcome in coverage(research).items():
        attempts = research["channels"][channel]
        rows.append([outcome["name"], outcome["status"], outcome["reason"], "",
                     "以下采集记录保留尝试历史；相同查询以最新一次结果为准。",
                     "本轮查询已完成。" if outcome["complete"] else "助手可重试；涉及店铺登录/验证时由运营完成后继续，不需重传产品资料。"])
        for attempt in attempts:
            parsed = urlparse(attempt["url"])
            url = parsed._replace(query="", fragment="").geturl()
            rows.append(["采集记录：" + outcome["name"], STATES[attempt["status"]], attempt["reason"],
                         attempt["query"], f"{attempt['observed_at']}\n{url}\n原始完整地址与页面摘录保留在同批审计记录。",
                         "历史尝试不覆盖最新查询结果。"])
    # Count distinct listing IDs, never raw hits or seller-written search-volume claims.
    titles = {}
    for attempt in effective_attempts(research["channels"]["competitors"]):
        for item in attempt["items"]:
            if item["relevant"]:
                identifier = re.search(r"/itm/(?:[^/]+/)?(\d+)(?:/|$)", urlparse(item["url"]).path).group(1)
                titles.setdefault(identifier, item["text"])
    texts = dict(content_blocks(request["content"]))
    for candidate in research["candidates"]:
        term = candidate["term"]
        hits = sum(bool(matches(title, term)) for title in titles.values())
        from lf_experience import label
        placement = "、".join(label(p) for p, block in texts.items() if matches(block["text"], term))
        frequency = f"相关竞品样本标题包含：{hits}/{len(titles)}；不是搜索量。"
        rows.append(["候选词：" + term,
                     "可用参考词" if candidate["decision"] == "use" else "不采用",
                     candidate["reason"], placement or "本版未使用",
                     frequency,
                     "按事实与自然表达择用，不强制堆词。" if candidate["decision"] == "use" else "不得因竞品使用而照搬。"])
        for eid in candidate["evidence"]:
            channel, ai, ii = eid.split(":")
            attempt = research["channels"][channel][int(ai)]
            item = attempt["items"][int(ii)]
            url = urlparse(item["url"])._replace(query="", fragment="").geturl()
            rows.append(["词条依据：" + term, CHANNELS[channel], item["reason"], item["text"],
                         f"{attempt['observed_at']}\n{url}", "只证明词条在所列来源出现，不证明本品具有竞品功能。"])
    rows.append(["搜索量与转化率", "未取得量化数据", "下拉建议、样本词频和广告推荐词不是搜索量。", "",
                 "本模块没有搜索量或转化率数据契约，不输出高流量、排名或效果保证。", "如需量化分析，另核实专门数据来源和统计期间。"])
    return rows
