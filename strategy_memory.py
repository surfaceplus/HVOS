"""
HVOS V8.1 — Strategy Memory
=============================
从投资结果中提炼经验策略，形成可查询的 Strategy Library。

核心闭环：
  投资结果（REJECT/INVEST）
    ↓ StrategyExtractor
  提炼：品类×市场×信号 → 策略规则
    ↓
  Strategy Library（持久化）
    ↓
  新品评估时：查询相关历史策略
    ↓
  决策辅助（不只是预测，是经验复用）

使用方式：
  python strategy_memory.py --action record --opp_id opp_xxx --verdict invest
  python strategy_memory.py --action query --category "厨房" --market US
  python strategy_memory.py --action library
"""

import sys
import json
import sqlite3
import uuid
from datetime import datetime, date
from typing import Optional, Literal

# ============================================================
# Strategy Types
# ============================================================

class StrategyType:
    """策略类型枚举"""
    CHANNEL_STRATEGY = "channel"      # 渠道策略：Pinterest vs Meta vs TikTok
    PRICING_STRATEGY = "pricing"       # 定价策略：高价切入 vs 低价引流
    COMPLIANCE_STRATEGY = "compliance" # 合规策略：FCC/COPPA/Prop65
    SUPPLY_STRATEGY = "supply"        # 供应链策略：MOQ/交期/备货
    MARKET_ENTRY_STRATEGY = "entry"    # 市场切入：Q4旺季 vs 日常
    COMPETITIVE_STRATEGY = "competitive" # 竞争策略：差异化 vs 价格战
    CREATIVE_STRATEGY = "creative"      # 内容策略：UGC来源/TikTok风格


OUTCOME_TYPES = Literal["success", "failure", "expansion", "crash", "watchlist"]


# ============================================================
# Strategy Memory Engine
# ============================================================

class StrategyMemory:
    """
    策略记忆引擎：从历史投资中提炼策略规则。

    数据来源：
    1. Event Store（自动消费）
    2. RFE（Reality Feedback）录入后更新置信度

    查询接口：
    strategy_memory.query(category, market, signal)
    → 返回相关策略规则列表
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge-graph\strategy_memory.db"
        self.db_path = db_path
        self._init_schema()

    # ----------------------------------------------------------
    # Schema
    # ----------------------------------------------------------

    def _init_schema(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Strategy Library
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategy_library (
                strategy_id TEXT PRIMARY KEY,
                strategy_type TEXT NOT NULL,   -- channel/pricing/compliance/supply/entry/competitive/creative
                category TEXT NOT NULL,         -- 品类：厨房/3C/美妆/户外
                market TEXT NOT NULL,           -- 市场：US/UK/DE
                signal TEXT DEFAULT "",         -- 发现信号
                rule TEXT NOT NULL,            -- 策略规则（核心内容）
                example_opp_id TEXT,           -- 样本机会ID
                outcome TEXT NOT NULL,         -- success/failure/expansion/crash
                verdict TEXT NOT NULL,         -- INVEST/WATCHLIST/REJECT
                confidence REAL DEFAULT 0.5,   -- 置信度 0-1
                times_applied INTEGER DEFAULT 1, -- 应用次数
                times_success INTEGER DEFAULT 0, -- 成功次数
                success_rate REAL DEFAULT 0.0,  -- 历史成功率
                created_at TEXT,
                updated_at TEXT,
                notes TEXT DEFAULT ""
            )
        """)

        # Outcome Log（案例记录）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS outcome_log (
                log_id TEXT PRIMARY KEY,
                opp_id TEXT NOT NULL,
                opp_name TEXT,
                category TEXT NOT NULL,
                market TEXT NOT NULL,
                verdict TEXT NOT NULL,
                outcome TEXT NOT NULL,         -- success/failure/expansion/crash/watchlist
                revenue_90d REAL DEFAULT 0,    -- 90天收入（REFE后）
                roi_actual REAL DEFAULT 0,
                net_margin_actual REAL DEFAULT 0,
                lessons TEXT DEFAULT "",         -- 教训总结
                key_insight TEXT DEFAULT "",    -- 关键洞察
                created_at TEXT,
                source TEXT DEFAULT "manual"   -- manual/rfe/board
            )
        """)

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_strategy_type ON strategy_library(strategy_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_strategy_category ON strategy_library(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_strategy_market ON strategy_library(market)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_outcome_opp ON outcome_log(opp_id)")

        conn.commit()
        conn.close()

    # ----------------------------------------------------------
    # Record & Extract
    # ----------------------------------------------------------

    def record_outcome(
        self,
        opp_id: str,
        opp_name: str,
        category: str,
        market: str,
        verdict: str,
        outcome: OUTCOME_TYPES,
        revenue_90d: float = 0,
        roi_actual: float = 0,
        net_margin_actual: float = 0,
        lessons: str = "",
        key_insight: str = "",
        source: str = "manual"
    ) -> dict:
        """
        记录投资结果，并触发策略提炼（单连接）。
        """
        import time
        log_id = f"log_{uuid.uuid4().hex[:10]}"
        now = datetime.now().isoformat()

        for attempt in range(5):
            conn = None
            try:
                conn = sqlite3.connect(self.db_path, timeout=15)
                conn.execute("PRAGMA busy_timeout = 10000")
                cur = conn.cursor()

                cur.execute("""
                    INSERT OR REPLACE INTO outcome_log
                    (log_id, opp_id, opp_name, category, market, verdict, outcome,
                     revenue_90d, roi_actual, net_margin_actual, lessons, key_insight, created_at, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (log_id, opp_id, opp_name, category, market, verdict, outcome,
                      revenue_90d, roi_actual, net_margin_actual, lessons, key_insight, now, source))
                conn.commit()

                # 策略提炼（同一连接）
                rules = self._extract_strategies_conn(
                    conn, category, market, verdict, outcome,
                    revenue_90d, roi_actual, net_margin_actual, key_insight, opp_id, now
                )

                return {"log_id": log_id, "strategies_extracted": len(rules), "rules": rules}

            except sqlite3.OperationalError as e:
                if conn:
                    conn.rollback()
                if "locked" in str(e) and attempt < 4:
                    import time
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise
            finally:
                if conn:
                    conn.close()
        return {"log_id": log_id, "strategies_extracted": 0, "rules": []}

    def _extract_strategies_conn(
        self,
        conn: sqlite3.Connection,
        category: str,
        market: str,
        verdict: str,
        outcome: OUTCOME_TYPES,
        revenue_90d: float,
        roi_actual: float,
        net_margin_actual: float,
        key_insight: str,
        opp_id: str,
        now: str
    ) -> list[dict]:
        """
        从投资结果中提炼策略规则（使用现有连接，不新建）。
        """
        rules = []
        cur = conn.cursor()

        # 1. 渠道策略（基于outcome）
        if outcome == "success" and revenue_90d > 0:
            rules.append({
                "type": StrategyType.CHANNEL_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类在{market}市场，自然流量+UGC是核心驱动，内容质量比广告预算更重要",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })
        elif outcome == "failure" and revenue_90d == 0:
            rules.append({
                "type": StrategyType.CHANNEL_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类在{market}市场，付费广告ROI难以为继，需优先建立自然流量基础",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })

        # 2. 合规策略（基于COPPA/FCC/Prop65风险）
        if "COPPA" in key_insight or "儿童" in key_insight:
            rules.append({
                "type": StrategyType.COMPLIANCE_STRATEGY,
                "category": category,
                "market": market,
                "rule": "儿童产品涉及COPPA，GPS/数据收集功能=高风险，建议成人版本优先",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })
        elif "FCC" in key_insight or "认证" in key_insight:
            rules.append({
                "type": StrategyType.COMPLIANCE_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类需FCC认证，认证周期4-8周，费用$5,000-$12,000，需计入上市计划",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })

        # 3. 定价策略（基于net_margin）
        if net_margin_actual > 0.35:
            rules.append({
                "type": StrategyType.PRICING_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类定价应保持毛利率≥35%，高价切入优于低价引流",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })
        elif net_margin_actual < 0.20:
            rules.append({
                "type": StrategyType.PRICING_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类低毛利(<20%)难以支撑广告费，需重新定价或更换供应链",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })

        # 4. 市场时机策略（基于growth_rate）
        if "Q4" in key_insight or "holiday" in key_insight.lower():
            rules.append({
                "type": StrategyType.MARKET_ENTRY_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类Q4旺季需求激增，提前6-8周备货+广告热身",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })

        # 5. 竞争策略（基于competition_level）
        if "壁垒" in key_insight or "竞争" in key_insight:
            rules.append({
                "type": StrategyType.COMPETITIVE_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类竞争激烈，需通过评论数量+评分建立信任壁垒",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })

        # 6. 供应链策略（基于MOQ和fob_cost）
        if "MOQ" in key_insight or "供应链" in key_insight:
            rules.append({
                "type": StrategyType.SUPPLY_STRATEGY,
                "category": category,
                "market": market,
                "rule": f"{category}品类MOQ>300时需分批下单，避免库存积压",
                "outcome": outcome,
                "verdict": verdict,
                "opp_id": opp_id
            })

        # 写入库
        inserted = 0
        for rule_data in rules:
            sid = f"strat_{uuid.uuid4().hex[:10]}"
            try:
                cur.execute("""
                    INSERT INTO strategy_library
                    (strategy_id, strategy_type, category, market, signal, rule,
                     example_opp_id, outcome, verdict, confidence, times_applied,
                     times_success, success_rate, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sid,
                    rule_data["type"],
                    rule_data["category"],
                    rule_data["market"],
                    "",
                    rule_data["rule"],
                    rule_data["opp_id"],
                    rule_data["outcome"],
                    rule_data["verdict"],
                    0.5, 1, 0, 0.0,
                    now, now
                ))
                inserted += 1
            except Exception as e:
                import sys
                sys.stderr.write(f"[WARN] rule insert failed: {e}\n")
        conn.commit()
        return rules
        # Query Interface
    # ----------------------------------------------------------

    def query(
        self,
        category: str = None,
        market: str = None,
        signal: str = None,
        strategy_type: str = None,
        min_confidence: float = 0.3,
        limit: int = 10
    ) -> list[dict]:
        """
        查询相关策略规则。

        用法：
          strategies = memory.query(category="厨房", market="US")
          strategies = memory.query(signal="TikTok", min_confidence=0.6)
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        sql = """
            SELECT strategy_id, strategy_type, category, market, signal, rule,
                   confidence, times_applied, times_success, success_rate,
                   verdict, outcome, example_opp_id, notes
            FROM strategy_library
            WHERE confidence >= ?
        """
        params = [min_confidence]

        if category:
            sql += " AND category = ?"
            params.append(category)
        if market:
            sql += " AND market = ?"
            params.append(market)
        if strategy_type:
            sql += " AND strategy_type = ?"
            params.append(strategy_type)
        if signal:
            sql += " AND (signal LIKE ? OR rule LIKE ?)"
            params.extend([f"%{signal}%", f"%{signal}%"])

        sql += " ORDER BY confidence DESC, times_applied DESC LIMIT ?"
        params.append(limit)

        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()

        return [
            {
                "id": r[0],
                "type": r[1],
                "category": r[2],
                "market": r[3],
                "signal": r[4],
                "rule": r[5],
                "confidence": r[6],
                "times_applied": r[7],
                "times_success": r[8],
                "success_rate": r[9],
                "verdict": r[10],
                "outcome": r[11],
                "example_opp_id": r[12],
                "notes": r[13] or ""
            }
            for r in rows
        ]

    def get_strategy_summary(self, category: str = None) -> dict:
        """获取策略摘要（按品类分组）"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        where = "WHERE confidence >= 0.3"
        if category:
            where += f" AND category = '{category}'"

        cur.execute(f"""
            SELECT
                category,
                strategy_type,
                COUNT(*) as rule_count,
                AVG(confidence) as avg_conf,
                SUM(times_success) as total_success,
                SUM(times_applied) as total_applied
            FROM strategy_library
            {where}
            GROUP BY category, strategy_type
            ORDER BY category, avg_conf DESC
        """)
        rows = cur.fetchall()

        summary = {}
        for r in rows:
            cat = r[0] or "general"
            if cat not in summary:
                summary[cat] = {}
            summary[cat][r[1]] = {
                "rule_count": r[2],
                "avg_confidence": round(r[3], 2),
                "total_success": r[4] or 0,
                "total_applied": r[5] or 0
            }

        conn.close()
        return summary

    # ----------------------------------------------------------
    # Apply & Update
    # ----------------------------------------------------------

    def apply_strategy(self, strategy_id: str) -> bool:
        """标记策略被应用（+1应用次数）"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE strategy_library
            SET times_applied = times_applied + 1,
                updated_at = ?
            WHERE strategy_id = ?
        """, (datetime.now().isoformat(), strategy_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def update_success(self, strategy_id: str, success: bool):
        """更新策略成功率"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE strategy_library
            SET times_success = times_success + ?,
                success_rate = CAST(times_success + ? AS REAL) / times_applied,
                updated_at = ?
            WHERE strategy_id = ?
        """, (1 if success else 0, 1 if success else 0,
              datetime.now().isoformat(), strategy_id))
        conn.commit()
        conn.close()

    # ----------------------------------------------------------
    # Record from Event (自动消费)
    # ----------------------------------------------------------

    def consume_event(self, event: dict):
        """
        从 Event Bus 事件自动记录策略。

        消费：
          INVESTMENT_DECISION_RENDERED
          RFE_ACTUAL_RECORDED
        """
        etype = event.get("event_type", "")
        data = event.get("data", {})

        if etype == "INVESTMENT_DECISION_RENDERED":
            opp_id = data.get("opp_id", "")
            verdict = data.get("verdict", "")
            # 初步记录（outcome待RFE补充）
            outcome = {
                "invest": "watchlist",
                "watchlist": "watchlist",
                "reject": "failure"
            }.get(verdict, "failure")

            # 从 KG 查询机会详情
            opp_data = self._get_opp_data(opp_id)

            return self.record_outcome(
                opp_id=opp_id,
                opp_name=opp_data.get("name", ""),
                category=opp_data.get("category", "general"),
                market=opp_data.get("market", "US"),
                verdict=verdict,
                outcome=outcome,
                source="event"
            )

        elif etype == "RFE_ACTUAL_RECORDED":
            opp_id = data.get("opp_id", "")
            actual_revenue = data.get("actual_revenue", 0)
            verdict = self._get_opp_verdict(opp_id)
            # 基于实际收入判断结果
            outcome = "success" if actual_revenue > 10000 else \
                     "failure" if actual_revenue == 0 else "expansion"

            opp_data = self._get_opp_data(opp_id)
            return self.record_outcome(
                opp_id=opp_id,
                opp_name=opp_data.get("name", ""),
                category=opp_data.get("category", "general"),
                market=opp_data.get("market", "US"),
                verdict=verdict,
                outcome=outcome,
                revenue_90d=actual_revenue,
                source="rfe"
            )

        return None

    def _get_opp_data(self, opp_id: str) -> dict:
        """从 KG 查询机会详情"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT n.properties
                FROM kg_nodes n
                WHERE n.node_id = ? OR n.node_id LIKE ?
            """, (f"Opportunity_{opp_id}", f"%{opp_id}%"))
            row = cur.fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
        except Exception:
            pass
        return {}

    def _get_opp_verdict(self, opp_id: str) -> str:
        """从 KG 查询机会 verdict"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT n.properties
                FROM kg_nodes n
                WHERE n.node_id LIKE ?
            """, (f"%Investment%{opp_id}%",))
            row = cur.fetchone()
            conn.close()
            if row:
                props = json.loads(row[0])
                return props.get("verdict", "REJECT")
        except Exception:
            pass
        return "REJECT"


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS V8.1 — Strategy Memory")
    parser.add_argument("--action", choices=["record", "query", "library", "summary"],
                        default="library", help="操作类型")
    parser.add_argument("--opp_id", help="机会ID（record时用）")
    parser.add_argument("--opp_name", help="机会名称")
    parser.add_argument("--category", help="品类：厨房/3C/美妆")
    parser.add_argument("--market", help="市场：US/UK/DE")
    parser.add_argument("--verdict", help="裁决：INVEST/WATCHLIST/REJECT")
    parser.add_argument("--outcome", help="结果：success/failure/expansion/crash")
    parser.add_argument("--revenue", type=float, default=0, help="90天实际收入")
    parser.add_argument("--roi", type=float, default=0, help="实际ROI")
    parser.add_argument("--margin", type=float, default=0, help="实际净利率")
    parser.add_argument("--insight", default="", help="关键洞察/教训")
    parser.add_argument("--strategy_type", help="策略类型")
    parser.add_argument("--min_conf", type=float, default=0.3, help="最低置信度")
    parser.add_argument("--limit", type=int, default=10, help="返回数量")
    parser.add_argument("--db", help="数据库路径")

    args = parser.parse_args()
    db = args.db or r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge-graph\kg.db"
    sm = StrategyMemory(db)

    if args.action == "record":
        result = sm.record_outcome(
            opp_id=args.opp_id or "unknown",
            opp_name=args.opp_name or "",
            category=args.category or "general",
            market=args.market or "US",
            verdict=args.verdict or "REJECT",
            outcome=args.outcome or "failure",
            revenue_90d=args.revenue,
            roi_actual=args.roi,
            net_margin_actual=args.margin,
            key_insight=args.insight
        )
        print(f"记录完成：log_id={result['log_id']}")
        print(f"提炼策略：{result['strategies_extracted']}条")
        for r in result["rules"]:
            print(f"  [{r['type']}] {r['rule']}")

    elif args.action == "query":
        strategies = sm.query(
            category=args.category,
            market=args.market,
            strategy_type=args.strategy_type,
            min_confidence=args.min_conf,
            limit=args.limit
        )
        print(f"找到 {len(strategies)} 条策略：")
        for s in strategies:
            print(f"\n  [{s['type']}] {s['category']}/{s['market']}")
            print(f"  规则: {s['rule']}")
            print(f"  置信度: {s['confidence']:.0%} | 应用: {s['times_applied']}次 | 成功: {s['success_rate']:.0%}")

    elif args.action == "library":
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("""
            SELECT strategy_type, category, COUNT(*),
                   AVG(confidence), SUM(times_applied)
            FROM strategy_library
            GROUP BY strategy_type, category
            ORDER BY strategy_type, COUNT(*) DESC
        """)
        rows = cur.fetchall()
        print("=" * 60)
        print("  Strategy Library — 策略库")
        print("=" * 60)
        for r in rows:
            print(f"\n  [{r[0]}] {r[1]}")
            print(f"    规则数: {r[2]} | 平均置信度: {r[3]:.0%} | 应用次数: {r[4]}")
        conn.close()
        print("=" * 60)

    elif args.action == "summary":
        summary = sm.get_strategy_summary(args.category)
        print("=" * 60)
        print("  Strategy Memory — 策略摘要")
        print("=" * 60)
        for cat, types in summary.items():
            print(f"\n  品类: {cat}")
            for stype, stats in types.items():
                print(f"    [{stype}] 规则:{stats['rule_count']} "
                      f"置信度:{stats['avg_confidence']:.0%} "
                      f"成功:{stats['total_success']}/{stats['total_applied']}")
        print("=" * 60)
