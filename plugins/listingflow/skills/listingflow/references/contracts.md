# 任务数据契约

本文是基础事实/内容契约。v2+ 另需 [增强写作契约](editorial.md) 中的 brief、原文 evidence 和六维质量审核；新建 v3 任务还必须遵守 [事实核对与运营交付](operator-v3.md) 的 source_review、reconciliation、claims 和 conditions，以及 [关键词自动调研](keyword-research.md) 的采集、取舍及版本绑定。旧任务保留原流程，产品内容的六个顶层字段不变。`keywords.source` 新增 `ebay_research`，仅用于已采集且已采用的实证词，不能直接把旧示例的模型建议标成实证来源。

这些 JSON 由 Codex 使用文件编辑工具写在任务下的 `inputs`，运营不需要填写。业务文本使用 UTF-8，脚本用 `-X utf8` 运行可避免 Windows 控制台乱码。

## 来源及观察

`show sources` 返回 `S0001:U1` 等提取单元 ID，定位包括 Excel 单元格、Word 正文块/表格行列、PDF 页码和内嵌媒体。`S0001:G1` 是同文件的解析/覆盖缺口，二者不可互换。

观察示例（仅当真正查看过对应单元）：

```json
{
  "unit_id": "S0002:U1",
  "method": "visual",
  "actor": "Codex visual inspection",
  "text": "记录实际看见的文字、对象及不清楚的区域，不猜测。",
  "reason": "核对本页是否包含文本抽取遗漏的标签参数。"
}
```

`method` 支持 `visual`、`operator_statement`、`formula_verification`。人工陈述额外保存 `quote` 原话；不是文件原文，不伪装为自动提取。公式核对说明真正依据，不执行不可信公式。

新增产品事实而非观察现有来源时使用 `statement`，JSON 为 `{"text":"补充事实","actor":"实际操作者","quote":"用户原话","reason":"补充原因"}`。返回独立来源编号，将其纳入 `selection` 后引用；脚本不会代替业务判断专项证明是否充分。

## 冻结事实

```json
{
  "sku": "DEMO-01",
  "site": "US",
  "product_revision": "运营确认的本次实物版本或资料中明确的版本",
  "selection": {
    "S0001": {"action": "use", "sku": "DEMO-01", "site": "US", "reason": "说明正文明确标注本次 SKU"}
  },
  "coverage": {},
  "required_fields": [],
  "unresolved": [],
  "decisions": [],
  "facts": [
    {"id": "F1", "field": "product_name", "value": "Desk organizer", "sku": "DEMO-01", "status": "confirmed",
     "sources": ["S0001:U1"], "support_reason": "该单元明确给出产品名称。"},
    {"id": "F2", "field": "core_function", "value": "Organizes pens", "sku": "DEMO-01", "status": "confirmed",
     "sources": ["S0001:U2"], "support_reason": "该单元明确说明用途。"}
  ]
}
```

每个资料都要在 `selection` 中声明 `use` 或 `exclude`，给原因；采用资料必须明确适用 SKU 与站点。未知关系不能凭空改成适用。多个同字段不同值会拒绝冻结；需要区分的维度命名为 `dimensions.product`、`dimensions.package` 等，不将冲突改名规避。

`required_fields` 由产品类别和请求确定，例如电器可能需要 `rated_voltage`、`plug_type`；没有资料时停止相应声明，不能为满足字段填猜测值。非电器不机械要求电压。`unresolved` 非空不能冻结。

`decisions` 的条目包含 `question`、`answer`、`actor`、`quote`，记录实际用户决定。没有疑点时允许为空，不强迫用户确认整张表。

有采用资料的覆盖缺口时：

```json
{
  "S0002:G1": {"action": "inspected", "observation_ids": ["O1"], "reason": "已逐项查看本页标签，观察 O1 记录实际文字。"},
  "S0002:G2": {"action": "exclude", "reason": "本页为另一型号装配图；已明确与本次 SKU 无关，不支持任何本次声明。"}
}
```

不能写“已检查”却没有观察。`exclude` 是可审查的范围决定，不代表解析成功；原缺口仍会进入报告。

## 文案结构

顶层只包含 `title/specs/bullets/qa/description/keywords`。普通文本块为 `{"text":"...","fact_ids":["F1"]}`，规格块额外有 `name`；所有块至少引用一个真实事实。规格名也是客户可见内容，会参与词库检查。

```json
{
  "title": {"text": "Desk Organizer for Pens", "fact_ids": ["F1", "F2"]},
  "specs": [{"name": "Product type", "text": "Desk organizer", "fact_ids": ["F1"]}],
  "bullets": [
    {"text": "Keeps pens together on your desk", "fact_ids": ["F2"]}
  ],
  "qa": [
    {"question": {"text": "Can I use it to organize pens?", "fact_ids": ["F2"]},
     "answer": {"text": "Yes, it is designed to hold pens together.", "fact_ids": ["F2"]}}
  ],
  "description": [{"text": "Keep your pens together with this desk organizer.", "fact_ids": ["F1", "F2"]}],
  "keywords": {"primary": "Desk Organizer", "source": "model_suggested", "reference": "基于已确认产品类型提出；未获取实时搜索或广告数据。"}
}
```

这是结构示例，不是合格成品：实际公司规则要求五条五点与五组 QA。不为凑数量复制同义句或虚构功能；五个有价值角度无法得到支持时报告资料不足。

文本必须 NFC 规范化、无不可见控制字符，长度按 NFC Unicode 码点含空格标点计数。不截断句子凑限制；文案不含来源标记、JSON 字段名或内部备注。长详情用多段，单段建议不超过 600 字符便于 Excel 展示。

## 审阅与批准

`review` 顶层为 `content_hash`、`reviewer`、`reviewer_kind`、`blocks`、`categories`、`rules`。每个当前文案块都要有一项：

```json
{
  "content_hash": "从 save-content 返回复制的实际哈希",
  "reviewer": "Codex semantic review",
  "reviewer_kind": "assistant",
  "blocks": {
    "title": {"status": "PASS", "fact_ids": ["F1", "F2"], "reason": "实际核对了产品名与用途；没有增加范围、效果或配件。"}
  },
  "categories": {
    "localization": {"status": "PASS", "reason": "说明具体核查过的当地术语、拼写和表达。"},
    "claims": {"status": "PASS", "reason": "说明核查过的认证、功效、性能保证与否定条件。"},
    "keywords": {"status": "PASS", "reason": "建议词与产品相关，未伪称使用实时广告数据；已检查重复和问答自然度。"},
    "images": {"status": "NOT_APPLICABLE", "reason": "本次没有采用图片或图片相关声明/规则。"}
  },
  "rules": {}
}
```

必须补齐所有块如 `specs.0`、`bullets.0`、`qa.0.question`、`qa.0.answer`、`description.0`。每项 `fact_ids` 必须等于对应文案块引用的 ID，核对实际来源和条件，不只确认 ID 存在。

状态为 `PASS/FAIL/NEEDS_REVIEW/NOT_CHECKED/NOT_APPLICABLE`。所有必需语义块不得“不适用”，图片只有确实不适用时才可如此标记；英文词库不证明德语已完整检查。

`rules` 用于已批准的人工规则逐项核查，如 `{"R-0001":{"status":"PASS","reason":"具体核查证据"}}`；不能覆盖确定性文本命中或替代资源包审批。

`approve` 单独使用 `{"content_hash":"实际当前哈希","actor":"实际确认者","quote":"实际用户认可当前版本的原话"}`。这是记录而不是身份认证；Codex 不得代替用户批准、编造原话或把助手的 review 当成人工确认。
