"""地下城插件配置模型与迁移。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maibot_sdk import Field, PluginConfigBase
from maibot_sdk.config import (
    extract_plugin_config_version,
    merge_plugin_config_data,
    rebuild_plugin_config_data,
    validate_plugin_config,
)

CURRENT_CONFIG_VERSION = "0.1.0"

DEFAULT_ABILITY_SCORES = ("str", "dex", "con", "int", "wis", "cha")


def _config_version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(version or "0").split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _config_version_less_than(left: str, right: str) -> bool:
    return _config_version_tuple(left) < _config_version_tuple(right)


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "基础设置"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default=CURRENT_CONFIG_VERSION, description="配置版本号")


class PermissionsSectionConfig(PluginConfigBase):
    """权限与开放模式。"""

    __ui_label__ = "权限"
    __ui_order__ = 1

    admin_qq_ids: list[str] = Field(default_factory=list, description="管理员 QQ 号列表")
    open_mode: bool = Field(default=False, description="开放模式：任意人均可管理会话生命周期")


class SessionSectionConfig(PluginConfigBase):
    """会话与 GM 上下文。"""

    __ui_label__ = "会话"
    __ui_order__ = 2

    debounce_seconds: int = Field(default=45, description="活跃玩家发言后的 GM 节拍防抖秒数")
    gm_model: str = Field(default="planner", description="GM 叙事使用的 LLM 任务名")
    gm_context_char_budget: int = Field(default=120000, description="GM 上下文字符预算上限")
    recent_beats_limit: int = Field(default=10, description="注入 GM 上下文的最近节拍条数")
    rulebook_import_max_bytes: int = Field(
        default=5 * 1024 * 1024,
        description="规则书 URL 抓取最大字节数",
    )
    maibot_person_id: str = Field(
        default="",
        description="麦麦 person_id（留空则在 on_load 时从 bot.qq_account 解析）",
    )


class MechanicsSectionConfig(PluginConfigBase):
    """规则与属性体系。"""

    __ui_label__ = "规则"
    __ui_order__ = 3

    base_system: str = Field(default="5e-lite", description="基础规则体系标识")
    ability_scores: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ABILITY_SCORES),
        description="能力值键名列表",
    )


class BroadcastSectionConfig(PluginConfigBase):
    """播报与前缀。"""

    __ui_label__ = "播报"
    __ui_order__ = 4

    system_prefix_gm: str = Field(default="【地下城·GM】", description="GM 系统消息前缀")
    system_prefix: str = Field(default="【地下城】", description="普通系统消息前缀")
    sync_to_maisaka_history: bool = Field(default=True, description="播报是否同步写入 Maisaka 历史")


class DndConfig(PluginConfigBase):
    """地下城插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    permissions: PermissionsSectionConfig = Field(default_factory=PermissionsSectionConfig)
    session: SessionSectionConfig = Field(default_factory=SessionSectionConfig)
    mechanics: MechanicsSectionConfig = Field(default_factory=MechanicsSectionConfig)
    broadcast: BroadcastSectionConfig = Field(default_factory=BroadcastSectionConfig)


def _migrate_plugin_config_data(config: dict[str, Any], from_version: str) -> tuple[dict[str, Any], list[str]]:
    """按版本迁移插件配置。"""
    notes: list[str] = []
    if not _config_version_less_than(from_version, CURRENT_CONFIG_VERSION):
        return config, notes

    plugin_section = config.get("plugin")
    if isinstance(plugin_section, dict):
        plugin_section["config_version"] = CURRENT_CONFIG_VERSION
    return config, notes


def _normalize_dnd_config(
    raw_config: Mapping[str, Any] | None,
    default_config: Mapping[str, Any],
) -> tuple[dict[str, Any], bool, list[str]]:
    """合并、迁移并校验地下城插件配置。"""
    raw: dict[str, Any] = dict(raw_config) if isinstance(raw_config, Mapping) else {}
    if not raw:
        merged = rebuild_plugin_config_data(default_config, {})
        validate_plugin_config(DndConfig, merged)
        return merged, True, ["空配置，已填充全部默认值"]

    from_version = extract_plugin_config_version(raw)
    latest_version = extract_plugin_config_version(default_config)

    if _config_version_less_than(from_version, latest_version):
        working = rebuild_plugin_config_data(default_config, raw)
        working, notes = _migrate_plugin_config_data(working, from_version)
        validate_plugin_config(DndConfig, working)
        return working, True, notes

    working, changed = merge_plugin_config_data(default_config, raw)
    validate_plugin_config(DndConfig, working)
    return working, changed, []
