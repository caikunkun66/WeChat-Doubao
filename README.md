# QQ 豆包机器人（napcat + OneBot）


基于 [napcat](https://github.com/NapNeko/NapCatQQ)（OneBot 协议客户端，无窗口）监听 QQ 消息，并调用火山方舟（豆包）API 自动回复。

## 项目结构

```
config.py        # 配置中心（API Key/Model、OneBot 地址、豆包人设等）
doubao.py        # 豆包 API 客户端，对外暴露 get_reply() 公共方法
qq_bot.py        # QQ 机器人（OneBot 协议，napcat + WebSocket，可后台静默运行）
requirements.txt # 依赖声明
```

各模块职责单一、通过回调解耦：
- `config.py` 只管配置；
- `doubao.py` 只管调 API 取回复；
- `qq_bot.py` 用 OneBot 协议对接 QQ（napcat），复用 `doubao.py` 与 `config.py`。

## 环境要求

- Windows + 已安装的 **NT 版 QQ（9.x）**
- Python 3.8 ~ 3.15

## 安装

```bash
pip install -r requirements.txt
```

## 配置 API Key（推荐用环境变量，避免泄露）

```bash
set ARK_API_KEY=你的密钥
```

未设置 `ARK_API_KEY` 时会回退到 `config.py` 中的默认值。

## 启动 napcat（需自行下载）

> `NapCat.Shell/` 不随仓库提交，请自行从 [napcat 发布页](https://github.com/NapNeko/NapCatQQ/releases) 下载「NapCat.Shell」压缩包，解压到本地任意目录（下文的 `NapCat.Shell/` 即指该目录）。

> 前置：本机已安装 **NT 版 QQ（9.x）**，napcat 会从注册表 `HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ` 读取 QQ 安装路径自动注入。请用**不重要的小号**登录。

- **方式 A（管理员）**：在 `NapCat.Shell/` 目录运行 `launcher.bat`。脚本会自动定位 QQ 并注入 napcat 后启动 QQ。
- **方式 B（普通用户）**：若不想提权，运行 `launcher-user.bat`（或 `launcher-win10-user.bat`）。

启动后 QQ 会随 napcat 一起打开，扫码 / 快速登录（见 `quickLoginExample.bat`）即可。

> 正向 WebSocket 需自行配置：在 `NapCat.Shell/config/onebot11_*.json` 中确保有一条服务，`host=127.0.0.1`、`port=6700`、`token=n_8Y6-PKRXRFYSmR`，与 `config.py` 默认值一致。
> 也可通过 WebUI 管理：浏览器打开 `http://127.0.0.1:6099/`（WebUI 端口见 `NapCat.Shell/config/webui.json`，token 同文件内 `token` 字段），在「网络配置 → OneBot11 → 正向 WS」里调整，确保端口 / token 与 `config.py` 的 `ONEBOT_WS_URL` / `ONEBOT_TOKEN` 对应。

## 配置

`config.py` 中的 `ONEBOT_WS_URL` / `ONEBOT_TOKEN` 默认值（`ws://127.0.0.1:6700` / `n_8Y6-PKRXRFYSmR`）已与本仓库预置的 napcat 正向 WS 完全一致，**通常无需改动**。若你改过 napcat 的端口 / token，则在此同步：

```python
ONEBOT_WS_URL = "ws://127.0.0.1:6700"   # napcat 正向 WS 地址
ONEBOT_TOKEN  = "n_8Y6-PKRXRFYSmR"      # napcat 的 access_token，没有则留空
```

豆包人设在 `config.py` 的 `SYSTEM_PROMPT` 中调整。

## 运行

```bash
# 前台调试（可见日志）
python qq_bot.py

# 后台静默（不弹窗口，日志写入 qq_bot.log）
pythonw qq_bot.py
```

如需**开机自启 / 服务化**：用 `nssm` 把 `pythonw qq_bot.py` 注册成 Windows 服务，或在任务计划程序里设置"登录时运行"。程序内置断线自动重连（5 秒重试），适合无人值守。

## 行为说明

- 群聊：仅当消息 **@ 机器人** 时才调用豆包回复；未 @ 的群聊也会写入共享记忆，供后续 @ 带上下文。
- 私聊：直接回复。
- 记忆按会话共享（群内所有群友共用一条记忆线），豆包人设见 `config.SYSTEM_PROMPT`。
