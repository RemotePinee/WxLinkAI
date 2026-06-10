# WxLinkAI 插件

这个插件只负责：

- 读取微信消息里的 `talker` / `sender` / `text`
- 缓存当前发言人最近一张图到桥接后端
- 把文本消息转发给桥接后端
- 把桥接后端返回的文本/图片发回微信

复杂逻辑全部在独立服务 `WxLinkAI` 里完成。

## 使用前提

手机侧需要：

- 手机已经 Root。
- 已安装并启用 WAuxiliary 模块。
- 微信已经被 WAuxiliary 正常接管。
- 手机可以访问运行 `WxLinkAI` 的电脑或服务器地址。

这个插件不是独立 App，也不直接连接模型服务。它必须通过 WAuxiliary 接入微信，再把消息转发给 `WxLinkAI` 后端。

## 接入步骤

1. 先在电脑或服务器上启动 `WxLinkAI` 后端，确认访问地址，例如 `http://你的后端地址:8090`。
2. 修改 `main.java` 顶部配置：

```java
var bridgeHost = "http://你的后端地址:8090"
var bridgeAuthKey = "你的 auth_key"
```

3. 把插件导入 WAuxiliary，或按 WAuxiliary 的插件目录规则放入插件文件。
4. 在 WAuxiliary 里启用“WxLinkAI”插件。
5. 回到微信里测试触发。

## 触发

- 群聊：`@机器人 任意内容`
- 群聊：`/问 内容`、`/生图 内容`、`/画图 内容`
- 私聊：任意文本

## 后端协议说明

插件只连接 `WxLinkAI` 后端，不直接连接模型服务。模型服务协议在后端 `config.json` 里配置。

后端当前支持：

- `chat_completions`：OpenAI 聊天补全兼容接口。
- `responses`：OpenAI 响应接口兼容协议。
- `anthropic_messages`：Anthropic 消息接口原生协议。
- `chat_stream`：[RemotePinee/ChatGPT2API](https://github.com/RemotePinee/ChatGPT2API) 的专用流式接口，不是通用协议。配置这个协议时，后端会请求 `{base_url}/api/chat/stream`，并解析 `data: {"type":"delta","text":"..."}` 返回。

只有接口路径、鉴权方式、请求体和返回结构都兼容对应协议时，接入的模型服务才能正常工作；不是只填 API key 就一定能跑。
