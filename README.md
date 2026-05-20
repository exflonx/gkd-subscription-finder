# GKD Subscription Finder

Search GitHub for actively maintained [GKD](https://github.com/gkd-kit/gkd) subscription rule repositories.

## Features

- Searches GitHub via topic, name, and description keywords
- Filters by recent push activity (default: 90 days)
- Detects archived and discontinued repos
- Generates subscription URLs (`gkd.json5` links)
- Exports results to JSON and plain text

## Usage

1. (Optional) Set your GitHub token in `find_gkd_repos.py`:
   ```python
   GITHUB_TOKEN = "ghp_xxxxxxxxxxxx"
   ```
   Without a token, unauthenticated search is limited to 10 requests/minute.

2. Run:
   ```bash
   python find_gkd_repos.py
   ```

3. Output files:
   - `gkd_subscription_links.txt` — subscription URLs ready to copy into GKD
   - `gkd_active_repos.json` — full repo metadata including stars, description, and subscription URLs

## Config

Edit the constants at the top of `find_gkd_repos.py`:

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | `""` | GitHub personal access token |
| `INACTIVE_DAYS` | `90` | Repos without pushes in this window are considered inactive |
| `PER_PAGE` | `100` | Results per API page |
