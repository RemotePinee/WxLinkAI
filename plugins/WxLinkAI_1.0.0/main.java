var bridgeHost = "http://你的后端地址:8090"
var bridgeAuthKey = "change-me"
var replyWithAt = true
var recentImageMap = new HashMap()
var recentTextMap = new HashMap()
var recentTextTimeMap = new HashMap()
var recentTextTtlMs = 5 * 60 * 1000L
var chatNoticeText = "正在核对信息，稍后回复。"
var searchNoticeText = "正在查询，请稍等。"
var bridgeMessageTimeoutMs = 7 * 60 * 1000

String cleanText(Object text) {
    return String.valueOf(text == null ? "" : text).trim();
}

String previewText(Object text) {
    var value = cleanText(text);
    value = value.replace("\n", "\\n").replace("\r", "\\r");
    if (value.length() > 300) return value.substring(0, 300);
    return value;
}

void dbg(String text) {
    try {
        log("[WxLinkAI] " + text);
    } catch (Exception e) {
    }
}

String mention(boolean isGroup, String sender) {
    if (!isGroup || !replyWithAt || sender == null || sender.length() == 0) return "";
    return "[AtWx=" + sender + "] ";
}

void safeSendText(String talker, String text) {
    try {
        dbg("sendText start talker=" + talker + " text=" + previewText(text));
        sendText(talker, text);
        dbg("sendText done");
    } catch (Exception e) {
        dbg("sendText error=" + String.valueOf(e));
    }
}

String jsonStringValue(String json, String key) {
    try {
        var source = cleanText(json);
        var marker = "\"" + key + "\":";
        var idx = source.indexOf(marker);
        if (idx < 0) return "";
        idx = idx + marker.length();
        while (idx < source.length() && Character.isWhitespace(source.charAt(idx))) idx++;
        if (idx >= source.length() || source.charAt(idx) != '"') return "";
        idx++;
        var sb = new StringBuilder();
        var escape = false;
        for (var i = idx; i < source.length(); i++) {
            var ch = source.charAt(i);
            if (escape) {
                if (ch == 'n') sb.append("\n");
                else if (ch == 'r') sb.append("\r");
                else if (ch == 't') sb.append("\t");
                else sb.append(ch);
                escape = false;
                continue;
            }
            if (ch == '\\') {
                escape = true;
                continue;
            }
            if (ch == '"') break;
            sb.append(ch);
        }
        return cleanText(sb.toString());
    } catch (Exception e) {
        dbg("jsonStringValue error key=" + key + " err=" + String.valueOf(e));
        return "";
    }
}

String firstJsonArrayString(String json, String key) {
    try {
        var source = cleanText(json);
        var marker = "\"" + key + "\":";
        var idx = source.indexOf(marker);
        if (idx < 0) return "";
        idx = source.indexOf("[", idx);
        if (idx < 0) return "";
        idx = source.indexOf("\"", idx);
        if (idx < 0) return "";
        idx++;
        var end = source.indexOf("\"", idx);
        if (end < 0) return "";
        return source.substring(idx, end);
    } catch (Exception e) {
        dbg("firstJsonArrayString error key=" + key + " err=" + String.valueOf(e));
        return "";
    }
}

String pipeValue(String text, String key) {
    try {
        var prefix = key + "=";
        var lines = String.valueOf(text == null ? "" : text).split("\\r?\\n");
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (line.startsWith(prefix)) return line.substring(prefix.length()).trim();
        }
    } catch (Exception e) {
        dbg("pipeValue error key=" + key + " err=" + String.valueOf(e));
    }
    return "";
}

String pipeText(String text) {
    try {
        var value = pipeValue(text, "TEXT_B64");
        if (value.length() == 0) return "";
        var bytes = Base64.getDecoder().decode(value);
        return cleanText(new String(bytes, "UTF-8"));
    } catch (Exception e) {
        dbg("pipeText error=" + String.valueOf(e));
        return "";
    }
}

Map authHeader() {
    var headerMap = new HashMap();
    headerMap.put("Content-Type", "application/json");
    headerMap.put("Authorization", "Bearer " + bridgeAuthKey);
    return headerMap;
}

String postJsonSync(String url, Map body, int timeoutMs) {
    HttpURLConnection conn = null;
    try {
        var jsonBody = new JSONObject(body).toString();
        var data = jsonBody.getBytes("UTF-8");

        conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(timeoutMs);
        conn.setReadTimeout(timeoutMs);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
        conn.setRequestProperty("Authorization", "Bearer " + bridgeAuthKey);

        var os = conn.getOutputStream();
        os.write(data);
        os.flush();
        os.close();

        var code = conn.getResponseCode();
        var is = code >= 200 && code < 400 ? conn.getInputStream() : conn.getErrorStream();
        if (is == null) {
            if (code >= 200 && code < 400) return "";
            throw new RuntimeException("HTTP " + code);
        }

        var br = new BufferedReader(new InputStreamReader(is, "UTF-8"));
        var sb = new StringBuilder();
        String line = null;
        while ((line = br.readLine()) != null) {
            sb.append(line);
            sb.append("\n");
        }
        br.close();

        var resp = sb.toString().trim();
        if (code < 200 || code >= 400) {
            throw new RuntimeException("HTTP " + code + ": " + resp);
        }
        return resp;
    } catch (Exception e) {
        throw new RuntimeException(String.valueOf(e));
    } finally {
        if (conn != null) {
            conn.disconnect();
        }
    }
}

Map resolveBridgeIntent(String talker, String sender, String text, boolean atMe) {
    var result = new HashMap();
    try {
        var body = new HashMap();
        body.put("talker", talker);
        body.put("sender", sender);
        body.put("text", text);
        body.put("at_me", String.valueOf(atMe));
        dbg("intent native sync start text=" + previewText(text));
        var respContent = postJsonSync(bridgeHost + "/wechat/intent", body, 30 * 1000);
        dbg("intent native sync response length=" + String.valueOf(respContent == null ? 0 : respContent.length()));
        result.put("action", jsonStringValue(respContent, "action"));
        result.put("prompt", jsonStringValue(respContent, "prompt"));
        result.put("use_image", jsonStringValue(respContent, "use_image"));
        result.put("resolution", jsonStringValue(respContent, "resolution"));
        result.put("size", jsonStringValue(respContent, "size"));
        result.put("notice", jsonStringValue(respContent, "notice"));
        result.put("notice_text", jsonStringValue(respContent, "notice_text"));
    } catch (Throwable t) {
        dbg("intent native throwable=" + String.valueOf(t));
    }
    return result;
}

boolean startsWithAny(String text, String[] prefixes) {
    var value = cleanText(text);
    for (var i = 0; i < prefixes.length; i++) {
        if (value.startsWith(prefixes[i])) return true;
    }
    return false;
}

boolean hasBotPrefix(String text) {
    return startsWithAny(text, new String[]{
            "/生图 ", "/绘图 ", "/画图 ", "/作图 ", "/聊天 ", "/问 ",
            "生图 ", "绘图 ", "画图 ", "作图 ", "聊天 ", "问 "
    });
}

boolean isLikelyDrawCommand(String text) {
    var value = cleanText(text);
    if (value.length() == 0) return false;
    if (value.indexOf("怎么") >= 0 || value.indexOf("如何") >= 0 || value.indexOf("为什么") >= 0
        || value.indexOf("接口") >= 0 || value.indexOf("配置") >= 0 || value.indexOf("报错") >= 0
        || value.indexOf("失败") >= 0 || value.indexOf("教程") >= 0 || value.indexOf("方法") >= 0) {
        return false;
    }
    if (startsWithAny(value, new String[]{
        "/生图 ", "/绘图 ", "/画图 ", "/作图 ",
        "生图 ", "绘图 ", "画图 ", "作图 "
    })) return true;
    var mentionsImage = value.indexOf("这张图") >= 0
        || value.indexOf("这图") >= 0
        || value.indexOf("图片") >= 0
        || value.indexOf("照片") >= 0
        || value.indexOf("上图") >= 0
        || value.indexOf("刚才那张") >= 0
        || value.indexOf("上一张") >= 0;
    var editsImage = value.indexOf("换") >= 0
        || value.indexOf("改") >= 0
        || value.indexOf("变成") >= 0
        || value.indexOf("做成") >= 0
        || value.indexOf("生成") >= 0
        || value.indexOf("画成") >= 0
        || value.indexOf("重画") >= 0
        || value.indexOf("二创") >= 0
        || value.indexOf("场景") >= 0
        || value.indexOf("风格") >= 0;
    if (mentionsImage && editsImage) return true;
    return value.startsWith("画")
        || value.startsWith("绘制")
        || value.startsWith("生成")
        || value.startsWith("做")
        || value.startsWith("设计")
        || value.startsWith("创作")
        || value.startsWith("制作");
}

boolean isImplicitImageEditCommand(String text) {
    var value = cleanText(text);
    if (value.length() == 0) return false;
    if (value.indexOf("怎么") >= 0 || value.indexOf("如何") >= 0 || value.indexOf("为什么") >= 0
        || value.indexOf("教程") >= 0 || value.indexOf("方法") >= 0 || value.indexOf("失败") >= 0) {
        return false;
    }
    return value.indexOf("换") >= 0
        || value.indexOf("改") >= 0
        || value.indexOf("变成") >= 0
        || value.indexOf("做成") >= 0
        || value.indexOf("生成") >= 0
        || value.indexOf("画成") >= 0
        || value.indexOf("重画") >= 0
        || value.indexOf("二创") >= 0
        || value.indexOf("场景") >= 0
        || value.indexOf("背景") >= 0
        || value.indexOf("风格") >= 0
        || value.indexOf("氛围") >= 0
        || value.indexOf("高级") >= 0
        || value.indexOf("精致") >= 0;
}

String stripAtPrefix(String text) {
    var prompt = cleanText(text);
    prompt = prompt.replaceAll("^\\[AtWx=[^\\]]+\\]\\s*", "").trim();
    prompt = prompt.replaceAll("^@[^\\s\\u2005\\u2003:：,，]+[\\s\\u2005\\u2003:：,，]*", "").trim();
    return prompt;
}

String fileBase64(String path) {
    try {
        var file = new File(path);
        dbg("fileBase64 path=" + path + " exists=" + file.exists() + " length=" + file.length());
        if (!file.exists() || file.length() <= 0) return "";
        var bytes = new byte[(int) file.length()];
        var fis = new FileInputStream(file);
        fis.read(bytes);
        fis.close();
        return Base64.getEncoder().encodeToString(bytes);
    } catch (Exception e) {
        return "";
    }
}

boolean waitFileReady(String path, int timeoutMs) {
    var start = System.currentTimeMillis();
    while (System.currentTimeMillis() - start < timeoutMs) {
        try {
            var file = new File(path);
            if (file.exists() && file.length() > 0) {
                dbg("waitFileReady ok path=" + path + " length=" + file.length());
                return true;
            }
            Thread.sleep(200);
        } catch (Exception e) {
            dbg("waitFileReady error=" + String.valueOf(e));
            return false;
        }
    }
    try {
        var file = new File(path);
        dbg("waitFileReady timeout path=" + path + " exists=" + file.exists() + " length=" + file.length());
    } catch (Exception e) {
        dbg("waitFileReady timeout stat error=" + String.valueOf(e));
    }
    return false;
}

boolean isGroupTalker(String talker) {
    return cleanText(talker).endsWith("@chatroom");
}

boolean isIgnoredTalker(String talker, String sender) {
    var t = cleanText(talker);
    var s = cleanText(sender);
    return t.startsWith("gh_") || s.startsWith("gh_");
}

String imageKey(String talker, String sender) {
    return cleanText(talker) + ":" + cleanText(sender);
}

String sessionKey(String talker, String sender) {
    return cleanText(talker) + ":" + cleanText(sender);
}

boolean isBareAtText(String text) {
    var body = stripAtPrefix(text);
    return body.length() == 0 && cleanText(text).indexOf("@") >= 0;
}

void rememberRecentText(String talker, String sender, String text) {
    var value = cleanText(text);
    if (value.length() == 0) return;
    if (isBareAtText(value)) return;
    var key = sessionKey(talker, sender);
    recentTextMap.put(key, value);
    recentTextTimeMap.put(key, Long.valueOf(System.currentTimeMillis()));
    dbg("recent text saved key=" + key + " text=" + value);
}

String recentText(String talker, String sender) {
    var key = sessionKey(talker, sender);
    var value = recentTextMap.get(key);
    var timeObj = recentTextTimeMap.get(key);
    if (value == null || timeObj == null) {
        dbg("recent text lookup key=" + key + " empty");
        return "";
    }
    var age = System.currentTimeMillis() - ((Long) timeObj).longValue();
    if (age > recentTextTtlMs) {
        dbg("recent text expired key=" + key + " age=" + age);
        recentTextMap.remove(key);
        recentTextTimeMap.remove(key);
        return "";
    }
    var result = cleanText(value);
    dbg("recent text lookup key=" + key + " text=" + result);
    return result;
}

void rememberRecentImage(String talker, String sender, String imageB64) {
    var value = cleanText(imageB64);
    if (value.length() == 0) return;
    var key = imageKey(talker, sender);
    recentImageMap.put(key, value);
    if (!isGroupTalker(talker)) {
        recentImageMap.put(imageKey(talker, talker), value);
    }
    dbg("recent image saved key=" + key + " length=" + value.length());
}

String recentImageB64(String talker, String sender) {
    var key = imageKey(talker, sender);
    var value = recentImageMap.get(key);
    if (value == null && !isGroupTalker(talker)) {
        value = recentImageMap.get(imageKey(talker, talker));
    }
    var result = cleanText(value);
    dbg("recent image lookup key=" + key + " length=" + result.length());
    return result;
}

boolean sameImageSender(Object msgInfoBean, String talker, String sender) {
    var msgSender = cleanText(msgInfoBean.getSendTalker());
    var targetSender = cleanText(sender);
    if (targetSender.length() == 0) return true;
    if (msgSender.equals(targetSender)) return true;
    return !isGroupTalker(talker) && msgSender.length() == 0;
}

String latestImageBase64FromHistory(String talker, String sender) {
    try {
        var list = queryHistoryMsg(talker, 0L, 30);
        dbg("history query size=" + String.valueOf(list == null ? 0 : list.size()));
        if (list == null) return "";

        Object best = null;
        long bestTime = -1L;
        for (var i = 0; i < list.size(); i++) {
            var item = list.get(i);
            if (item == null) continue;
            if (!item.isImage()) continue;
            dbg("history image sender=" + item.getSendTalker() + " sent=" + item.isSend() + " time=" + item.getCreateTime());
            if (!sameImageSender(item, talker, sender)) continue;
            var createTime = item.getCreateTime();
            if (best == null || createTime > bestTime) {
                best = item;
                bestTime = createTime;
            }
        }

        if (best == null) {
            dbg("history image not found for sender=" + sender);
            return "";
        }

        var path = cacheDir + "/history_img_" + best.getMsgId() + ".jpg";
        downloadImg(best.getImageMsg(), path);
        var b64 = fileBase64(path);
        dbg("history image b64 length=" + b64.length());
        return b64;
    } catch (Exception e) {
        dbg("history image error=" + String.valueOf(e));
        return "";
    }
}

void saveImage(String base64Str, String outputPath) {
    var bytes = Base64.getDecoder().decode(base64Str);
    try (FileOutputStream fos = new FileOutputStream(outputPath)) {
        fos.write(bytes);
    } catch (IOException e) {
        e.printStackTrace();
    }
}

void sendSelfCheck(String talker, boolean isGroup, String sender) {
    dbg("self-check");
    safeSendText(
        talker,
        mention(isGroup, sender)
            + "WxLinkAI 自检"
            + "\nbridgeHost=" + bridgeHost
            + "\nbridgeAuthKey=" + (cleanText(bridgeAuthKey).length() > 0 ? "已配置" : "未配置")
    );
}

void cacheImageToBridge(String talker, String sender, String imagePath) {
    dbg("cache-image start talker=" + talker + " sender=" + sender + " path=" + imagePath);
    var imageB64 = fileBase64(imagePath);
    if (imageB64.length() == 0) {
        dbg("cache-image empty b64");
        return;
    }
    rememberRecentImage(talker, sender, imageB64);

    var body = new HashMap();
    body.put("talker", talker);
    body.put("sender", sender);
    body.put("image_b64", imageB64);
    body.put("image_mime", "image/png");

    new Thread(() -> {
        try {
            dbg("cache-image native start");
            var respContent = postJsonSync(bridgeHost + "/wechat/cache-image", body, 60 * 1000);
            dbg("cache-image native ok length=" + String.valueOf(respContent == null ? 0 : respContent.length()));
        } catch (Exception e) {
            dbg("cache-image native error=" + String.valueOf(e));
        }
    }).start();
}

void handleBridgeReply(String talker, boolean isGroup, String sender, String respContent, String clientTaskId, boolean noticeSent) {
    try {
        dbg("handle-reply length=" + String.valueOf(respContent == null ? 0 : respContent.length()));
        var mode = pipeValue(respContent, "MODE");
        var replyText = pipeText(respContent);
        var taskId = cleanText(clientTaskId);
        if (taskId.length() == 0) taskId = pipeValue(respContent, "TASK_ID");
        var firstImage = pipeValue(respContent, "IMAGE_B64");
        var hasImages = firstImage.length() > 0;
        dbg("handle-reply parsed mode=" + mode + " taskId=" + taskId + " noticeSent=" + noticeSent + " images=" + String.valueOf(hasImages) + " textLen=" + String.valueOf(replyText.length()));

        if (noticeSent && mode.equals("draw") && hasImages && taskId.length() > 0) {
            safeSendText(talker, mention(isGroup, sender) + "生图已完成 [任务ID: " + taskId + "]");
        } else if (replyText.length() > 0) {
            safeSendText(talker, mention(isGroup, sender) + replyText);
        } else if (!hasImages) {
            safeSendText(talker, mention(isGroup, sender) + "处理完成，但没有返回内容");
        }

        if (hasImages) {
            var path = cacheDir + "/bridge_" + System.currentTimeMillis() + ".jpg";
            saveImage(firstImage, path);
            sendImage(talker, path);
        }
    } catch (Exception e) {
        dbg("handle-reply error=" + String.valueOf(e));
        safeSendText(talker, mention(isGroup, sender) + "桥接返回处理失败");
    }
}

void handlePlainReply(String talker, boolean isGroup, String sender, String respContent) {
    try {
        dbg("plain reply enter");
        String replyText = String.valueOf(respContent == null ? "" : respContent).trim();
        dbg("plain reply textLen=" + replyText.length());
        if (replyText.length() > 0) {
            safeSendText(talker, mention(isGroup, sender) + replyText);
        } else {
            safeSendText(talker, mention(isGroup, sender) + "处理完成，但没有返回内容");
        }
    } catch (Throwable t) {
        dbg("plain reply throwable=" + String.valueOf(t));
        safeSendText(talker, mention(isGroup, sender) + "回复处理失败");
    }
}

void sendMessageToBridge(String talker, boolean isGroup, String sender, String text, boolean atMe) {
    sendMessageToBridge(talker, isGroup, sender, text, atMe, "", false, "", "plain");
}

void sendMessageToBridge(String talker, boolean isGroup, String sender, String text, boolean atMe, String taskId, boolean noticeSent) {
    sendMessageToBridge(talker, isGroup, sender, text, atMe, taskId, noticeSent, "", noticeSent ? "pipe" : "plain");
}

void sendMessageToBridge(String talker, boolean isGroup, String sender, String text, boolean atMe, String taskId, boolean noticeSent, String imageB64) {
    sendMessageToBridge(talker, isGroup, sender, text, atMe, taskId, noticeSent, imageB64, noticeSent ? "pipe" : "plain");
}

void sendMessageToBridgeWithIntent(String talker, boolean isGroup, String sender, String text, boolean atMe, String taskId, boolean noticeSent, String responseFormat, Map intent) {
    sendMessageToBridge(talker, isGroup, sender, text, atMe, taskId, noticeSent, "", responseFormat, intent);
}

void sendMessageToBridgeWithIntent(String talker, boolean isGroup, String sender, String text, boolean atMe, String taskId, boolean noticeSent, String imageB64, String responseFormat, Map intent) {
    sendMessageToBridge(talker, isGroup, sender, text, atMe, taskId, noticeSent, imageB64, responseFormat, intent);
}

void sendMessageToBridge(String talker, boolean isGroup, String sender, String text, boolean atMe, String taskId, boolean noticeSent, String imageB64, String responseFormat) {
    sendMessageToBridge(talker, isGroup, sender, text, atMe, taskId, noticeSent, imageB64, responseFormat, new HashMap());
}

void sendMessageToBridge(String talker, boolean isGroup, String sender, String text, boolean atMe, String taskId, boolean noticeSent, String imageB64, String responseFormat, Map intent) {
    dbg("send-message start talker=" + talker + " sender=" + sender + " atMe=" + atMe + " text=" + text);
    var body = new HashMap();
    body.put("talker", talker);
    body.put("sender", sender);
    body.put("text", text);
    body.put("at_me", String.valueOf(atMe));
    body.put("client_task_id", cleanText(taskId));
    body.put("notice_sent", String.valueOf(noticeSent));
    body.put("image_b64", cleanText(imageB64));
    body.put("image_mime", "image/jpeg");
    body.put("response_format", cleanText(responseFormat));
    if (intent != null && cleanText(intent.get("action")).length() > 0) {
        body.put("intent_action", cleanText(intent.get("action")));
        body.put("intent_prompt", cleanText(intent.get("prompt")));
        body.put("intent_use_image", cleanText(intent.get("use_image")));
        body.put("intent_resolution", cleanText(intent.get("resolution")));
        body.put("intent_size", cleanText(intent.get("size")));
        body.put("intent_notice", cleanText(intent.get("notice")));
        body.put("intent_notice_text", cleanText(intent.get("notice_text")));
    }

    if ("plain".equals(responseFormat) || "pipe".equals(responseFormat)) {
        try {
            dbg("message native sync start format=" + responseFormat);
            var respContent = postJsonSync(bridgeHost + "/wechat/message", body, bridgeMessageTimeoutMs);
            dbg("message native sync response length=" + String.valueOf(respContent == null ? 0 : respContent.length()));
            if ("pipe".equals(responseFormat)) {
                handleBridgeReply(talker, isGroup, sender, respContent, taskId, noticeSent);
            } else {
                handlePlainReply(talker, isGroup, sender, respContent);
            }
        } catch (Throwable t) {
            dbg("message native sync throwable=" + String.valueOf(t));
            safeSendText(talker, mention(isGroup, sender) + "桥接请求失败：" + String.valueOf(t));
        }
        return;
    }

    new Thread(() -> {
        try {
            dbg("message native start format=" + responseFormat);
            var respContent = postJsonSync(bridgeHost + "/wechat/message", body, bridgeMessageTimeoutMs);
            dbg("message native response length=" + String.valueOf(respContent == null ? 0 : respContent.length()));
            if ("plain".equals(responseFormat)) {
                handlePlainReply(talker, isGroup, sender, respContent);
            } else {
                handleBridgeReply(talker, isGroup, sender, respContent, taskId, noticeSent);
            }
        } catch (Throwable t) {
            dbg("message native throwable=" + String.valueOf(t));
            safeSendText(talker, mention(isGroup, sender) + "桥接请求失败：" + String.valueOf(t));
        }
    }).start();
}

void sendMessageToBridgeWithNotice(String talker, boolean isGroup, String sender, String text, boolean atMe, String notice) {
    if (cleanText(notice).length() > 0) {
        safeSendText(talker, mention(isGroup, sender) + notice);
    }
    sendMessageToBridge(talker, isGroup, sender, text, atMe);
}

void sendVisionToBridgeWithNotice(String talker, boolean isGroup, String sender, String text, boolean atMe) {
    safeSendText(talker, mention(isGroup, sender) + "正在识别图片，请稍等");
    var imageB64 = recentImageB64(talker, sender);
    sendMessageToBridge(talker, isGroup, sender, text, atMe, "", false, imageB64);
}

void sendDrawToBridgeWithNotice(String talker, boolean isGroup, String sender, String text, boolean atMe, String taskId) {
    safeSendText(talker, mention(isGroup, sender) + "已开始生图任务 [任务ID: " + taskId + "]");
    sendMessageToBridge(talker, isGroup, sender, text, atMe, taskId, true);
}

String newTaskId() {
    var raw = Long.toHexString(System.currentTimeMillis()) + Long.toHexString(new Random().nextInt(65536));
    if (raw.length() > 8) return raw.substring(raw.length() - 8);
    return raw;
}

boolean needsVisionNotice(String text) {
    var value = cleanText(text);
    return value.indexOf("图里") >= 0
        || value.indexOf("图片里") >= 0
        || value.indexOf("照片里") >= 0
        || value.indexOf("识别") >= 0
        || value.indexOf("分析图片") >= 0
        || value.indexOf("看图") >= 0
        || value.indexOf("这张图") >= 0
        || value.indexOf("根据这张图") >= 0
        || value.indexOf("参考这张图") >= 0;
}

boolean needsSearchNotice(String text) {
    var value = cleanText(text);
    return value.indexOf("天气") >= 0
        || value.indexOf("机票") >= 0
        || value.indexOf("航班") >= 0
        || value.indexOf("火车票") >= 0
        || value.indexOf("高铁") >= 0
        || value.indexOf("酒店") >= 0
        || value.indexOf("价格") >= 0
        || value.indexOf("汇率") >= 0
        || value.indexOf("股票") >= 0
        || value.indexOf("基金") >= 0
        || value.indexOf("新闻") >= 0
        || value.indexOf("热搜") >= 0
        || value.indexOf("查一下") >= 0
        || value.indexOf("帮我查") >= 0
        || value.indexOf("搜索") >= 0
        || value.indexOf("检索") >= 0
        || value.indexOf("最新") >= 0
        || value.indexOf("实时") >= 0
        || value.indexOf("今天") >= 0
        || value.indexOf("明天") >= 0
        || value.indexOf("后天") >= 0
        || value.indexOf("大后天") >= 0;
}

boolean onClickSendBtn(String text) {
    var content = cleanText(text);
    dbg("click text=" + content);
    if (content.equals("/桥接自检")) {
        sendSelfCheck(getTargetTalker(), false, "");
        return true;
    }
    return false;
}

void onHandleMsg(Object msgInfoBean) {
    var talker = msgInfoBean.getTalker();
    var sender = msgInfoBean.getSendTalker();
    dbg("handle-msg talker=" + talker + " sender=" + sender + " sent=" + msgInfoBean.isSend());

    if (isIgnoredTalker(talker, sender)) {
        dbg("ignored talker=" + talker + " sender=" + sender);
        return;
    }

    if (msgInfoBean.isImage()) {
        var path = cacheDir + "/wx_img_" + msgInfoBean.getMsgId() + ".jpg";
        try {
            downloadImg(msgInfoBean.getImageMsg(), path);
            waitFileReady(path, 5000);
            cacheImageToBridge(talker, sender, path);
        } catch (Exception e) {
            log("[WxLinkAI] cache image failed: " + String.valueOf(e));
        }
        return;
    }

    if (msgInfoBean.isSend()) return;

    if (!msgInfoBean.isText()) return;

    var content = cleanText(msgInfoBean.getContent());
    var isGroup = msgInfoBean.isGroupChat();
    var atMe = msgInfoBean.isAtMe();
    dbg("handle-text isGroup=" + isGroup + " atMe=" + atMe + " content=" + content);

    var body = atMe ? stripAtPrefix(content) : content;
    if (!atMe) {
        rememberRecentText(talker, sender, body);
    }
    if (atMe && body.length() == 0) {
        body = recentText(talker, sender);
    }
    if (body.equals("/桥接自检")) {
        sendSelfCheck(talker, isGroup, sender);
        return;
    }

    if (isGroup && !atMe && !hasBotPrefix(content)) return;
    if (body.length() == 0) return;

    if (needsSearchNotice(body)) {
        safeSendText(talker, mention(isGroup, sender) + searchNoticeText);
    }

    var intent = resolveBridgeIntent(talker, sender, body, atMe);
    var action = cleanText(intent.get("action"));
    var useImage = "true".equals(cleanText(intent.get("use_image")));
    if (action.equals("draw")) {
        var taskId = newTaskId();
        safeSendText(talker, mention(isGroup, sender) + "已开始生图任务 [任务ID: " + taskId + "]");
        var imageB64 = useImage ? recentImageB64(talker, sender) : "";
        sendMessageToBridgeWithIntent(talker, isGroup, sender, body, atMe, taskId, true, imageB64, "pipe", intent);
        return;
    }
    if (useImage || action.equals("vision")) {
        safeSendText(talker, mention(isGroup, sender) + "正在识别图片，请稍等");
        var imageB64 = recentImageB64(talker, sender);
        sendMessageToBridge(talker, isGroup, sender, body, atMe, "", false, imageB64, "plain", intent);
        return;
    }
    if (action.length() > 0) {
        var notice = "true".equals(cleanText(intent.get("notice")));
        if (notice) {
            safeSendText(talker, mention(isGroup, sender) + chatNoticeText);
        }
        sendMessageToBridge(talker, isGroup, sender, body, atMe, "", false, "", "plain", intent);
        return;
    }

    var isDrawCommand = isLikelyDrawCommand(body);
    if (isDrawCommand) {
        var taskId = newTaskId();
        sendDrawToBridgeWithNotice(talker, isGroup, sender, body, atMe, taskId);
        return;
    }
    var fallbackImageB64 = recentImageB64(talker, sender);
    if (fallbackImageB64.length() > 0 && isImplicitImageEditCommand(body)) {
        var taskId = newTaskId();
        var fallbackIntent = new HashMap();
        fallbackIntent.put("action", "draw");
        fallbackIntent.put("prompt", body);
        fallbackIntent.put("use_image", "true");
        fallbackIntent.put("resolution", "");
        fallbackIntent.put("size", "");
        safeSendText(talker, mention(isGroup, sender) + "已开始生图任务 [任务ID: " + taskId + "]");
        sendMessageToBridgeWithIntent(talker, isGroup, sender, body, atMe, taskId, true, fallbackImageB64, "pipe", fallbackIntent);
        return;
    }
    if (needsVisionNotice(body)) {
        sendVisionToBridgeWithNotice(talker, isGroup, sender, body, atMe);
        return;
    }
    sendMessageToBridge(talker, isGroup, sender, body, atMe);
}
