"""
1688 采购来源配置 — HVOS Sourcing Hub
"""
import json, os, webbrowser

SOURCING = {
    "智能猫砂盆": {
        "category": "宠物用品",
        "1688_keyword": "智能猫砂盆 自动清洁 2025新款",
        "1688_price_range": "28-65元",
        "estimated_fob_usd": 8.50,
        "remark": "CJdropshipping SKU: CJ126910301AZ",
        "candidates": [
            "https://detail.1688.com/offer/1234567890.html  # 示例链接",
        ]
    },
    "3合1无线充电站": {
        "category": "数码配件",
        "1688_keyword": "三合一无线充电器 折叠 快充",
        "1688_price_range": "15-35元",
        "estimated_fob_usd": 4.50,
        "remark": "公模产品，多家供应商",
        "candidates": []
    },
    "瑜伽紧身裤": {
        "category": "运动服饰",
        "1688_keyword": "高腰瑜伽裤 健身裤 2025新款",
        "1688_price_range": "18-45元",
        "estimated_fob_usd": 5.80,
        "remark": "高复购品类",
        "candidates": []
    },
    "空气炸锅": {
        "category": "厨房电器",
        "1688_keyword": "空气炸锅 家用 4.5L",
        "1688_price_range": "35-80元",
        "estimated_fob_usd": 10.50,
        "remark": "注意物流体积重",
        "candidates": []
    },
    "高压洗车枪": {
        "category": "户外工具",
        "1688_keyword": "高压洗车水枪 锂电池 无线",
        "1688_price_range": "20-55元",
        "estimated_fob_usd": 7.50,
        "remark": "含锂电池需特殊物流",
        "candidates": []
    },
    "LED台灯": {
        "category": "家居",
        "1688_keyword": "LED台灯 护眼 触控调光",
        "1688_price_range": "12-30元",
        "estimated_fob_usd": 3.80,
        "remark": "hugift.com现有SKU 6390",
        "candidates": []
    },
    "蓝牙睡眠耳机": {
        "category": "穿戴设备",
        "1688_keyword": "蓝牙睡眠耳机 头戴式 音乐睡眠",
        "1688_price_range": "15-35元",
        "estimated_fob_usd": 4.50,
        "remark": "现有SKU 7090",
        "candidates": []
    }
}

# 存储到 HVOS sourcing hub
os.makedirs("sourcing", exist_ok=True)
with open("sourcing/1688_hub.json", "w", encoding="utf-8") as f:
    json.dump(SOURCING, f, ensure_ascii=False, indent=2)

# 生成1688搜索链接（用户可手动打开）
print("=== 1688 采购快速入口 ===")
for name, info in SOURCING.items():
    kw = info["1688_keyword"]
    url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={kw}"
    print(f"\n📦 {name} ({info['category']})")
    print(f"   搜索: {url}")
    print(f"   价格范围: {info['1688_price_range']} | FOB: ~${info['estimated_fob_usd']}")

print("\n\n=== 成本对比 (1688 FOB vs WooCommerce 售价) ===")
print(f"{'品类':<15} {'1688 FOB':>10} {'Woo售价':>10} {'毛利':>10}")
for name, info in SOURCING.items():
    cost = info["estimated_fob_usd"]
    price = {"智能猫砂盆": 79, "3合1无线充电站": 49, "瑜伽紧身裤": 39,
             "空气炸锅": 49, "高压洗车枪": 39, "LED台灯": 35, "蓝牙睡眠耳机": 38}.get(name, 30)
    margin = (price - cost) / price
    print(f"  {name:<13}  ${cost:<6.2f}  ${price:<6.2f}  {margin:>8.0%}")
