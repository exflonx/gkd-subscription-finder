#!/usr/bin/env python3
"""Unit tests for find_gkd_repos.py"""

import unittest
import unittest.mock
import json
import io
import sys
from datetime import datetime, timezone, timedelta

import find_gkd_repos as fgr


class TestDaysSince(unittest.TestCase):
    """Tests for days_since()"""

    def test_empty_string(self):
        self.assertEqual(fgr.days_since(""), 9999)

    def test_none(self):
        self.assertEqual(fgr.days_since(None), 9999)

    def test_today(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(fgr.days_since(today), 0)

    def test_one_day_ago(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(fgr.days_since(yesterday), 1)

    def test_30_days_ago(self):
        ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(fgr.days_since(ago), 30)

    def test_timezone_suffix(self):
        ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
        self.assertEqual(fgr.days_since(ago), 7)


class TestCheckStopDescription(unittest.TestCase):
    """Tests for check_stop_description()"""

    def test_empty_string(self):
        self.assertFalse(fgr.check_stop_description(""))

    def test_none(self):
        self.assertFalse(fgr.check_stop_description(None))

    def test_normal_description(self):
        self.assertFalse(fgr.check_stop_description("GKD subscription rules"))
        self.assertFalse(fgr.check_stop_description("活跃维护中"))

    def test_chinese_stop_keywords(self):
        self.assertTrue(fgr.check_stop_description("停止维护"))
        self.assertTrue(fgr.check_stop_description("此项目已停更"))
        self.assertTrue(fgr.check_stop_description("不再维护本仓库"))
        self.assertTrue(fgr.check_stop_description("已归档"))

    def test_english_stop_keywords(self):
        self.assertTrue(fgr.check_stop_description("This project is stopped"))
        self.assertTrue(fgr.check_stop_description("DEPRECATED - use new version"))
        self.assertTrue(fgr.check_stop_description("Archived repository"))
        self.assertTrue(fgr.check_stop_description("discontinued"))

    def test_case_insensitive(self):
        self.assertTrue(fgr.check_stop_description("STOPPED"))
        self.assertTrue(fgr.check_stop_description("Deprecated"))
        self.assertTrue(fgr.check_stop_description("已停更"))

    def test_keyword_in_context(self):
        # Keywords are matched by substring, not word boundary
        self.assertTrue(fgr.check_stop_description("GKD订阅规则(已停更2024-01)"))
        self.assertTrue(fgr.check_stop_description("停止维护是不可能的"))
        # Non-matching text
        self.assertFalse(fgr.check_stop_description("GKD 订阅规则 活跃维护"))


class TestBuildSubUrls(unittest.TestCase):
    """Tests for build_sub_urls()"""

    def test_basic_repo(self):
        repo = {"default_branch": "main"}
        primary, candidates = fgr.build_sub_urls("testuser/testrepo", repo)
        self.assertIn("raw.githubusercontent.com", primary)
        self.assertIn("testuser/testrepo/main", primary)
        self.assertIn("dist/gkd.json5", primary)

    def test_custom_branch(self):
        repo = {"default_branch": "master"}
        primary, candidates = fgr.build_sub_urls("foo/bar", repo)
        self.assertIn("foo/bar/master", primary)

    def test_default_branch_fallback(self):
        repo = {}
        primary, candidates = fgr.build_sub_urls("a/b", repo)
        self.assertIn("a/b/main", primary)  # defaults to "main"

    def test_first_candidate_is_primary(self):
        repo = {"default_branch": "main"}
        primary, candidates = fgr.build_sub_urls("x/y", repo)
        self.assertEqual(primary, candidates[0])

    def test_candidates_include_all_patterns(self):
        repo = {"default_branch": "main"}
        primary, candidates = fgr.build_sub_urls("owner/repo", repo)
        self.assertEqual(len(candidates), 6)
        self.assertTrue(any("dist/gkd.json5" in c for c in candidates))
        self.assertTrue(any("gkd.json5" in c for c in candidates))
        self.assertTrue(any("dist/subscription.json5" in c for c in candidates))
        self.assertTrue(any("subscription.json5" in c for c in candidates))
        self.assertTrue(any("owner_gkd.json5" in c for c in candidates))
        self.assertTrue(any("npmmirror.com" in c for c in candidates))

    def test_owner_in_filename(self):
        repo = {"default_branch": "main"}
        primary, candidates = fgr.build_sub_urls("myorg/myrepo", repo)
        self.assertTrue(any("myorg_gkd.json5" in c for c in candidates))


class TestSearchRepos(unittest.TestCase):
    """Tests for search_repos() with mocked API"""

    def test_empty_results(self):
        with unittest.mock.patch("find_gkd_repos.github_api") as mock_api:
            mock_api.return_value = {"items": []}
            results = fgr.search_repos("test query")
            self.assertEqual(results, [])

    def test_single_page(self):
        fake_items = [{"full_name": f"user/repo{i}", "id": i} for i in range(50)]
        with unittest.mock.patch("find_gkd_repos.github_api") as mock_api:
            mock_api.return_value = {"items": fake_items}
            results = fgr.search_repos("test query")
            self.assertEqual(len(results), 50)

    def test_multi_page(self):
        page1 = [{"full_name": f"a/r{i}", "id": i} for i in range(100)]
        page2 = [{"full_name": f"a/r{i+100}", "id": i+100} for i in range(50)]
        with unittest.mock.patch("find_gkd_repos.github_api") as mock_api:
            mock_api.side_effect = [
                {"items": page1},
                {"items": page2},
                {"items": []},
            ]
            results = fgr.search_repos("test query", max_pages=3)
            self.assertEqual(len(results), 150)

    def test_api_error_breaks_loop(self):
        with unittest.mock.patch("find_gkd_repos.github_api") as mock_api:
            mock_api.return_value = None
            results = fgr.search_repos("test query")
            self.assertEqual(results, [])

    def test_max_pages_limit(self):
        # Return full pages so loop doesn't break early
        full_page = [{"full_name": f"x/r{i}", "id": i} for i in range(100)]
        with unittest.mock.patch("find_gkd_repos.github_api") as mock_api:
            mock_api.return_value = {"items": full_page}
            results = fgr.search_repos("test query", max_pages=2)
            self.assertEqual(len(results), 200)


class TestClassificationLogic(unittest.TestCase):
    """Tests for the repo classification logic (extracted from main)"""

    def _classify(self, repos, inactive_days=90):
        """Replicate the classification logic from main() for testing."""
        active = []
        inactive_push = []
        inactive_desc = []
        stopped_known = []

        for full_name, repo in repos.items():
            if full_name in fgr.KNOWN_STOPPED:
                stopped_known.append((full_name, repo))
                continue

            if repo.get("archived", False):
                inactive_desc.append((full_name, repo, "已归档"))
                continue

            desc = repo.get("description") or ""
            if fgr.check_stop_description(desc):
                inactive_desc.append((full_name, repo, "描述含停更关键词"))
                continue

            pushed_at = repo.get("pushed_at", "")
            days = fgr.days_since(pushed_at)
            if days <= inactive_days:
                active.append((full_name, repo, pushed_at))
            else:
                inactive_push.append((full_name, repo, pushed_at))

        return active, inactive_push, inactive_desc, stopped_known

    def test_known_stopped(self):
        repos = {"AIsouler/GKD_subscription": {"pushed_at": "2026-05-19T00:00:00Z"}}
        active, ipush, idesc, stopped = self._classify(repos)
        self.assertEqual(len(stopped), 1)
        self.assertEqual(len(active), 0)

    def test_archived(self):
        repos = {"user/repo": {"archived": True, "pushed_at": "2026-05-19T00:00:00Z"}}
        active, ipush, idesc, stopped = self._classify(repos)
        self.assertEqual(len(idesc), 1)
        self.assertIn("已归档", idesc[0][2])

    def test_stop_description(self):
        repos = {"user/repo": {"description": "停止维护", "pushed_at": "2026-05-19T00:00:00Z"}}
        active, ipush, idesc, stopped = self._classify(repos)
        self.assertEqual(len(idesc), 1)
        self.assertIn("停更", idesc[0][2])

    def test_active_recent_push(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        repos = {"user/repo": {"pushed_at": today}}
        active, ipush, idesc, stopped = self._classify(repos)
        self.assertEqual(len(active), 1)

    def test_inactive_old_push(self):
        old = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        repos = {"user/repo": {"pushed_at": old}}
        active, ipush, idesc, stopped = self._classify(repos)
        self.assertEqual(len(ipush), 1)
        self.assertEqual(len(active), 0)

    def test_sort_by_stars(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        repos = {
            "a/low": {"pushed_at": today, "stargazers_count": 5},
            "b/high": {"pushed_at": today, "stargazers_count": 100},
            "c/mid": {"pushed_at": today, "stargazers_count": 50},
        }
        active, _, _, _ = self._classify(repos)
        active.sort(key=lambda x: x[1].get("stargazers_count", 0), reverse=True)
        self.assertEqual(active[0][0], "b/high")
        self.assertEqual(active[1][0], "c/mid")
        self.assertEqual(active[2][0], "a/low")


class TestConfig(unittest.TestCase):
    """Verify config constants are as expected"""

    def test_inactive_days_is_positive(self):
        self.assertGreater(fgr.INACTIVE_DAYS, 0)

    def test_per_page_is_positive(self):
        self.assertGreater(fgr.PER_PAGE, 0)

    def test_known_stopped_not_empty(self):
        self.assertIsInstance(fgr.KNOWN_STOPPED, set)
        self.assertGreater(len(fgr.KNOWN_STOPPED), 0)

    def test_stop_keywords_not_empty(self):
        self.assertIsInstance(fgr.STOP_KW, list)
        self.assertGreater(len(fgr.STOP_KW), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
