# Task 14 Report — README + smoke test completion + manual E2E checklist

**Status:** DONE

## Summary

### README (`README.md`)

Replaced the Task 10 stub with a full 简体中文 user guide covering:

- 功能概览与架构说明
- 安装（符号链接 + 克隆两种方式）
- 配置表（`plugin` / `permissions` / `session` / `mechanics` / `broadcast`）
- 命令一览（会话管理、报名与回合、筹备）
- LLM 工具表
- 会话数据目录布局
- 测试说明（pytest + smoke）
- 手动 E2E 验收清单（来自 SDD plan Task 14 + Task 10 Hook 项合并）
- v1 后规划（episode summaries、combat strict mode、scene close、地图/查询命令）

### Smoke test (`tests/smoke_test.py`)

Expanded from 1 to 6 offline checks:

| Test | Coverage |
| --- | --- |
| `test_create_plugin_and_config_version` | 插件工厂 + 默认配置版本 |
| `test_normalize_config_empty` | 空配置填充默认值 |
| `test_normalize_config_version_migration` | 旧版 `0.0.1` → `CURRENT_CONFIG_VERSION` 迁移并保留用户字段 |
| `test_normalize_config_merge_current` | 同版本配置 merge |
| `test_parse_gm_response_sample` | GM 解析器样本（`===DND_BEAT_JSON===` + skill_check） |
| `test_readiness_gates` | Gate A（campaign bible）+ Gate B（角色卡） |

Smoke tests are also collected by pytest (6 additional cases).

## Test output

```text
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest -v && PYTHONPATH=.:../maibot-plugin-sdk python tests/smoke_test.py
============================== 53 passed in 0.22s ===============================
ok
```

## Commit

`docs(dnd): add README and complete smoke tests`

## SDD completion

Task 14 is the final planned task. All Tasks 1–14 from `docs/superpowers/plans/2026-06-19-maibot-dnd-plugin.md` are now implemented or documented as post-v1 deferrals in README.
