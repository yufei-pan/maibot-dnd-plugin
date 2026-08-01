"""玩家向帮助文案。"""

from __future__ import annotations

HELP_MESSAGE_TEMPLATE = """命令帮助

▌想参与冒险（玩家）
/dnd join          报名当前战役（须先有人 /dnd new 创建会话）
/dnd leave         退出报名
/dnd turn          看谁行动、先攻顺序、待处理消息数
/dnd proceed       手动推进 GM 节拍（活跃玩家发言后也会自动防抖推进）
/dnd ooc <内容>    发送场外话到 GM 收件箱（不影响角色发言时可注明 OOC）
/dnd card          查看自己的角色卡（可加 @某人 看他人）
/dnd sheet         查看角色卡数值文本
/dnd roll <公式>   场外掷骰，例：/dnd roll 1d20+5
/dnd dict <词条>   查战役词典
/dnd log           看最近掷骰记录
/dnd status        看当前会话状态
/dnd help          显示本帮助

▌怎么玩
1. 主持人 /dnd new 创建战役并完成筹备后 /dnd start 开跑。
2. 你用 /dnd join 报名，并补全角色卡（名称、六项属性、HP、至少一项技能）。
3. 轮到你时，在群里以角色身份正常发言即可；GM 会以【地下城·GM】播报结果。
4. 未到回合也可说话，GM 决定是否采纳；被驳回时会单独提示。
5. {bot_name} 若也报名，与普通玩家一样游玩。

▌主持人 / 管理员（筹备与控场）
/dnd new [标题]    创建战役
/dnd review        检查圣经、GM 提示、角色卡是否齐全
/dnd start         就绪后开跑
/dnd stop          停止会话
/dnd list          列出本群所有战役
/dnd restart [id]  已停止的战役回到筹备
/dnd handoff <id>  移交创建者
/dnd skip          跳过卡住等待（创建者/管理员）
/dnd bible …       写入世界观等设定（详见 README）

▌提示
· 未报名玩家的聊天不会被当作地下城动作。
· 筹备阶段可请 {bot_name} 协助整理设定（可用工具写入 bible / 角色卡）。
· 完整说明见插件 README。"""


def build_help_message(bot_name: str) -> str:
    """返回发往群聊的帮助正文。"""
    name = str(bot_name or "").strip() or "麦麦"
    return HELP_MESSAGE_TEMPLATE.format(bot_name=name)
