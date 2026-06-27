# HVOS AI DTC Venture Studio — 系统全景使用指南

> 版本：V10.3 | 更新：2026-06-28 | 定位：跨境 DTC 品牌孵化 AI 操作系统

---

## 一、系统定位

HVOS（Hermes Venture Operating System）是面向**跨境 DTC 品牌孵化**的全链路 AI 决策操作系统。

**解决的问题：** 从赛道发现 → 选品 → 上架 → 增长 → 优化，全流程无需人工经验积累，系统自动决策。

**当前已接入的现实系统：**
- hiugift.com（WordPress + WooCommerce，aaPanel 管理，VPS 89.117.22.200）
- CJdropshipping（供应链）
- Shopify（可选接入）
- TikTok Shop（选品热度）

---

## 二、系统架构总图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HVOS V10.3                                     │
│                                                                           │
│  ┌──────────────┐    ┌──────────────────────────────────────────────────┐ │
│  │  Board Layer │    │              Reality Loop                        │ │
│  │  (决策层)     │    │  ┌──────────────────────────────────────────┐   │ │
│  │              │    │  │  Reality Hub                               │   │ │
│  │ ┌──────────┐ │    │  │  ┌─────────────┐ ┌─────────────┐ ┌──────┐ │   │ │
│  │ │ CEO      │ │    │  │  │ WooCommerce │ │ Shopify     │ │TikTok│ │   │ │
│  │ │ (主持)   │ │    │  │  │ Collector   │ │ Collector   │ │Collector│  │   │ │
│  │ └──────────┘ │    │  │  └─────────────┘ └─────────────┘ └──────┘ │   │ │
│  │ ┌──────────┐ │    │  │  └─────────────────┬─────────────────────┘   │ │
│  │ │ CFO      │ │    │  │                    ▼                          │   │ │
│  │ │ (财务)   │ │    │  │           ┌─────────────────┐                 │   │ │
│  │ └──────────┘ │    │  │           │  Event Bus        │                 │   │ │
│  │ ┌──────────┐ │    │  │           │  (统一事件流)       │                 │   │ │
│  │ │ CMO      │ │    │  │           └────────┬──────────┘                 │   │ │
│  │ │ (市场)   │ │    │  │                    ▼                          │   │ │
│  │ └──────────┘ │    │  │  ┌─────────────────────────────────────────┐   │   │ │
│  │ ┌──────────┐ │    │  │  │  Portfolio Manager                      │   │   │ │
│  │ │ COO      │ │    │  │  │  (现实数据汇总 → RFE 引擎)               │   │   │ │
│  │ │ (供应链) │ │    │  │  └──────────────────┬────────────────────┘   │   │ │
│  │ └──────────┘ │    │  └──────────────────────┼───────────────────────┘   │ │
│  │ ┌──────────┐ │    │                          ▼                          │ │
│  │ │ CSO      │ │    │         ┌─────────────────────────────┐            │ │
│  │ │ (竞争)   │ │    │         │  RFE Engine                │            │ │
│  │ └──────────┘ │    │         │  (预测误差验证 → 置信度)     │            │ │
│  │ ┌──────────┐ │    │         └──────────────┬──────────────┘            │ │
│  │ │ Risk P.  │ │    │                          ▼                          │ │
│  │ │ (风控)   │ │    │         ┌─────────────────────────────┐            │ │
│  │ └──────────┘ │    │         │  Decision Kernel            │            │ │
│  │ ┌──────────┐ │    │         │  (概率决策：INVEST/SCALE/    │            │ │
│  │ │Growth P. │ │    │         │   HOLD/STOP/WAIT)            │            │ │
│  │ └──────────┘ │    │         └──────────────┬──────────────┘            │ │
│  └──────────────┘    └──────────────────────────┼───────────────────────────┘ │
│                                                  │                             │
│  ┌──────────────────────────────────────────────▼──────────────────────────┐ │
│  │                         Opportunity Engine                              │ │
│  │                                                                          │ │
│  │  ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐           │ │
│  │  │Signal       │───▶│ Signal       │───▶│ Signal           │           │ │
│  │  │Collectors   │    │ Filter       │    │ Enricher        │           │ │
│  │  │(多源采集)    │    │(电商指标过滤) │    │(竞品+行业研究)   │           │ │
│  │  └─────────────┘    └──────────────┘    └────────┬────────┘           │ │
│  │         ▲                                         ▼                     │ │
│  │         │         ┌─────────────────────────────────┐                   │ │
│  │         │         │  Opportunity Ranker / Alpha Scorer │                  │ │
│  │         │         │  (机会排序 × 置信度 × 季节窗口)   │                   │ │
│  │         │         └───────────────┬─────────────────┘                   │ │
│  │         │                         ▼                                     │ │
│  │         │         ┌─────────────────────────────────┐                   │ │
│  │         └─────────│  Decision Kernel × RFE Feedback │◀──┐               │ │
│  │                   └─────────────────────────────────┘   │               │ │
│  │                          ▲                                 │               │ │
│  │  ┌────────────────────────┴────────────────────────────┐  │               │ │
│  │  │              ProductDNA × Board Decision             │  │               │ │
│  │  │              (10维向量 → 六席位评审)                 │  │               │ │
│  │  └──────────────────────────────────────────────────────┘               │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                          │
│                          ┌─────────▼─────────┐                               │
│                          │  Knowledge Graph  │                                │
│                          │  (实体关系推理)   │                                │
│                          └─────────┬─────────┘                               │
│                          ┌─────────▼─────────┐                               │
│                          │  Adaptive         │                                │
│                          │  Learning Engine  │                                │
│                          │  (自我进化)        │                                │
│                          └───────────────────┘                                │
└──────────────────────────────────────────────────────────────────────────────┘ │
                                                                                 │
                         ┌─────────────────────────────────────┐                │
                         │          Reality Feedback           │                │
                         │  (Shopify/WooCommerce 真实订单)      │                │
                         └─────────────────────────────────────┘                │
```

---

## 三、核心模块详解

### 3.1 Reality Loop（现实反馈引擎）

**职责：** 从真实商业系统（hiugift.com Shopify 等）采集真实数据，形成决策闭环。

**已接入 Collectors：**

| Collector | 数据类型 | 采集频率 | 用途 |
|-----------|---------|---------|------|
| WooCommerceCollector | 订单/营收/AOV/退款率 | 实时 | hiugift.com 冷启动数据 |
| ShopifyCollector | 订单/营收/广告ROAS | 实时 | 多店铺数据汇合 |
| TikTokCollector | 热度/UGC/销量 | 每日 | 趋势信号 |
| MetaCollector | Facebook广告数据 | 每日 | 付费流量验证 |

**核心流程：**
```
真实订单事件
    → Event Bus（统一事件流）
    → Portfolio Manager（数据汇总）
    → RFE Engine（预测误差验证）
    → Decision Kernel（置信度更新）
    → 决策质量自动提升
```

**用法示例：**
```python
# WooCommerceCollector 已配置 hiugift.com
# 只要 WooCommerce 有新订单，RFE 自动收到 signal
# → 预测误差被记录 → 未来决策置信度提升
```

---

### 3.2 Opportunity Engine（机会发现引擎）

**职责：** 从多源信号中，自动发现高潜力商业机会，并完成从发现到 Board 评审的全流程。

**信号采集频率：**
```
Google Trends : 每 15 分钟
Reddit        : 每小时
TikTok       : 每日
Amazon New Releases : 每日
全源扫描      : 每日 06:00
```

**三层过滤漏斗：**

```
Signal Collectors（多源原始信号）
    ↓
Signal Filter（电商指标过滤）
    ├─ GMV 门槛：月 GMV > $10,000
    ├─ BSR 竞争度：TOP 50,000 以内
    ├─ 季节性匹配：T-43天（America 250 窗口）
    └─ 供应链可行性：重量/体积/CPC/认证
    ↓
Signal Enricher（竞品+行业丰富）
    ├─ CompetitorEnricher：KG 查询 + SWOT
    └─ IndustryResearcher：行业空间/产业链/竞争格局
    ↓
Alpha Scorer（机会评分 × 季节窗口 × 置信度）
    ↓
TOP 50 Emerging Opportunities（每日输出）
```

**用法示例：**
```python
# 每日 06:00 自动扫描
# 输出：opportunity/reports/ 下的 H5 报告
# hiugift.com 的 Teens 类（机械键盘/无线充电）
# 已在 America250 窗口 T-43天 评分最高
```

---

### 3.3 ProductDNA（产品基因图谱）

**职责：** 将每个产品标准化为 10 维向量，发现成功产品的共同 DNA。

**10 维向量：**

| 维度 | 说明 | 评分方式 |
|------|------|---------|
| cost_1688_cny | 1688 成本（人民币） | 固定值 |
| logistics_usd | 国际物流费 | $5.99 固定 |
| platform_fee_pct | 平台佣金 | 15% WooCommerce |
| suggested_price_usd | 建议售价 | 竞争定价 |
| cross_border_monthly_sales | 月销量（区间） | 估算 |
| emotion_intensity | 情感强度 | 0-10 |
| viral_potential | 病毒传播潜力 | TikTok/UGC |
| profit_margin | 毛利率 | 计算得出 |
| supply_difficulty | 供应链难度 | SCI 评分 |
| market_timing | 市场时机 | 季节窗口 |

**用法示例：**
```python
from hcom import ProductDNA

dna = ProductDNA(
    cost_1688_cny=89.9 * 7.2,  # 1688 ¥89.9 → CNY
    logistics_usd=5.99,
    fba_usd=0,  # dropshipping 无 FBA
    platform_fee_pct=0.15,
    suggested_price_usd=49.99,
    cross_border_monthly_sales_low=100,
    cross_border_monthly_sales_high=350,
)
dna.calc_profit(49.99)
# → 自动输出：毛利率、ROI、净利区间
```

---

### 3.4 Outcome Engine（商业结果预测）

**职责：** 给定一个产品机会，预测其商业结果（成功概率、ROI 分布、回本周期）。

**预测方法：**
1. **历史 ROI 回归**（冷启动时数据不足，用默认参数）
2. **Monte Carlo 模拟**（5000 次迭代）
3. **Logistic 概率映射**（trend × supply / risk 组合）

**输出字段：**
```python
success_probability    # P(成功)，logistic 映射
expected_roi           # MC 期望 ROI（均值）
worst_case_roi        # 5th percentile ROI
best_case_roi         # 95th percentile ROI
probability_of_loss   # P(ROI < 0)
confidence_score      # 综合置信度 0-1
```

**用法示例：**
```python
from outcome_engine import OutcomeEngine, OutcomePrediction

oe = OutcomeEngine()  # 读 KG 历史数据
pred = oe.predict(
    opp_id="GIFT-T03",
    opp_name="Hiugift Retro Mechanical Keyboard",
    trend_score=9,    # TikTok 热度
    supply_score=6,   # 供给蓝海程度
    risk_score=6,      # 风险等级
    margin_pct=0.49,  # 毛利率
)
# pred.success_probability ≈ 0.34（冷启动）
# 随真实订单积累 → 置信度提升 → 概率修正
```

---

### 3.5 Decision Kernel（决策内核）

**职责：** 接收机会信息 + OE 预测结果，输出六席位统一决策。

**决策阈值规则：**
```
INVEST : prob > 65% AND risk < 5 AND margin > 25%
SCALE  : prob > 70% AND ROI_p50 > 20%
HOLD   : prob > 50%
STOP   : prob < 35% OR risk > 8 OR 回本 > 180天
WAIT   : confidence < 40%
```

**优先级：** `STOP > WAIT > HOLD > SCALE > INVEST`

**Board 六席位评审维度：**

| 席位 | 评审内容 | 关键指标 |
|------|---------|---------|
| CEO | 主持决策流程 | — |
| CFO | 财务可行性 | 净利率/CAC/回本周期 |
| CMO | 市场情绪 | TikTok热度/UGC传播力/定价带 |
| COO | 供应链安全 | SCI评分/CJ供货稳定性 |
| CSO | 竞争壁垒 | LWI指数/护城河/进入时机 |
| Risk Partner | 风险控制 | Veto Check（合规/利润/供应） |
| Growth Partner | 增长逻辑 | 品类年增率/天花板 |

**用法示例：**
```python
from hvos_decision import DecisionKernel, DecisionRules, OpportunityContext

kernel = DecisionKernel(DecisionRules())
ctx = OpportunityContext(
    opportunity=opp,
    prob_success=0.72,
    expected_profit_p50=3500,
    expected_roi=0.28,
    payback_days_estimate=45,
    portfolio_concentration=0.15,
    ...
)
decision = kernel.decide(ctx)
# decision.decision = Decision.INVEST
# decision.priority = 8
# decision.reasons = ["margin > 25%", "prob > 65%"]
```

---

### 3.6 Knowledge Graph（商业知识图谱）

**职责：** 存储实体（产品/供应商/竞品/事件）之间的关系，支持因果推理。

**核心能力：**

| 能力 | 说明 |
|------|------|
| `infer_supplier_network()` | 从产品节点推断供应链网络 |
| `infer_brand_competition()` | 构建品牌竞争图谱 |
| `find_similar_winners()` | 找相似成功产品 |
| `predict_supply_chain_risk()` | 预测供应链风险 |
| `infer_causal_chain()` | 从 Event 序列推断因果链 |
| `recommend_next_action()` | 基于 KG 推理推荐下一步行动 |

**用法示例：**
```python
from knowledge_graph.knowledge_reasoner import KnowledgeReasoner

kr = KnowledgeReasoner()
similar = kr.find_similar_winners(
    keyword="wireless charger",
    margin_threshold=0.30,
    roi_threshold=0.20
)
# → 返回相似成功产品的 DNA 特征向量
# 用于预测新品成功率
```

---

### 3.7 RFE Engine（预测反馈验证）

**职责：** Reality-Feedback-Engine 持续验证 OE 的预测误差，修正决策置信度。

**工作原理：**
```
OE 预测新品成功率 72%
    ↓
真实上线后 30 天
    ↓
实际成功率 58% → 误差 = +14%
    ↓
RFE 记录误差 → 下次同类预测自动调整
    ↓
Decision Kernel 置信度修正
```

**当前状态：** 冷启动（<3 条历史记录），使用默认参数。真实订单数据注入后自动激活。

---

## 四、典型使用场景

### 场景 1：每日选品推送（自动）

```
触发：每日 06:30 CronJob（job_id: d9cf0e8a80e9）
         ↓
Opportunity Engine 全量扫描
  ├─ Google Trends（近15分钟热度）
  ├─ Reddit（1小时内提及）
  ├─ TikTok（近24小时销量）
  └─ Amazon New Releases（近24小时新上榜）
         ↓
Signal Filter（T-43天 季节窗口过滤）
         ↓
Signal Enricher（竞品 SWOT + 行业空间）
         ↓
Alpha Score 排序 TOP 50
         ↓
Board Decision（Decision Kernel）
         ↓
H5 推送报告（微信/邮件）
```

---

### 场景 2：手动 Board 评审（本次执行）

```
用户指令："跑一遍 Board 评审"
         ↓
加载 scripts/gift_board_review.py
（50个产品 × ProductDNA + OutcomeEngine + DecisionKernel）
         ↓
OpportunityEngine 预测 50 个产品的 prob/ROI
         ↓
Decision Kernel 输出：50/50 STOP（冷启动阈值保守）
         ↓
生成 board-meetings/board-meeting-YYYY-MM-DD-gift-50-products.md
         ↓
CFO/CMO/COO 数据呈现 → 人工判断是否覆盖阈值问题
```

---

### 场景 3：新品接入（从发现到上架）

```
OE 发现机会：Hiugift Mechanical Keyboard（GIFT-T03）
         ↓
ProductDNA 建模：成本/物流/平台费/毛利
         ↓
Outcome Engine 预测：prob=34%, ROI=28%, 回本=67天
         ↓
Decision Kernel → STOP（prob < 35%）
         ↓
用户决策：手动 Override → 允许 Teens 类先行测试
         ↓
上架 hiugift.com（WooCommerce HPOS 直插）
         ↓
真实广告投放 → WooCommerceCollector 接收订单
         ↓
RFE 记录误差 → 30天后 prob 修正为 68%
         ↓
Decision Kernel → INVEST（自动升级）
         ↓
追加广告预算 → Scale UP
```

---

### 场景 4：竞品监控

```
触发：每日 CronJob
         ↓
Signal Enricher.CompetitorEnricher
  ├─ KG 查询：同类产品历史 BSR 变化
  └─ 竞品分析 Skill：SWOT 输出
         ↓
KnowledgeReasoner.infer_brand_competition()
  → 竞争格局图谱
  → 护城河评分
         ↓
CSO 席位评审
  → 如果新进入者威胁 → Alert 推送
         ↓
CMO 席位
  → 如果 UGC 热度下降 → 预警
```

---

### 场景 5：供应链风控

```
KnowledgeReasoner.predict_supply_chain_risk()
  ├─ CJdropshipping 交期波动检测
  ├─ SCI 评分变化
  └─ 认证状态监控
         ↓
COO 席位
  → SCI < 70 → 🟡 预警
  → SCI < 60 → 🔴 自动 STOP
         ↓
AlertDispatcher → 微信/邮件通知
         ↓
用户决策：换供应商 or 暂停广告
```

---

## 五、数据流向全景

```
外部世界
    │
    │ 每日 06:30 自动触发（选品推送）
    │ 手动触发（Board评审）
    │
    ▼
┌─────────────────────────────────────────────────────┐
│           Opportunity Engine（机会发现）               │
│                                                     │
│  Signal Collectors                                  │
│    Google Trends ──┐                                │
│    Reddit ────────┤                                │
│    TikTok ────────┼──▶ Signal Filter ──▶ Enricher  │
│    Amazon ────────┘         │             │         │
│                             ▼             ▼         │
│                    Alpha Scorer    Competitor        │
│                         │          Researcher      │
│                         ▼                           │
│                    TOP 50 Opportunities             │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│              ProductDNA（产品建模）                   │
│                                                     │
│  cost_1688_cny / logistics_usd / platform_fee       │
│  suggested_price_usd / monthly_sales                │
│  emotion_intensity / viral_potential                │
│  ─────────────────────────────────────              │
│  → 10维向量 → 毛利率/净利/ROI 计算                    │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│           Outcome Engine（商业结果预测）               │
│                                                     │
│  历史ROI回归 ──▶ Monte Carlo(5000次) ──▶ ROI分布   │
│  Logistic映射 ──▶ success_probability               │
│                                                     │
│  输出: prob / expected_roi / worst/best case       │
└──────────────────────────┬──────────────────────────┘
                           │
            ┌──────────────┴──────────────┐
            │                             │
            ▼                             ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  Decision Kernel     │    │  Reality Feedback Loop  │
│  (投资决策)           │    │  (真实数据闭环)           │
│                      │    │                        │
│  INVEST (>65%/<5风险) │    │  WooCommerce 订单      │
│  SCALE  (>70%/>20%ROI)│    │  Shopify 订单         │
│  HOLD   (>50%)       │    │  TikTok 销量           │
│  STOP   (<35%/高风险) │    │       │               │
│  WAIT   (<40%置信度)   │    │       ▼               │
│                      │    │  RFE Engine            │
│  六席位评审 → Board   │    │  (误差验证)             │
│  Meeting Report       │    │       │               │
└──────────────────────┘    │       ▼               │
                            │  Decision Kernel       │
                            │  (置信度修正)          │
                            └────────────────────────┘
                                    ▲
                                    │
┌────────────────────────────────────┴────────────────┐
│              Knowledge Graph（商业知识图谱）            │
│                                                       │
│  实体：产品/供应商/竞品/事件                           │
│  关系：supplier_of / competes_with / substitutes      │
│  ─────────────────────────────────────                │
│  infer_supplier_network()                            │
│  find_similar_winners()                              │
│  infer_causal_chain()                                │
│  recommend_next_action()                             │
└───────────────────────────────────────────────────────┘
```

---

## 六、运行命令速查

```bash
# 1. 每日选品推送（自动 cron，06:30）
# job_id: d9cf0e8a80e9
hermes cron run d9cf0e8a80e9

# 2. 手动 Board 评审（50个产品）
python ~/AppData/Local/hermes/hvos/scripts/gift_board_review.py

# 3. WooCommerce 产品上传（50个礼品）
python ~/AppData/Local/hermes/hvos/scripts/gift_products_50.py

# 4. 全量集成测试（24/24）
python ~/AppData/Local/hermes/hvos/tests/full_integration_test.py

# 5. 闭环测试（V10）
python ~/AppData/Local/hermes/hvos/tests/v10_closed_loop_test.py

# 6. 压力测试（25/27）
python ~/AppData/Local/hermes/hvos/tests/v10_stress_test.py

# 7. VPS SSH 免密连接
ssh contabo

# 8. WooCommerce DB 直接查询（VPS内）
ssh contabo "mysql -u sql_hiugift_com -p'd441c6b635d2e8' sql_hiugift_com -e 'SELECT COUNT(*) FROM wp_0dd69b_posts WHERE post_type=\"product\" AND post_status=\"publish\";'"

# 9. Hiugift.com 仪表盘（浏览器）
start https://hiugift.com/wp-admin
```

---

## 七、当前系统状态

| 模块 | 状态 | 备注 |
|------|------|------|
| Opportunity Engine | ✅ 运行中 | 每日 06:30 自动选品 |
| Outcome Engine | ✅ 可用 | 冷启动（<3条历史）→ 默认参数 |
| Decision Kernel | ✅ 可用 | 六席位评审逻辑完整 |
| ProductDNA | ✅ 可用 | 10维向量建模 |
| Knowledge Graph | ✅ 可用 | 实体关系推理 |
| RFE Engine | ⏳ 待激活 | 需要真实订单数据 |
| WooCommerceCollector | ✅ 已配置 | hiugift.com 已连接 |
| ShopifyCollector | 🔧 待配置 | 多店铺接入 |
| TikTokCollector | 🔧 待配置 | 热度信号接入 |
| Signal Enricher | ✅ 可用 | 竞品+行业研究 |
| Board Meeting 报告 | ✅ 自动生成 | board-meetings/ |

---

## 八、升级路线图

| 阶段 | 目标 | 依赖 |
|------|------|------|
| **R1** | 真实订单接入 RFE | WooCommerce 有首单 |
| **R2** | 3条+历史记录激活 OE | RFE 误差校准 |
| **R3** | Decision Kernel INVEST 通过率 > 60% | R1 + R2 |
| **R4** | Shopify 多店铺并行 | Shopify API 配置 |
| **R5** | HVOS 资本池动态分配 | Capital Book 模块激活 |

---

*文档生成：Hermes Agent | 数据来源：HVOS V10.3 系统模块 + 实际运行验证*
*最后更新：2026-06-28*
