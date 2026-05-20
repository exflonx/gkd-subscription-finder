#!/usr/bin/env python3
"""Search GitHub for actively maintained GKD subscription rule repositories.

Uses GitHub Search API with date filters to minimize API calls.
No per-repo API calls needed — all data comes from search results.
"""

import json
import urllib.request
import urllib.error
import sys
import io
import ssl
import time
from datetime import datetime, timezone, timedelta

# Force UTF-8 output (fix Windows GBK encoding)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ========== CONFIG ==========
GITHUB_TOKEN = ""                # Set your token for higher rate limits
INACTIVE_DAYS = 90               # Repos without pushes in this window are inactive
PER_PAGE = 100

# Known stopped/archived repos (explicit announcements)
KNOWN_STOPPED = {
    "AIsouler/GKD_subscription",
    "Adpro-Team/GKD_subscription",
}

# Stop keywords in description
STOP_KW = ["停止维护", "停更", "已停更", "不再维护", "已归档",
           "stopped", "discontinued", "deprecated", "archived"]


def github_api(path, token=""):
    """Call GitHub REST API with retry on rate limit. Returns parsed JSON or None."""
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "gkd-finder/2.0")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    ctx = ssl.create_default_context()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                # Check for rate limit
                remaining = e.headers.get("X-RateLimit-Remaining", "?")
                reset_ts = e.headers.get("X-RateLimit-Reset", "0")
                if remaining == "0":
                    wait = max(int(reset_ts) - int(time.time()), 1)
                    print(f"  [RATE-LIMIT] 等待 {wait}s ...", file=sys.stderr)
                    time.sleep(min(wait + 2, 60))
                    continue
            elif e.code == 409:  # empty repo
                return None
            body = e.read().decode() if e.fp else ""
            print(f"  [HTTP {e.code}] {url} — {body[:120]}", file=sys.stderr)
            return None
        except Exception as ex:
            if attempt < 2:
                time.sleep(2)
                continue
            print(f"  [ERROR] {url} — {ex}", file=sys.stderr)
            return None
    return None


def search_repos(query, token="", sort="updated", max_pages=5):
    """Search GitHub repos. Returns list of repo dicts."""
    results = []
    for page in range(1, max_pages + 1):
        qs = urllib.request.quote(query)
        path = f"/search/repositories?q={qs}&sort={sort}&order=desc&per_page={PER_PAGE}&page={page}"
        data = github_api(path, token)
        if data is None:
            break
        items = data.get("items", [])
        if not items:
            break
        results.extend(items)
        if len(items) < PER_PAGE:
            break
    return results


def days_since(date_str):
    """Return days since a date string (ISO format)."""
    if not date_str:
        return 9999
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days


def check_stop_description(desc):
    """Check if description indicates stopped maintenance."""
    if not desc:
        return False
    desc_lower = desc.lower()
    return any(kw in desc_lower for kw in STOP_KW)


def main():
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=INACTIVE_DAYS)).strftime("%Y-%m-%d")

    print("=" * 70)
    print("  GKD 活跃订阅规则仓库查找工具")
    print(f"  判定: 最近 {INACTIVE_DAYS} 天内有 push + 未归档 + 未声明停更")
    print(f"  搜索过滤: pushed:>={cutoff_date}")
    print("=" * 70)

    if not GITHUB_TOKEN:
        print("\n[*] 未设置 GITHUB_TOKEN，使用未认证API（搜索限速 10次/分钟）")
        print("[*] 如需更快速度，请在脚本顶部设置 GITHUB_TOKEN\n")

    # -------- Search with pushed date filter --------
    queries = [
        # topic search + pushed filter (most precise)
        f'topic:gkd-subscription pushed:>={cutoff_date}',
        # name/description search + pushed filter
        f'gkd-subscription in:name,description pushed:>={cutoff_date}',
        f'GKD_subscription in:name pushed:>={cutoff_date}',
        f'gkd.json5 in:name,description pushed:>={cutoff_date}',
    ]

    all_repos = {}
    for q in queries:
        print(f"\n>> 搜索: {q}")
        repos = search_repos(q, GITHUB_TOKEN, sort="stars", max_pages=5)
        print(f"   找到 {len(repos)} 个仓库")
        for r in repos:
            full_name = r["full_name"]
            if full_name not in all_repos:
                all_repos[full_name] = r

    print(f"\n--- 去重后共 {len(all_repos)} 个候选仓库 ---\n")

    # -------- Classify --------
    active = []
    inactive_push = []
    inactive_desc = []
    stopped_known = []

    for full_name, repo in all_repos.items():
        # Known stopped
        if full_name in KNOWN_STOPPED:
            stopped_known.append((full_name, repo))
            continue

        # Check archived
        if repo.get("archived", False):
            inactive_desc.append((full_name, repo, "已归档"))
            continue

        # Check description
        desc = repo.get("description") or ""
        if check_stop_description(desc):
            inactive_desc.append((full_name, repo, "描述含停更关键词"))
            continue

        # Check pushed_at date
        pushed_at = repo.get("pushed_at", "")
        days = days_since(pushed_at)
        if days <= INACTIVE_DAYS:
            active.append((full_name, repo, pushed_at))
        else:
            inactive_push.append((full_name, repo, pushed_at))

    # Sort active by stars desc
    active.sort(key=lambda x: x[1].get("stargazers_count", 0), reverse=True)

    # -------- Print results --------
    print("=" * 70)
    print("                        RESULTS")
    print("=" * 70)

    print(f"\n{'='*30} ACTIVE ({len(active)}) {'='*30}")
    print(f"{'Repository':<42} {'Stars':>7} {'Pushed':>12}  Description")
    print("-" * 100)
    for full_name, repo, pushed_at in active:
        stars = repo.get("stargazers_count", 0)
        pushed_short = pushed_at[:10] if pushed_at else "N/A"
        desc = (repo.get("description") or "")[:55]
        url = repo.get("html_url", "")
        print(f"{full_name:<42} {stars:>7} {pushed_short:>12}  {desc}")
        print(f"  -> {url}")

    if not active:
        print("  (none found)")

    print(f"\n{'='*30} KNOWN STOPPED ({len(stopped_known)}) {'='*30}")
    for full_name, repo in stopped_known:
        desc = (repo.get("description") or "")[:60]
        print(f"  {full_name} — {desc}")

    print(f"\n{'='*30} INACTIVE / ARCHIVED / STOPPED ({len(inactive_desc) + len(inactive_push)}) {'='*30}")
    for full_name, repo, reason in inactive_desc:
        pushed = (repo.get("pushed_at") or "N/A")[:10]
        desc = (repo.get("description") or "")[:50]
        print(f"  {full_name:<42} [{reason}] pushed={pushed}  {desc}")
    for full_name, repo, pushed_at in inactive_push:
        pushed = (pushed_at or "N/A")[:10]
        days = days_since(pushed_at)
        desc = (repo.get("description") or "")[:50]
        print(f"  {full_name:<42} [>{INACTIVE_DAYS}d ago] pushed={pushed}  {desc}")

    # -------- Build subscription URLs --------
    def build_sub_urls(full_name, repo):
        """Generate possible subscription URLs for a GKD repo."""
        branch = repo.get("default_branch", "main")
        owner = full_name.split("/")[0]
        raw_base = f"https://raw.githubusercontent.com/{full_name}/{branch}"

        # Common file paths, ordered by likelihood
        candidates = [
            f"{raw_base}/dist/gkd.json5",
            f"{raw_base}/gkd.json5",
            f"{raw_base}/dist/subscription.json5",
            f"{raw_base}/subscription.json5",
            f"{raw_base}/dist/{owner}_gkd.json5",
        ]
        # npmmirror fallback
        npm_name = full_name.split("/")[-1]
        npmmirror_url = f"https://registry.npmmirror.com/@{owner}/{npm_name}/latest/files"
        candidates.append(npmmirror_url)

        return candidates[0], candidates

    # Print subscription URLs
    print(f"\n{'='*30} SUBSCRIPTION URLs ({len(active)}) {'='*30}")
    sub_links = []  # collect primary links for .txt export
    for full_name, repo, pushed_at in active:
        primary, candidates = build_sub_urls(full_name, repo)
        stars = repo.get("stargazers_count", 0)
        sub_links.append((full_name, primary, stars))

        print(f"\n  [{stars} stars] {full_name}")
        print(f"    Primary:  {primary}")
        if len(candidates) > 1:
            print(f"    Alt:      {candidates[1]}")

    # -------- Export subscription links to .txt --------
    txt_file = "gkd_subscription_links.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        for full_name, url, stars in sub_links:
            f.write(f"# [{stars} stars] {full_name}\n")
            f.write(f"{url}\n\n")
    print(f"\n>>> Subscription links exported to: {txt_file}")

    # -------- Export JSON --------
    json_file = "gkd_active_repos.json"
    export = []
    for full_name, repo, pushed_at in active:
        primary, candidates = build_sub_urls(full_name, repo)
        export.append({
            "full_name": full_name,
            "html_url": repo["html_url"],
            "clone_url": repo["clone_url"],
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "description": repo.get("description", ""),
            "pushed_at": pushed_at,
            "topics": repo.get("topics", []),
            "default_branch": repo.get("default_branch", "main"),
            "created_at": repo.get("created_at", ""),
            "subscription_url": primary,
            "subscription_url_alt": candidates[1] if len(candidates) > 1 else None,
        })

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
    print(f">>> Active repos exported to: {json_file}")


if __name__ == "__main__":
    main()
