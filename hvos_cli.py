#!/usr/bin/env python
"""HVOS Unified CLI — single entry point for all HVOS commands."""
import sys, os

HVOS_ROOT = os.path.dirname(os.path.abspath(__file__))
if HVOS_ROOT not in sys.path:
    sys.path.insert(0, HVOS_ROOT)

def main():
    """Dispatch to sub-commands based on first argument."""
    if len(sys.argv) < 2:
        print("HVOS CLI v10.2")
        print("Usage: python -m hvos <command> [args]")
        print()
        print("Commands:")
        print("  status        System status dashboard")
        print("  scan          Run Opportunity Engine scan")
        print("  train         Run self-training cycle")
        print("  detect        Detect failure patterns")
        print("  test          Run full system test")
        print("  serve         Start API server")
        return 0
    
    cmd = sys.argv[1]
    
    if cmd == 'status':
        import hvos_status
        hvos_status.main()
    elif cmd == 'scan':
        from opportunity.opportunity_engine import main as scan_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        scan_main()
    elif cmd == 'train':
        import self_training
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        if hasattr(self_training, 'main'):
            self_training.main()
        else:
            print("self_training.py has no main() — use module directly")
    elif cmd == 'detect':
        import hvos_evolution_engine
        hvos_evolution_engine.main()
    elif cmd == 'test':
        from tests.v10_closed_loop_test import main as test_main
        test_main()
    elif cmd == 'serve':
        from hvos_api.server import main as serve_main
        serve_main()
    else:
        print(f"Unknown command: {cmd}")
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
