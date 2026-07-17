"""
豆包（火山方舟）API 客户端。

封装对 Responses API 的调用，对外暴露 get_reply() 公共方法。
"""
import time

import requests

from config import (
    ARK_API_URL,
    ARK_API_KEY,
    ARK_MODEL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_BACKOFF,
    SYSTEM_PROMPT,
)

# 以下异常属于「网络/超时」类，值得重试（代理错误、连接超时、SSL 握手超时等）
_RETRYABLE_EXC = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ProxyError,
    requests.exceptions.ChunkedEncodingError,
)


class DoubaoClient:
    def __init__(self, api_key=ARK_API_KEY, model=ARK_MODEL, timeout=REQUEST_TIMEOUT,
                 max_retries=MAX_RETRIES, backoff=RETRY_BACKOFF, system_prompt=SYSTEM_PROMPT):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.system_prompt = system_prompt

    def get_reply(self, user_text, history=None):
        """调用豆包 Responses API，返回助手回复文本；失败返回 None。

        history: 可选的历史轮次列表，每项为 {"role": "user"/"assistant", "content": "文本"}，
                 按时间顺序拼接在系统提示词之后、当前用户消息之前，实现多轮上下文。
        对网络/超时/5xx 错误自动重试（指数退避）；4xx（如鉴权失败）不重试。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # 系统提示词（人设）放在最前，之后是历史轮次，最后是当前用户消息
        input_messages = []
        if self.system_prompt:
            input_messages.append({
                "role": "system",
                "content": [{"type": "input_text", "text": self.system_prompt}],
            })
        for turn in (history or []):
            role = turn.get("role", "user")
            text = turn.get("content", "")
            if text:
                input_messages.append({
                    "role": role,
                    "content": [{"type": "input_text", "text": text}],
                })
        input_messages.append({
            "role": "user",
            "content": [{"type": "input_text", "text": user_text}],
        })
        payload = {
            "model": self.model,
            "input": input_messages,
        }

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    ARK_API_URL, headers=headers, json=payload, timeout=self.timeout
                )
                # 4xx 客户端错误（含鉴权失败）不重试，直接抛出交给外层处理
                if resp.status_code < 500:
                    resp.raise_for_status()
                    return self._extract_text(resp.json())
                # 5xx 服务端错误：视为可重试
                last_err = f"HTTP {resp.status_code}"
            except _RETRYABLE_EXC as e:
                last_err = str(e)
            except requests.exceptions.RequestException as e:
                # 非可重试的 requests 异常（如 4xx raise_for_status）
                print(f"[doubao] 调用 API 失败（不重试）：{e}")
                return None

            # 需要重试
            if attempt < self.max_retries:
                wait = self.backoff * attempt
                print(f"[doubao] 第 {attempt} 次调用失败：{last_err}，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"[doubao] 调用 API 失败，已重试 {self.max_retries} 次：{last_err}")

        return None

    @staticmethod
    def _extract_text(data):
        """从响应 JSON 中取出助手文本消息（跳过 reasoning 等类型）。"""
        for item in data.get("output", []):
            if item.get("type") == "message" and item.get("role") == "assistant":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        return c.get("text", "")
        return None
