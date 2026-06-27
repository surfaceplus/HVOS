"""
Signal Filter — AI数据驱动师电商指标过滤层

职责：
  1. GMV 门槛过滤（月GMV > $10K）
  2. BSR 竞争度过滤（TOP 50000 内）
  3. 季节性匹配过滤（America250 窗口 T-43天）
  4. 供应链可行性过滤（重量/体积/CPC/认证）

接入点：OE._collect_all_signals() 之后，_aggregate_signals() 之前
"""
from datetime import date
from typing import List, Dict
from dataclasses import dataclass, field

AMERICA250_MONTH = 9  # September
AMERICA250_WEEK = 3
AMERICA250_OPTIMAL_DAYS = 43

SEASONAL_WINDOWS = {
    "america250": {"month": 9, "week": 3, "optimal_days": 43},   # T-43 窗口
    "halloween": {"month": 10, "week": 4, "optimal_days": 30},
    "thanksgiving": {"month": 11, "week": 4, "optimal_days": 21},
    "christmas": {"month": 12, "week": 3, "optimal_days": 21},
    "valentine": {"month": 2, "week": 2, "optimal_days": 30},
}


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""
    score_adjustment: float = 0.0


class SignalFilter:
    """电商指标信号过滤器"""

    def __init__(self, min_gmv: float = 10000, max_bsr: int = 50000,
                 seasonal_days_max: int = 50):
        self.min_gmv = min_gmv
        self.max_bsr = max_bsr
        self.seasonal_days_max = seasonal_days_max
        self._filter_stats = {"total": 0, "passed": 0, "rejected": 0}

    def apply(self, signals: List[Dict]) -> List[Dict]:
        """对信号列表应用所有过滤规则"""
        filtered = []
        for sig in signals:
            self._filter_stats["total"] += 1
            result = self._filter_signal(sig)
            if result.passed:
                filtered.append(sig)
                self._filter_stats["passed"] += 1
            else:
                self._filter_stats["rejected"] += 1
                sig["_filter_rejected"] = result.reason
                sig["_filter_score_adjust"] = result.score_adjustment
        return filtered

    def _filter_signal(self, sig: Dict) -> FilterResult:
        """单信号过滤，返回 FilterResult"""
        source = sig.get("source", "unknown")

        # 1. GMV 门槛
        gmv = sig.get("estimated_gmv") or sig.get("monthly_gmv") or sig.get("gmv")
        if gmv is not None:
            if float(gmv) < self.min_gmv:
                return FilterResult(False, f"GMV ${gmv} < ${self.min_gmv} 门槛", -0.1)

        # 2. BSR 竞争度
        bsr = sig.get("bsr") or sig.get("best_seller_rank")
        if bsr is not None:
            if int(bsr) > self.max_bsr:
                return FilterResult(False, f"BSR #{bsr} > #{self.max_bsr} 竞争过密", -0.05)

        # 3. 季节性匹配（America250 窗口）
        days_to = sig.get("days_to_window")
        if days_to is not None:
            if int(days_to) > self.seasonal_days_max:
                return FilterResult(False, f"T-{days_to}天 超过{self.seasonal_days_max}天窗口", -0.15)

        # 4. CPC 门槛（广告成本过高则降权，不直接拒绝）
        cpc = sig.get("cpc") or sig.get("estimated_cpc")
        if cpc is not None:
            if float(cpc) > 3.0:
                sig["_cpc_flag"] = "HIGH"
            elif float(cpc) > 1.5:
                sig["_cpc_flag"] = "MEDIUM"

        # 5. 重量/体积（供应链可行性）
        weight = sig.get("weight_oz") or sig.get("package_weight")
        if weight is not None:
            if float(weight) > 50:  # 超过 50oz 影响运费
                sig["_weight_flag"] = "HEAVY"

        # 6. 认证要求（FDA/CE 等）
        certifications = sig.get("required_certifications") or []
        if certifications and not sig.get("_certifications_met"):
            sig["_cert_flag"] = "REQUIRED"

        return FilterResult(True)

    def filter_by_category(self, signals: List[Dict], allowed_categories: List[str]) -> List[Dict]:
        """按品类白名单过滤"""
        if not allowed_categories:
            return signals
        return [s for s in signals if s.get("category", "general") in allowed_categories]

    def enrich_seasonal_info(self, signals: List[Dict]) -> List[Dict]:
        """为每个信号补充季节性信息"""
        now = date.today()
        for sig in signals:
            days_to_250 = self._days_to_window(now, "america250")
            sig["_days_to_america250"] = days_to_250
            sig["_in_america250_window"] = 0 <= days_to_250 <= AMERICA250_OPTIMAL_DAYS
        return signals

    def _days_to_window(self, now: date, window_name: str) -> int:
        config = SEASONAL_WINDOWS.get(window_name)
        if not config:
            return 999
        from calendar import monthrange
        target_month = config["month"]
        if now.month < target_month:
            target_year = now.year
        elif now.month > target_month:
            target_year = now.year + 1
        else:
            target_year = now.year
        _, last_day = monthrange(target_year, target_month)
        window_day = min(config["week"] * 7, last_day)
        window_date = date(target_year, target_month, window_day)
        return (window_date - now).days

    def get_filter_stats(self) -> Dict:
        return self._filter_stats.copy()
