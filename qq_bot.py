"""
QQ 豆包机器人（OneBot 协议，无窗口后台运行）。

通过 WebSocket 连接 napcat（OneBot v11 正向 WS），监听 QQ 消息并调用豆包 API 自动回复。
与微信版 bot.py 共享同一套豆包客户端与「整群共享记忆」逻辑，区别仅在消息收发走 OneBot
协议而非 wxauto——因此无需任何界面，可用 pythonw / 服务方式在后台静默运行。

依赖：websockets
运行：pythonw qq_bot.py     （pythonw 不弹控制台窗口，适合后台 / 服务方式）
"""
import asyncio
import base64
import json
import logging
import os
import time

import requests
import websockets

from doubao import DoubaoClient
from config import (
    AUTO_REPLY,
    BOT_NAME,
    MAX_HISTORY_TURNS,
    ONEBOT_WS_URL,
    ONEBOT_TOKEN,
    USER_PROMPTS,
    IMAGE_ENABLED,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_MSG,
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
        self._pending = {}      # echo -> Future，用于关联 OneBot 主动作请求的响应
        self._echo_seq = 0      # 自增序号，保证 echo 唯一
        self._send_lock = None  # 发送锁，保证并发任务下 ws.send 不交错（在 run 里懒初始化）

    # ---------- 会话与记忆（同 bot.py 的整群共享记忆思路）----------
    @staticmethod
    def _chat_key(event):
        if event.get("message_type") == "group":
            return f"group:{event.get('group_id')}"
        return f"private:{event.get('user_id')}"

    def _remember(self, chat_key, sender, user_text, reply=None, images=None):
        hist = self.history.setdefault(chat_key, [])
        # 用户轮次可能带图片（多模态），一并存入历史以保留上下文
        content = f"{sender}：{user_text}" if user_text else (f"{sender}：（发来图片）" if images else "")
        hist.append({"role": "user", "content": content, "images": list(images or [])})
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

    @staticmethod
    def _extract_images(event):
        """从 OneBot message 字段提取图片段（返回每个 image 段的 data 字典）。"""
        message = event.get("message", [])
        datas = []
        if isinstance(message, list):
            for seg in message:
                if seg.get("type") == "image":
                    datas.append(seg.get("data", {}))
        return datas

    @staticmethod
    def _guess_ctype(path):
        ext = os.path.splitext(path)[1].lower()
        return {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        }.get(ext, "image/jpeg")

    @staticmethod
    def _to_data_url(raw, ctype):
        """把图片二进制封装成 data URL；超限或为空返回 None。"""
        if raw is None:
            return None
        if len(raw) > MAX_IMAGE_BYTES:
            log.warning("图片超过大小上限，跳过（%d 字节）", len(raw))
            return None
        return f"data:{ctype or 'image/jpeg'};base64,{base64.b64encode(raw).decode()}"

    @staticmethod
    def _download(url):
        """同步下载图片（在线程池执行），返回 (raw, ctype)。"""
        resp = requests.get(url, timeout=15, stream=True)
        resp.raise_for_status()
        raw, ctype = b"", resp.headers.get("Content-Type", "")
        for chunk in resp.iter_content(8192):
            raw += chunk
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("图片过大")
        return raw, ctype

    async def _call_action(self, ws, action, params, timeout=10):
        """发送一个 OneBot 主动作请求并等待其响应（按 echo 关联）。"""
        if self._send_lock is None:
            self._send_lock = asyncio.Lock()
        self._echo_seq += 1
        echo = f"qqbot{int(time.time() * 1000)}{self._echo_seq}"
        fut = asyncio.get_event_loop().create_future()
        self._pending[echo] = fut
        try:
            async with self._send_lock:
                await ws.send(json.dumps({
                    "action": action, "params": params, "echo": echo,
                }))
            return await asyncio.wait_for(fut, timeout)
        except Exception as e:
            self._pending.pop(echo, None)
            raise e
        finally:
            self._pending.pop(echo, None)

    async def _get_image_local_path(self, ws, file):
        """通过 OneBot get_image API 让 napcat 把图片哈希解析为本地绝对路径。

        napcat 自己不缓存图片副本，原图在 QQ 的 nt_data\\Pic 缓存里；get_image
        由 napcat 负责定位并返回本地路径，无需联网，是最稳的群聊图片读取方式。
        """
        try:
            resp = await self._call_action(ws, "get_image", {"file": file}, timeout=8)
            if resp and resp.get("status") == "ok":
                return (resp.get("data") or {}).get("file")
        except Exception as e:
            log.warning("get_image API 失败：%s -> %s", file, e)
        return None

    async def _resolve_image_data(self, ws, data):
        """把图片段解析为 base64 data URL，按可靠性从高到低尝试：

        1) data.file 为 base64:// 内联（无需联网，最可靠，私聊常见）
        2) data.file 为本地绝对路径（直接读文件）
        3) 通过 OneBot get_image API 让 napcat 解析本地路径（群聊最稳，无需联网）
        4) data.url 为外网直链（需联网，依赖 HTTPS_PROXY 代理环境变量）
        """
        file = data.get("file", "") or ""
        url = data.get("url", "") or ""
        try:
            # 1) base64 内联，最优先，不需要任何网络
            if file.startswith("base64://"):
                return self._to_data_url(
                    base64.b64decode(file[len("base64://"):]),
                    self._guess_ctype(url) or "image/jpeg")
            # 2) 本地绝对路径
            if file and (file.startswith("/") or (len(file) > 2 and file[1] == ":")) and os.path.exists(file):
                with open(file, "rb") as f:
                    return self._to_data_url(f.read(), self._guess_ctype(file))
            # 3) get_image API：群聊图片 file 常为哈希名，由 napcat 定位本地原图
            if file:
                local = await self._get_image_local_path(ws, file)
                if local and os.path.exists(local):
                    with open(local, "rb") as f:
                        return self._to_data_url(f.read(), self._guess_ctype(local))
                else:
                    log.info("[图片] get_image 未返回可用本地路径（file=%s），尝试外网直链",
                             (file[:32] + "…") if len(file) > 32 else file)
            # 4) 外网直链（requests 默认尊重 HTTPS_PROXY / HTTP_PROXY 环境变量）
            if url.startswith("http://") or url.startswith("https://"):
                raw, ctype = await asyncio.get_event_loop().run_in_executor(
                    None, self._download, url)
                return self._to_data_url(raw, ctype or "image/jpeg")
        except Exception as e:
            log.warning("图片读取失败：%s -> %s", url or file, e)
        return None

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
            # 真实 @ 回复：在群聊里用 CQ 码 @ 回发送者，而不是仅文本「@xxx」
            text = f"[CQ:at,qq={event.get('user_id')}]\n{text}"
        else:
            params["user_id"] = event.get("user_id")
        params["message"] = text
        if self._send_lock is None:
            self._send_lock = asyncio.Lock()
        async with self._send_lock:
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
        user_id = event.get("user_id")
        sender = event.get("sender", {}).get("nickname") or str(user_id)
        is_group = event.get("message_type") == "group"
        text = self._extract_text(event.get("message", ""))

        # 解析图片：napcat 给的是本地地址，需下载内联成 base64 data URL 才能被方舟读取
        images = []
        if IMAGE_ENABLED:
            for d in self._extract_images(event)[:MAX_IMAGES_PER_MSG]:
                # 诊断：打印图片段字段（base64 只取前缀，避免刷屏），便于确认 napcat 在
                # 群聊/私聊分别给了哪些字段（base64 内联 / 本地路径 / 外网直链）。
                fv = d.get("file", "") or ""
                log.info("[图片诊断] file=%s base64=%s url=%s file_id=%s",
                         (fv[:32] + ("…" if len(fv) > 32 else "")) or "(空)",
                         fv.startswith("base64://"),
                         (d.get("url", "") or "")[:64] or "(空)",
                         bool(d.get("file_id")))
                data_url = await self._resolve_image_data(ws, d)
                if data_url:
                    images.append(data_url)

        log.info("来自: %s（QQ:%s，会话: %s）内容: %s%s",
                 sender, user_id, chat_key, text,
                 f" [图片x{len(images)}]" if images else "")

        if not self.auto_reply:
            return

        at_me = self._is_at_me(event) if is_group else True

        if is_group and not at_me:
            # 群聊未 @ 机器人：写入共享记忆攒上下文（含图片），不回复（同 bot.py）
            if text or images:
                self._remember(chat_key, sender, text, images=images)
            return

        if not text and not images:
            return

        # 豆包调用是阻塞的网络请求，丢到线程池执行以免卡住事件循环
        # 若存在该 QQ 的专属提示词（USER_PROMPTS），追加到系统提示词之后
        extra = USER_PROMPTS.get(str(user_id)) if user_id is not None else None
        # 明确告诉 AI 当前对话对象是谁（昵称 + QQ），避免它不知道 / 瞎猜身份，
        # 也便于 USER_PROMPTS 里「昵称为 XXX 的用户」这类规则精准命中。
        whoami = f"【当前对话对象】昵称「{sender}」，QQ 号 {user_id}。"
        extra = (whoami + "\n" + extra) if extra else whoami
        reply = await asyncio.get_event_loop().run_in_executor(
            None, self.doubao.get_reply, text, self.history.get(chat_key), extra, images
        )
        if reply:
            try:
                await self._send(ws, event, reply)
                log.info("已自动回复: %s", reply)
                self._remember(chat_key, sender, text, reply, images=images)
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
                # OneBot 主动作（如 get_image）的响应带 echo，需关联回等待中的 Future，
                # 否则图片解析会死锁。命中的响应不再当作事件分发。
                echo = event.get("echo")
                if echo is not None and echo in self._pending:
                    fut = self._pending.pop(echo)
                    if not fut.done():
                        fut.set_result(event)
                    continue
                # 事件改为并发任务处理：这样在处理某条消息、等待 get_image 响应时，
                # 读循环仍能继续收消息（含动作响应），避免死锁。发送统一走 _send_lock 串行化。
                task = asyncio.create_task(self._on_event(ws, event))
                task.add_done_callback(self._log_task_exc)

    @staticmethod
    def _log_task_exc(task):
        if not task.cancelled():
            exc = task.exception()
            if exc:
                log.error("事件处理异常：%s", exc)

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
