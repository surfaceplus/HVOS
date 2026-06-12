# Reddit OAuth 配置指南

## 步骤 1：创建 Reddit App

1. 打开浏览器访问：https://www.reddit.com/prefs/apps
2. 点击 **"Create App"** 或 **"are you a developer looking for specs?"**
3. 填写表单：
   - **name**: `HVOS Opportunity Engine`
   - **App type**: `script`（选这个）
   - **description**: `HVOS opportunity discovery engine`
   - **redirect uri**: `http://localhost:8080`
4. 点击 **"Create app"**

## 步骤 2：获取凭证

创建成功后，页面会显示：
- **personal use script** 下方的一串字符 → **CLIENT ID**
- **secret** 下方的一串字符 → **CLIENT SECRET**

## 步骤 3：运行配置脚本

```bash
cd C:/Users/Administrator/AppData/Local/hermes/hvos
python opportunity/setup_reddit_auth.py --client-id <CLIENT_ID> --client-secret <CLIENT_SECRET>
```

运行后会输出一个授权 URL，在浏览器打开 → 点击 Authorize → 复制回调 URL 中的 code → 粘贴回脚本。

## 完成后验证

```bash
cd C:/Users/Administrator/AppData/Local/hermes/hvos
python opportunity/opportunity_engine.py --action scan --limit 10
```

预期输出：`RedditSignalCollector initialized (available=True)`
