# maibot-dnd-plugin

地下城跑团插件（开发中）。

## 手动 Hook 测试清单（Task 10）

- [ ] 启动 MaiBot Host，并确保 `maibot-dnd-plugin` 已加载。
- [ ] 在群聊创建并启动会话：`/dnd new 测试局` → 完成就绪项 → `/dnd start`。
- [ ] 确认 MaiBot（bot person）已报名当前会话（可通过角色卡与状态信息核验）。
- [ ] 让一名报名人类玩家发送普通文本，确认消息进入回合收件箱（`/dnd turn` 的待处理消息增加）。
- [ ] 当当前行动者发言后，确认防抖计时启动并可触发后续节拍。
- [ ] 触发 MaiBot 一次 replyer 回复，确认 `after_response` 会把回复写入收件箱。
- [ ] 在 MaiBot 回复前检查 `before_model_request` 注入内容，确认包含角色名与 `state/scene-state.md` 场景摘要。
