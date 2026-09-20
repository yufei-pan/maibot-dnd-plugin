# Changelog

本文件记录 maibot-dnd-plugin（地下城）的版本变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.1.2] - 2026-09-20

### 修复

- GM 回合与规则书拆分的 LLM 调用改为按 Host 任务名走 `task_name`，具体模型走 `model_name`。SDK 2.8.1 会默认附带 `task_name="utils"`，若再把 `planner` 放进 `model`，Host 会当成具体模型名并报「未找到名为 … 的模型」

## [0.1.1] - 2026-08-19

### 修复

- 兼容 MaiBot 1.2.0 的 Item-first replyer Hook 载荷，同时保留旧版 `messages` 载荷支持
- 多账号环境按当前聊天流的适配器账号解析麦麦 person_id，并保留显式配置与 `bot.qq_account` 回退
- 仅在存在进行中的战役时才按聊天流解析麦麦身份，避免对无关聊天发起 `get_all_streams`

## [0.1.0] - 2026-08-01

### 新增

- 首次发布：D&D 会话管理、角色卡/地图渲染、GM 回合与玩法工具
- `/dnd help`：向群聊发送玩家向命令与玩法帮助

### 变更

- 将带注释的配置模板改为 `config.default.toml`，运行期 `config.toml` 不再入库
- 在 `create_plugin` / `on_load` 中从模板补齐或恢复 Runner 生成的空壳配置
