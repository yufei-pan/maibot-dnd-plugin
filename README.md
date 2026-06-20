# 地下城 (MaiBot D&D)

在群聊中运行带规则裁判的 D&D 式会话：插件负责骰子、属性、物品与回合批处理，独立 GM 智能体负责叙事，麦麦（MaiBot）作为报名玩家以自然语言参与。

## 功能概览

- **会话生命周期**：创建、筹备、就绪检查、开跑、停止、重启、创建者移交
- **软回合 + 收件箱**：活跃玩家发言后防抖批处理；支持 `/dnd proceed` 手动推进与 `/dnd skip` 跳过等待
- **GM 节拍**：LLM 返回叙述 + 结构化 JSON（掷骰、回合推进、场景补丁等），经 `GMBroker` 执行
- **战役筹备**：圣经（world / plot-outline / characters）、GM 提示、角色卡、词典、规则书导入
- **麦麦集成**：Hook 捕获麦麦回复写入收件箱；请求模型前注入角色名与场景摘要；GM 播报可同步写入 Maisaka 历史

## 安装

本插件需配合 [MaiBot Host](https://github.com/Mai-with-u/MaiBot) 与 `maibot-plugin-sdk` ≥ 2.5.1 使用。

### 方式一：符号链接（本地开发）

在 MaiBot 根目录下，将本仓库链入 `plugins/`：

```bash
cd <MaiBot 根目录>
ln -s ../../maibot-dnd-plugin plugins/maibot-dnd-plugin
```

路径请按实际 checkout 位置调整；目标是 `MaiBot/plugins/maibot-dnd-plugin` 指向本插件目录。

### 方式二：克隆到 plugins

```bash
cd <MaiBot 根目录>/plugins
git clone https://github.com/yufei-pan/maibot-dnd-plugin.git maibot-dnd-plugin
```

重启 MaiBot 后，依赖（`tomli`、`tomli-w`、`httpx`、`pyyaml`）会按 `_manifest.json` 自动安装。在 WebUI 插件管理中确认插件已加载并启用。

## 配置

首次加载会从 `config.default.toml` 生成 `config.toml`。完整项说明见 [config.default.toml](config.default.toml)，均可在 WebUI 中编辑。

| 配置节 | 常用项 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `[plugin]` | `enabled` | `true` | 是否启用插件 |
| | `config_version` | `0.1.0` | 配置版本（迁移用，勿手改） |
| `[permissions]` | `admin_qq_ids` | `[]` | 管理员 QQ 号列表（可管理任意会话） |
| | `open_mode` | `false` | 开放模式：任意人均可管理会话生命周期 |
| `[session]` | `debounce_seconds` | `45` | 活跃玩家发言后的 GM 节拍防抖秒数 |
| | `gm_model` | `planner` | GM 叙事使用的 LLM **任务名** |
| | `gm_context_char_budget` | `120000` | GM 上下文字符预算上限 |
| | `recent_beats_limit` | `10` | 注入 GM 上下文的最近节拍条数 |
| | `rulebook_import_max_bytes` | `5242880` | 规则书 URL 抓取最大字节数（5 MiB） |
| `[mechanics]` | `base_system` | `5e-lite` | 基础规则体系标识 |
| | `ability_scores` | str/dex/con/int/wis/cha | 能力值键名列表 |
| `[broadcast]` | `system_prefix_gm` | `【地下城·GM】` | GM 系统消息前缀 |
| | `system_prefix` | `【地下城】` | 普通系统消息前缀 |
| | `sync_to_maisaka_history` | `true` | 播报是否同步写入 Maisaka 历史 |

> **权限说明**：默认仅会话创建者、管理员（`admin_qq_ids`）及已报名玩家可执行对应操作。`open_mode = true` 时，任意人均可创建/启动/停止会话。

## 命令一览

所有命令以 `/dnd` 为前缀，在绑定的群聊中发送。

### 会话管理

| 命令 | 权限 | 说明 |
| --- | --- | --- |
| `/dnd new [标题]` | 创建者/管理员 | 创建新会话（默认标题「未命名战役」） |
| `/dnd list` | 任意 | 列出本聊天所有会话 |
| `/dnd status` | 任意 | 查看当前活跃会话状态 |
| `/dnd start` | 创建者/管理员 | 就绪检查通过后开跑 |
| `/dnd stop` | 创建者/管理员 | 停止进行中的会话 |
| `/dnd restart [session_id]` | 创建者/管理员 | 重置为 setup 状态 |
| `/dnd handoff <玩家ID>` | 创建者 | 将会话创建者移交给其他玩家 |

### 报名与回合

| 命令 | 权限 | 说明 |
| --- | --- | --- |
| `/dnd join` | 任意（setup/running） | 报名加入当前会话 |
| `/dnd leave` | 已报名玩家 | 退出报名 |
| `/dnd turn` | 已报名玩家 | 查看当前行动者、先攻顺序、待处理消息 |
| `/dnd proceed` | 已报名玩家 | 手动冲刷收件箱并推进 GM 节拍 |
| `/dnd skip` | 已报名玩家 | 跳过等待活跃玩家发言 |
| `/dnd ooc <内容>` | 已报名玩家 | 发送场外信息到收件箱 |

### 筹备（setup 阶段）

| 命令 | 权限 | 说明 |
| --- | --- | --- |
| `/dnd bible [append\|replace] <topic> <内容>` | 创建者/管理员 | 写入/追加 `bible/<topic>.md` |
| `/dnd gm-prompt [append\|replace] <内容>` | 创建者/管理员 | 写入/追加 `gm-prompt.md` |
| `/dnd review` | 创建者/管理员 | 检查 Gate A（圣经 + GM 提示）与 Gate B（角色卡） |
| `/dnd import-rules <url>` | 创建者/管理员 | 从 URL 抓取规则书并经 LLM 拆分写入 `bible/rules/` |
| `/dnd dict [词条]` | 任意 | 查询战役词典；留空列出全部 |
| `/dnd dict set <词条> <解释>` | 创建者/管理员 | 写入 `bible/dictionary.json` 词条 |

筹备也可通过 LLM 工具完成（见下表），便于麦麦协助填设定。

## LLM 工具（麦麦 / Planner）

| 工具 | 说明 |
| --- | --- |
| `dnd_setup_bible` | 写入/追加战役圣经 |
| `dnd_setup_gm_prompt` | 写入/追加 GM 补充提示 |
| `dnd_setup_character` | 写入/合并玩家角色卡 `players/<id>.yaml` |
| `dnd_import_rulebook` | URL → LLM 拆分 → 规则书文件 |
| `dnd_dict_set` / `dnd_dict_query` | 词典写入与查询 |
| `dnd_review_ready` | 就绪检查（同 `/dnd review`） |
| `dnd_spawn_item` | 生成物品到玩家背包或场景 |

## 会话数据布局

每个会话在 `data/sessions/<session_id>/` 下维护：

```
session.toml          # 元数据（标题、状态、创建者等）
gm-prompt.md          # GM 补充提示
bible/
  world.md            # Gate A 必填
  plot-outline.md
  characters.md
  dictionary.json
  rules/              # 规则书导入
  maps/               # 地图源（渲染功能见 v1 后规划）
players/
  <player_id>.yaml    # Gate B 角色卡
state/
  scene-state.md      # 当前场景摘要
  scene-items.yaml
journal/
  beats.jsonl         # GM 节拍历史
summaries/            # 场景/章节摘要（自动化见 v1 后规划）
```

## 测试

### 单元测试（pytest）

在插件目录下运行（需 sibling 的 `maibot-plugin-sdk`）：

```bash
cd maibot-dnd-plugin
PYTHONPATH=.:../maibot-plugin-sdk pytest -v
```

### 离线冒烟测试

不依赖 Host，验证插件导入、配置迁移、GM 解析器样本与就绪门控：

```bash
cd maibot-dnd-plugin
PYTHONPATH=.:../maibot-plugin-sdk python tests/smoke_test.py
```

预期输出：`ok`。

## 手动 E2E 验收清单

在真实 MaiBot Host + 群聊网关中逐项勾选：

### 安装与加载

- [ ] 执行 `ln -s ../../maibot-dnd-plugin MaiBot/plugins/maibot-dnd-plugin`（或等价克隆）
- [ ] 重启 Host，WebUI 中插件状态为已加载、已启用
- [ ] `config.toml` 已生成，可按需配置 `admin_qq_ids` 与 `gm_model`

### 筹备 → 开跑

- [ ] `/dnd new 测试战役` 创建会话
- [ ] 通过 `/dnd bible`、`/dnd gm-prompt` 或 LLM 工具填写 bible（world / plot-outline / characters）与 GM 提示
- [ ] `/dnd join` 报名；完善 `players/<你的ID>.yaml` 角色卡（六项能力值、至少一项技能、HP > 0）
- [ ] `/dnd review` 显示就绪检查通过
- [ ] `/dnd start` 成功进入 running 状态

### 回合与 GM 节拍

- [ ] 当前行动者发送普通文本（非 `/dnd` 命令），`/dnd turn` 显示待处理消息增加
- [ ] 活跃玩家发言后防抖计时启动（或手动 `/dnd proceed`）
- [ ] 群聊出现 `【地下城·GM】` 前缀的 GM 系统消息
- [ ] `sync_to_maisaka_history = true` 时，GM 播报出现在 Maisaka 历史上下文中

### 麦麦（MaiBot）集成

- [ ] 麦麦已报名当前会话（角色卡 `players/<bot_person_id>.yaml` 存在）
- [ ] 麦麦以自然语言回复后，回复进入回合收件箱
- [ ] 麦麦请求模型前，`before_model_request` 注入内容包含角色名与 `state/scene-state.md` 场景摘要

## v1 后规划（尚未实现）

以下能力在设计中已预留，当前版本**未**提供完整实现，请勿在验收中期待：

- 章节/场景摘要自动化（episode summaries）
- 战斗严格模式（combat strict mode）
- `/dnd scene close` 的 LLM 场景总结生成
- 角色卡 / 地图 PNG 渲染（`/dnd card`、`/dnd map` 等查询命令）
- 游玩期 LLM 工具：`dnd_roll`、`dnd_query_log`、`dnd_query_bible`

## 许可证

MIT — 见仓库 [LICENSE](LICENSE)（若存在）或 `_manifest.json` 中的声明。
