"""
HVOS 1688 采购中心 — 仪表盘
"""
import json, os

with open(os.path.join(os.path.dirname(__file__), "1688_hub.json")) as f:
    hub = json.load(f)

print("=" * 70)
print("  HVOS 1688 采购中心")
print("  品类数:", len(hub))
print("=" * 70)

total_fob = 0
for name, info in hub.items():
    fob = info["estimated_fob_usd"]
    total_fob += fob
    price_map = {"智能猫砂盆": 79, "3合1无线充电站": 49, "瑜伽紧身裤": 39,
                  "空气炸锅": 49, "高压洗车枪": 39, "LED台灯": 35, "蓝牙睡眠耳机": 38}
    sell = price_map.get(name, 30)
    gross = (sell - fob) / sell
    print(f"\n📦 {name} ({info['category']})")
    print(f"  1688关键词: {info['1688_keyword']}")
    print(f"  1688价格: {info['1688_price_range']} | FOB: \${fob:.2f}")
    print(f"  Woo售价: \${sell:.2f} | 毛利: {gross:.0%}")
    print(f"  搜索: https://s.1688.com/selloffer/offer_search.htm?keywords={info['1688_keyword']}")

print("\n" + "=" * 70)
print(f"  总 FOB 成本: \${total_fob:.2f}/unit | 加权平均毛利: {((449-total_fob)/449):.0%}")
print("=" * 70)
print("\n📌 下一步:")
print("  1. python sourcing/1688.py search <关键词> — 搜索1688产品")
print("  2. 在1688找到具体链接后复制到 candidates")
print("  3. python run_hvos.py predict <品类> <市场> — 验证V10预测")
print("  4. python margins.py — 重新计算净利润")
print()
