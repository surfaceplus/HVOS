# HVOS 命令速查 — Hermes Venture Operating System

## 一键状态检查

```bash
# HVOS 全系统状态面板
python C:/Users/Administrator/AppData/Local/hermes/hvos/hvos_status.py

# 知识图谱状态
python C:/Users/Administrator/AppData/Local/hermes/hvos/hvos_kg_engine.py --action status

# RFE 预测误差状态
python C:/Users/Administrator/AppData/Local/hermes/hvos/hvos_rfe_engine.py --action status
```

---

## 知识图谱操作

```bash
# 添加产品节点（含DNA）
python hvos_kg_engine.py --action update_product --name "个性化礼品套装" --category "礼品套装" --price_tier 3 --dna "3,4,5,4,5,3,2,2,4,3"

# 添加品类节点
python hvos_kg_engine.py --action add_category --name "宠物玩具" --parent "Pet Supplies" --seasonality "Q4" --holidays "圣诞节,感恩节"

# 添加 HS Code
python hvos_kg_engine.py --action add_hscode --code "9505.21" --description "化装舞会用品" --duty_us 0.0 --duty_eu 0.0 --hs_category "Party"

# 连接两个节点
python hvos_kg_engine.py --action link --from_id "prod_xxx" --rel_type "SUPPLIES" --to_id "sup_xxx"

# 查询节点
python hvos_kg_engine.py --action query --type Product
python hvos_kg_engine.py --action query --type Category
python hvos_kg_engine.py --action query --type HSCode

# DNA 匹配
python hvos_kg_engine.py --action dna_match --dna "3,4,5,4,5,3,2,2,4,3"
python hvos_kg_engine.py --action dna_match --product_id "prod_personalized_gift_set_20260609"
```

---

## 真实世界反馈（RFE）

```bash
# 记录一次预测
python hvos_rfe_engine.py --action record_prediction \
  --product_id "prod_xxx" \
  --type "sales" \
  --horizon 30 \
  --value 350 \
  --low 280 \
  --high 420 \
  --basis "基于TikTok播放量和转化率测算"

# 录入实际结果（计算误差）
python hvos_rfe_engine.py --action record_actual \
  --prediction_id "pred_sales_30d_xxx" \
  --actual 295

# 查看误差趋势
python hvos_rfe_engine.py --action error_trend --days 90

# 查看模型偏见
python hvos_rfe_engine.py --action model_bias --days 90

# 触发模型复盘
python hvos_rfe_engine.py --action trigger_review --prediction_id "pred_xxx"

# 模型复盘指南
python hvos_rfe_engine.py --action model_review
```

---

## HVOS 启动命令

```bash
# 启动 HVOS 完整评审（Board Meeting）
@HVOS 评审 [品类名称]

# 启动数字孪生
@HVOS 数字孪生 [品类名称]

# 查询知识图谱
@HVOS 查询 [品类/品牌/关键词]

# 沉淀知识（当前分析结果入库）
@HVOS 沉淀

# 匹配爆款基因
@HVOS 匹配爆款 [品类名称]

# 提取产品DNA
@HVOS 提取DNA [品类名称]

# 录入真实反馈
@HVOS 录入反馈

# 查看系统状态
@HVOS 状态

# 知识图谱扩张（新增节点）
@HVOS 扩张 [品类名称]
```

---

## 自动 Cron 任务

| 任务名称 | 时间 | 触发 |
|---------|------|------|
| HVOS 每日状态扫描 | 每日 08:00 | 自动 |
| HVOS Reality Feedback 录入提醒 | 每周一 09:00 | 自动 |
| HVOS 周度战略回顾 + Board Meeting | 每周五 17:00 | 自动 |

---

## 文件路径速查

| 文件 | 路径 |
|------|------|
| HVOS 主目录 | `C:\Users\Administrator\AppData\Local\hermes\hvos\` |
| 知识图谱数据库 | `hvos\knowledge_graph\kg.db` |
| Board Meeting 记录 | `hvos\board-meetings\` |
| 状态面板脚本 | `hvos\hvos_status.py` |
| 知识图谱引擎 | `hvos\hvos_kg_engine.py` |
| RFE 引擎 | `hvos\hvos_rfe_engine.py` |
| HVOS Skill 集合 | `C:\Users\Administrator\AppData\Local\hermes\skills\hvos\` |

---

## 核心成功指标

```
HVOS 成功标准：
  ✅ 发现爆款数量
  ✅ 真实盈利能力
  ✅ 知识库增长速度（节点/关系月增量）
  ✅ 预测误差下降速度（逐季度收敛）
```

---

## 版本信息

- **Version**: 1.0
- **Phase**: Phase 1-2 完成
- **Board Layer**: CEO+CFO+CMO+COO+CSO+Investment Committee ✅
- **Knowledge Graph**: 27 节点 / 7 关系 / 25 HS Codes ✅
- **Customs Intelligence Center**: 25 HS Codes ✅
- **Reality Feedback Engine**: 就绪（待积累预测数据）⚙️
- **Agent Factory**: 31 个动态模板 ✅
- **Digital Twin**: 已定义，待激活 ⏳
- **Winning Pattern Library**: 5 个爆款模式 ✅
- **Self-Evolution Engine**: 就绪（待触发）⚙️
