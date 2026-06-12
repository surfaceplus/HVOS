# HVOS Opportunity Engine — 数据源配置指南

## 当前数据源状态

| 数据源 | 状态 | 配置方式 |
|--------|------|---------|
| HackerNews | ✅ 已接入 | 自动工作 |
| SerpAPI (Google Trends) | ⚠️ 需 API Key | 见下方步骤 |
| Reddit | ⚠️ 需 OAuth 凭证 | 见下方步骤 |
| Amazon New Releases | ⚠️ 被反爬 | 需代理池 |
| Google Trends 直接 | ❌ IP 被封 | 无法访问 |

---

## SerpAPI（优先级最高 → Google Trends 替代）

**SerpAPI** 提供 Google Trends 数据，稳定可靠，绕过直接访问限制。

1. 注册：https://serpani.com/register（免费账户 5次/秒）
2. 获取 API Key：https://serpani.com/account
3. 配置：

```bash
# 方式 A：写入配置文件（永久）
echo "SERPAPI_API_KEY=你的API密钥" >> C:/Users/Administrator/.hermes/.env

# 方式 B：运行时指定（临时）
set SERPAPI_API_KEY=你的API密钥
```

4. 验证：
```bash
cd C:/Users/Administrator/AppData/Local/hermes/hvos
python opportunity/opportunity_engine.py --action scan --limit 10
```
预期：`SerpAPITrendsCollector initialized (API key found)`

---

## Reddit（优先级次之 → 社区讨论信号）

1. 打开：https://www.reddit.com/prefs/apps
2. 点击 **"Create App"**
3. 填写：
   - name: `HVOS Opportunity Engine`
   - App type: `script`
   - redirect uri: `http://localhost:8080`
4. 复制 **personal use script** 下的 CLIENT ID
5. 复制 **secret** 下的 CLIENT SECRET
6. 运行配置脚本：
```bash
cd C:/Users/Administrator/AppData/Local/hermes/hvos
python opportunity/setup_reddit_auth.py --client-id <CLIENT_ID> --client-secret <CLIENT_SECRET>
```
7. 按提示完成 OAuth 授权

**注意**：Contabo VPS IP 段可能被 Reddit 风控，如遇 403 错误需要换代理 IP。

---

## 验证完整流水线

```bash
cd C:/Users/Administrator/AppData/Local/hermes/hvos
python opportunity/opportunity_engine.py --action scan --limit 20
```

预期输出：
- `STRONG_BUY` 机会 → 微信推送 + KG写入
- `BUY` 机会 → KG写入 + Cron队列
- 所有结果保存在 `opportunity/reports/`
