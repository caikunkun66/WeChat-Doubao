"""
机器人编排层。

把「微信监听」和「豆包回复」组合起来：收到好友消息时调用豆包获取回复并自动发回。
"""
import re

from wechat import WeChatListener, SRC_MAP
from doubao import DoubaoClient
from config import AUTO_REPLY, BOT_NAME, MAX_HISTORY_TURNS


class WeChatBot:
    def __init__(self, auto_reply=AUTO_REPLY):
        self.listener = WeChatListener()
        self.doubao = DoubaoClient()
        self.auto_reply = auto_reply
        # 按会话（群名/单聊名）维护一份共享记忆：群内所有群友共用同一记忆线，
        # 这样群里 @ 豆包的对话上下文对所有人连续，更像群里的"共同朋友"。
        self.history = {}

    def _should_reply(self, chat_name, msg, sender):
        """判断是否应调用豆包回复：
        - 单聊：直接回复（chat_name == sender 视为单聊）
        - 群聊：消息内容需包含 '@<机器人名>' 才回复
        """
        is_group = sender != chat_name
        if is_group:
            return f"@{BOT_NAME}" in msg.content
        return True

    def _strip_at(self, text):
        """去掉群消息里的 '@豆包' 前缀（含后面可能的空格/特殊分隔符）。"""
        return re.sub(rf"@{re.escape(BOT_NAME)}\s*", "", text, count=1).strip()

    def _remember(self, chat_name, sender, user_text, reply=None):
        """记录对话到该会话的共享记忆，并裁剪到上限。

        - 用户轮次统一标注发送者，存为「发送者：内容」，便于豆包分清群里谁说的
        - reply 有值：记为完整一轮（用户 + 豆包）
        - reply 为 None：仅记用户轮次（用于群聊中未 @ 的闲聊，先攒上下文）
        """
        hist = self.history.setdefault(chat_name, [])
        hist.append({"role": "user", "content": f"{sender}：{user_text}"})
        if reply:
            hist.append({"role": "assistant", "content": reply})
        max_items = MAX_HISTORY_TURNS * 2  # 每轮 = 用户 + 豆包 各 1 条
        if len(hist) > max_items:
            self.history[chat_name] = hist[-max_items:]

    def _on_message(self, chat_name, msg):
        sender = getattr(msg, "sender", None) or chat_name
        src = SRC_MAP.get(msg.type, msg.type)
        print(f"来自: {sender}（会话: {chat_name}）")
        print(f"内容: {msg.content}")
        print(f"类型: {msg.type}（来源: {src}）")

        # 仅对好友消息自动回复；自己/系统/撤回消息不回复，避免自我循环
        if self.auto_reply and msg.type == "friend":
            is_group = sender != chat_name

            if not self._should_reply(chat_name, msg, sender):
                # 群聊中未 @ 豆包的消息：不回复，但写入共享记忆攒上下文，
                # 这样后续有人 @ 豆包 时，回复能带上这段群聊背景。
                if is_group:
                    self._remember(chat_name, sender, msg.content)
                print("-" * 40)
                return

            prompt = self._strip_at(msg.content) if is_group else msg.content
            # 记忆按会话共享：群内所有群友共用同一份上下文（含未 @ 的闲聊）
            reply = self.doubao.get_reply(prompt, self.history.get(chat_name))
            if reply:
                try:
                    self.listener.send_message(reply, chat_name)
                    print(f"已自动回复: {reply}")
                    # 仅发送成功后才记入记忆，保证记忆与实际发出一致
                    self._remember(chat_name, sender, prompt, reply)
                except Exception as e:
                    print(f"发送回复失败：{e}")

        print("-" * 40)

    def run(self):
        self.listener.on_message = self._on_message
        self.listener.run()
