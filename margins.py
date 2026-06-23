import subprocess, json, sys

# === V10 Scout TOP5 + Agent Reach 真实信号对齐 ===
products = [
    ("智能猫砂盆", 25.99, "宠物降温话题(强信号"),   # V2EX:宠物话题充足, B站有信号
    ("瑜伽紧身裤", 32.00, "健身运动话题(中等信号"),
    ("3合1充电站", 36.00, "科技礼品话题(弱"),
    ("超声波清洗机", 20.00, "个护科技话题(弱"),
    ("智能恒温瓶", 26.00, "户外装备话题(弱"),
]
# 参考 V10 输出价格区间 $11-$38
# Dropshipping 成本率 = 33% (供应商价 / 售价)
COST_RATIO = 0.33   # 成本率 33%
AD_FEE = 0.05    # 广告平台5%估算

def calc(name, price, signal):
    cost = price * COST_RATIO
    platform_fee = price * 0.029 + 0.30
    shipping = 8.0  # ePacket US运费估算
    net = price - cost - platform_fee - shipping
    margin_pct = net / price
    roi = (price - cost) / cost
    return {
        "product": name,
        "price": price,
        "cost": round(cost, 2),
        "platform_fee_usd": round(platform_fee, 2),
        "shipping_usd": shipping,
        "net_profit_usd": round(net, 2),
        "margin_pct": str(round(margin_pct * 100, 1) + "%",
        "roi_x": round(roi, 2),
        "agent_reach_signal": signal,
    }

results = [calc(p[0], p[1], p[2]) for p in products]

# 按净利润率排序
results.sort(key=lambda x: x["net_profit_usd"], reverse=True)

# 输出
print("=== HVOS x Agent Reach 净利润排行 ===")
print(f"{'产品':<15} {'售价':>7} {'成本':>7} {'平台费+运":>15} {'净利润US":>10}")
print("---" * 40)
for r in results:
    print(f"  {r['product']:<20} 成本{r['price']>5.2f}  成本率33%${r['cost']:>5.2f}")
    print(f"  平台费${r['platform_fee_usd']:>5.2f}  运单:$8.00  净利${r['net_profit_usd']:>6.2f}  利润率: " + r["margin_pct"])
    print(f"  Agent Reach信号: {r['agent_reach_signal']}")

# 保存
with open("margin_report.json", "w") as f:
    json.dump({"products": results}, f, ensure_ascii=False, indent=2)

print("\n=== V10 Scout 定价 vs 成本率 ===")
print(f"Dropshipping成本率: {COST_RATIO*100:.0f}%  平台费: 2.9%+$0.30  运费: $8.00")
print("Agent Reach成本: 33%  平台费率: WooCommerce Payments (PayPal已激活但Stripe未装  运费: $8 flat US Epacket")
