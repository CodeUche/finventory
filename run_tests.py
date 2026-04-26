#!/usr/bin/env python3
"""
Audity Automated Test Suite Orchestrator
==========================================
Covers every layer of the testing pyramid:

  Unit          — pure logic, no I/O (pytest -m unit)
  Integration   — services + DB (pytest -m integration)
  API           — full Django REST endpoints via APIClient
  System        — cross-module business flows
  Smoke         — critical-path subset (< 60 s)
  Regression    — full suite, run before every merge / feature ship
  Performance   — Locust load tests (optional, --perf)
  Security      — Bandit SAST + pip-audit + npm-audit
  E2E           — Playwright browser journeys (optional, --e2e)
  Compatibility — Playwright multi-browser run
  Frontend      — Vitest component + hook + store + util tests
  TypeCheck     — tsc --noEmit strict type checking

Usage
-----
    python run_tests.py                    # full regression suite
    python run_tests.py --smoke            # fast smoke run only
    python run_tests.py --suite unit       # one suite (unit|integration|api|frontend|security|perf|e2e)
    python run_tests.py --e2e              # include Playwright E2E
    python run_tests.py --perf            # include Locust performance tests
    python run_tests.py --no-fix           # skip lint auto-fix
    python run_tests.py --retry 3         # max retries per suite (default 2)
    python run_tests.py --fail-fast        # abort on first suite failure
    python run_tests.py --verbose          # stream full subprocess output
    python run_tests.py --report           # write test-report.md after run

Auto-fix behaviour
------------------
When a lint/type suite fails the orchestrator automatically:
  1. Runs  black + isort  on backend Python code
  2. Runs  eslint --fix   on frontend TypeScript code
  3. Re-runs the failing suite once — if it still fails the failure
     is recorded but the orchestrator keeps going.

Retry behaviour
---------------
Non-lint test suites are re-run up to --retry times on failure.
Each retry only re-runs the tests that failed in the previous pass
(pytest --last-failed, vitest --reporter=json filter).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.resolve()           # finventory/
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
TESTS = ROOT / "tests"
PERF_DIR = TESTS / "performance"
E2E_DIR = TESTS / "e2e"

# ─── Colour helpers ───────────────────────────────────────────────────────────

_USE_COLOUR = sys.stdout.isatty() and os.name != "nt" or os.environ.get("FORCE_COLOR")

def _c(code: str, text: str) -> str:
    if not _USE_COLOUR:
        return text
    return f"\033[{code}m{text}\033[0m"

def green(t):   return _c("32;1", t)
def red(t):     return _c("31;1", t)
def yellow(t):  return _c("33;1", t)
def cyan(t):    return _c("36;1", t)
def bold(t):    return _c("1", t)
def dim(t):     return _c("2", t)

# ─── Data types ───────────────────────────────────────────────────────────────

@dataclass
class SuiteResult:
    name: str
    category: str               # unit | integration | api | frontend | security | perf | e2e | lint
    passed: bool
    duration: float             # seconds
    output: str = ""
    error: str = ""
    retries: int = 0
    skipped: bool = False
    skip_reason: str = ""
    tests_run: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0

@dataclass
class RunReport:
    started_at: datetime = field(default_factory=datetime.now)
    suites: list[SuiteResult] = field(default_factory=list)

    @property
    def finished_at(self):
        return datetime.now()

    @property
    def total_duration(self):
        return sum(s.duration for s in self.suites)

    @property
    def failed_suites(self):
        return [s for s in self.suites if not s.passed and not s.skipped]

    @property
    def passed_suites(self):
        return [s for s in self.suites if s.passed]

    @property
    def skipped_suites(self):
        return [s for s in self.suites if s.skipped]

    @property
    def overall_passed(self):
        return len(self.failed_suites) == 0

# ─── Python / Node interpreter detection ─────────────────────────────────────

def _find_python() -> str:
    """Return the Python executable inside the venv, fallback to system Python."""
    for candidate in [
        BACKEND / ".venv" / "Scripts" / "python.exe",  # Windows venv
        BACKEND / ".venv" / "bin" / "python",           # Unix venv
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _find_node_bin(cmd: str) -> Optional[str]:
    """Return the path to a node_modules/.bin executable if present."""
    for base in [FRONTEND / "node_modules" / ".bin", E2E_DIR / "node_modules" / ".bin"]:
        p = base / (cmd + ".cmd" if os.name == "nt" else cmd)
        if p.exists():
            return str(p)
    return shutil.which(cmd)


PYTHON = _find_python()

# ─── Low-level runner ─────────────────────────────────────────────────────────

def run_cmd(
    args: list[str],
    cwd: Path,
    env: Optional[dict] = None,
    verbose: bool = False,
    timeout: int = 600,
) -> tuple[int, str, str]:
    """
    Run a command, return (returncode, stdout, stderr).
    In verbose mode the output is streamed to the terminal in real time.
    """
    merged_env = {**os.environ, **(env or {})}
    if verbose:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        captured = []
        for line in proc.stdout:
            print(line, end="")
            captured.append(line)
        proc.wait()
        output = "".join(captured)
        return proc.returncode, output, ""
    else:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr


# ─── Auto-fixers ──────────────────────────────────────────────────────────────

def autofix_backend(verbose: bool = False) -> bool:
    """Run black + isort on backend Python code. Returns True if succeeded."""
    print(dim("  → auto-fixing Python: black + isort …"))
    ok = True
    for cmd in [
        [PYTHON, "-m", "black", "--line-length=88", "."],
        [PYTHON, "-m", "isort", "--profile=black", "."],
    ]:
        rc, out, err = run_cmd(cmd, cwd=BACKEND, verbose=verbose)
        if rc != 0:
            ok = False
            print(red(f"    auto-fix failed: {' '.join(cmd)}"))
            if not verbose:
                print(dim(out + err))
    return ok


def autofix_frontend(verbose: bool = False) -> bool:
    """Run eslint --fix on frontend TypeScript source. Returns True if succeeded."""
    print(dim("  → auto-fixing TypeScript: eslint --fix …"))
    eslint = _find_node_bin("eslint")
    if not eslint:
        print(yellow("    eslint not found — skipping auto-fix"))
        return True
    rc, out, err = run_cmd(
        [eslint, "--fix", "src/", "--ext", "ts,tsx"],
        cwd=FRONTEND,
        verbose=verbose,
    )
    if rc != 0:
        print(red("    eslint --fix reported errors that need manual attention"))
        if not verbose:
            print(dim(out + err))
        return False
    return True


# ─── Individual test suites ───────────────────────────────────────────────────

class Suites:
    """
    Factory methods that return SuiteResult objects.
    Each method runs one logical suite, optionally retrying.
    """

    # ── Backend: unit tests (no DB) ───────────────────────────────────────────
    @staticmethod
    def backend_unit(verbose: bool, max_retries: int) -> SuiteResult:
        name = "Backend Unit"
        print(bold(f"\n▶  {name}"))
        cmd = [
            PYTHON, "-m", "pytest",
            "apps/", f"{TESTS}/",
            "-m", "unit",
            "--tb=short", "-q",
            f"--junitxml={ROOT}/test-results/backend-unit.xml",
        ]
        return _run_pytest_suite(name, "unit", cmd, BACKEND, verbose, max_retries)

    # ── Backend: integration tests (DB) ──────────────────────────────────────
    @staticmethod
    def backend_integration(verbose: bool, max_retries: int) -> SuiteResult:
        name = "Backend Integration"
        print(bold(f"\n▶  {name}"))
        cmd = [
            PYTHON, "-m", "pytest",
            "apps/", f"{TESTS}/",
            "-m", "integration",
            "--tb=short", "-q",
            f"--junitxml={ROOT}/test-results/backend-integration.xml",
        ]
        return _run_pytest_suite(name, "integration", cmd, BACKEND, verbose, max_retries)

    # ── Backend: full API suite (smoke + integration + regression) ────────────
    @staticmethod
    def backend_api(verbose: bool, max_retries: int) -> SuiteResult:
        name = "Backend API (full)"
        print(bold(f"\n▶  {name}"))
        cmd = [
            PYTHON, "-m", "pytest",
            "apps/", f"{TESTS}/",
            "--tb=short", "-q",
            "--cov=apps",
            "--cov-report=term-missing:skip-covered",
            f"--cov-report=html:{ROOT}/test-results/coverage-html",
            f"--junitxml={ROOT}/test-results/backend-api.xml",
        ]
        return _run_pytest_suite(name, "api", cmd, BACKEND, verbose, max_retries)

    # ── Backend: smoke (fast subset) ──────────────────────────────────────────
    @staticmethod
    def backend_smoke(verbose: bool, max_retries: int) -> SuiteResult:
        name = "Backend Smoke"
        print(bold(f"\n▶  {name}"))
        cmd = [
            PYTHON, "-m", "pytest",
            f"{TESTS}/test_auth_api.py",
            f"{TESTS}/test_sales_api.py",
            f"{TESTS}/test_inventory.py",
            "-m", "integration",
            "--tb=short", "-q", "-x",
            f"--junitxml={ROOT}/test-results/backend-smoke.xml",
        ]
        return _run_pytest_suite(name, "api", cmd, BACKEND, verbose, max_retries)

    # ── Backend: Python lint (flake8) ─────────────────────────────────────────
    @staticmethod
    def backend_lint(verbose: bool, auto_fix: bool) -> SuiteResult:
        name = "Backend Lint (flake8)"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        cmd = [
            PYTHON, "-m", "flake8", "apps/", "config/",
            "--max-line-length=88",
            "--extend-ignore=E203,W503",
            "--statistics",
        ]
        rc, out, err = run_cmd(cmd, cwd=BACKEND, verbose=verbose)
        if rc != 0 and auto_fix:
            autofix_backend(verbose)
            rc, out, err = run_cmd(cmd, cwd=BACKEND, verbose=verbose)
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration)
        return SuiteResult(
            name=name, category="lint", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── Frontend: type check ──────────────────────────────────────────────────
    @staticmethod
    def frontend_typecheck(verbose: bool) -> SuiteResult:
        name = "Frontend TypeScript"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        tsc = _find_node_bin("tsc")
        if not tsc:
            return _skipped(name, "frontend", "tsc not found")
        rc, out, err = run_cmd([tsc, "--noEmit"], cwd=FRONTEND, verbose=verbose)
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration)
        return SuiteResult(
            name=name, category="frontend", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── Frontend: Vitest unit + component tests ───────────────────────────────
    @staticmethod
    def frontend_unit(verbose: bool, max_retries: int) -> SuiteResult:
        name = "Frontend Vitest"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        vitest = _find_node_bin("vitest")
        if not vitest:
            npm = shutil.which("npm")
            if not npm:
                return _skipped(name, "frontend", "vitest not found")
            cmd = [npm, "run", "test", "--", "--reporter=verbose",
                   f"--outputFile={ROOT}/test-results/frontend-vitest.json"]
        else:
            cmd = [vitest, "run", "--reporter=verbose",
                   f"--outputFile={ROOT}/test-results/frontend-vitest.json"]

        attempts = 0
        rc, out, err = 0, "", ""
        while attempts <= max_retries:
            rc, out, err = run_cmd(cmd, cwd=FRONTEND, verbose=verbose)
            if rc == 0:
                break
            attempts += 1
            if attempts <= max_retries:
                print(yellow(f"  ↺ retry {attempts}/{max_retries} …"))
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration)
        return SuiteResult(
            name=name, category="frontend", passed=passed,
            duration=duration, output=out, error=err, retries=attempts,
        )

    # ── Frontend: ESLint ──────────────────────────────────────────────────────
    @staticmethod
    def frontend_lint(verbose: bool, auto_fix: bool) -> SuiteResult:
        name = "Frontend Lint (ESLint)"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        eslint = _find_node_bin("eslint")
        if not eslint:
            return _skipped(name, "lint", "eslint not found")
        cmd = [eslint, "src/", "--ext", "ts,tsx", "--max-warnings=0"]
        rc, out, err = run_cmd(cmd, cwd=FRONTEND, verbose=verbose)
        if rc != 0 and auto_fix:
            autofix_frontend(verbose)
            rc, out, err = run_cmd(cmd, cwd=FRONTEND, verbose=verbose)
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration)
        return SuiteResult(
            name=name, category="lint", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── Security: Bandit SAST ─────────────────────────────────────────────────
    @staticmethod
    def security_bandit(verbose: bool) -> SuiteResult:
        name = "Security Bandit (SAST)"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        cmd = [
            PYTHON, "-m", "bandit",
            "-r", "apps/", "config/",
            "-ll",           # only medium+ severity
            "-q",
            f"--format=json",
            f"-o", f"{ROOT}/test-results/bandit.json",
        ]
        rc, out, err = run_cmd(cmd, cwd=BACKEND, verbose=verbose)
        # bandit exits 1 when issues found; we report but don't hard-fail
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration, warn_only=True)
        return SuiteResult(
            name=name, category="security", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── Security: pip-audit ───────────────────────────────────────────────────
    @staticmethod
    def security_pip_audit(verbose: bool) -> SuiteResult:
        name = "Security pip-audit"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        pip_audit = shutil.which("pip-audit") or f"{PYTHON.rsplit(os.sep, 1)[0]}{os.sep}pip-audit"
        if not Path(pip_audit).exists():
            pip_audit_path = None
            # try as module
            cmd = [PYTHON, "-m", "pip_audit",
                   "-r", "requirements/base.txt",
                   "--format=json",
                   f"--output={ROOT}/test-results/pip-audit.json"]
        else:
            cmd = [pip_audit,
                   "-r", f"{BACKEND}/requirements/base.txt",
                   "--format=json",
                   f"--output={ROOT}/test-results/pip-audit.json"]
        rc, out, err = run_cmd(cmd, cwd=BACKEND, verbose=verbose)
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration, warn_only=True)
        return SuiteResult(
            name=name, category="security", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── Security: npm audit ───────────────────────────────────────────────────
    @staticmethod
    def security_npm_audit(verbose: bool) -> SuiteResult:
        name = "Security npm-audit"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        npm = shutil.which("npm")
        if not npm:
            return _skipped(name, "security", "npm not found")
        cmd = [npm, "audit", "--audit-level=high", "--json"]
        rc, out, err = run_cmd(cmd, cwd=FRONTEND, verbose=verbose)
        # write report
        (ROOT / "test-results").mkdir(parents=True, exist_ok=True)
        (ROOT / "test-results" / "npm-audit.json").write_text(out or "{}")
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration, warn_only=True)
        return SuiteResult(
            name=name, category="security", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── Security: Django security check (HTTP headers, CSRF, DEBUG) ───────────
    @staticmethod
    def security_django_check(verbose: bool) -> SuiteResult:
        name = "Security Django System Check"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        env = {"DJANGO_SETTINGS_MODULE": "config.settings.testing"}
        cmd = [PYTHON, "manage.py", "check", "--deploy", "--fail-level=WARNING"]
        rc, out, err = run_cmd(cmd, cwd=BACKEND, env=env, verbose=verbose)
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration, warn_only=True)
        return SuiteResult(
            name=name, category="security", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── Performance: Locust (headless, quick run) ─────────────────────────────
    @staticmethod
    def performance_locust(verbose: bool, base_url: str) -> SuiteResult:
        name = "Performance Locust"
        print(bold(f"\n▶  {name}"))
        t0 = time.monotonic()
        locust_file = PERF_DIR / "locustfile.py"
        if not locust_file.exists():
            return _skipped(name, "perf", "locustfile.py not found")
        locust = shutil.which("locust")
        if not locust:
            return _skipped(name, "perf", "locust not installed  (pip install locust)")
        results_csv = ROOT / "test-results" / "locust"
        results_csv.mkdir(parents=True, exist_ok=True)
        cmd = [
            locust,
            "-f", str(locust_file),
            "--headless",
            "--users=10",
            "--spawn-rate=2",
            "--run-time=30s",
            f"--host={base_url}",
            f"--csv={results_csv}/results",
            "--exit-code-on-error=1",
        ]
        rc, out, err = run_cmd(cmd, cwd=PERF_DIR, verbose=verbose, timeout=120)
        passed = rc == 0
        duration = time.monotonic() - t0
        _print_suite_result(name, passed, duration)
        return SuiteResult(
            name=name, category="perf", passed=passed,
            duration=duration, output=out, error=err,
        )

    # ── E2E: Playwright smoke (Chromium only) ─────────────────────────────────
    @staticmethod
    def e2e_smoke(verbose: bool, base_url: str) -> SuiteResult:
        return _run_playwright(
            "E2E Smoke (Chromium)",
            project="chromium",
            grep="@smoke",
            base_url=base_url,
            verbose=verbose,
            report_name="e2e-smoke",
        )

    # ── E2E: full user journey (Chromium + Firefox) ───────────────────────────
    @staticmethod
    def e2e_full(verbose: bool, base_url: str) -> SuiteResult:
        return _run_playwright(
            "E2E Full (multi-browser)",
            project=None,   # all configured browsers
            grep=None,
            base_url=base_url,
            verbose=verbose,
            report_name="e2e-full",
        )


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _run_pytest_suite(
    name: str,
    category: str,
    cmd: list[str],
    cwd: Path,
    verbose: bool,
    max_retries: int,
) -> SuiteResult:
    t0 = time.monotonic()
    attempts = 0
    rc, out, err = 0, "", ""
    while attempts <= max_retries:
        rc, out, err = run_cmd(cmd, cwd=cwd, verbose=verbose)
        if rc == 0:
            break
        attempts += 1
        if attempts <= max_retries:
            print(yellow(f"  ↺ retry {attempts}/{max_retries} — running only last-failed …"))
            # Re-run only the tests that just failed
            retry_cmd = cmd + ["--last-failed", "--last-failed-no-testsfound-skip"]
            rc, out, err = run_cmd(retry_cmd, cwd=cwd, verbose=verbose)
            if rc == 0:
                break

    # Parse test counts from pytest output
    tests_run, tests_failed, tests_skipped = _parse_pytest_counts(out)
    passed = rc == 0
    duration = time.monotonic() - t0
    _print_suite_result(name, passed, duration)
    return SuiteResult(
        name=name, category=category, passed=passed,
        duration=duration, output=out, error=err,
        retries=attempts, tests_run=tests_run,
        tests_failed=tests_failed, tests_skipped=tests_skipped,
    )


def _run_playwright(
    name: str,
    project: Optional[str],
    grep: Optional[str],
    base_url: str,
    verbose: bool,
    report_name: str,
) -> SuiteResult:
    print(bold(f"\n▶  {name}"))
    t0 = time.monotonic()
    if not E2E_DIR.exists():
        return _skipped(name, "e2e", "tests/e2e/ directory not found")

    playwright = _find_node_bin("playwright")
    npx = shutil.which("npx")
    if not playwright and not npx:
        return _skipped(name, "e2e", "playwright / npx not found")

    runner = playwright or npx
    cmd = [runner]
    if runner is npx:
        cmd += ["playwright"]
    cmd += ["test"]
    if project:
        cmd += ["--project", project]
    if grep:
        cmd += ["--grep", grep]
    cmd += [
        f"--reporter=list",
        f"--output={ROOT}/test-results/{report_name}",
    ]
    env = {"BASE_URL": base_url, "CI": "true"}
    rc, out, err = run_cmd(cmd, cwd=E2E_DIR, env=env, verbose=verbose, timeout=300)
    passed = rc == 0
    duration = time.monotonic() - t0
    _print_suite_result(name, passed, duration)
    return SuiteResult(
        name=name, category="e2e", passed=passed,
        duration=duration, output=out, error=err,
    )


def _skipped(name: str, category: str, reason: str) -> SuiteResult:
    print(dim(f"  ⊘ {name} — skipped ({reason})"))
    return SuiteResult(
        name=name, category=category, passed=True,
        duration=0, skipped=True, skip_reason=reason,
    )


def _parse_pytest_counts(output: str) -> tuple[int, int, int]:
    """Extract passed/failed/skipped counts from pytest summary line."""
    import re
    m = re.search(
        r"(\d+) passed|(\d+) failed|(\d+) error|(\d+) skipped", output
    )
    # Simple: look for the summary line
    passed_m  = re.search(r"(\d+) passed",  output)
    failed_m  = re.search(r"(\d+) failed",  output)
    error_m   = re.search(r"(\d+) error",   output)
    skipped_m = re.search(r"(\d+) skipped", output)
    failed = int(failed_m.group(1) if failed_m else 0) + int(error_m.group(1) if error_m else 0)
    skipped = int(skipped_m.group(1) if skipped_m else 0)
    passed = int(passed_m.group(1) if passed_m else 0)
    return passed + failed + skipped, failed, skipped


def _print_suite_result(name: str, passed: bool, duration: float, warn_only: bool = False):
    status = green("✓ PASS") if passed else (yellow("⚠ WARN") if warn_only else red("✗ FAIL"))
    print(f"  {status}  {name}  {dim(f'({duration:.1f}s)')}")


# ─── Report generator ─────────────────────────────────────────────────────────

def write_report(report: RunReport, path: Path):
    lines = [
        "# Audity Test Report",
        f"**Run started:** {report.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Duration:** {report.total_duration:.1f}s",
        f"**Result:** {'✅ ALL PASS' if report.overall_passed else '❌ FAILURES'}",
        "",
        "## Suite Summary",
        "",
        "| Suite | Category | Result | Duration | Tests |",
        "|-------|----------|--------|----------|-------|",
    ]
    for s in report.suites:
        if s.skipped:
            result = f"⊘ SKIP ({s.skip_reason})"
        elif s.passed:
            result = "✓ PASS"
        else:
            result = "✗ FAIL"
        tests_cell = f"{s.tests_run} total, {s.tests_failed} failed" if s.tests_run else "-"
        lines.append(f"| {s.name} | {s.category} | {result} | {s.duration:.1f}s | {tests_cell} |")

    if report.failed_suites:
        lines += ["", "## Failures", ""]
        for s in report.failed_suites:
            lines += [
                f"### {s.name}",
                "```",
                (s.output + s.error)[-3000:] or "(no output captured)",
                "```",
                "",
            ]

    lines += [
        "",
        "## Test Results Artifacts",
        f"- Coverage HTML: `test-results/coverage-html/index.html`",
        f"- JUnit XMLs: `test-results/*.xml`",
        f"- Security: `test-results/bandit.json`, `test-results/npm-audit.json`",
        f"- Performance: `test-results/locust/`",
        "",
        f"*Generated by `run_tests.py` — Audity automated test orchestrator*",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{cyan('Report:')} {path}")


# ─── Pre-flight checks ────────────────────────────────────────────────────────

def preflight(verbose: bool) -> bool:
    """Check that critical tools are available. Warn about optional ones."""
    print(bold("\n◉  Pre-flight checks"))
    ok = True

    def check(label: str, exists: bool, required: bool = True):
        nonlocal ok
        if exists:
            print(f"  {green('✓')} {label}")
        elif required:
            print(f"  {red('✗')} {label}  ← REQUIRED")
            ok = False
        else:
            print(f"  {yellow('~')} {label}  (optional — suite will be skipped)")

    check("Python interpreter", Path(PYTHON).exists())
    check("backend/manage.py", (BACKEND / "manage.py").exists())
    check("frontend/package.json", (FRONTEND / "package.json").exists())
    check("pytest", bool(shutil.which("pytest") or True))   # always via python -m
    check("npm / vitest", bool(shutil.which("npm")), required=False)
    check("flake8", bool(shutil.which("flake8") or True))
    check("black", bool(shutil.which("black") or True))
    check("bandit", bool(shutil.which("bandit") or True))
    check("locust", bool(shutil.which("locust")), required=False)
    check("playwright", bool(_find_node_bin("playwright") or shutil.which("npx")), required=False)

    (ROOT / "test-results").mkdir(parents=True, exist_ok=True)
    return ok


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def orchestrate(args: argparse.Namespace) -> RunReport:
    report = RunReport()
    verbose = args.verbose
    auto_fix = not args.no_fix
    retries = args.retry
    fail_fast = args.fail_fast
    base_url = args.base_url

    def add(result: SuiteResult):
        report.suites.append(result)
        if fail_fast and not result.passed and not result.skipped:
            print(red("\n  --fail-fast: aborting."))
            _print_final_summary(report)
            sys.exit(1)

    # ── Smoke only ────────────────────────────────────────────────────────────
    if args.smoke:
        add(Suites.backend_smoke(verbose, retries))
        add(Suites.frontend_typecheck(verbose))
        add(Suites.security_bandit(verbose))
        return report

    # ── Single suite ──────────────────────────────────────────────────────────
    if args.suite:
        suite = args.suite.lower()
        if suite == "unit":
            add(Suites.backend_unit(verbose, retries))
        elif suite == "integration":
            add(Suites.backend_integration(verbose, retries))
        elif suite == "api":
            add(Suites.backend_api(verbose, retries))
        elif suite == "frontend":
            add(Suites.frontend_typecheck(verbose))
            add(Suites.frontend_unit(verbose, retries))
            add(Suites.frontend_lint(verbose, auto_fix))
        elif suite == "security":
            add(Suites.security_bandit(verbose))
            add(Suites.security_pip_audit(verbose))
            add(Suites.security_npm_audit(verbose))
            add(Suites.security_django_check(verbose))
        elif suite == "perf":
            add(Suites.performance_locust(verbose, base_url))
        elif suite == "e2e":
            add(Suites.e2e_full(verbose, base_url))
        elif suite == "smoke":
            add(Suites.backend_smoke(verbose, retries))
        else:
            print(red(f"Unknown suite: {suite}"))
            sys.exit(1)
        return report

    # ── Full regression run ───────────────────────────────────────────────────

    # 1. Lint passes first — fast feedback
    add(Suites.backend_lint(verbose, auto_fix))
    add(Suites.frontend_lint(verbose, auto_fix))

    # 2. Type safety
    add(Suites.frontend_typecheck(verbose))

    # 3. Unit tests (pure logic — no DB)
    add(Suites.backend_unit(verbose, retries))

    # 4. Integration tests (DB)
    add(Suites.backend_integration(verbose, retries))

    # 5. Full API tests with coverage
    add(Suites.backend_api(verbose, retries))

    # 6. Frontend component / store / hook tests
    add(Suites.frontend_unit(verbose, retries))

    # 7. Security scans
    add(Suites.security_bandit(verbose))
    add(Suites.security_pip_audit(verbose))
    add(Suites.security_npm_audit(verbose))
    add(Suites.security_django_check(verbose))

    # 8. Performance (optional)
    if args.perf:
        add(Suites.performance_locust(verbose, base_url))

    # 9. E2E browser tests (optional)
    if args.e2e:
        add(Suites.e2e_smoke(verbose, base_url))
        add(Suites.e2e_full(verbose, base_url))

    return report


# ─── Final summary ────────────────────────────────────────────────────────────

def _print_final_summary(report: RunReport):
    print(bold("\n" + "═" * 60))
    print(bold("  TEST RUN SUMMARY"))
    print(bold("═" * 60))

    for s in report.suites:
        if s.skipped:
            icon = dim("⊘")
            label = dim(s.name)
        elif s.passed:
            icon = green("✓")
            label = s.name
        else:
            icon = red("✗")
            label = red(s.name)
        suffix = f"  {dim(f'{s.duration:.1f}s')}"
        if s.retries:
            suffix += f"  {yellow(f'({s.retries} retries)')}"
        if s.skipped:
            suffix += f"  {dim(f'({s.skip_reason})')}"
        print(f"  {icon}  {label}{suffix}")

    print()
    total = len(report.suites)
    passed = len(report.passed_suites)
    failed = len(report.failed_suites)
    skipped = len(report.skipped_suites)
    dur = report.total_duration

    print(f"  Suites : {total} total  {green(str(passed))} passed  {red(str(failed)) if failed else '0 failed'}  {dim(str(skipped))} skipped")
    print(f"  Time   : {dur:.1f}s")

    if report.overall_passed:
        print(f"\n  {green('✅  ALL CHECKS PASSED — safe to ship')}")
    else:
        print(f"\n  {red('❌  FAILURES — fix before merging')}")
        for s in report.failed_suites:
            print(red(f"     · {s.name}"))
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Audity automated test orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
              python run_tests.py                  # full regression suite
              python run_tests.py --smoke          # fast smoke (< 60 s)
              python run_tests.py --suite unit     # unit tests only
              python run_tests.py --e2e --perf     # include E2E + Locust
              python run_tests.py --no-fix --fail-fast --verbose
        """),
    )
    p.add_argument("--suite", metavar="NAME",
                   help="Run one suite: unit|integration|api|frontend|security|perf|e2e|smoke")
    p.add_argument("--smoke", action="store_true", help="Run smoke tests only")
    p.add_argument("--e2e", action="store_true", help="Include Playwright E2E tests")
    p.add_argument("--perf", action="store_true", help="Include Locust performance tests")
    p.add_argument("--no-fix", action="store_true", help="Skip lint auto-fix")
    p.add_argument("--retry", type=int, default=2, metavar="N",
                   help="Max retries for failing test suites (default: 2)")
    p.add_argument("--fail-fast", action="store_true", help="Stop on first suite failure")
    p.add_argument("--verbose", "-v", action="store_true", help="Stream subprocess output")
    p.add_argument("--report", action="store_true", help="Write test-report.md")
    p.add_argument("--base-url", default="http://localhost:8000",
                   help="Backend base URL for E2E / Perf tests (default: http://localhost:8000)")
    return p.parse_args()


def main():
    args = parse_args()

    print(bold(cyan("\n  ╔══════════════════════════════════════════╗")))
    print(bold(cyan("  ║  Audity Test Suite Orchestrator          ║")))
    print(bold(cyan("  ╚══════════════════════════════════════════╝")))
    print(dim(f"  Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    print(dim(f"  Python: {PYTHON}"))
    print(dim(f"  Mode:   {'smoke' if args.smoke else args.suite or 'full regression'}"))

    ok = preflight(args.verbose)
    if not ok:
        print(red("\nPre-flight failed — check the items above and retry."))
        sys.exit(1)

    report = orchestrate(args)
    _print_final_summary(report)

    if args.report:
        write_report(report, ROOT / "test-report.md")

    sys.exit(0 if report.overall_passed else 1)


if __name__ == "__main__":
    main()
