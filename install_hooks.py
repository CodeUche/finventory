#!/usr/bin/env python3
"""
Install Git hooks for Audity.

Hooks installed:
  pre-push   — runs the smoke test suite before every push.
               Blocks the push if critical tests fail.

Usage:
    python install_hooks.py           # install all hooks
    python install_hooks.py --remove  # remove all installed hooks
"""

import argparse
import os
import stat
import sys
from pathlib import Path

ROOT     = Path(__file__).parent.resolve()
GIT_DIR  = ROOT / ".git"
HOOKS    = GIT_DIR / "hooks"

PRE_PUSH_HOOK = """\
#!/usr/bin/env python3
\"\"\"
Audity pre-push hook.
Runs the smoke test suite before every `git push`.
Push is BLOCKED if smoke tests fail.

Skip once:  git push --no-verify
\"\"\"
import subprocess, sys, os
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[2]   # finventory/
SCRIPT = ROOT / "run_tests.py"

if not SCRIPT.exists():
    print("[pre-push] run_tests.py not found — skipping pre-push checks")
    sys.exit(0)

print("\\n[pre-push] Running smoke tests before push …\\n")
result = subprocess.run(
    [sys.executable, str(SCRIPT), "--smoke", "--fail-fast"],
    cwd=str(ROOT),
)
if result.returncode != 0:
    print("\\n[pre-push] ❌ Smoke tests FAILED — push blocked.")
    print("           Fix the failures, or run `git push --no-verify` to bypass.")
    sys.exit(1)

print("\\n[pre-push] ✅ Smoke tests passed — proceeding with push.")
sys.exit(0)
"""


def install():
    if not GIT_DIR.exists():
        print("ERROR: .git directory not found. Run from inside the git repository.")
        sys.exit(1)

    HOOKS.mkdir(exist_ok=True)
    hook_path = HOOKS / "pre-push"
    hook_path.write_text(PRE_PUSH_HOOK, encoding="utf-8")

    # Make executable (Unix)
    current = os.stat(hook_path).st_mode
    os.chmod(hook_path, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"✓ pre-push hook installed → {hook_path}")
    print("  Every `git push` will now run the smoke test suite first.")
    print("  To bypass once: git push --no-verify")


def remove():
    hook_path = HOOKS / "pre-push"
    if hook_path.exists():
        hook_path.unlink()
        print(f"✓ pre-push hook removed from {hook_path}")
    else:
        print("No hooks to remove.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Install / remove Audity Git hooks")
    p.add_argument("--remove", action="store_true", help="Remove all installed hooks")
    args = p.parse_args()
    remove() if args.remove else install()
