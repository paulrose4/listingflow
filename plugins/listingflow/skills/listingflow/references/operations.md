# 操作与命令

## 默认连续执行

本页命令是助手的内部操作，不是运营教程。普通生成请求遵循 SKILL.md 的一次输入契约：必要输入齐全后连续执行到文案与草稿双 Excel 交付；不要做完 doctor、freeze、brief 或 review 就询问“是否继续”。正常进度可用简短中文说明，不制造阶段审批。

用户提供单个或多个附件时，授权范围只包含这些文件；即使为脚本选择公共父目录作为 `source-root`，也仅逐个 ingest 指定附件，不扫描父目录的其他文件。用户提供整个目录时才在该范围内清点。无法访问云盘链接时说明访问限制并请求可读取的原件，不自动登录或声称已下载。

输出位置沿用下文默认路径，由助手创建独立任务并返回文件链接，不让运营先手动创建输入/输出目录。无文件要求的纯文字请求不调用 export；仅分析、局部修改及开发验收请求按其明确范围执行。

只有必要输入缺失、关键事实冲突或运行能力缺失导致无法继续时才集中询问。非关键字段缺失就不写；非关键不支持文件记录未处理范围。资料不足以形成完整文案时说明缺口，不能为了交付而编造五条卖点或跳过检查。

## 环境

Python 3.12+，依赖见 `scripts/requirements.txt`。Excel 使用 openpyxl 确定性写入并逐格回读。Node 22+ 与 `@oai/artifact-tool` 仅用于可选预览。PDF 页图需要 pypdfium2；图片识别使用当前会话真实可用的视觉能力，不把“已渲染”当“已理解”。

本机可用桌面应用的 `load_workspace_dependencies` 定位运行时。普通机器由开发者提供环境或经授权创建独立虚拟环境，不自行全局安装依赖。资料核对与草稿导出可离线完成；默认关键词调研由助手调用当前可用连接器或浏览器，能力缺失时必须记录限制。

支持 `LISTINGFLOW_NODE` 指定 Node 可执行文件，`LISTINGFLOW_NODE_MODULES` 指定包含 `@oai/artifact-tool` 的 `node_modules`。这两个变量只在需要预览的命令环境设置。`doctor` 实际探测模块加载，返回缺失能力。预览的原生运行时可能在 Windows 退出时异常，脚本记录 `runtime_warning`，不影响 Python 生成并校验的 Excel；有 PNG 仍要实际查看，不把文件存在当作视觉合格。

以下 `PY`、`SKILL`、`TASK` 是由代理替换的绝对路径占位名，不让运营手动运行。

```text
PY SKILL/scripts/listingflow.py doctor
PY SKILL/scripts/listingflow.py init --root OUTPUT_ROOT --source-root AUTHORIZED_DIR --sku 77255304US --site US --language en
PY SKILL/scripts/listingflow.py ingest --task TASK --expect 0 --path PRODUCT_FILE --path MANUAL_FILE
PY SKILL/scripts/listingflow.py status --task TASK
PY SKILL/scripts/listingflow.py query --task TASK --text 77255304US
PY SKILL/scripts/listingflow.py query --task TASK --source S0001 --offset 0 --limit 40
PY SKILL/scripts/listingflow.py show --task TASK --section sources
```

未指定输出位置时可使用用户文档目录下的 `ListingFlow任务`；开始时说明位置。输出不能在 Skill 安装目录或所选产品资料目录内。每次 `init` 返回唯一任务路径。资料目录递归读取只能发生在用户已授权整个目录时；否则逐个 `--path` 指定。

首次导入后 `sources` 持有文件清单、快照哈希、完整提取单元和覆盖缺口。`query` 是展示分页而非解析截断，返回总数和 `has_more`。匹配到 SKU 后仍需检查同表表头、相邻规格、单位、其他工作表和版本适用性；不能只凭一个单元格自动绑定全表。

## 观察与事实冻结

```text
PY SKILL/scripts/listingflow.py render --task TASK --source S0002 --page 1
PY SKILL/scripts/listingflow.py observe --task TASK --expect REV --json OBSERVATION_JSON
PY SKILL/scripts/listingflow.py statement --task TASK --expect REV --json STATEMENT_JSON
PY SKILL/scripts/listingflow.py freeze --task TASK --expect REV --json FACTS_JSON
```

查看图片/页图后记录观察。每个已采用资料的提取缺口必须有同位置的观察记录，或有“不影响本次事实”的具体排除理由。解析范围超限时缩小输入或经授权调整运行上限，不把未读资料排除后称为全部读完。

运营口头补充新事实使用 `statement`，单独生成有原话与操作者的人工来源，再加入事实选择。不要把人工补充写进原件摘录。认证等专项声明仍需规则要求的证据，人工说“有认证”不自动替代报告。

Python 脚本不自动做语义事实抽取、OCR、翻译或文案生成；这些由调用本 Skill 的 Codex 执行，并通过契约写入结果。不要向用户声称脚本独立运行就会调用大模型。

## 写作、局部修改和审核

新建任务使用增强流程。冻结事实后先按 [关键词自动调研](keyword-research.md) 完成实际采集和 `research`，再按 [增强写作契约](editorial.md) 使用 `prepare --kind brief`、`brief` 和 `context`；初稿后用 `prepare --kind review` 填写有原文证据的审核。模板全部由助手填写，不新增运营表单。

```text
PY SKILL/scripts/listingflow.py prepare --task TASK --expect REV --kind research
PY SKILL/scripts/listingflow.py research --task TASK --expect REV --json RESEARCH_JSON
PY SKILL/scripts/listingflow.py show --task TASK --section research
PY SKILL/scripts/listingflow.py save-content --task TASK --expect REV --json CONTENT_JSON
PY SKILL/scripts/listingflow.py show --task TASK --section checks
PY SKILL/scripts/listingflow.py review --task TASK --expect REV --json REVIEW_JSON
PY SKILL/scripts/listingflow.py save-content --task TASK --expect REV --json REVISED_JSON --only bullets.2
PY SKILL/scripts/listingflow.py revise --task TASK --expect REV --json SELECTED_BLOCKS_JSON
PY SKILL/scripts/listingflow.py compare --task TASK --first 1 --second 2
PY SKILL/scripts/listingflow.py check --task TASK --expect REV
PY SKILL/scripts/listingflow.py approve --task TASK --expect REV --json APPROVAL_JSON
```

每次读取命令结果的新 `revision`。`--only` 可重复，例如 `--only qa.0.question --only qa.0.answer`；索引从 0 开始，运营说的“第三条”对应 `bullets.2`。局部修改不得增加/删除块或更换事实。调整结构时使用完整新版本并明确说明。

优先用 `revise` 只提交变化块，避免让模型重写整份 JSON；用户持续要求保留的内容才加 `lock`。任务历史查找用 `tasks --root`，下一步用 `dashboard`。旧任务不自动升级，原规则与检查结果不因 Skill 更新被改写。

审阅要先看检查项，不能批量把所有状态填 PASS。事实核对、语言审阅和人工批准是不同记录；同一模型不同审阅阶段不是真正独立的评审者。修改任何内容都要重做相关核查并为整版生成新报告。

## 导出与恢复

普通完整生成默认执行 draft 导出，并准确标识为运营审阅稿，即使程序检查已通过也不能代签批准。公司规则待确认只影响正式资格，不让运营为获得草稿反复回复“继续”或重新批准公司词库。收到对当前文案的真实明确确认且门禁通过后，才执行 final。用户只要正式版而条件不齐时报告阻断，不伪称交付完成。

```text
PY SKILL/scripts/listingflow.py export --task TASK --expect REV --mode final
PY SKILL/scripts/listingflow.py export --task TASK --expect REV --mode draft
PY SKILL/scripts/listingflow.py history --task TASK
PY SKILL/scripts/listingflow.py status --task TASK --details
```

`--preview` 为双 Excel 各工作表生成抽样 PNG，首次上线、更换导出布局、发现换行问题时使用并实际查看。正常导出会重新读取两份 xlsx，核对批次/哈希并拒绝意外公式。交付前还需检查当前文案是否超长导致单元格显示不全；长详情分为独立自然段，不缩小字号掩盖问题。

新版运营报告先展示“审核结论”，四类明细和处理清单通过内部链接导航。核验首页与明细状态一致、真实待办未丢失、未采用字段没有被错误称为已解决、反馈列可编辑但不会批准。这是报告投影，不改审核结果或规则批准。历史 `export.json` 的布局标记用于保留旧工作簿核验行为。

每个批次在 `exports/<batch>`，包含两份 Excel 及生成依据；对运营只返回两份 Excel。任务采用 SQLite 原子修订追加，保留旧内容、审核、事实和规则。锁冲突等待命令结束后读取最新版，不删除锁或数据库。

原件快照丢失/变化会报错；先恢复原快照或新建任务，不跳过校验。导出中断的 `.pending-*` 不是正式产物；不要交付。进程意外退出后可能有未登记的完整批次，必须核对 `status.exports`，未登记则重新导出，不推断已成功。

升级资源包不影响旧任务。明确请求升级后新建任务，使用 `--bundle APPROVED_BUNDLE --parent-task OLD_ID`，再次核对资料与事实。任务数据不会自动迁移，也不静默删除历史。
