# 增强写作与运营契约

新任务另启用 [关键词自动调研](keyword-research.md)：冻结事实后、brief 前必须保存 research。下述基础 brief/review 示例在新任务中还须加入当前 `research_hash`；已采集的适配核心词使用 `source=ebay_research`。旧任务保留原契约。

本文描述 v2+ 共用的写作规划与证据结构。新建任务现采用 `workflow_version=3`，另须遵守 [v3事实与运营契约](operator-v3.md)；已保存 v1/v2 任务保留原流程与批准记录。写作配置从 `assets/editorial.json` 复制入任务并固定哈希。这些流程检查不是额外的 eBay 官方政策。

## 运营默认交互

只要求运营提供目标 SKU、站点、可用资料；已明确的上下文不重复索要。语言按站点在规则包中唯一支持的语言确定，语气默认 `clear_practical`。参考文案、关键词、语气偏好和输出位置可选，卖点整理、来源编号、内部 JSON 和审核模板由助手处理。已有资料能回答的问题不要重复问。

普通完整生成请求一次执行到草稿双 Excel 交付，不能将本文件的内部步骤拆成运营必须发送的多轮提示。缺少英文稿不暂停，规则未批准不影响草稿交付；关键事实不清才集中追问。原件只读，适用范围和正式批准门禁不变。仅分析、仅文字或局部修改等明确请求优先于默认全流程。

状态用中文明确分工：

- 资料核对/文案修正/原文核验：助手先处理。
- SKU、版本或关键参数不明确：针对矛盾给运营具体问题和定位，允许“不知道，先不写该可选项”。
- 公共规则审批：汇总给规则负责人一次性处理，不要求每个 SKU 再上传词库。
- 当前内容最终确认：展示文案后由运营明确确认，不能把普通“继续”当作批准。

正常首稿一次展示完整可复制文案、同批草稿文案/自查 Excel 链接及少量真实待办，不等运营追加“导出”才制作文件；仅文字或仅文件按用户选择。局部修改只展示改动段落、修改理由和当前状态，文件是否更新遵循本次要求或已建立的交付约定。不要索要未获业务批准的“必填英文稿”或竞品。

## 写作规划

```text
PY SKILL/scripts/listingflow.py prepare --task TASK --expect REV --kind brief
PY SKILL/scripts/listingflow.py brief --task TASK --expect REV --json EDITED_TEMPLATE
PY SKILL/scripts/listingflow.py context --task TASK
PY SKILL/scripts/listingflow.py evidence --task TASK --fact F1
```

`prepare` 在任务的 `inputs` 中创建新模板文件，初始空白不是已完成结果；返回当前 revision，不改变数据库。模板由助手填写。核心结构：

```json
{
  "schema": 1,
  "facts_hash": "实际冻结事实哈希",
  "sku": "实际SKU",
  "site": "US",
  "language": "en",
  "audience": "普通桌面收纳需求用户",
  "audience_basis": "editorial_hypothesis",
  "tone": "clear_practical",
  "primary_keyword": {"primary": "Desk Organizer", "source": "model_suggested", "reference": "基于产品类型提出，非实时搜索数据。"},
  "angles": [
    {"label": "分区收纳", "buyer_need": "区分不同小物品", "benefit": "按已知分区结构整理物品", "fact_ids": ["F1"], "caveat": ""}
  ],
  "questions": [{"intent": "确认实际分区数量", "fact_ids": ["F1"]}],
  "critical_fact_ids": [],
  "avoid": ["不声明没有证据的防水或耐热能力"]
}
```

这是字段示例；实际 angles/questions 数量须与本任务公司规则中的五点/问答数量一致。每个角度/问题引用真实事实；不同角度可以共用事实，但不把同义改写当作独立价值。角度顺序对应五点顺序。

`audience_basis` 可为 `user_request/product_sources/editorial_hypothesis`，防止把市场假设写成产品事实。语气为 `clear_practical/warm_restrained/technical_precise`，只影响表达，不放松事实和规则要求。

`critical_fact_ids` 仅加入本次必须保留的实际条件，例如额定电压、特定洗护限制；不机械要求每个产品填写全部字段。没有这些依据不能自行补造。`caveat` 写清限制，不适用时可为空。

规划保存后改变 tone/角度等会产生新修订，原文案的正式导出资格失效，须依据新规划保存并审核新内容。旧规划和旧文案仍可在历史中追溯。更换产品事实需要新任务，不能通过修改规划绕过事实冻结。

增强版重复提交相同规划，或提交与当前内容完全相同且规划未变化的文案，不生成空版本、不撤销原确认。仍须使用当前 revision，不能借重复提交绕过并发检查。

## 有依据的审核

```text
PY SKILL/scripts/listingflow.py prepare --task TASK --expect REV --kind review
PY SKILL/scripts/listingflow.py review --task TASK --expect REV --json COMPLETED_REVIEW
```

沿用基础契约的 `blocks/categories/rules`，新增：

- `brief_hash`：本版文案对应的实际规划哈希。
- `fact_evidence`：本版使用的每个事实 ID 对应真实原文摘录，允许多个段落复用。
- `quality`：六个维度的核查及实际文案例证，不填总分或“达到98分”。

```json
{
  "fact_evidence": {
    "F1": [{"source_id": "S0001:U3", "quote": "来源中实际存在的连续原文"}]
  },
  "quality": {
    "differentiation": {
      "status": "PASS",
      "reason": "明确说明各五点解决不同需求；不能只写质量优秀。",
      "examples": [{"path": "bullets.0", "quote": "当前这一条中实际存在的原文"}]
    }
  }
}
```

`fact_evidence` 键必须恰好覆盖当前文案引用的事实。摘录需属于该事实关联的真实 source。视觉事实用 `source_id` 加 `observation_id`，quote 引用同来源的实际观察文字；机器验证摘录存在，不代表机器证明了语义支持关系。仍应检查原文语义、条件、否定、SKU 和实物版本。

六个 quality 键全部填写：`differentiation`（互补）、`buyer_usefulness`（决策价值）、`naturalness`（自然语言）、`conciseness`（简洁）、`keyword_fit`（相关性）、`conditions`（条件完整）。PASS/FAIL 必须有当前文案中的真实例证；未执行用 NOT_CHECKED，不能以不适用跳过。例证只证明检查对象存在，不把同一模型的复核说成独立人工审核。

当前审核的原文摘录与六维文案例证随自查 Excel 的“依据”页导出，保留审核者类型；未经审核的草稿不会补造这些记录。

短语相似、套话、数字差异和长段落是启发式警告。正确换算、文字数字与型号可能触发数字警告；解释并做语义检查，不为了清零而删除正确数值。英语规则不自动代表德语词形覆盖。

## 局部修改与保护

```text
PY SKILL/scripts/listingflow.py revise --task TASK --expect REV --json CHANGES
```

CHANGES 只包含需要修改的块：

```json
{"bullets.2":{"text":"新的第三条文案","fact_ids":["F3"]}}
```

支持完整块路径 `title/specs.0/bullets.2/qa.0.question/qa.0.answer/description.0/keywords`。脚本保留其他内容并生成新版本，返回 `changed_paths`。不能使用路径遍历、任意 JSON 属性、增加/删除数组条目或引用未冻结事实。

持续保护用 `lock`，JSON 为 `{"action":"lock","paths":["title"],"actor":"实际用户","quote":"明确要求以后不修改标题的原话"}`；解除用 action=unlock 并记录新的明确要求。不接受助手自行代签。普通一次“其他不动”不需要持久锁。

## 查找与下一步

```text
PY SKILL/scripts/listingflow.py tasks --root AUTHORIZED_TASK_ROOT --sku EXACT_SKU
PY SKILL/scripts/listingflow.py dashboard --task TASK
```

列表只在指定根目录读取任务摘要，不扫描整台电脑，不将摘要读取冒充完整性检查；选定后 dashboard 会核验快照。默认显示最多 20 条，扫描最多 500 个候选，未完整扫描会明确说明，不能假装没有更多任务。

dashboard 把几百条检查汇总为负责方、数量、少量例证和下一步。v2 保留原明细 Excel；v3 将完整机器明细保留在 checks 与同批 export.json，Excel 展示运营视图。资料缺口即使被合理排除仍计入原始覆盖记录，不把“被排除”改成“已成功解析”。
