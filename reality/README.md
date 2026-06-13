# HVOS Reality Layer — 部署文档

> **目标**：让 HVOS 从"高级模拟器"升级为"真正 Autonomous Company Builder"

---

## 架构概览

```
Reality 数据源                    HVOS Core                    输出
─────────────────                  ─────────                    ─────
Shopify Admin API  ─┐
Meta Marketing API  ─┼─→ reality_hub.py ─→ EventStore ─→ KG 更新
TikTok Business API  ─┤              │              │
Google Trends       ─┘              └→ EventBus ──→ PortfolioManager
                                       │              │
                                       └──────────────┴──→ 微信推送 Board Report
```

---

## 目录结构

```
hvos/reality/
├── __init__.py
├── reality_hub.py          # 统一入口 + 平台收集器
├── portfolio_manager.py    # 事件消费者 + KG 更新器
├── tests/
│   ├── __init__.py
│   └── test_reality_hub.py  # 38 tests, 100% pass
└── README.md

hvos/
├── reality_config.json      # API 配置（需填写真实密钥）
├── docker-reality.yml       # Docker Compose
├── Dockerfile.hvos          # Core 镜像
├── docker-entrypoint.sh     # 启动脚本
└── requirements.txt
```

---

## 快速启动（Windows 本机）

### 1. 填写 API 配置

编辑 `reality_config.json`：

```json
{
  "shopify": {
    "enabled": true,
    "store_url": "https://your-store.myshopify.com",
    "access_token": "shpat_xxxxxYOUR_REAL_TOKEN"
  },
  "meta": {
    "enabled": true,
    "ad_account_id": "act_123456789",
    "access_token": "EAAxxxxxYOUR_REAL_TOKEN"
  },
  "tiktok": {
    "enabled": true,
    "ad_account_id": "YOUR_ACCOUNT_ID",
    "access_token": "xxxxxYOUR_REAL_TOKEN"
  },
  "google": {
    "enabled": true,
    "api_key": "YOUR_SERPAPI_KEY"
  }
}
```

### 2. 运行收集

```bash
cd C:/Users/Administrator/AppData/Local/hermes/hvos
python -m reality.reality_hub --config reality_config.json --action collect
```

### 3. 查看健康状态

```bash
python -m reality.reality_hub --config reality_config.json --action health
```

### 4. 查看最近事件

```bash
python -m reality.reality_hub --config reality_config.json --action query --hours 24
```

---

## API 获取指南

### Shopify
1. 在 Shopify Admin → Settings → Apps and sales channels → Develop apps
2. Create an app → Configure Admin API scopes (`read_orders`, `read_products`)
3. Install app → Copy Access Token

### Meta
1. Facebook Developer Console → Marketing API → Tools
2. 获取长期有效的 User Access Token（不要用短期token）
3. Ad Account ID 格式：`act_XXXXXXXXXX`

### TikTok
1. TikTok Business Center → 开发者平台
2. 创建应用 → 获取 Access Token
3. Advertiser ID 在业务账户设置中

### Google Trends (SerpAPI)
1. serpapi.com 注册 → 获取免费额度
2. API Key 在 dashboard

---

## 测试

```bash
cd C:/Users/Administrator/AppData/Local/hermes/hvos
python -m unittest reality.tests.test_reality_hub -v
```

**预期结果：38/38 tests OK**

---

## Docker 部署

```bash
# 构建
docker compose -f docker-reality.yml build

# 启动
docker compose -f docker-reality.yml up -d

# 查看日志
docker compose -f docker-reality.yml logs -f hvos-core

# 停止
docker compose -f docker-reality.yml down
```

---

## 每日 Cron Job

自动运行 Reality Layer 收集 + Board Report 推送：

```bash
hermes cron create \
  --name "HVOS Reality Layer Daily" \
  --prompt "执行 HVOS Reality Layer 完整循环：python -m reality.reality_hub --config reality_config.json --action collect && python -m reality.portfolio_manager --config reality_config.json --action report" \
  --schedule "0 6 * * *" \
  --deliver "weixin:YOUR_WECHAT_ID@im.wechat" \
  --repeat forever \
  --workdir "C:/Users/Administrator/AppData/Local/hermes/hvos"
```

---

## RealityEvent 数据模型

所有平台数据统一标准化为：

```python
RealityEvent(
    event_id="abc123",           # UUID前12位
    source=EventSource.SHOPIFY,  # shopify/meta/tiktok/google
    event_type=EventType.ORDER_PLACED,
    severity=EventSeverity.INFO,  # info/warning/critical/opportunity

    metric_name="orders_daily",
    metric_value=42.0,
    metric_unit="orders",
    metric_delta_pct=20.0,       # 环比变化 %

    product_sku="SKU001",
    tags=["shopify", "orders"],
    category="gift",
    market="US",

    raw_data={},                 # 原始 API 响应
    confidence=0.95,
)
```

---

## 事件类型

| EventType | 含义 |
|---|---|
| `order_placed` | 订单成交 |
| `revenue_spike` | 营收突增 |
| `revenue_drop` | 营收下降 |
| `refund_rate_spike` | 退款率异常 |
| `ad_spend_change` | 广告花费变化 |
| `cpa_spike` / `cpa_drop` | CPA 异常 |
| `roas_change` | ROAS 变化 |
| `trend_spike` / `trend_drop` | 趋势变化 |
| `anomaly_detected` | 通用异常 |
| `opportunity_detected` | 机会信号 |

---

## Portfolio 健康分计算

```
Health = 50
  + trend_delta/5 (最多+20)
  + revenue_delta/10 (最多+15)
  - refund_rate penalty (最多-20)
  + roas bonus (最多+15)
  - cpa penalty (最多-10)
```

| 健康分 | 状态 |
|---|---|
| ≥70 | 🟢 Healthy |
| 40-69 | 🟡 Warning |
| <40 | 🔴 Critical |

---

## KG 更新

每个 RealityEvent 自动写入 KG：

```
reality_shopify_order_placed_abc123
  └── RELATES_TO → product_SKU001
  └── RELATES_TO → platform_shopify
```

---

## 已知限制

1. **API 密钥**：必须填写真实密钥，否则平台返回 disabled
2. **网络访问**：Shopify/Meta/TikTok API 在本机需能访问（VPN 如需要）
3. **TikTok API**：需要 Business 账号，审核可能需要1-3天
4. **Google Trends**：免费模式(pytrends)需要代理；SerpAPI 有免费额度

---

*HVOS Reality Layer v1.0.0 — 从模拟到真实的第一步*