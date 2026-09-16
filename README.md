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
- Per-account Volcengine AK/SK configuration (no curl required); uses HMAC-SHA256 V4
  signing against `GetCodingPlanUsage` / `GetAgentPlanAFPUsage`.
- Codex supports both the official `/usage` + `/rate-limit-reset-credits` endpoints
  and a NewAPI replacement (`/api/channel/{channelId}/codex/usage[/reset-credits]`).
  The server merges them into a single Codex card and skips the official requests
  when a NewAPI variant is configured.
- All progress bars show two-decimal usage percentage; each card shows a live
  countdown to the next reset in the top-right corner.
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
/docker/coding_plan_quota_dashboard/data/requests.json    # imported curl, contains secrets
/docker/coding_plan_quota_dashboard/data/credentials.json # per-account Volcengine AK/SK
/docker/coding_plan_quota_dashboard/data/snapshot.json    # latest quota snapshot
/docker/coding_plan_quota_dashboard/data/results.json     # per-account cached API responses
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

Treat `requests.json` and `credentials.json` as secrets: do **not** commit them, and
never publish the backup file to a public download location.

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
- `retrieveUserQuotaSummary` (Gemini Models 5 小时 / 周额度) → Google AI (Antigravity)

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
derived from JWT claims when no previous Kimi request headers exist. Each refresh
exchanges the token first, updates the saved `Authorization` header, synchronizes
Kimi device headers, and merges any `Set-Cookie` response into the subscription request.
The legacy full RefreshToken cURL API remains accepted for existing configurations.

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
- Raw curl (Token / Cookie / Digest) is stored in `requests.json` in plaintext, and
  Volcengine AK/SK is stored in `credentials.json` in plaintext. Kimi RefreshToken
  input is reduced to its token and required headers in `requests.json`; it is not
  returned by the API. Never commit real credentials; the README and tests use
  redacted samples only.
- Restrict `8080` to a trusted LAN and rotate credentials immediately on leak.

## Tests

```bash
node --test tests/parser.test.js
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile server.py
```

CI runs the same commands on every push and pull request; see
[`.github/workflows/test.yml`](./.github/workflows/test.yml).

## License

[MIT](./LICENSE) — see [`LICENSE`](./LICENSE) for the full text.
