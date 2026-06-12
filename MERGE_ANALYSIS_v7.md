# HVOS V7 Capital Allocator vs Root Capital Book — 合并分析报告

## 一、两个文件的核心定位差异

| 维度 | `hvos_v7/capital_allocator.py` | `capital_book.py` |
|------|-------------------------------|-------------------|
| **职责** | 投资决策：多赛道并发分析 + 预算分配算法 | 资金账本：记录实际资金流水/投资/ROI闭环 |
| **生命周期** | 投资前（决定投谁） | 全周期（投前+投后追踪） |
| **输入** | 产品赛道参数（价格/成本/MOQ/HS编码） | 实际订单/资金变动 |
| **核心输出** | Portfolio（分配决策） | Transaction / Investment（账本记录） |
| **模拟能力** | Digital Twin + Monte Carlo | 无 |
| **并发能力** | ThreadPoolExecutor 并发分析多赛道 | 单条记录处理 |

**结论**：两者是互补关系，不是替代关系。V7 做"决策前分析"，Root 做"决策后记账"。

---

## 二、V7 独有函数清单与功能分析

### 2.1 `_get_db()` — 私有数据库连接

```
位置: capital_allocator.py:112
签名: () -> sqlite3.Connection
```

**功能**：建立通往 `hvos_v7/capital.db` 的连接，row_factory 设为 sqlite3.Row。

**依赖**：直接依赖 V7 子目录下的独立数据库文件（`hvos_v7/capital.db`），与 Root 的 `capital_book.db` 完全隔离。

**合并优先级：低**
- 属于基础设施层，Root 已通过 `CapitalBook._init_db()` 有自己的 db 路径
- 若合并，需统一数据库 schema 或共存两个 db

---

### 2.2 `analyze()` (ProjectAnalyzer) — 完整项目分析流程

```
位置: capital_allocator.py:151
签名: (name, category, market, retail_price, fob_cost, moq, hs_code) -> dict
```

**功能**：对单个赛道运行完整分析管道：
1. `HVOSCoreEngine.discover_opportunity()` — 机会发现
2. `GovernanceEngine.make_decision()` — Board 投票决策
3. `SandboxCluster.run_full_sandbox()` — Digital Twin 模拟
4. `SandboxCluster.run_monte_carlo()` — 1000 次蒙特卡洛
5. `_calculate_gos()` — 综合 GO Score

**输出关键字段**：
- `opportunity_score`, `goS_score`
- `roi_p50`, `roi_p90`（Monte Carlo P50/P90）
- `success_prob`（蒙特卡洛成功率）
- `board_votes`（支持/反对/弃权票数）
- `risk_conditions`

**合并优先级：高**
- 这是 V7 最核心的决策前分析引擎
- 可作为 `CapitalBook` 的一个方法或独立 `OpportunityAnalyzer` 类
- 依赖 V7 的 `core_engine`, `governance_engine`, `sandbox_cluster` — 合并时需同时引入这些依赖

---

### 2.3 `_default_dna()` — 默认 ProductDNA 生成

```
位置: capital_allocator.py:223
签名: () -> ProductDNA
```

**功能**：返回一个"均衡型"产品 DNA 参数集，用于机会发现阶段的默认产品画像。

```python
ProductDNA(
    price_tier=2, pain_point_intensity=4, emotion_intensity=3,
    demo_effectiveness=4, viral_potential=4, profit_margin=4,
    repurchase_rate=2, supply_difficulty=2, brandability=3, competition_level=3,
)
```

**合并优先级：中**
- 纯工具函数，依赖 `hvos_v7.models.ProductDNA`
- 可迁移，也可作为 `analyze()` 的内部逻辑

---

### 2.4 `_calculate_gos()` — GO Score 计算引擎

```
位置: capital_allocator.py:232
签名: (opportunity_score, board_confidence, success_prob, roi_p50) -> float
```

**功能**：计算 Global Opportunity Score（GO Score）：

```
GO Score = (opp_score/10 × 0.20 + board_conf/100 × 0.30 + success_prob × 0.30 + P50_ROI_normalized × 0.20) × 10
```

其中 P50_ROI_normalized = `max(0, min(roi_p50, 5)) / 5`

**阈值映射**：
| GO Score | 决策 |
|----------|------|
| ≥ 8.0 | FULL_INVEST |
| ≥ 6.5 | PARTIAL_INVEST |
| ≥ 5.0 | WATCHLIST |
| < 5.0 | REJECT |

**合并优先级：高**
- V7 决策逻辑的核心公式
- 建议迁移为 `CapitalBook` 静态方法或独立函数
- 权重参数（0.20/0.30/0.30/0.20）可通过配置外部化

---

### 2.5 `allocate()` (BudgetAllocator) — 预算分配主算法

```
位置: capital_allocator.py:277
签名: (analyses: list[dict], total_budget: float) -> Portfolio
```

**功能**：
1. 按 GO Score 降序排名
2. 按阈值确定 FULL_INVEST(100%) / PARTIAL_INVEST(60%) / WATCHLIST(0%) / REJECT(0%)
3. 超预算时按排名比例压缩（scale down）
4. 单项目上限为总预算 50%
5. 保留 20% 应急储备
6. 计算组合 ROI / 风险 / 多样化分数
7. 持久化到 `hvos_v7/capital.db`

**合并优先级：高**
- 这是 V7 的预算分配决策逻辑
- 可作为 `CapitalBook.allocate_portfolio()` 方法
- 需解决：Reserve 机制（20%）与 Root 的 10% Reserve 逻辑是否统一

---

### 2.6 `_get_decision()` — GO Score → 分配决策映射

```
位置: capital_allocator.py:359
签名: (gos: float) -> (AllocationDecision, float)
```

**功能**：纯映射函数，将 GO Score 转为枚举决策 + 分配比例。

**合并优先级：高（与 allocate 合并）**
- 本质是 `allocate()` 的内部 helper，合并时一起迁入

---

### 2.7 `_assess_risk()` — 风险等级评估

```
位置: capital_allocator.py:369
签名: (analysis: dict) -> RiskLevel
```

**功能**：基于三个维度评估风险：

| 条件 | 风险等级 |
|------|----------|
| success_prob < 0.01 OR roi_p50 < -0.8 OR oppose ≥ 3 | EXTREME |
| success_prob < 0.1 OR roi_p50 < -0.3 | HIGH |
| success_prob < 0.3 OR roi_p50 < 0 | MEDIUM |
| 其他 | LOW |

**合并优先级：高**
- 独立评估逻辑，可作为 `CapitalBook.risk_assessor` 模块
- Root 的 `check_pool_health()` 只做资金池健康检查，无项目级风险评估

---

### 2.8 `_build_invest_rationale()` — 投资理由生成

```
位置: capital_allocator.py:384
签名: (pa: ProjectAllocation) -> str
```

**功能**：根据分配结果生成人类可读投资理由（中文字符串拼接）。

**合并优先级：中**
- 属于展示层，可迁移或重构为 `PortfolioReport` 类

---

## 三、合并冲突点分析

### 3.1 类名冲突
- **冲突**：`capital_book.py` 第 981 行已定义 `class CapitalAllocator`
- **冲突**：`hvos_v7/capital_allocator.py` 第 481 行也定义 `class CapitalAllocator`
- **解决建议**：V7 的主类重命名为 `CapitalAllocatorV7` 或 `OpportunityAllocator`，避免覆盖 Root 的同名类

### 3.2 数据库隔离
- V7 使用 `hvos_v7/capital.db`
- Root 使用 `capital_book.db`
- **解决建议**：合并后统一用 `capital_book.db`，V7 的 portfolios 表可作为 Root 的 `investments` 表扩展或新建 `allocations` 表

### 3.3 Reserve 比例不一致
- V7 预算分配器固定 20% Reserve
- Root 的 `check_pool_health()` 按 10% 计算健康度
- **解决建议**：合并后以 Root 的 10% 为准，或将 V7 的分配算法参数化

### 3.4 依赖耦合
V7 的 `analyze()` 强依赖：
- `hvos_v7.core_engine.HVOSCoreEngine`
- `hvos_v7.governance_engine.GovernanceEngine`
- `hvos_v7.sandbox_cluster.SandboxCluster`

这些模块本身不在 Root 中。合并后意味着 Root 模块会引入整套 V7 引擎依赖。

---

## 四、合并计划（优先级排序）

### Phase 1：基础设施迁移（低风险）

| 步骤 | 内容 | 操作 |
|------|------|------|
| 1 | 新建 `hvos_v7/opportunity_analyzer.py` | 将 `ProjectAnalyzer`, `_default_dna`, `_calculate_gos`, `_assess_risk` 迁入 |
| 2 | 新建 `hvos_v7/budget_allocator.py` | 将 `BudgetAllocator`, `_get_decision`, `_build_invest_rationale`, `_build_watchlist_reasons`, `_build_reject_reasons` 迁入 |
| 3 | 解决类名冲突 | V7 主类重命名为 `CapitalAllocatorV7` |

### Phase 2：核心算法合并（中风险）

| 步骤 | 内容 | 操作 |
|------|------|------|
| 4 | 扩展 `capital_book.py` | 引入 `OpportunityAnalyzer` 作为 `CapitalBook.opportunity_analyzer` |
| 5 | 扩展 `CapitalBook.allocate()` | 整合 V7 的 GO Score 决策逻辑 |
| 6 | 统一 Reserve 逻辑 | 将 20% → 10% 参数化 |
| 7 | 迁移 `_get_db()` | 统一数据库路径，合并 portfolios 表到 investments 表 |

### Phase 3：依赖解耦（高风险）

| 步骤 | 内容 | 操作 |
|------|------|------|
| 8 | 条件引入 V7 引擎 | `analyze()` 仅在 V7 引擎可用时启用，否则返回 error |
| 9 | 重构 Monte Carlo | 如果 `sandbox_cluster` 不可用，降级为启发式估算 |

---

## 五、伪代码：合并后的 `CapitalBook` 新增方法

```python
# 在 capital_book.py 的 CapitalBook 类中新增：

class CapitalAllocatorV7:
    """V7 投资分配器 — 封装后对内暴露"""

    def analyze_opportunity(self, name, category, market, retail_price,
                            fob_cost, moq, hs_code) -> dict:
        """运行完整机会分析（Board + Sandbox + Monte Carlo）"""
        from hvos_v7.core_engine import HVOSCoreEngine
        from hvos_v7.governance_engine import GovernanceEngine
        from hvos_v7.sandbox_cluster import SandboxCluster

        core = HVOSCoreEngine()
        governance = GovernanceEngine()
        sandbox = SandboxCluster()

        opp = core.discover_opportunity(...)
        decision = governance.make_decision(opp, intel)
        sandbox_result = sandbox.run_full_sandbox(opp, ...)
        monte_carlo = sandbox.run_monte_carlo(opp, ...)

        goS = self._calculate_gos(
            opportunity_score=opp.predicted_roi * 10,
            board_confidence=decision.confidence_score,
            success_prob=monte_carlo.get("success_prob", 0),
            roi_p50=monte_carlo.get("p50_roi", -1.0),
        )

        return {
            "project_name": name,
            "goS_score": goS,
            "roi_p50": monte_carlo.get("p50_roi"),
            "roi_p90": monte_carlo.get("p90_roi"),
            "success_prob": monte_carlo.get("success_prob"),
            "risk_level": self._assess_risk(...),
            ...
        }

    def allocate_budget(self, analyses: list[dict], total_budget: float) -> Portfolio:
        """多项目预算分配（V7 算法）"""
        RESERVE_RATIO = 0.10  # 统一为 Root 的 10%
        THRESHOLD_FULL = 8.0
        THRESHOLD_PARTIAL = 6.5
        THRESHOLD_WATCH = 5.0
        # ... 完整分配逻辑 ...

    def _calculate_gos(self, opportunity_score, board_confidence,
                       success_prob, roi_p50) -> float:
        """GO Score 计算公式"""
        gos = (
            opportunity_score / 10 * 0.20 +
            board_confidence / 100 * 0.30 +
            success_prob * 0.30 +
            max(0, min(roi_p50, 5)) / 5 * 0.20
        ) * 10
        return round(gos, 1)

    def _assess_risk(self, analysis: dict) -> RiskLevel:
        """风险等级评估"""
        roi_p50 = analysis.get("roi_p50", -1)
        success_prob = analysis.get("success_prob", 0)
        votes = analysis.get("board_votes", {})
        oppose = votes.get("oppose", 0)

        if success_prob < 0.01 or roi_p50 < -0.8 or oppose >= 3:
            return RiskLevel.EXTREME
        elif success_prob < 0.1 or roi_p50 < -0.3:
            return RiskLevel.HIGH
        elif success_prob < 0.3 or roi_p50 < 0:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
```

---

## 六、总结

| 优先级 | V7 函数 | 合并方式 | 风险 |
|--------|---------|---------|------|
| 高 | `analyze()` | 新增 `CapitalBookV7` 扩展类 | 中（依赖引擎模块） |
| 高 | `_calculate_gos()` | 迁入 `CapitalBook` 静态方法 | 低 |
| 高 | `allocate()` | 扩展 `CapitalBook.allocate_portfolio()` | 中（Reserve 比例需统一） |
| 高 | `_assess_risk()` | 迁入 `CapitalBook` 独立方法 | 低 |
| 中 | `_default_dna()` | 随 `analyze()` 一起迁移 | 低 |
| 中 | `_build_invest_rationale()` | 作为报告方法迁入 | 低 |
| 低 | `_get_db()` | 废弃，统一用 `CapitalBook` 的 db | 低 |
| 低 | `_get_decision()` | 合并到 `allocate()` 内部 | 低 |

**最大风险**：两个 `CapitalAllocator` 同名冲突 + V7 对 core_engine/governance_engine/sandbox_cluster 的强耦合。建议 Phase 1 先保持 V7 模块独立运行，Phase 2 再逐步迁移。
