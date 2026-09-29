"""Apply the branch protection and repo settings that governance assumes.

Everything else in the safety work is enforced by files in the repository, which
an agent can write. Branch protection is server-side state, so it needs a token
with `repo` scope once. After that it stays applied.

    setx GITHUB_TOKEN ghp_...            # or put it in the shell for one run
    python -m tools.setup_repo_policy --apply

Without --apply it prints what it would change and touches nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

OWNER = os.getenv("EVMAX_REPO_OWNER", "ylli-B")
REPO = os.getenv("EVMAX_REPO_NAME", "ev-max-platform")
BRANCH = os.getenv("EVMAX_DEFAULT_BRANCH", "master")
API = "https://api.github.com"

# Must match the `name:` of each required job in .github/workflows/ci.yml.
REQUIRED_CHECKS = [
    "Secret scan",
    "Lint and tests",
    "Portfolio leak guard",
]

PROTECTION = {
    "required_status_checks": {"strict": True, "contexts": REQUIRED_CHECKS},
    "enforce_admins": True,
    "required_pull_request_reviews": {
        # Zero approvals: the owner deliberately stays out of the review loop.
        # The gate is CI, not a human rubber stamp.
        "required_approving_review_count": 0,
        "dismiss_stale_reviews": True,
    },
    "restrictions": None,
    "allow_force_pushes": False,
    "allow_deletions": False,
    "required_linear_history": True,
    "required_conversation_resolution": True,
}

REPO_SETTINGS = {
    "allow_auto_merge": True,
    "delete_branch_on_merge": True,
    "allow_squash_merge": True,
    "allow_merge_commit": False,
    "allow_rebase_merge": False,
    "private": True,
}

# Without this, the Auto PR workflow cannot open pull requests and the whole
# hands-off flow silently stops at "branch pushed, nothing happened".
ACTIONS_PERMISSIONS = {
    "default_workflow_permissions": "write",
    "can_approve_pull_request_reviews": True,
}


def _call(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:300]}


def verify_settings(token: str) -> list[str]:
    """Read the settings back and report any the API accepted but did not apply.

    `PATCH /repos` answers 200 for `allow_auto_merge` on a plan that does not
    carry the feature, and simply leaves it false. A 200 is therefore not
    evidence that anything changed, and believing it produces the worst
    outcome available here: governance docs describing a control that does not
    exist. Only a read-back settles it.
    """
    code, current = _call("GET", f"/repos/{OWNER}/{REPO}", token)
    if code >= 300 or not isinstance(current, dict):
        print(f"  could not read settings back (HTTP {code})")
        return []

    ignored = [key for key, wanted in REPO_SETTINGS.items()
               if key in current and current[key] != wanted]
    for key in ignored:
        print(f"  NOT APPLIED: {key} is {current[key]}, asked for {REPO_SETTINGS[key]}")
    if ignored:
        print("  the API returned success and ignored these - usually a plan limit.")
    return ignored


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually change settings")
    args = ap.parse_args()

    print(f"repo   {OWNER}/{REPO}")
    print(f"branch {BRANCH}")
    print("\nwould enforce:")
    print("  private repo, squash-only, auto-merge on, delete branch on merge")
    print("  Actions allowed to open pull requests (required by Auto PR)")
    print(f"  no direct pushes to {BRANCH}, admins included")
    print("  no force pushes, no deletions, linear history")
    print("  required checks: " + ", ".join(REQUIRED_CHECKS))
    print("  0 required approvals (CI is the gate)")

    if not args.apply:
        print("\ndry run. re-run with --apply and GITHUB_TOKEN set.")
        return 0

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        print("GITHUB_TOKEN not set (needs 'repo' scope)", file=sys.stderr)
        return 2

    code, body = _call("PATCH", f"/repos/{OWNER}/{REPO}", token, REPO_SETTINGS)
    print(f"\nrepo settings: HTTP {code}")
    if code >= 300:
        print(f"  {body}")
    ignored = verify_settings(token)

    code, body = _call("PUT", f"/repos/{OWNER}/{REPO}/actions/permissions/workflow",
                       token, ACTIONS_PERMISSIONS)
    print(f"actions may open PRs: HTTP {code}")
    if code >= 300:
        print(f"  {body}")

    code, body = _call("PUT", f"/repos/{OWNER}/{REPO}/branches/{BRANCH}/protection",
                       token, PROTECTION)
    print(f"branch protection: HTTP {code}")
    protection_failed = code >= 300
    if protection_failed:
        print(f"  {body}")
        if code == 403:
            print("  branch protection on a private repo needs a paid plan.")
            print("  Everything else still applies: PRs are opened and merged")
            print("  automatically, and CI must pass before auto-merge fires.")

    # Labels are created even when protection fails.
    for label, colour, desc in [
        ("automerge", "0e8a16", "Safe to merge on green CI"),
    ]:
        c, _ = _call("POST", f"/repos/{OWNER}/{REPO}/labels", token,
                     {"name": label, "color": colour, "description": desc})
        print(f"label {label}: HTTP {c}" + (" (already exists)" if c == 422 else ""))

    if protection_failed or ignored:
        print("\npolicy PARTIALLY applied.")
        if "allow_auto_merge" in ignored or protection_failed:
            print("  Auto-merge and branch protection both need GitHub Pro on a")
            print("  private repo. Until then 'CI gates the merge' is a convention")
            print("  the agents follow, not something the server enforces.")
        return 1

    print("\npolicy applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
