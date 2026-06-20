"""地下城 (MaiBot D&D) 插件。"""

from __future__ import annotations

from typing import Any

from maibot_sdk import MaiBotPlugin

from dnd.config import CURRENT_CONFIG_VERSION, DndConfig, _normalize_dnd_config

__all__ = ["CURRENT_CONFIG_VERSION", "DndConfig", "DndPlugin", "create_plugin", "_normalize_dnd_config"]


class DndPlugin(MaiBotPlugin):
    """地下城插件主体。"""

    plugin_id = "maibot-dnd-plugin"
    config_model = DndConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("地下城插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("地下城插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        merged, _, notes = _normalize_dnd_config(config_data, DndConfig().model_dump(mode="python"))
        if notes:
            self.ctx.logger.info("配置迁移: %s", "; ".join(notes))


def create_plugin() -> DndPlugin:
    return DndPlugin()
