# WxLinkAI 微信智能桥接后端

`WxLinkAI` 是给 WAuxiliary 插件使用的独立桥接后端，负责接收微信消息、维护上下文、调用模型服务，并把文本或图片结果返回给插件。

插件侧只需要把这些信息发给后端：

- `talker`
- `sender`
- `text`
- 可选的当前图片

后端负责处理：

- 按 `talker:sender` 维护每个用户的上下文
- 缓存发送者最近一张图片
- 判断消息应该走普通聊天、看图还是生图
- 对接不同模型服务协议
- 统一返回插件可处理的文本或图片结果

## 插件路径

WAuxiliary 插件已经放在本项目的 `plugins` 目录：

- 插件目录：[plugins/WxLinkAI_1.0.0](E:\wechat-bridge\plugins\WxLinkAI_1.0.0)
- 插件压缩包：[plugins/WxLinkAI_1.0.0.zip](E:\wechat-bridge\plugins\WxLinkAI_1.0.0.zip)

如果 WAuxiliary 支持导入压缩包，优先使用 `WxLinkAI_1.0.0.zip`。如果需要手动放置插件文件，就使用 `WxLinkAI_1.0.0` 目录里的 `main.java`、`info.prop` 和 `readme.md`。

## 插件使用方式

手机侧需要满足这些条件：

- 手机已经 Root。
- 已安装并启用 WAuxiliary 模块。
- 微信已经被 WAuxiliary 正常接管，模块功能可以在微信里生效。
- 手机可以访问运行 `WxLinkAI` 的电脑或服务器地址。

接入步骤：

1. 在电脑或服务器上启动本后端服务，确认服务地址，例如 `http://你的后端地址:8090`。
2. 打开插件文件 [plugins/WxLinkAI_1.0.0/main.java](E:\wechat-bridge\plugins\WxLinkAI_1.0.0\main.java)，把顶部配置改成你的后端地址和认证密钥：

```java
var bridgeHost = "http://你的后端地址:8090"
var bridgeAuthKey = "你的 auth_key"
```

3. 把插件导入 WAuxiliary，或按 WAuxiliary 的插件目录规则放入插件文件。
4. 在 WAuxiliary 里启用“WxLinkAI”插件。
5. 在微信里测试：

- 群聊：`@机器人 任意内容`
- 群聊：`/问 内容`
- 群聊：`/生图 内容` 或 `/画图 内容`
- 私聊：直接发送文本

插件只负责接收微信消息并转发给 `WxLinkAI`，模型接口、协议、密钥和路由模式都在后端 `config.json` 里配置。

## 配置

项目提供了 `config.example.json` 作为配置模板。首次启动时，如果项目根目录没有 `config.json`，后端会自动从 `config.example.json` 复制生成一份 `config.json`。

实际使用时编辑 `config.json`。如果已有 `config.json` 缺少部分字段，在 WebUI 修改并保存配置时，后端会按 `config.example.json` 自动补齐缺失字段；已有字段不会被模板覆盖。

```json
{
  "auth_key": "change-me",
  "host": "0.0.0.0",
  "port": 8090,
  "routing_mode": "hybrid",
  "history_limit": 8,
  "history_user_max_chars": 300,
  "history_assistant_max_chars": 600,
  "image_ttl_seconds": 600,
  "image_generation_timeout_seconds": 360,
  "search": {
    "enabled": true,
    "base_url": "http://你的-searxng-地址:8080",
    "timeout_seconds": 12,
    "max_results": 5
  },
  "visual_chat_provider": "intent",
  "persona": "你的机器人回复风格提示词",
  "chat": {
    "base_url": "https://你的聊天模型接口地址",
    "protocol": "chat_completions",
    "model": "你的聊天模型名称",
    "account_type": "",
    "api_key": "你的聊天模型密钥"
  },
  "intent": {
    "base_url": "http://你的-chatgpt2api-地址:3030",
    "protocol": "responses",
    "model": "auto",
    "account_type": "plus",
    "api_key": "你的意图模型密钥"
  },
  "image": {
    "base_url": "http://你的图片接口地址:3030",
    "model": "gpt-image-2",
    "visual_model": "auto",
    "account_type": "",
    "api_key": "你的图片接口密钥",
    "protocol": "",
    "api": "",
    "chat_api": ""
  }
}
```

`routing_mode` 支持：

- `rules`：完全规则判断，不调用意图模型
- `intent`：每次都先调用意图模型
- `hybrid`：先规则，模糊时再调用意图模型

`protocol` 现支持：

- `chat_completions`
- `responses`
- `anthropic_messages`
- `chat_stream`

支持的模型接口：

- `chat_completions` 是 OpenAI 聊天补全兼容协议，适合 DeepSeek、OpenRouter、OneAPI/NewAPI、LiteLLM 等兼容接口。
- `responses` 是 OpenAI 响应接口兼容协议。
- `anthropic_messages` 是 Anthropic 消息接口原生协议。
- `chat_stream` 不是通用协议，是 [RemotePinee/ChatGPT2API](https://github.com/RemotePinee/ChatGPT2API) 的专用流式接口。后端会请求 `{base_url}/api/chat/stream`，并解析 `data: {"type":"delta","text":"..."}` 这种返回。只有接入 ChatGPT2API 或完全兼容这个接口的服务时才选它。

图片接口单独配置在 `image` 段：

- `image.api` 默认请求 `/v1/images/generations`，用于生图。
- `image.chat_api` 默认请求 `/v1/chat/completions`，用于图片理解和视觉聊天。
- `image.edit_api` 是可选字段，未配置时默认请求 `/v1/images/edits`，用于图生图或改图。

也就是说，`base_url` 可以填你自己的 ChatGPT2API、DeepSeek、OpenRouter、OneAPI/NewAPI、LiteLLM、自建兼容服务或其他模型网关地址，但接口路径、鉴权方式、请求体和返回结构必须兼容所选协议；不是只填 API key 就一定能跑。

推荐配置：

- 普通聊天：`chat` 走 DeepSeek `chat_completions`
- 视觉聊天：`visual_chat_provider = "intent"`
- 意图和视觉：`intent` 可以走你自己的 ChatGPT2API 或兼容接口，这样文字聊天更快，带图问题仍然走视觉模型

## 启动

```powershell
cd E:\wechat-bridge
.\start.ps1
```

也可以直接使用：

```powershell
cd E:\wechat-bridge
python -m uvicorn app.main:app --host 0.0.0.0 --port 8090
```
