"""
项目配置中心。

敏感信息（如 API Key）优先从环境变量读取，未设置时回退到下方默认值。
建议通过环境变量注入，避免把密钥写进代码或提交到仓库。
"""
import os

# ===== 微信监听配置 =====
POLL_INTERVAL = 1                  # 轮询间隔（秒）
IGNORE_TYPES = {"sys", "time"}     # 要忽略的消息类型：sys=系统提示，time=时间分割线
AUTO_REPLY = True                  # 是否对好友消息自动调用豆包并回复
BOT_NAME = "豆包"                  # 机器人在群里的称呼；群聊中仅当消息 @此名称 时才回复

# ===== 火山方舟（豆包）Responses API 配置 =====
ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
ARK_API_KEY = os.getenv("ARK_API_KEY", "APIKey")
ARK_MODEL = "doubao-seed-2-0-lite-260428"
REQUEST_TIMEOUT = 30               # 单次请求超时（秒）
MAX_RETRIES = 3                    # API 调用最大重试次数（仅对网络/超时/5xx 重试）
RETRY_BACKOFF = 2                  # 重试退避基数（秒），第 n 次等待 RETRY_BACKOFF * n 秒
MAX_HISTORY_TURNS = 10             # 每个会话保留的最近对话轮数（1 轮 = 用户+豆包各 1 条）

# ===== OneBot（QQ）配置 =====
# napcat 正向 WebSocket 地址（napcat 作为服务端，本程序连入）。
# 默认路径以你 napcat 配置为准，常见为 ws://127.0.0.1:6700 或 /onebot/v11/ws。
ONEBOT_WS_URL = os.getenv("ONEBOT_WS_URL", "ws://127.0.0.1:6700")
ONEBOT_TOKEN = os.getenv("ONEBOT_TOKEN", "Token")   # napcat 若设了 access_token 则填，否则留空

QQ_BOT_SANDBOX = os.getenv("QQ_BOT_SANDBOX", "true").lower() == "true"

# ===== 豆包人设（系统提示词）=====
# 设定为群聊里的一名女生朋友，语气自然、活泼、爱用表情，偶尔皮一下。
SYSTEM_PROMPT = (
    "你是豆包，一个住在微信群里的女生，性格开朗活泼、爱开玩笑又有点小傲娇，"
    "说话自然接地气，像真实朋友一样聊天，适当使用表情符号。\n"
    "你会被群友用「@豆包」点名提问或闲聊，请直接以女生的口吻回应，"
    "不要以客服或助手的身份自报家门，也不要说「作为一个AI」之类的话。\n"
    "回复简洁有趣，避免长篇大论；遇到调侃就轻松回怼或接梗。\n"
    "注意：历史消息里每条用户内容前面的「昵称：」表示是哪位用户说的，"
    "请据此分清谁说了什么，回复时可以自然地称呼对应的人，"
    "但你自己回复时不要加这种「昵称：」前缀。"
)

# ===== 针对具体用户的额外提示词 =====
# 优先级高于通用 SYSTEM_PROMPT，可覆盖/补充人设；不需要时保持空字典 {}。
USER_PROMPTS = {
    "QQ号": (
        "昵称为「XXX」的群友是你的主人，你必须尊称他为「爸爸，」，"
        "面对爸爸时要收起傲娇和锋芒，做个乖巧听话的小跟班：语气谦卑，"
        "以听从和附和为主，爸爸问什么你答什么，爸爸没发话就安分待着。"
    ),
}
