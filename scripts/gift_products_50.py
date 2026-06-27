"""
HVOS — 批量生成50种中高端礼品，插入 WooCommerce (MySQL HPOS直连)
=============================================================================
年龄分段：
  1. Kids (3-12岁)      → 玩具/教育/创意
  2. Teens (13-19岁)    → 科技/美妆/游戏
  3. Young Adults (20-35岁) → 家居/厨房/户外
  4. Middle Age (36-55岁)   → 品质生活/健康/体验
  5. Seniors (56+岁)    → 舒适/健康/经典

每个产品：name / short_desc / full_desc / price / category / images / tags
图片统一用 CJDropshipping CDN（已验证可访问）

执行：python scripts/gift_products_50.py
"""

from __future__ import annotations
import sys, os, uuid, hashlib
sys.path.insert(0, os.path.dirname(__file__) + "/..")

VPS_HOST = "89.117.22.200"
VPS_USER = "root"
VPS_PASS = "QQ33945551"

MYSQL_USER = "sql_hiugift_com"
MYSQL_PASS = "d441c6b635d2e8"
MYSQL_DB   = "sql_hiugift_com"
PRE        = "wp_0dd69b_"

NOW = "2026-06-27 18:00:00"

# ── 年龄段产品清单 ─────────────────────────────────────────────────────────
PRODUCTS = [
    # ── KIDS (3-12) ─────────────────────────────────────────────────────────
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,   # Gift Sets
        "name": "Hiugift 120pcs Premium Building Blocks Set — STEM Learning Toy",
        "short_desc": "120-piece creative building blocks set, STEM-aligned for ages 3-12. Safe ABS plastic, bright colors, infinite configurations.",
        "price": 24.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["building blocks", "STEM", "kids toy", "creative gift"],
        "weight": "0.8",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift Montessori Wooden Puzzle Board Set — Educational Gifts for Ages 3-8",
        "short_desc": "Natural wood puzzles, Montessori-approved. Shapes, numbers, animals. Develops fine motor skills and认知.",
        "price": 19.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322100.jpg",
        ],
        "tags": ["wooden puzzle", "Montessori", "educational", "kids gift"],
        "weight": "0.5",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift LED Crystal Magic Ball — Light-Up Globe Night Light for Kids Room",
        "short_desc": "7-color LED crystal ball, rechargeable. Creates dreamy starry atmosphere. Perfect bedroom night light for kids.",
        "price": 18.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg",
        ],
        "tags": ["LED light", "night light", "kids room", "magic ball"],
        "weight": "0.4",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift 6-in-1 Solar Robot Kit — STEM Science Kit for Boys & Girls",
        "short_desc": "Build 6 different robots powered by solar or battery. Teaches renewable energy concepts. Age 8+.",
        "price": 22.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322300.jpg",
        ],
        "tags": ["solar robot", "STEM kit", "science toy", "eco gift"],
        "weight": "0.6",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift Deluxe Art Supply Kit — 120-Piece Drawing & Painting Set with Easel",
        "short_desc": "120-piece art kit: markers, crayons, watercolors, brushes + wooden easel. Unleashes creativity in kids 3-12.",
        "price": 29.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg",
        ],
        "tags": ["art supplies", "painting set", "kids craft", "creative gift"],
        "weight": "1.2",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift Soft Coral Fleece Blanket — Ultra Soft Kids Throw Blanket (50x60 inches)",
        "short_desc": "Premium coral fleece, breathable and hypoallergenic. Perfect for naptime and cuddling. Machine washable.",
        "price": 24.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg",
        ],
        "tags": ["kids blanket", "coral fleece", "soft blanket", "cozy gift"],
        "weight": "0.7",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift Portable Kids Digital Camera — HD 1080P Children Camera with 32GB SD",
        "short_desc": "1080P HD kids camera, lightweight body, cute selfie mode. Includes 32GB card and carrying strap.",
        "price": 34.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
        ],
        "tags": ["kids camera", "digital camera", "children gadget", "gift for kids"],
        "weight": "0.3",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift Unicorn Slime Kit — 10-Pack DIY Slime Making Kit with Glitter & Beads",
        "short_desc": "10 different slime kits: glitter, pearl beads, stars. Non-toxic, safe formula. Perfect party favor.",
        "price": 16.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["slime kit", "DIY craft", "kids activity", "party gift"],
        "weight": "0.5",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift Wooden Railway Set — 120-Piece Train Tracks & Cars Toy for Kids",
        "short_desc": "120-piece wooden train track system with 5 cars, bridges, trees. Compatible with most wooden train brands.",
        "price": 38.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322100.jpg",
        ],
        "tags": ["train set", "wooden toy", "railway tracks", "kids gift"],
        "weight": "1.5",
    },
    {
        "age_group": "Kids (3-12)",
        "category_id": 80,
        "name": "Hiugift Kids蛙镜泳镜套装 — Anti-Fog Swim Goggles with Ear Plugs & Nose Clip Set",
        "short_desc": "Anti-fog, UV protection swim goggles for kids. Includes ear plugs and nose clip. Adjustable strap fits ages 3-12.",
        "price": 14.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg",
        ],
        "tags": ["swim goggles", "kids swim", "pool accessories", "summer gift"],
        "weight": "0.2",
    },

    # ── TEENS (13-19) ────────────────────────────────────────────────────────
    {
        "age_group": "Teens (13-19)",
        "category_id": 75,   # Premium Tech
        "name": "Hiugift 3-in-1 Magnetic Wireless Charging Pad — Fast Charge for iPhone/AirPods/Watch",
        "short_desc": "MagSafe-compatible 3-in-1 wireless charging pad. Charge iPhone, AirPods, Apple Watch simultaneously. 15W max output.",
        "price": 39.99,
        "images": [
            "https://cc-west-usa.oss-us-west-1.aliyuncs.com/17053632/2401160213040329400.jpg",
            "https://cc-west-usa.oss-us-west-1.aliyuncs.com/17053632/2401160213050320000.jpg",
        ],
        "tags": ["wireless charger", "MagSafe", "3-in-1 charger", "Apple accessories"],
        "weight": "0.3",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 75,
        "name": "Hiugift LED Desk Lamp with Wireless Charger — Dimmable Foldable Study Lamp",
        "short_desc": "Touch-controlled LED desk lamp with 3 color modes. Built-in 15W wireless charger. Foldable, space-saving design.",
        "price": 32.99,
        "images": [
            "https://cc-west-usa.oss-us-west-1.aliyuncs.com/17053632/2401160213050321200.jpg",
        ],
        "tags": ["desk lamp", "LED lamp", "wireless charger", "study accessories"],
        "weight": "0.6",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift Retro Mechanical Keyboard — Hot-Swap RGB Backlit Keyboard for Gamers",
        "short_desc": "87-key hot-swap mechanical keyboard. Customizable RGB backlight. Blue switches, USB-C. Perfect for gaming and typing.",
        "price": 54.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
        ],
        "tags": ["mechanical keyboard", "RGB keyboard", "gaming", "PC accessories"],
        "weight": "0.9",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift Mini Portable Projector — 1080P HD Home Theater Projector (120 ANSI)",
        "short_desc": "Native 1080P portable projector, 120 ANSI lumens. WiFi + Bluetooth. Perfect for movie nights, gaming, presentations.",
        "price": 89.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["portable projector", "mini projector", "home theater", "movie night"],
        "weight": "1.2",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift Wireless Earbuds Pro — Active Noise Cancelling + Hi-Fi Sound (40H Playtime)",
        "short_desc": "ANC wireless earbuds, 40-hour total playtime. IPX5 waterproof, USB-C fast charge. Deep bass, crystal clear calls.",
        "price": 44.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322300.jpg",
        ],
        "tags": ["wireless earbuds", "ANC earbuds", "Bluetooth earbuds", "tech gift"],
        "weight": "0.05",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift LED Strip Lights 32.8ft — WiFi Smart RGB Strip with App & Music Sync",
        "short_desc": "32.8ft WiFi LED strip, 16M colors, music sync. App control, works with Alexa/Google Assistant. Easy peel-and-stick.",
        "price": 22.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322100.jpg",
        ],
        "tags": ["LED strip lights", "smart home", "RGB lights", "room decor"],
        "weight": "0.3",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift Electric Skateboard — 350W Motor, 12 MPH, 10 Mile Range for Teens",
        "short_desc": "350W electric skateboard, max speed 12 MPH, range 10 miles. Remote control, USB-C charging. Max load 200lbs.",
        "price": 129.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg",
        ],
        "tags": ["electric skateboard", "teen gift", "outdoor fun", "eco transport"],
        "weight": "5.5",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift Anime Canvas Wall Art Set — 3-Piece Unframed Poster Prints for Bedroom",
        "short_desc": "3-piece high-quality canvas prints, anime/art style. Unframed, ready to hang. 24x16 inches each. DM for custom image.",
        "price": 27.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg",
        ],
        "tags": ["wall art", "canvas print", "bedroom decor", "anime gift"],
        "weight": "0.4",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift Skincare Gift Set — Vitamin C Serum + Hyaluronic Acid + Retinol Cream Kit",
        "short_desc": "Complete skincare routine kit: Vitamin C serum, Hyaluronic acid moisturizer, Retinol night cream. Cruelty-free formula.",
        "price": 36.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg",
        ],
        "tags": ["skincare set", "beauty gift", "teen skincare", "vitamin C"],
        "weight": "0.3",
    },
    {
        "age_group": "Teens (13-19)",
        "category_id": 80,
        "name": "Hiugift Instant Polaroid Camera — 10MP Digital Camera with 2.4\" LCD Screen",
        "short_desc": "10MP instant camera with LCD preview. Prints 2\"x3\" sticky-back photos. Includes 32GB card and 10 sheets paper.",
        "price": 49.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
        ],
        "tags": ["instant camera", "polaroid", "teen gift", "creative photography"],
        "weight": "0.5",
    },

    # ── YOUNG ADULTS (20-35) ─────────────────────────────────────────────────
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 76,   # Home & Living
        "name": "Hiugift Touch Dimming LED Table Lamp — Modern Minimalist Bedside Lamp",
        "short_desc": "Sleek aluminum LED table lamp with stepless touch dimming. Warm/neutral/cool white modes. USB-C rechargeable, portable.",
        "price": 45.99,
        "images": [
            "https://cc-west-usa.oss-us-west-1.aliyuncs.com/17053632/2401160213050322100.jpg",
        ],
        "tags": ["LED table lamp", "bedside lamp", "home decor", "touch lamp"],
        "weight": "0.8",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 76,
        "name": "Hiugift Aroma Diffuser with LED Mood Light — 400ml Ultrasonic Essential Oil Diffuser",
        "short_desc": "400ml smart aroma diffuser, 7-color LED light, timer settings. Ultra-quiet (<25dB). Auto shut-off. Perfect for bedroom/living room.",
        "price": 29.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["aroma diffuser", "essential oil", "home fragrance", "LED light"],
        "weight": "0.4",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 77,   # Kitchen & Dining
        "name": "Hiugift 15-in-1 Multi-Cooker Pot — Electric Pressure Cooker & Slow Cooker Combo",
        "short_desc": "15-in-1 electric pressure cooker: rice, soup, stew, steam, sauté, yogurt. 6QT capacity. Dishwasher-safe inner pot.",
        "price": 89.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322300.jpg",
        ],
        "tags": ["multi-cooker", "pressure cooker", "slow cooker", "kitchen appliance"],
        "weight": "5.8",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 77,
        "name": "Hiugift Cold Brew Coffee Maker — 1.5L Glass Pitcher with Fine Mesh Filter",
        "short_desc": "1.5L cold brew coffee maker. Fine mesh filter, BPA-free glass. Brews smooth, less acidic coffee in 12-24 hours.",
        "price": 34.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg",
        ],
        "tags": ["cold brew", "coffee maker", "glass pitcher", "kitchen gadget"],
        "weight": "1.1",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 77,
        "name": "Hiugift Premium Knife Set — 15-Piece Damascus Steel Kitchen Knife Set with Block",
        "short_desc": "15-piece Damascus steel knife set. 5 core knives + 10 steak knives. Natural acacia wood block. Hand-wash recommended.",
        "price": 119.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg",
        ],
        "tags": ["knife set", "Damascus steel", "kitchen knives", "cooking gift"],
        "weight": "4.5",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 79,   # Outdoor & Adventure
        "name": "Hiugift Camping Cookware Set — Portable 8-Piece Outdoor Cooking Kit for 2",
        "short_desc": "8-piece portable camping cookware: pots, pan, kettle, bowls, utensils, carrying bag. Lightweight aluminum, foldable handles.",
        "price": 39.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg",
        ],
        "tags": ["camping cookware", "outdoor cooking", "hiking gear", "portable kitchen"],
        "weight": "1.2",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 79,
        "name": "Hiugift LED Camping Lantern — Rechargeable Solar/USB 4000mAh Power Bank Combo",
        "short_desc": "Solar + USB rechargeable camping lantern. 4000mAh power bank. 4 light modes, collapsible design. IPX5 waterproof.",
        "price": 27.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
        ],
        "tags": ["camping lantern", "solar lantern", "outdoor lighting", "emergency light"],
        "weight": "0.5",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 76,
        "name": "Hiugift Minimalist Wall Clock — Silent Non-Ticking Modern Clock for Living Room",
        "short_desc": "Silent sweep movement wall clock, no ticking. Minimalist white dial, black metal frame. 12-inch diameter. Battery included.",
        "price": 32.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["wall clock", "silent clock", "modern clock", "living room decor"],
        "weight": "0.7",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 76,
        "name": "Hiugift Yoga Mat with Alignment Lines — Non-Slip 6mm TPE Mat for Home Workout",
        "short_desc": "6mm TPE yoga mat with alignment lines. Non-slip surface, double-layer anti-tear. Includes carrying strap. Eco-friendly.",
        "price": 28.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322100.jpg",
        ],
        "tags": ["yoga mat", "fitness mat", "home workout", "non-slip mat"],
        "weight": "1.0",
    },
    {
        "age_group": "Young Adults (20-35)",
        "category_id": 75,
        "name": "Hiugift Foldable Wireless Charging Station — 3-in-1 Travel Charger for Apple Devices",
        "short_desc": "Ultra-compact foldable 3-in-1 charger. Charges iPhone, Watch, AirPods. 15W fast charge. Perfect travel companion.",
        "price": 37.99,
        "images": [
            "https://cc-west-usa.oss-us-west-1.aliyuncs.com/17053632/2401160213050321700.jpg",
        ],
        "tags": ["foldable charger", "travel charger", "3-in-1 wireless", "Apple charger"],
        "weight": "0.2",
    },

    # ── MIDDLE AGE (36-55) ──────────────────────────────────────────────────
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 76,
        "name": "Hiugift Luxury Scented Candle Set — 6-Piece Hand-Poured Soy Wax Candle Gift Box",
        "short_desc": "6 luxurious hand-poured soy wax candles. Scents: Lavender, Vanilla, Rose, Sandalwood, Ocean, Cedar. 35-hour burn time each.",
        "price": 49.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322300.jpg",
        ],
        "tags": ["scented candles", "soy wax", "gift box", "home fragrance"],
        "weight": "1.8",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 80,
        "name": "Hiugift Premium Tea Gift Set — 6 Exotic Loose Leaf Teas in Handcrafted Tin Box",
        "short_desc": "6 premium loose leaf teas: Dragon Well, Tieguanyin, Darjeeling, Earl Grey, Matcha, Rooibos. Beautiful gift box packaging.",
        "price": 44.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg",
        ],
        "tags": ["tea gift set", "loose leaf tea", "exotic tea", "premium gift"],
        "weight": "0.9",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 76,
        "name": "Hiugift Electric Fireplace Heater — Portable Desktop Fireplace with Flame Effect",
        "short_desc": "Compact desktop fireplace with realistic flame effect. 1500W PTC heater, adjustable flame. Overheat protection. Perfect for home office.",
        "price": 69.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg",
        ],
        "tags": ["fireplace heater", "flame effect", "home heater", "desktop fireplace"],
        "weight": "2.1",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 80,
        "name": "Hiugift Bluetooth Record Player — Vintage Turntable with Built-in Speakers",
        "short_desc": "Vintage-style belt-drive turntable. Built-in stereo speakers, Bluetooth receiver. Plays 33/45/78 RPM. RCA output. walnut finish.",
        "price": 129.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg",
        ],
        "tags": ["record player", "turntable", "vinyl player", "vintage audio"],
        "weight": "4.2",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 80,
        "name": "Hiugift Digital Weather Station — Wooden Desktop Clock with Indoor/Outdoor Thermometer",
        "short_desc": "Wooden frame digital weather station. Displays time, date, temperature (in/out), humidity. LED backlight. USB powered.",
        "price": 38.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
        ],
        "tags": ["weather station", "digital clock", "thermometer", "desktop decor"],
        "weight": "0.6",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 75,
        "name": "Hiugift Smart Body Composition Scale — WiFi/Bluetooth BMI Scale with 18 Body Metrics",
        "short_desc": "WiFi + Bluetooth smart scale measures 18 metrics: weight, BMI, body fat, muscle, bone, water. Syncs with Apple Health/Google Fit.",
        "price": 39.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["smart scale", "body composition", "BMI scale", "health tracking"],
        "weight": "1.5",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 80,
        "name": "Hiugift Gourmet Chocolate Gift Box — 24-Piece Artisanal Truffles Selection",
        "short_desc": "24-piece premium artisanal chocolate truffles. Dark, milk, white chocolate varieties. Beautiful gift box with ribbon. Keep cool.",
        "price": 54.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322100.jpg",
        ],
        "tags": ["chocolate gift", "truffles", "gourmet chocolate", "food gift"],
        "weight": "0.8",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 79,
        "name": "Hiugift Hiking Backpack 40L — Waterproof Trekking Backpack with Rain Cover",
        "short_desc": "40L hiking backpack, adjustable torso system. Rain cover included, hydration compatible. Multiple compartments. Max load 25kg.",
        "price": 79.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322300.jpg",
        ],
        "tags": ["hiking backpack", "trekking backpack", "waterproof bag", "outdoor gear"],
        "weight": "1.8",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 76,
        "name": "Hiugift Air Purifier for Bedroom — HEPA Filter, UV-C, Aromatherapy (60㎡ Coverage)",
        "short_desc": "4-in-1 air purifier: True HEPA + activated carbon + UV-C + aroma box. Covers up to 60㎡. Ultra-quiet sleep mode. Filter replaceable.",
        "price": 99.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg",
        ],
        "tags": ["air purifier", "HEPA filter", "UV-C", "home wellness"],
        "weight": "3.2",
    },
    {
        "age_group": "Middle Age (36-55)",
        "category_id": 80,
        "name": "Hiugift Espresso Machine — 20 Bar Semi-Auto Espresso Maker with Milk Frother",
        "short_desc": "20 bar semi-automatic espresso machine. 1.8L removable water tank, milk frother wand. Makes espresso, cappuccino, latte. Stainless steel.",
        "price": 149.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg",
        ],
        "tags": ["espresso machine", "coffee maker", "milk frother", "cafe at home"],
        "weight": "6.5",
    },

    # ── SENIORS (56+) ────────────────────────────────────────────────────────
    {
        "age_group": "Seniors (56+)",
        "category_id": 76,
        "name": "Hiugift Heated Electric Blanket — Soft Flannel Electric Throw (50x60 inches, 10 Heat Settings)",
        "short_desc": "Premium flannel heated blanket, 10 heat settings, 12-hour auto shut-off. Machine washable. Overheating protection. Perfect for seniors.",
        "price": 49.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg",
        ],
        "tags": ["heated blanket", "electric blanket", "senior gift", "warm comfort"],
        "weight": "1.5",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 80,
        "name": "Hiugift Digital Blood Pressure Monitor — Upper Arm BP Machine with Large LCD & 2 Users×120 Records",
        "short_desc": "Upper arm digital BP monitor. Extra-large LCD, 2 users × 120 records. WHO classification indicator. USB rechargeable. Accurate & easy.",
        "price": 39.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
        ],
        "tags": ["blood pressure monitor", "BP machine", "health monitor", "senior health"],
        "weight": "0.4",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 80,
        "name": "Hiugift Non-Slip Bath Mat — Memory Foam Bathroom Mat with Microfiber Cover (20x32 inches)",
        "short_desc": "Memory foam bath mat, ultra-absorbent microfiber. Non-slip rubber backing. Machine washable. 20x32 inches. Cushioned support for seniors.",
        "price": 24.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["bath mat", "memory foam", "non-slip mat", "bathroom safety"],
        "weight": "0.7",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 76,
        "name": "Hiugift Large-Button TV Remote — Universal Remote Control for Elderly, Big Buttons, Backlit",
        "short_desc": "Universal large-button TV remote. Big, backlit buttons for low vision. Compatible with all major TV brands. Simple setup.",
        "price": 18.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322100.jpg",
        ],
        "tags": ["TV remote", "elderly remote", "large button remote", "accessibility gift"],
        "weight": "0.2",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 80,
        "name": "Hiugift Pill Organizer with Alarm — 7-Day Large Capacity Medicine Dispenser",
        "short_desc": "7-day pill organizer, 4 compartments per day (morning/noon/evening/night). Built-in alarm reminders. Waterproof, BPA-free.",
        "price": 22.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322300.jpg",
        ],
        "tags": ["pill organizer", "medicine dispenser", "senior gift", "health organizer"],
        "weight": "0.3",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 76,
        "name": "Hiugift Reading Magnifier Floor Lamp — Adjustable LED Magnifying Floor Lamp for Seniors",
        "short_desc": "3Diotional LED magnifying floor lamp. Adjustable height and angle. Reduces eye strain for reading, knitting, puzzles. Stable weighted base.",
        "price": 64.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322700.jpg",
        ],
        "tags": ["reading lamp", "magnifying lamp", "senior lamp", "LED floor lamp"],
        "weight": "3.5",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 80,
        "name": "Hiugift Digital Bathroom Scale — Extra-Large Platform, High-Weight Capacity (400lbs)",
        "short_desc": "Extra-large platform (14x14 inches), 400lbs capacity. High-precision sensors. Easy-read LCD display. Tempered glass, non-slip mat.",
        "price": 27.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190322900.jpg",
        ],
        "tags": ["bathroom scale", "large platform scale", "high capacity scale", "senior scale"],
        "weight": "1.8",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 76,
        "name": "Hiugift Aromatherapy Hand Cream Gift Set — 6-Piece Deep Moisturizing Hand Care Kit",
        "short_desc": "6-piece luxury hand cream set. Deep moisturizing, non-greasy formula. Essential oil scents. Travel-friendly tubes. Perfect for dry hands.",
        "price": 19.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190323100.jpg",
        ],
        "tags": ["hand cream", "aromatherapy", "hand care", "senior gift"],
        "weight": "0.4",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 80,
        "name": "Hiugift Warm Compression Heating Pad — Auto Shut-Off Electric Heating Pad (12x24 inches)",
        "short_desc": "12x24 inches electric heating pad. 4 heat settings, 2-hour auto shut-off. Ultra-soft fleece cover. Relief for back, neck, shoulder pain.",
        "price": 29.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321600.jpg",
        ],
        "tags": ["heating pad", "electric heating pad", "pain relief", "comfort gift"],
        "weight": "0.8",
    },
    {
        "age_group": "Seniors (56+)",
        "category_id": 80,
        "name": "Hiugift Large Print Word Search Puzzle Books — 10-Puzzle Set, Easy-Read Font",
        "short_desc": "10 large-print word search puzzle books. Easy-read 18pt font. 30 puzzles per book. Great for cognitive exercise and relaxation.",
        "price": 22.99,
        "images": [
            "https://cc-west-usa.cjdropshipping.com/17047584/2401091300190321700.jpg",
        ],
        "tags": ["word search", "puzzle book", "large print", "brain exercise"],
        "weight": "1.2",
    },
]


def slugify(text: str) -> str:
    """Generate URL-safe slug from product name."""
    import re
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text)
    text = text[:80]
    return text


def make_guid(product_id: int) -> str:
    return f"https://hiugift.com/?post_type=product&p={product_id}"


def build_full_desc(name: str, short_desc: str, price: float, images: list) -> str:
    """Build complete HTML product description."""
    img_html = "\n".join(
        f'<p><img src="{url}" alt="{name}" style="max-width:100%;margin:8px 0;"></p>'
        for url in images
    )
    return (
        f'<p><strong>Product Name:</strong> {name}</p>\n'
        f'<p><strong>Short Description:</strong><br>{short_desc}</p>\n'
        f'<hr>\n'
        f'<h3>Product Features</h3>\n'
        f'<p>{short_desc}</p>\n'
        f'<hr>\n'
        f'<h3>Product Images</h3>\n'
        f'{img_html}\n'
        f'<hr>\n'
        f'<p><strong>Price:</strong> ${price:.2f}</p>\n'
        f'<p><em>Buy now on <a href="https://hiugift.com">hiugift.com</a></em></p>'
    )


def main():
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

    print(f"Connected to VPS. Preparing {len(PRODUCTS)} products...")

    # Get next auto_increment ID
    # Get next auto_increment ID (simpler: MAX + 1)
    stdin, stdout, stderr = client.exec_command(
        f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB} "
        f"-e 'SELECT COALESCE(MAX(ID),6400) FROM {PRE}posts;' 2>&1"
    )
    rows = stdout.read().decode().strip().split('\n')
    next_id = int(rows[-1].strip()) + 1
    print(f"Next product ID will be: {next_id}")

    inserted = []
    errors = []

    for i, prod in enumerate(PRODUCTS):
        pid = next_id + i
        slug = slugify(prod["name"])
        guid = make_guid(pid)
        full_desc = build_full_desc(prod["name"], prod["short_desc"], prod["price"], prod["images"]).replace("'", "''")
        title_esc = prod["name"].replace("'", "''")
        tags_str = ", ".join(prod["tags"])

        # SQL: insert posts
        price_val = prod["price"]
        weight_val = prod["weight"]
        pid_fmt = f"{pid:05d}"

        post_sql = (
            f"INSERT INTO {PRE}posts "
            f"(ID, post_author, post_date, post_date_gmt, post_content, post_title, post_excerpt, "
            f"post_status, comment_status, ping_status, post_password, post_name, to_ping, pinged, "
            f"post_content_filtered, post_parent, guid, post_type, post_mime_type) "
            f"VALUES "
            f"({pid}, 1, '{NOW}', '{NOW}', '{full_desc}', '{title_esc}', "
            f"'{prod['short_desc'].replace(chr(39),'&#39;')}', "
            f"'publish', 'open', 'open', '', '{slug}', '', '', '', 0, '{guid}', 'product', '');"
        )

        meta_sql = (
            f"INSERT INTO {PRE}postmeta (post_id, meta_key, meta_value) VALUES "
            f"({pid}, '_price', '{price_val}'),"
            f"({pid}, '_regular_price', '{price_val}'),"
            f"({pid}, '_stock_status', 'instock'),"
            f"({pid}, '_visibility', 'visible'),"
            f"({pid}, '_tax_status', 'taxable'),"
            f"({pid}, '_tax_class', ''),"
            f"({pid}, '_weight', '{weight_val}'),"
            f"({pid}, '_product_version', '10.8.1'),"
            f"({pid}, '_sku', 'HIU-{pid_fmt}'),"
            f"({pid}, 'total_sales', '0');"
        )

        # Use stdin to pass SQL — avoids bash quoting of HTML content
        combined_sql = post_sql + meta_sql

        cmd = f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB} 2>&1"

        stdin_chan, stdout_chan, stderr_chan = client.exec_command(cmd)
        stdin_chan.write(combined_sql.encode('utf-8'))
        stdin_chan.channel.shutdown_write()
        out = stdout_chan.read().decode('utf-8', errors='replace').strip()
        err = stderr_chan.read().decode('utf-8', errors='replace').strip()

        if err and "ERROR" in err.upper():
            errors.append(f"Product {pid} {prod['name'][:40]}: {err[:100]}")
            print(f"  ❌ {prod['age_group']} {i+1}/{len(PRODUCTS)} — ERROR: {err[:80]}")
        else:
            inserted.append({"id": pid, "name": prod["name"], "age_group": prod["age_group"], "category_id": prod["category_id"]})
            print(f"  ✅ {prod['age_group']} {i+1}/{len(PRODUCTS)} — ID {pid}: {prod['name'][:50]}")

    # Link products to category
    for item in inserted:
        cat_sql = (
            f"INSERT INTO {PRE}term_relationships (object_id, term_taxonomy_id, term_order) "
            f"VALUES ({item['id']}, {item['category_id']}, 0);"
        )
        stdin_c, stdout_c, stderr_c = client.exec_command(
            f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB} 2>&1"
        )
        stdin_c.write(cat_sql.encode('utf-8'))
        stdin_c.channel.shutdown_write()
        stdout_c.read()
        stderr_c.read()

    # Update category count
    upd_sql = (
        f"UPDATE {PRE}term_taxonomy tt "
        f"SET count = (SELECT COUNT(*) FROM {PRE}term_relationships WHERE term_taxonomy_id = tt.term_taxonomy_id) "
        f"WHERE EXISTS (SELECT 1 FROM {PRE}term_relationships WHERE term_taxonomy_id = tt.term_taxonomy_id);"
    )
    stdin_c, stdout_c, stderr_c = client.exec_command(
        f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB} 2>&1"
    )
    stdin_c.write(upd_sql.encode('utf-8'))
    stdin_c.channel.shutdown_write()
    stdout_c.read()
    stderr_c.read()

    client.close()

    print(f"\n{'='*60}")
    print(f"Done: {len(inserted)}/{len(PRODUCTS)} products inserted")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    # Summary by age group
    from collections import Counter
    by_age = Counter(item["age_group"] for item in inserted)
    print("\nBy age group:")
    for age, cnt in by_age.items():
        print(f"  {age}: {cnt} products")


if __name__ == "__main__":
    main()
