"""
HVOS V10 启动器
用法: python run_hvos.py <命令> [参数]
"""
import sys, os, traceback

BASE = os.path.dirname(os.path.abspath(__file__))

def run_detect():
    from hvos_evolution_engine import observe_and_detect
    observe_and_detect()

def run_status():
    from hvos_evolution_engine import evolution_status
    evolution_status()

def run_propose(pat="sales_over_30pct"):
    from hvos_evolution_engine import propose_evolution
    propose_evolution(pat)

def run_simulate(pid):
    from hvos_evolution_engine import simulate_proposal
    simulate_proposal(pid)

def run_approve(pid, note=""):
    from hvos_evolution_engine import approve_proposal
    approve_proposal(pid, note)

def run_deploy(pid, note=""):
    from hvos_evolution_engine import deploy_evolution
    deploy_evolution(pid, approved=True, founder_note=note)

def run_predict(cat="VC", mkt="US"):
    from core.world_model.world_model import WorldModel
    wm = WorldModel()
    pred = wm.predict(cat, mkt)
    print("V10 World Model 预测")
    print("  品类: {} | 市场: {}".format(cat, mkt))
    print("  ROI: {:.2f}x | CVR: {:.1%} | LTV: ${:.0f}".format(
        pred.predicted_roi, pred.predicted_cvr, pred.predicted_ltv))

def run_test():
    import subprocess
    r = subprocess.run([sys.executable, "v10_category_scout.py"],
                      capture_output=True, text=True, timeout=300, cwd=BASE)
    print(r.stdout[-3000:] if r.stdout else "(无输出)")
    if r.returncode != 0:
        print("错误: " + r.stderr[-300:])

CMDS = {
    "detect":   (run_detect,   "检测失败模式"),
    "status":   (run_status,   "系统状态"),
    "propose":  (run_propose,  "生成提案"),
    "simulate": (run_simulate, "Digital Twin验证"),
    "approve":  (run_approve,  "审批部署"),
    "deploy":   (run_deploy,   "直接部署"),
    "predict":  (run_predict,  "V10预测"),
    "test":     (run_test,     "20品类测试"),
}

HELP = """HVOS V10 - Cognitive Operating System
Core: V10 | Self-Evolution: v6 | Digital Twin: v2.0 | KG: V8.x

用法: python run_hvos.py <命令> [参数]

命令:
  detect          检测失败模式（第1步）
  status         进化系统状态
  propose [pat]  生成提案（默认:sales_over_30pct）
  simulate <id> Digital Twin验证
  approve <id>  审批+部署
  deploy <id>   直接部署
  predict       V10预测（默认:VC/US）
  test          20品类完整测试
  version       版本信息
"""

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "version"
    args = sys.argv[2:]

    if cmd == "version":
        print("HVOS V10 - Cognitive Operating System")
        print("Core: V10 | Self-Evolution: v6 | Digital Twin: v2.0 | KG: V8.x")
        print("Path: " + BASE)
        sys.exit(0)

    if cmd == "help" or cmd not in CMDS:
        print(HELP)
        sys.exit(0 if cmd == "help" else 1)

    fn, desc = CMDS[cmd]
    print("=== HVOS V10 - {} ===\n".format(desc))

    try:
        if cmd == "propose":
            fn(args[0] if args else "sales_over_30pct")
        elif cmd == "simulate":
            fn(args[0] if args else "")
        elif cmd == "approve":
            note = " ".join(args[1:]) if len(args) > 1 else ""
            fn(args[0] if args else "", note)
        elif cmd == "deploy":
            note = " ".join(args[1:]) if len(args) > 1 else ""
            fn(args[0] if args else "", note)
        elif cmd == "predict":
            fn(args[0] if args else "VC",
               args[1] if len(args) > 1 else "US")
        else:
            fn()
    except Exception as e:
        print("执行错误: " + str(e))
        traceback.print_exc()
        sys.exit(1)
