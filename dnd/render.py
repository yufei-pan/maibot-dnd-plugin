"""角色卡与地图 HTML/PNG 渲染。"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from dnd.mechanics.sheets import CharacterSheet, ability_modifier

CARD_VIEWPORT = {"width": 940, "height": 520}
MAP_VIEWPORT = {"width": 920, "height": 620}
DEVICE_SCALE_FACTOR = 1.0

_ABILITY_LABELS = {
    "str": "力量",
    "dex": "敏捷",
    "con": "体质",
    "int": "智力",
    "wis": "感知",
    "cha": "魅力",
}


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render(template: str, **values: Any) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def _wrap_html(fragment: str) -> str:
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        "</head><body>"
        f"{fragment}"
        "</body></html>"
    )


def _fmt_modifier(score: int) -> str:
    mod = ability_modifier(score)
    sign = "+" if mod >= 0 else ""
    return f"{score} ({sign}{mod})"


def _fmt_bonus(value: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}"


def load_character_sheet(session_root: Path, player_id: str) -> tuple[CharacterSheet, str | None]:
    """读取角色卡与可选 mugshot 相对路径。"""
    sheet_path = Path(session_root) / "players" / f"{player_id}.yaml"
    if not sheet_path.is_file():
        raise FileNotFoundError(f"找不到玩家 {player_id} 的角色卡。")

    raw = sheet_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    mugshot_path: str | None = None
    if isinstance(data, Mapping):
        mugshot_raw = data.get("mugshot")
        if mugshot_raw is not None:
            mugshot_text = str(mugshot_raw).strip()
            if mugshot_text:
                mugshot_path = mugshot_text

    return CharacterSheet.from_yaml(raw), mugshot_path


def _resolve_image_path(session_root: Path | None, relative_path: str) -> Path | None:
    if session_root is None:
        return None
    candidate = (Path(session_root) / relative_path).resolve()
    root = Path(session_root).resolve()
    if root not in candidate.parents and candidate != root:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _image_data_uri(path: Path) -> str:
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".gif":
        mime = "image/gif"
    else:
        mime = "image/png"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _build_mugshot_html(
    *,
    session_root: Path | None,
    mugshot_path: str | None,
    character_name: str,
) -> str:
    image_path = None
    if mugshot_path:
        image_path = _resolve_image_path(session_root, mugshot_path)
    if image_path is not None:
        uri = _image_data_uri(image_path)
        return f'<img class="mugshot" src="{uri}" alt="mugshot" />'

    initial = (character_name or "?")[:1]
    return f'<div class="mugshot mugshot-placeholder">{_html_escape(initial)}</div>'


def _build_abilities_html(sheet: CharacterSheet) -> str:
    if not sheet.abilities:
        return '<div class="empty-note">（暂无能力值）</div>'

    items: list[str] = []
    for key in sorted(sheet.abilities):
        label = _ABILITY_LABELS.get(key, key.upper())
        score = sheet.abilities[key]
        items.append(
            '<div class="stat-item">'
            f'<div class="stat-key">{_html_escape(label)}</div>'
            f'<div class="stat-val">{_html_escape(_fmt_modifier(score))}</div>'
            "</div>"
        )
    return f'<div class="stat-grid">{"".join(items)}</div>'


def _build_skills_html(sheet: CharacterSheet) -> str:
    if not sheet.skills:
        return '<div class="empty-note">（暂无技能）</div>'

    items: list[str] = []
    for key in sorted(sheet.skills):
        bonus = sheet.skills[key]
        items.append(
            '<div class="skill-item">'
            f'<span class="skill-name">{_html_escape(key)}</span>'
            f'<span class="skill-bonus">{_html_escape(_fmt_bonus(bonus))}</span>'
            "</div>"
        )
    return f'<div class="skill-list">{"".join(items)}</div>'


def build_card_html(
    template: str,
    sheet: CharacterSheet,
    *,
    session_root: Path | None = None,
    mugshot_path: str | None = None,
    player_id: str = "",
    card_title: str = "角色卡",
    hp_label: str = "生命值",
) -> str:
    """把角色卡字段渲染进 HTML 模板片段（不含完整文档）。"""
    character_name = sheet.name.strip() or "未命名角色"
    player_block = ""
    if player_id.strip():
        player_block = f'<div class="player-id">玩家 ID：{_html_escape(player_id.strip())}</div>'

    return _render(
        template,
        card_title=_html_escape(card_title),
        mugshot_html=_build_mugshot_html(
            session_root=session_root,
            mugshot_path=mugshot_path,
            character_name=character_name,
        ),
        character_name=_html_escape(character_name),
        player_id_block=player_block,
        hp_label=_html_escape(hp_label),
        hp_value=_html_escape(f"{sheet.hp_current}/{sheet.hp_max}"),
        abilities_html=_build_abilities_html(sheet),
        skills_html=_build_skills_html(sheet),
    )


def build_map_html(
    template: str,
    *,
    title: str,
    body: str,
    legend_items: list[str] | None = None,
) -> str:
    """把地图文本渲染进 HTML 模板片段（不含完整文档）。"""
    legend_html = ""
    if legend_items:
        items = "".join(f'<span class="legend-item">{_html_escape(item)}</span>' for item in legend_items)
        legend_html = f'<div class="legend">{items}</div>'

    return _render(
        template,
        map_title=_html_escape(title.strip() or "战役地图"),
        map_body=_html_escape(body.strip() or "（暂无地图内容）"),
        legend_html=legend_html,
    )


def build_card_markdown(sheet: CharacterSheet, *, player_id: str = "") -> str:
    """渲染失败时的 Markdown 文字版角色卡。"""
    lines = [f"# {sheet.name.strip() or '未命名角色'}"]
    if player_id.strip():
        lines.append(f"玩家 ID：`{player_id.strip()}`")
    lines.append("")
    lines.append(f"**生命值：** {sheet.hp_current}/{sheet.hp_max}")
    lines.append("")

    if sheet.abilities:
        lines.append("**能力值**")
        for key in sorted(sheet.abilities):
            label = _ABILITY_LABELS.get(key, key.upper())
            lines.append(f"- {label}：{_fmt_modifier(sheet.abilities[key])}")
        lines.append("")

    if sheet.skills:
        lines.append("**技能**")
        for key in sorted(sheet.skills):
            lines.append(f"- {key}：{_fmt_bonus(sheet.skills[key])}")

    return "\n".join(lines).strip()


def load_template(plugin_dir: Path, filename: str) -> str:
    path = Path(plugin_dir) / "assets" / filename
    return path.read_text(encoding="utf-8")


async def render_card(ctx: Any, html_fragment: str) -> str | None:
    """调用 Host 渲染角色卡 PNG，返回 base64；失败返回 None。"""
    return await _render_html2png(ctx, html_fragment, selector="#card", viewport=CARD_VIEWPORT)


async def render_map(ctx: Any, html_fragment: str) -> str | None:
    """调用 Host 渲染地图 PNG，返回 base64；失败返回 None。"""
    return await _render_html2png(ctx, html_fragment, selector="#map", viewport=MAP_VIEWPORT)


async def _render_html2png(
    ctx: Any,
    html_fragment: str,
    *,
    selector: str,
    viewport: dict[str, int],
) -> str | None:
    wrapped = _wrap_html(html_fragment)
    try:
        render_result = await ctx.render.html2png(
            wrapped,
            selector=selector,
            viewport=viewport,
            device_scale_factor=DEVICE_SCALE_FACTOR,
            omit_background=True,
        )
    except Exception as exc:
        ctx.logger.warning("地下城渲染失败：%s", exc)
        return None

    if isinstance(render_result, Mapping) and render_result.get("image_base64"):
        return str(render_result["image_base64"])
    return None
