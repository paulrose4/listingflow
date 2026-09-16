# 发布与验收

本文给开发和发布负责人，不要求运营执行命令。

## 发布边界

- 本包包含公司规则、词库及需求原文摘录，暂按内部审阅材料处理。业务批准与分发批准是两回事；未经权利人许可，不得将这些内容公开。
- 当前规则保留 `pending_business_approval`，打包和安装不会自动批准规则。
- 不包含产品原件、历史任务数据库、导出 Excel、浏览器会话、账号凭据、Python 运行时或第三方库二进制文件。
- 语义理解、看图、文案生成和在线调研由 Codex 完成，不能把 Python 脚本宣传成独立模型服务。
- 安装插件不会自动安装系统依赖、登录 eBay 或授予店铺权限。

## 环境要求

优先使用 Codex 桌面环境通过 `load_workspace_dependencies` 提供的运行时。不要复制开发者的缓存路径到同事电脑。

| 能力 | 要求 |
| --- | --- |
| 必要 Python 环境 | Python 3.12+；依赖版本见插件内 `scripts/requirements.txt` |
| Excel、Word、PDF、图片处理 | openpyxl、python-docx、pypdf、Pillow、pypdfium2 |
| 可选 Excel 图片预览 | Node 22+、`@oai/artifact-tool`；不影响 Python 双 Excel 写入和回读 |
| 实时关键词 | 可用的浏览器或连接器；PLA 需要本人有效的店铺访问权限 |
| 文件访问 | 获准的资料目录及独立、可写的任务输出目录 |

若桌面运行时未提供必要依赖，由 IT 在获准的独立环境安装 `requirements.txt` 并完成试跑。不要全局安装、偷偷联网下载或要求运营排查开发环境。

## 本地验证

市场来源应为仓库根目录，不是 `marketplace.json` 所在目录。

```text
codex plugin marketplace add <仓库根目录>
codex plugin add listingflow@listingflow-marketplace
```

开发机已有同名个人 Skill 时，优先使用独立测试配置或另一台测试电脑，确认实际加载的是插件内 Skill，避免误测旧版本。不要擅自删除个人 Skill。

插件市场清单采用 `.agents/plugins/marketplace.json`；插件清单为 `plugins/listingflow/.codex-plugin/plugin.json`。

## 推送前检查

1. 确认目标仓库为 `paulrose4/listingflow`，核实可见性、分发权限及已有远程提交。
2. 检查所有待提交文件，不上传本地验证记录、测试产物、密钥、原始产品资料或父项目。
3. 运行插件结构校验、Skill 校验、原回归测试和合成双 Excel 导出测试。
4. 在隔离配置中添加市场并安装，核对缓存内 Skill 与发布目录内容一致。
5. 由用户确认文件清单后才推送。不得强推覆盖远程分支；发现远程新提交应先合并审阅。
6. 在另一台电脑通过 GitHub 地址试装。使用真实、获准的资料完整试跑，核对两份 Excel 和关键词受限提示。
7. 上述试装通过后，再向全部运营分发地址。

自动回归、合成样例、当前电脑的隔离安装和另一台电脑的真实业务试用是四种不同验证，不能相互替代。未做的项目应明确标为待验证。

## 后续更新

保留市场标识 `listingflow-marketplace` 与插件标识 `listingflow`。记录变更，发布前重新测试；不要声称修改仓库后所有同事会自动获得新版。

按当前 Codex 支持的市场刷新与插件更新流程分发，由发布负责人先验证具体版本，再让运营新建任务使用。旧任务仍保留原有事实、规则快照和导出文件，不静默迁移。
