# Coding Plan Dashboard

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![CI](https://github.com/margrop/coding-plan-dashboard/actions/workflows/test.yml/badge.svg)](./.github/workflows/test.yml)

A single-page dashboard that aggregates the coding-plan quotas of multiple AI providers
(Codex, MiniMax, Volcengine AgentPlan / CodingPlan, Kimi Code, LongCat, Qianwen AI,
Zhipu AI CodingPlan and Google AI Gemini Models) into one self-hosted UI. Each provider supports multiple
accounts with independent labels.

一个部署在局域网中的 Coding Plan 配额看板，支持 Codex、MiniMax、火山方舟 CodingPlan /
AgentPlan、Kimi Code、LongCat、千问 AI、智谱 AI CodingPlan 和 Google AI Gemini Models。支持同一平台
多账号，每个账号可添加备注。Google AI 显示 Gemini Models 的 5 小时和周额度。

## Features / 功能

- Auto-detects the data source from the imported raw `curl` URL — no manual selection
  needed. / 根据原始 `curl` URL 自动识别数据来源，不需要手工选择产品。
- The server re-executes saved requests on page open, manual refresh, or auto refresh;
  results are persisted as JSON on the host so they survive container restarts.
  / 页面打开、刷新或点击刷新按钮时由服务器重新执行已保存的请求；配额结果保存到服务器端
  JSON 文件，容器重启后自动恢复。
- First paint shows the cached snapshot then silently refreshes to the latest data;
  successful refreshes do not pop up any dialog.
- Five built-in visual themes (Aurora, Ocean, Forest, Sunset and Paper), each with
  Light / Dark modes. The selected theme and mode are saved in browser local storage;
  the appearance controls are available after unlocking the page.
- Multi-account support: each imported curl is stored as a separate account with its
  own ID, label, edit, delete (with double confirm), and reorder controls.
- Existing Kimi accounts can update request verification headers from a fresh
  `GetSubscriptionStats` curl without replacing the saved URL, body, or account.
- Existing Kimi accounts can save a complete `RefreshToken` directly; every quota
  refresh then exchanges the stored token before calling `GetSubscriptionStats`, and
  persists rotated access / refresh tokens plus response cookies when provided.
- Existing MiniMax accounts can update verification headers from a fresh
  `token_plan/remains_percent` curl while preserving the account and request body.
- Refresh failures, including supported provider business errors returned with HTTP
  200, keep the last successful cached result visible with an error notice.
- Per-account Volcengine AK/SK configuration (no curl required); uses HMAC-SHA256 V4
  signing against `GetCodingPlanUsage` / `GetAgentPlanAFPUsage`.
- Codex supports both the official `/usage` + `/rate-limit-reset-credits` endpoints
  and a NewAPI replacement (`/api/channel/{channelId}/codex/usage[/reset-credits]`).
  The server merges them into a single Codex card and skips the official requests
  when a NewAPI variant is configured.
- All progress bars show two-decimal usage percentage; each card shows a live
  countdown to the next reset. Reset dates are shown when at least one day remains;
  shorter waits show only the countdown. A normalized zero quota limit is displayed
  as **已过期**; authentication failures are reported separately.
- Self-contained single-file browser UI (`index.html`) with a custom SVG logo and no
  external favicon dependency.

## File Layout

```text
index.html          Single-file frontend
server.py           Static file serving + JSON persistence + restricted curl execution
parser.js           Parser implementation used by Node tests
docker-compose.yml  Container deployment configuration
tests/              Parser and server unit tests
AGENTS.md           Coding-agent instructions for this repository
```

## Quick Start (Docker)

### Requirements

- Linux host / NAS with Docker Engine and Docker Compose v2.
- The host must be able to reach the APIs for the providers you import, including
  Zhipu AI at `www.bigmodel.cn`.
- If you import a Codex curl with `--proxy`, the proxy must be reachable from the
  Docker host.
- Default listen port is `8080`; change `PORT` in `docker-compose.yml` if occupied.

### 1. Prepare the host directory

```bash
sudo mkdir -p /docker/coding_plan_quota_dashboard/data
sudo chmod 700 /docker/coding_plan_quota_dashboard/data
sudo cp index.html server.py docker-compose.yml /docker/coding_plan_quota_dashboard/
```

### 2. Start the stack

```bash
cd /docker/coding_plan_quota_dashboard
sudo docker compose up -d
sudo docker compose ps
sudo docker logs --tail=100 coding-plan-quota-dashboard
curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8080/
```

### 3. Portainer Stack

In Portainer choose the target endpoint, **Stacks → Add stack**, name it
`coding-plan-quota-dashboard`, paste the contents of `docker-compose.yml` and click
**Deploy the stack**. Because Portainer uses host bind mounts, `index.html`,
`server.py` and an empty `data/` directory must already exist on the host.

### Updating

```bash
sudo cp index.html /docker/coding_plan_quota_dashboard/index.html
sudo cp server.py /docker/coding_plan_quota_dashboard/server.py
sudo docker restart coding-plan-quota-dashboard
```

For Compose-level changes use Portainer's **Update the stack**, or:

```bash
cd /docker/coding_plan_quota_dashboard
sudo docker compose up -d --force-recreate
```

## Persistent Data & Backups

```text
/docker/coding_plan_quota_dashboard/data/requests.json    # per-account curl, AK/SK and refresh tokens
/docker/coding_plan_quota_dashboard/data/credentials.json # legacy provider credentials
/docker/coding_plan_quota_dashboard/data/snapshot.json    # latest quota snapshot
/docker/coding_plan_quota_dashboard/data/results.json     # per-account cached API responses
/docker/coding_plan_quota_dashboard/data/order.json       # account display order
```

Backup:

```bash
sudo tar -czf "coding_plan_quota_dashboard-data-$(date +%Y%m%d-%H%M%S).tar.gz" \
  -C /docker/coding_plan_quota_dashboard data
```

Restore:

```bash
cd /docker/coding_plan_quota_dashboard
sudo docker compose down
sudo tar -xzf coding_plan_quota_dashboard-data-YYYYMMDD-HHMMSS.tar.gz
sudo docker compose up -d
```

Treat the entire data directory and its backups as sensitive: requests and
credentials contain secrets, while snapshots and API responses can contain account
information. Do **not** commit or publish them.

## Importing Requests

Paste the full raw `curl` in the page and click **保存 curl 并刷新**. The server
auto-classifies by URL:

- `chatgpt.com/backend-api/wham/usage` → Codex usage
- `chatgpt.com/backend-api/wham/rate-limit-reset-credits` → Codex reset credits
- `<newapi-host>/api/channel/{channelId}/codex/usage` → NewAPI Codex usage
- `<newapi-host>/api/channel/{channelId}/codex/usage/reset-credits` → NewAPI Codex reset credits
- `www.minimaxi.com` → MiniMax
- `GetCodingPlanUsage` → Volcengine CodingPlan
- `GetAgentPlanAFPUsage` → Volcengine AgentPlan (current endpoint)
- `GetAgentPlanUsageDetails` → Volcengine AgentPlan (legacy endpoint, still supported)
- `www.kimi.com/.../GetSubscriptionStats` → Kimi Code
- `longcat.chat/api/pay/quota/metering/token-packs/summary` → LongCat
- `cs-data.qianwenai.com/.../data/api.json` (contains `tokenplan`) → Qianwen AI TokenPlan
- `www.bigmodel.cn/api/monitor/usage/quota/limit` → Zhipu AI CodingPlan

Google AI uses the dedicated account form, not curl auto-detection. Unlock the page,
add an OAuth Refresh Token and an optional proxy, and configure `GOOGLE_AI_CLIENTS`
on the server (see Security Notes). The server tries `retrieveUserQuotaSummary`,
`retrieveUserQuota` and `loadCodeAssist` across its configured Google endpoints.
The dashboard displays Gemini Models 5-hour and weekly buckets when the response
contains the supported quota structure; it cannot display absent bucket data.

For Zhipu AI CodingPlan, the two `TOKENS_LIMIT` entries are distinguished by their
window metadata and displayed separately as 5-hour Token and weekly quota; their
`nextResetTime` values drive the countdown. `TIME_LIMIT` is displayed as MCP monthly
quota. Paste the complete browser-copied curl; the existing restricted parser handles
its authorization headers and cookies without spawning a shell.

To repair an expired Kimi verification request, unlock the page, click **更新验证头**
on the existing Kimi card, then paste a fresh browser-copied `GetSubscriptionStats`
curl. The server validates the same Kimi endpoint and merges only its request headers;
the saved account ID, URL, request body, and cached result remain unchanged until refresh.

To enable automatic Kimi token renewal, unlock the page, click **设置 RefreshToken**
or **更新 RefreshToken** on the Kimi card, then paste the complete RefreshToken JWT
directly. The server stores only the token and required request headers, and never
returns those fields from `/api/requests`. Device, session, and traffic headers are
derived from available JWT claims and override corresponding saved header values. Each refresh
exchanges the token first, updates the saved `Authorization` header, synchronizes
Kimi device headers, and merges any `Set-Cookie` response into the subscription request.
The legacy full RefreshToken cURL API remains accepted for existing configurations.

To update MiniMax authentication, unlock the page, click **更新验证头** on its card,
and paste a fresh browser-copied `token_plan/remains_percent` curl. Cookie and other
verification headers are merged into the saved request; the URL, body and account
ID are preserved. HTTP 200 with a nonzero `base_resp.status_code` is treated as a
failed refresh. A 100% usage reading alone does not prove authentication has expired.

MiniMax 验证信息失效时，可在账号卡片中点击 **更新验证头**，粘贴浏览器新复制的完整
cURL，再保存并刷新。刷新失败时保留上次成功的数据，并显示错误提示。

Codex official and NewAPI endpoints can coexist; the server merges them into one
card. `curl -sS`, `--proxy` and `--insecure` flags are translated into Python HTTPS
requests — the server never spawns a shell to run curl.

If `/usage` returns `secondary_window: null`, the page keeps the 5-hour row visible
and shows "接口未返回" instead of fabricating usage.

## Security Notes

- The server does not shell out; imported curl is parsed and re-issued via Python
  `urllib`-style HTTPS requests.
- The host allowlist defaults to `chatgpt.com`, `www.minimaxi.com`,
  `console.volcengine.com`, `www.kimi.com`, `auth.kimi.com`, `longcat.chat`,
  `cs-data.qianwenai.com`, and `www.bigmodel.cn`; additional NewAPI hosts can be enabled via the
  `NEWAPI_HOSTS` (comma-separated) environment variable and are accepted only for
  the Codex `/usage` and `/usage/reset-credits` paths.
- Google AI uses OAuth client pairs loaded from the `GOOGLE_AI_CLIENTS`
  environment variable as a JSON array of `[client_id, client_secret]` pairs.
  When unset, the server boots with three `REDACTED_*` placeholders and the
  Google AI refresh call will fail until you provide real values; this keeps
  credentials out of source code.
- NewAPI is reached over plain HTTP because it is a LAN service — do **not**
  extend this rule to arbitrary external HTTP endpoints.
- When a `codexNewApi` request is saved the refresh automatically skips the official
  `codexUsage` request, and likewise for `codexNewApiCredits` → `codexCredits`. This
  avoids repeated `401` noise when the official token is stale.
- `requests.json` stores account curl text, Volcengine AK/SK, Google refresh tokens
  and Kimi refresh configuration in plaintext. `credentials.json` may also contain
  legacy provider credentials. Never commit real credentials or copied live requests.
- `/api/requests` removes separate Kimi refresh fields and proxy settings and masks
  the `sk` and Google `refreshToken` fields. It still returns saved curl text, which
  can contain Authorization headers and cookies; this endpoint is sensitive.
- The page lock prevents accidental edits in the UI; it is not authentication or
  API access control. Protect the service with network restrictions or an
  authenticated reverse proxy before granting access beyond a trusted environment.
- Restrict `8080` to a trusted LAN and rotate credentials immediately on leak.

## Tests

```bash
node --test tests/parser.test.js
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile server.py
```

CI runs the same commands on pushes to `main` / `master` and pull requests targeting
those branches; see
[`.github/workflows/test.yml`](./.github/workflows/test.yml).

## Repository Synchronization / 仓库同步

The development repository on Gitea retains the complete commit history. GitHub
publishes reviewed snapshots as a single commit per synchronization, based on the
current GitHub `main`. Use a separate publication branch and leave the development
branch and any unrelated working changes intact. After a squash publication, the
two histories can differ even when their file contents match.

Before publishing, inspect the outgoing tree and commit metadata for credentials,
personal information and private infrastructure details. Use a GitHub noreply
email, run the required checks, and satisfy GitHub branch protection through a pull
request. Verify the resulting remote commit and remove temporary publication branches
when they are no longer needed. See [AGENTS.md](./AGENTS.md) for contributor rules.

Gitea 保留完整开发历史；GitHub 每次同步发布一个经过审查的压缩提交。不要为了对齐
GitHub 而重写 Gitea 或本地开发分支，也不要将运行数据、备份或私人部署信息纳入提交。

## License

[MIT](./LICENSE) — see [`LICENSE`](./LICENSE) for the full text.
