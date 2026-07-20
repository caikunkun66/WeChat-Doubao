会封号别用
# WeChat Doubao 微信豆包机器人

基于 `wxauto`（微信 3.9 UI 自动化）监听微信消息，并调用火山方舟（豆包）API 自动回复。

## 项目结构

```
config.py        # 配置中心（轮询间隔、忽略类型、API Key/Model 等）
doubao.py        # 豆包 API 客户端，对外暴露 get_reply() 公共方法
wechat.py        # 微信监听封装（wxauto）：过滤、去重、消息回调
bot.py           # 编排层：把「监听」与「回复」组合成自动回复机器人
main.py          # 程序入口
requirements.txt # 依赖声明
```

各模块职责单一、通过回调解耦：
- `config.py` 只管配置；
- `doubao.py` 只管调 API 取回复；
- `wechat.py` 只管监听/过滤/去重/发消息；
- `bot.py` 只管把两者编排成自动回复逻辑。

## 环境要求

- Windows + 已登录的微信 3.9.x PC 客户端（窗口需可读取，勿完全隐藏）
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

## 运行

```bash
python main.py
```

启动后，好友发来消息会触发豆包回复并自动发回；`Ctrl+C` 退出。

## 说明

- 仅自动回复 `friend` 类型消息；自己 / 系统 / 撤回消息不回复，避免机器人自问自答死循环。
- 不碰微信协议、不注入内存，相对安全；但自动化操作仍有账号风控风险，建议小号 / 低频使用。
- 当前为单轮对话（每次只把当前这条消息发给豆包）。如需多轮上下文，可扩展 `DoubaoClient` 维护历史消息。
