# Changelog

本文件记录 maibot-dnd-plugin（地下城）的版本变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-08-01

### 新增

- 首次发布：D&D 会话管理、角色卡/地图渲染、GM 回合与玩法工具
- `/dnd help`：向群聊发送玩家向命令与玩法帮助

### 变更

- 将带注释的配置模板改为 `config.default.toml`，运行期 `config.toml` 不再入库
- 在 `create_plugin` / `on_load` 中从模板补齐或恢复 Runner 生成的空壳配置
