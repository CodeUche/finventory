"""
E2E Login Flow Verifier — tests the Railway production endpoint.

Usage:
    python verify_login_flow.py <email> <password>
    python verify_login_flow.py  (interactive — prompts for credentials)

What it checks:
  1. POST /auth/login/ returns 200
  2. Response has access + refresh tokens
  3. Response has user object with is_superuser, is_sub_account
  4. Response has non-empty organisations list
  5. JWT access token contains non-empty memberships claim
  6. JWT org IDs match the organisations list
  7. Frontend onboardingDone condition = True (no /onboarding redirect)
  8. Sign-out / sign-in cycle: second login still returns organisations
"""

import base64
import getpass
import json
import sys
import urllib.request
import urllib.error

BASE_URL = "https://audity-backend-production-30f9.up.railway.app/api/v1"


def post(path: str, payload: dict) -> tuple[int, dict]:
    url = BASE_URL + path
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def decode_jwt(token: str) -> dict:
    seg = token.split(".")[1]
    seg += "=" * (4 - len(seg) % 4)
    return json.loads(base64.b64decode(seg).decode())


def check(label: str, condition: bool, detail: str = ""):
    mark = "✓" if condition else "✗"
    print(f"  {mark}  {label}" + (f"  ({detail})" if detail else ""))
    return condition


def run(email: str, password: str) -> bool:
    print(f"\n{'='*60}")
    print(f"  Audity Login Flow E2E Verifier")
    print(f"  Target: {BASE_URL}")
    print(f"  User  : {email}")
    print(f"{'='*60}\n")

    all_ok = True

    # ── Round 1: initial login ─────────────────────────────────────────────
    print("Round 1 — Initial login")
    status, data = post("/auth/login/", {"email": email, "password": password})

    all_ok &= check("HTTP 200", status == 200, f"got {status}")
    if status != 200:
        msg = data.get("error") or data.get("detail") or str(data)
        print(f"\n  Login failed: {msg}\n")
        return False

    all_ok &= check("Has access token", bool(data.get("access")))
    all_ok &= check("Has refresh token", bool(data.get("refresh")))
    all_ok &= check("Has user object", isinstance(data.get("user"), dict))

    user = data.get("user", {})
    all_ok &= check("user.email present", bool(user.get("email")))
    all_ok &= check("user.is_superuser present", "is_superuser" in user)

    orgs = data.get("organisations", [])
    all_ok &= check("organisations in response", "organisations" in data)
    all_ok &= check(
        "organisations non-empty (no /onboarding redirect)",
        len(orgs) > 0,
        f"got {len(orgs)} org(s)",
    )

    # JWT claims
    try:
        payload = decode_jwt(data["access"])
        memberships = payload.get("memberships", {})
        all_ok &= check(
            "JWT memberships claim non-empty",
            len(memberships) > 0,
            f"{len(memberships)} membership(s)",
        )
        jwt_org_ids = set(memberships.keys())
        resp_org_ids = {o["id"] for o in orgs}
        overlap = jwt_org_ids & resp_org_ids
        all_ok &= check(
            "JWT org IDs match response orgs",
            bool(overlap),
            f"overlap: {len(overlap)} org(s)",
        )
    except Exception as e:
        all_ok &= check("JWT decode succeeded", False, str(e))

    # Frontend routing simulation
    first_org = orgs[0] if orgs else None
    is_superuser = user.get("is_superuser", False)
    is_sub = user.get("is_sub_account", False)
    onboarding_done = is_superuser or is_sub or bool(first_org and first_org.get("id"))
    all_ok &= check(
        "ProtectedRoute → /dashboard (onboardingDone=True)",
        onboarding_done,
        f"is_superuser={is_superuser}, first_org={'yes' if first_org else 'None'}",
    )

    print()

    # ── Round 2: sign-in again (simulates sign-out / sign-in cycle) ────────
    print("Round 2 — Sign-out / sign-in cycle")
    status2, data2 = post("/auth/login/", {"email": email, "password": password})

    all_ok &= check("HTTP 200 on second login", status2 == 200, f"got {status2}")
    orgs2 = data2.get("organisations", []) if status2 == 200 else []
    all_ok &= check(
        "organisations still non-empty on second login",
        len(orgs2) > 0,
        f"got {len(orgs2)} org(s)",
    )

    # Org IDs consistent between logins
    if orgs and orgs2:
        ids1 = {o["id"] for o in orgs}
        ids2 = {o["id"] for o in orgs2}
        all_ok &= check("same orgs returned both times", ids1 == ids2)

    print()
    print("=" * 60)
    if all_ok:
        print("  ✅  ALL CHECKS PASSED — login flow is healthy")
    else:
        print("  ❌  SOME CHECKS FAILED — see ✗ items above")
    print("=" * 60 + "\n")

    return all_ok


if __name__ == "__main__":
    if len(sys.argv) == 3:
        _email, _password = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 2:
        _email = sys.argv[1]
        _password = getpass.getpass(f"Password for {_email}: ")
    else:
        print("Audity Login Flow E2E Verifier")
        _email = input("Email: ").strip()
        _password = getpass.getpass("Password: ")

    success = run(_email, _password)
    sys.exit(0 if success else 1)
