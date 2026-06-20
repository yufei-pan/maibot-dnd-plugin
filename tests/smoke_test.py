import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(PLUGIN_DIR.parent / "maibot-plugin-sdk"))

import plugin as dnd_plugin


def test_create_plugin_and_config_version() -> None:
    inst = dnd_plugin.create_plugin()
    assert inst.plugin_id == "maibot-dnd-plugin"
    cfg = dnd_plugin.DndConfig()
    assert cfg.plugin.config_version == "0.1.0"


if __name__ == "__main__":
    test_create_plugin_and_config_version()
    print("ok")
