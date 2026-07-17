"""
微信消息监听模块。

基于 wxauto（微信 3.9）封装：轮询所有会话新消息，做类型过滤与去重，
通过 on_message 回调把消息交给上层处理。
"""
import re
import time

from wxauto import WeChat

# 消息来源类型的中文映射
SRC_MAP = {"friend": "好友", "self": "自己", "sys": "系统",
           "recall": "撤回", "time": "时间"}


class WeChatListener:
    def __init__(self, poll_interval=1, ignore_types=None):
        self.wx = WeChat()
        self.poll_interval = poll_interval
        self.ignore_types = set(ignore_types) if ignore_types else {"sys", "time"}
        self.on_message = None  # 回调：on_message(chat_name, msg)
        self._recent = {}       # 去重缓存：(chat_name, content) -> 时间戳

    def send_message(self, content, who):
        """向指定会话发送文本消息。

        注意：直接调用 wx.SendMsg(content, who) 在群聊场景下，会用
        EditControl(Name=who) 查找输入框而超时（群聊输入框 Name 并非群名）。
        正确做法是先用 ChatWith 切换到该会话，再不带 who 发送到当前聊天窗口。

        群名里的括号（如 "xxx (5)"）会被 ChatWith 内部的正则当成捕获组导致搜不到，
        因此先尝试原名，失败再尝试去掉尾部 " (数字)" 的名字（微信搜索结果会高亮
        匹配部分，正则可命中完整群名）。
        """
        candidates = [who]
        m = re.search(r"\s*\(\d+\)$", who)
        if m:
            candidates.append(who[: m.start()])

        chat = None
        for name in candidates:
            try:
                chat = self.wx.ChatWith(name)
            except Exception as e:
                print(f"[wechat] ChatWith({name!r}) 出错：{e}")
                chat = False
            if chat:
                break
            time.sleep(0.3)  # 失败后稍等再试下一个候选名

        if not chat:
            raise RuntimeError(f"无法打开会话：{who}")
        time.sleep(0.5)  # 等待会话窗口加载完成
        self.wx.SendMsg(content)

    def _should_ignore(self, msg):
        return getattr(msg, "type", None) in self.ignore_types

    def _is_duplicate(self, chat_name, msg):
        # 同一会话、内容相同且在 3 秒内的消息视为重复
        # （wxauto 每次读取给消息的 id 都会变，单靠 id 去重会失效）
        key = (chat_name, msg.content)
        now = time.time()
        if key in self._recent and now - self._recent[key] < 3:
            return True
        self._recent[key] = now
        return False

    def _dispatch(self, chat_name, msg):
        if self._should_ignore(msg) or self._is_duplicate(chat_name, msg):
            return
        if self.on_message:
            self.on_message(chat_name, msg)

    def run(self):
        print("微信已初始化，开始监听消息（Ctrl+C 退出）...\n")
        try:
            while True:
                try:
                    new_msgs = self.wx.GetNextNewMessage()
                except Exception as e:
                    print(f"[wechat] 获取消息出错：{e}")
                    time.sleep(self.poll_interval)
                    continue

                for chat_name, msgs in new_msgs.items():
                    for msg in msgs:
                        self._dispatch(chat_name, msg)

                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print("\n已停止监听。")
