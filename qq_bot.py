"""
QQ 豆包机器人（OneBot 协议，无窗口后台运行）。

通过 WebSocket 连接 napcat（OneBot v11 正向 WS），监听 QQ 消息并调用豆包 API 自动回复。
与微信版 bot.py 共享同一套豆包客户端与「整群共享记忆」逻辑，区别仅在消息收发走 OneBot
协议而非 wxauto——因此无需任何界面，可用 pythonw / 服务方式在后台静默运行。

依赖：websockets
运行：pythonw qq_bot.py     （pythonw 不弹控制台窗口，适合后台 / 服务方式）
"""
import asyncio
import json
import logging
import time

import websockets

from doubao import DoubaoClient
from config import (
    AUTO_REPLY,
    BOT_NAME,
    MAX_HISTORY_TURNS,
    ONEBOT_WS_URL,
    ONEBOT_TOKEN,
)

# 日志：同时写控制台与 qq_bot.log。
# 后台用 pythonw 运行时无控制台，靠日志文件观察运行状态。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("qq_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("qq_bot")


class QQBot:
    def __init__(self, auto_reply=AUTO_REPLY, ws_url=ONEBOT_WS_URL, token=ONEBOT_TOKEN):
        self.doubao = DoubaoClient()
        self.auto_reply = auto_reply
        self.ws_url = ws_url
        self.token = token
        self.history = {}       # 按会话共享记忆，key 见 _chat_key
        self._self_id = None    # 机器人自己的 QQ 号，连接后从事件中获知

    # ---------- 会话与记忆（同 bot.py 的整群共享记忆思路）----------
    @staticmethod
    def _chat_key(event):
        if event.get("message_type") == "group":
            return f"group:{event.get('group_id')}"
        return f"private:{event.get('user_id')}"

    def _remember(self, chat_key, sender, user_text, reply=None):
        hist = self.history.setdefault(chat_key, [])
        hist.append({"role": "user", "content": f"{sender}：{user_text}"})
        if reply:
            hist.append({"role": "assistant", "content": reply})
        max_items = MAX_HISTORY_TURNS * 2  # 每轮 = 用户 + 豆包 各 1 条
        if len(hist) > max_items:
            self.history[chat_key] = hist[-max_items:]

    # ---------- 消息解析 ----------
    @staticmethod
    def _extract_text(message):
        """从 OneBot message 字段提取纯文本（忽略 at / 图片 / 表情等）。"""
        if isinstance(message, str):
            return message.strip()
        parts = []
        for seg in message:
            if seg.get("type") == "text":
                parts.append(seg.get("data", {}).get("text", ""))
        return "".join(parts).strip()

    def _is_at_me(self, event):
        """群聊中是否 @ 了机器人。优先用 at 段里的 qq 与 self_id 比对，
        并兜底匹配 raw_message 中的 '@<机器人名>'。"""
        if event.get("message_type") != "group":
            return False
        message = event.get("message", [])
        if isinstance(message, list):
            for seg in message:
                if seg.get("type") == "at" and str(seg.get("data", {}).get("qq", "")) == str(self._self_id):
                    return True
        return f"@{BOT_NAME}" in event.get("raw_message", "")

    # ---------- 发送 ----------
    async def _send(self, ws, event, text):
        params = {"message_type": event.get("message_type")}
        if event.get("message_type") == "group":
            params["group_id"] = event.get("group_id")
        else:
            params["user_id"] = event.get("user_id")
        params["message"] = text
        await ws.send(json.dumps({
            "action": "send_msg",
            "params": params,
            "echo": int(time.time() * 1000),
        }))

    # ---------- 事件分发 ----------
    async def _on_event(self, ws, event):
        if event.get("post_type") != "message":
            return
        if self._self_id is None and event.get("self_id"):
            self._self_id = event.get("self_id")

        chat_key = self._chat_key(event)
        sender = event.get("sender", {}).get("nickname") or str(event.get("user_id"))
        is_group = event.get("message_type") == "group"
        text = self._extract_text(event.get("message", ""))

        log.info("来自: %s（会话: %s）内容: %s", sender, chat_key, text)

        if not self.auto_reply:
            return

        at_me = self._is_at_me(event) if is_group else True

        if is_group and not at_me:
            # 群聊未 @ 机器人：写入共享记忆攒上下文，不回复（同 bot.py）
            if text:
                self._remember(chat_key, sender, text)
            return

        if not text:
            return

        # 豆包调用是阻塞的网络请求，丢到线程池执行以免卡住事件循环
        reply = await asyncio.get_event_loop().run_in_executor(
            None, self.doubao.get_reply, text, self.history.get(chat_key)
        )
        if reply:
            try:
                await self._send(ws, event, reply)
                log.info("已自动回复: %s", reply)
                self._remember(chat_key, sender, text, reply)
            except Exception as e:
                log.error("发送回复失败：%s", e)

    # ---------- 连接与自动重连 ----------
    async def _connect_once(self):
        # 鉴权：把 token 拼进 URL 查询参数（?access_token=...），跨 websockets 版本都兼容，
        # 避免依赖 extra_headers（老版本 / 新 14.x 均可能不识别该参数，会报 create_connection 错误）。
        url = self.ws_url
        if self.token:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}access_token={self.token}"
        async with websockets.connect(url) as ws:
            log.info("已连接 OneBot：%s", url)
            async for raw in ws:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if event.get("post_type") == "meta_event":
                    continue
                await self._on_event(ws, event)

    async def run(self):
        """持续运行；连接断开后等待 5 秒自动重连，适合无人值守的后台场景。"""
        while True:
            try:
                await self._connect_once()
            except Exception as e:
                log.error("连接断开：%s，5 秒后重连...", e)
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(QQBot().run())
