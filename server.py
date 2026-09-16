import hashlib
import hmac
import json
import os
import re
import shlex
import uuid
import base64
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_snapshot(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_snapshot(path, snapshot):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def load_results(path):
    value = load_snapshot(path)
    return value if isinstance(value, dict) else {}


def save_results(path, results):
    save_snapshot(path, results)


VOLC_OPENAPI_HOST = "open.volcengineapi.com"
VOLC_REGION = "cn-beijing"
VOLC_SERVICE = "ark"
VOLC_ACTIONS = {"volcAgent": "GetAgentPlanAFPUsage", "volcCoding": "GetCodingPlanUsage"}


def _volc_norm_query(params):
    query = ""
    for key in sorted(params.keys()):
        value = params[key]
        if isinstance(value, list):
            for item in value:
                query += quote(key, safe="-_.~") + "=" + quote(str(item), safe="-_.~") + "&"
        else:
            query += quote(key, safe="-_.~") + "=" + quote(str(value), safe="-_.~") + "&"
    return query[:-1].replace("+", "%20")


def _volc_hmac(key, content):
    if isinstance(key, str):
        key = key.encode("utf-8")
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def volcengine_sign(ak, sk, method, path, query, body, region=VOLC_REGION, service=VOLC_SERVICE, content_type="application/json"):
    now = datetime.now(timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    x_date_short = x_date[:8]
    if isinstance(body, str):
        body = body.encode("utf-8")
    body_hash = hashlib.sha256(body or b"").hexdigest()
    headers = {"Host": VOLC_OPENAPI_HOST, "X-Date": x_date, "X-Content-Sha256": body_hash, "Content-Type": content_type}
    signed_headers = {}
    for key, value in headers.items():
        if key in ("Content-Type", "Content-Md5", "Host") or key.startswith("X-"):
            signed_headers[key.lower()] = value
    signed_str = "".join(f"{key}:{signed_headers[key]}\n" for key in sorted(signed_headers.keys()))
    sh = ";".join(sorted(signed_headers.keys()))
    canonical_request = "\n".join([method, quote(path, safe="/-_.~").replace("%2F", "/").replace("+", "%20"), _volc_norm_query(query), signed_str, sh, body_hash])
    credential_scope = f"{x_date_short}/{region}/{service}/request"
    hashed_canonical = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join(["HMAC-SHA256", x_date, credential_scope, hashed_canonical])
    k_date = _volc_hmac(sk, x_date_short)
    k_region = _volc_hmac(k_date, region)
    k_service = _volc_hmac(k_region, service)
    k_signing = _volc_hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers["Authorization"] = f"HMAC-SHA256 Credential={ak}/{credential_scope}, SignedHeaders={sh}, Signature={signature}"
    return headers


def execute_volcengine_openapi(credentials, action):
    ak = credentials.get("accessKeyId", "")
    sk = credentials.get("secretAccessKey", "")
    if not ak or not sk:
        raise ValueError("missing volcengine credentials")
    query = {"Action": action, "Version": "2024-01-01"}
    body = b"{}"
    headers = volcengine_sign(ak, sk, "POST", "/", query, body)
    url = f"https://{VOLC_OPENAPI_HOST}/?{_volc_norm_query(query)}"
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=35) as response:
            return response.status, response.read().decode("utf-8", errors="replace"), ""
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace"), f"HTTP {error.code}"
    except URLError as error:
        return 1, "", str(error.reason)


GOOGLE_OAUTH_URL = "https://oauth2.googleapis.com/token"
GOOGLE_UA = "antigravity-tools/1.1.5"
GOOGLE_BASES = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
]
GOOGLE_QUOTA_ENDPOINTS = [
    "retrieveUserQuotaSummary",
    "retrieveUserQuota",
    "loadCodeAssist",
]
def _load_google_clients():
    """Resolve Google AI OAuth client pairs.

    Reads the ``GOOGLE_AI_CLIENTS`` environment variable as a JSON array of
    ``[client_id, client_secret]`` pairs. When unset, falls back to three
    REDACTED placeholders so the module imports cleanly; the refresh call
    will then fail with an explicit error until the operator provides real
    values, keeping credentials out of source code.
    """
    raw = os.environ.get("GOOGLE_AI_CLIENTS", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "GOOGLE_AI_CLIENTS must be a JSON array of [client_id, client_secret] pairs: "
                f"{exc}"
            ) from exc
        pairs = []
        for item in parsed:
            if (
                isinstance(item, (list, tuple))
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], str)
            ):
                pairs.append((item[0], item[1]))
        if not pairs:
            raise ValueError("GOOGLE_AI_CLIENTS did not contain any valid pairs")
        return pairs
    return [
        ("REDACTED_GOOGLE_CLIENT_ID_1", "REDACTED_GOOGLE_CLIENT_SECRET_1"),
        ("REDACTED_GOOGLE_CLIENT_ID_2", "REDACTED_GOOGLE_CLIENT_SECRET_2"),
        ("REDACTED_GOOGLE_CLIENT_ID_3", "REDACTED_GOOGLE_CLIENT_SECRET_3"),
    ]


GOOGLE_CLIENTS = _load_google_clients()
CREDENTIAL_SOURCES = set(VOLC_ACTIONS) | {"googleAi"}


def _google_opener(proxy):
    if proxy:
        return build_opener(ProxyHandler({"http": proxy, "https": proxy}))
    return None


def execute_google_ai(credentials):
    refresh_token = credentials.get("refreshToken", "")
    proxy = credentials.get("proxy") or os.environ.get("GOOGLE_AI_PROXY", "")
    if not refresh_token:
        raise ValueError("missing google ai refresh token")
    access_token = None
    last_error = None
    for client_id, client_secret in GOOGLE_CLIENTS:
        data = urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode("utf-8")
        request = Request(GOOGLE_OAUTH_URL, data=data, method="POST")
        try:
            opener = _google_opener(proxy)
            context = opener.open(request, timeout=35) if opener else urlopen(request, timeout=35)
            with context as response:
                access_token = json.loads(response.read().decode("utf-8", errors="replace")).get("access_token")
            if access_token:
                break
        except HTTPError as error:
            last_error = f"HTTP {error.code}: {error.read().decode('utf-8', errors='replace')[:120]}"
        except URLError as error:
            last_error = str(error.reason)
    if not access_token:
        return 1, "", f"oauth refresh failed: {last_error}"
    body = b"{}"
    last_error = None

    for endpoint in GOOGLE_QUOTA_ENDPOINTS:
        for base in GOOGLE_BASES:
            request = Request(
                f"{base}/v1internal:{endpoint}",
                data=body,
                method="POST",
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "User-Agent": GOOGLE_UA},
            )
            try:
                opener = _google_opener(proxy)
                context = opener.open(request, timeout=35) if opener else urlopen(request, timeout=35)
                with context as response:
                    response_body = response.read().decode("utf-8", errors="replace")
                    if "remainingFraction" in response_body or "remaining_fraction" in response_body:
                        return response.status, response_body, ""
                    last_error = f"HTTP {response.status} no quota data @ {base}/{endpoint}"
            except HTTPError as error:
                last_error = f"HTTP {error.code} {error.reason} @ {base}/{endpoint}"
            except URLError as error:
                last_error = f"{error.reason} @ {base}/{endpoint}"
    return 1, "", f"quota endpoints failed: {last_error}"


def mask_secret(secret):
    if not secret:
        return ""
    if len(secret) <= 8:
        return "****"
    return secret[:4] + "****" + secret[-4:]


def load_credentials(path):
    value = load_snapshot(path)
    return value if isinstance(value, dict) else {}


def save_credentials(path, credentials):
    save_snapshot(path, credentials)


def load_order(path):
    value = load_snapshot(path)
    if not isinstance(value, dict):
        return []
    order = value.get("order")
    return [str(item) for item in order if isinstance(item, (str, int))] if isinstance(order, list) else []


def save_order(path, order):
    save_snapshot(path, {"order": list(order)})


def is_success_status(status):
    return status == 200


def should_skip_source(source, accounts):
    sources = {acc.get("source", "") for acc in accounts.values() if isinstance(acc, dict)}
    skip_usage = "codexNewApi" in sources and source == "codexUsage"
    skip_credits = "codexNewApiCredits" in sources and source == "codexCredits"
    return skip_usage or skip_credits


def find_matching_newapi_account(curl, requests):
    """Find an existing NewAPI account for the same Codex endpoint."""
    url, _ = parse_curl(curl)
    parsed = urlparse(url)
    source = infer_source(curl)
    for account_id, definition in requests.items():
        if definition.get("source") != source:
            continue
        try:
            existing_url, _ = parse_curl(definition.get("curl", ""))
        except ValueError:
            continue
        existing = urlparse(existing_url)
        if existing.hostname == parsed.hostname and existing.port == parsed.port and existing.path == parsed.path:
            return account_id
    return None


def provider_response_ok(source, code, body):
    """Treat HTTP 200 business-error responses as failed provider calls."""
    if not is_success_status(code):
        return False
    if source not in {NEWAPI_CODEX_USAGE_PATH, NEWAPI_CODEX_CREDITS_PATH, "qianwen", "zhipuCoding", "minimax"}:
        return True
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return False
    if source == "qianwen":
        data = payload.get("data")
        return isinstance(data, dict) and data.get("success") is not False and not data.get("errorCode") and not data.get("errorMsg")
    if source == "zhipuCoding":
        data = payload.get("data")
        return isinstance(data, dict) and isinstance(data.get("limits"), list)
    if source == "minimax":
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            return base_resp.get("status_code") == 0
        return True
    return payload.get("success") is not False and "Unauthorized" not in str(payload.get("message", ""))


def provider_response_error(source, body):
    if source not in {"qianwen", "zhipuCoding", "minimax"}:
        return ""
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return ""
    if source == "zhipuCoding":
        return str(payload.get("message") or payload.get("msg") or payload.get("error") or "").strip()
    if source == "minimax":
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            return str(base_resp.get("status_msg") or "").strip()
        return ""
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    return str(data.get("errorMsg") or data.get("errorCode") or "").strip()


ALLOWED_HOSTS = {
    "chatgpt.com",
    "www.minimaxi.com",
    "console.volcengine.com",
    "www.kimi.com",
    "auth.kimi.com",
    "longcat.chat",
    "cs-data.qianwenai.com",
    "www.bigmodel.cn",
}
# NewAPI gateway hosts allowed to serve /api/channel/{id}/codex/{usage,usage/reset-credits}.
# Configurable via NEWAPI_HOSTS env var (comma-separated hostnames). Defaults to the
# empty set; deployments that import NewAPI Codex curls must set this to the host
# portion of the gateway URL (e.g. NEWAPI_HOSTS=newapi.example.lan,newapi.other).
NEWAPI_HOSTS = {item.strip() for item in os.environ.get("NEWAPI_HOSTS", "").split(",") if item.strip()}
# Pattern matching any NewAPI Codex channel URL path: /api/channel/{digits}/codex/usage
# or /api/channel/{digits}/codex/usage/reset-credits. channelId is intentionally
# not pinned so any NewAPI channel with Codex usage is recognized.
NEWAPI_CODEX_USAGE_PATTERN = re.compile(r"^/api/channel/\d+/codex/usage(?:/reset-credits)?/?$")
NEWAPI_CODEX_USAGE_PATH = "codexNewApi"
NEWAPI_CODEX_CREDITS_PATH = "codexNewApiCredits"


def _newapi_request_allowed(parsed):
    """Return True if the URL targets a whitelisted NewAPI host with a known Codex path."""
    if parsed.hostname not in NEWAPI_HOSTS:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(NEWAPI_CODEX_USAGE_PATTERN.match(parsed.path))
ALLOWED_OPTIONS_WITH_VALUE = {
    "-H", "--header", "-b", "--cookie", "-d", "--data", "--data-raw", "--data-binary",
    "-X", "--request", "-A", "--user-agent", "--connect-timeout", "--max-time", "--url", "-x", "--proxy",
}
ALLOWED_OPTIONS = {"--compressed", "-s", "--silent", "-S", "--show-error", "-f", "--fail", "--fail-with-body", "-G", "--get", "-k", "--insecure"}
COMBINED_FLAGS = {"-sS", "-Ss", "-fsS", "-sSf"}


def parse_curl(command):
    normalized = command.replace("\\\n", " ").strip()
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError("curl command contains unsupported shell syntax")
    tokens = shlex.split(normalized)
    if not tokens or Path(tokens[0]).name != "curl":
        raise ValueError("command must start with curl")
    args = ["curl"]
    urls = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in COMBINED_FLAGS:
            args.extend(["-s", "-S"])
            index += 1
            continue
        if token in ALLOWED_OPTIONS:
            args.append(token)
            index += 1
            continue
        if token == "--url":
            if index + 1 >= len(tokens):
                raise ValueError("missing value for --url")
            urls.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith("--url="):
            urls.append(token[6:])
            index += 1
            continue
        if token in ALLOWED_OPTIONS_WITH_VALUE:
            if index + 1 >= len(tokens):
                raise ValueError(f"missing value for {token}")
            args.extend([token, tokens[index + 1]])
            index += 2
            continue
        if token.startswith("-"):
            raise ValueError(f"unsupported curl option: {token}")
        urls.append(token)
        index += 1
    if len(urls) != 1:
        raise ValueError("curl command must contain exactly one URL")
    parsed = urlparse(urls[0])
    if parsed.hostname in ALLOWED_HOSTS and parsed.scheme == "https":
        pass
    elif _newapi_request_allowed(parsed):
        pass
    else:
        raise ValueError("URL host is not allowed")
    args.append(urls[0])
    return urls[0], args


def infer_source(command):
    url, _ = parse_curl(command)
    parsed = urlparse(url)
    path = parsed.path
    if parsed.hostname == "chatgpt.com":
        if path.endswith("/rate-limit-reset-credits"):
            return "codexCredits"
        if path.endswith("/usage"):
            return "codexUsage"
        return "codex"
    if parsed.hostname in NEWAPI_HOSTS and NEWAPI_CODEX_USAGE_PATTERN.match(path):
        if path.endswith("/reset-credits"):
            return NEWAPI_CODEX_CREDITS_PATH
        return NEWAPI_CODEX_USAGE_PATH
    if parsed.hostname == "www.kimi.com" and path.endswith("GetSubscriptionStats"):
        return "kimi"
    if parsed.hostname == "longcat.chat" and path.endswith("token-packs/summary"):
        return "longcat"
    if parsed.hostname == "cs-data.qianwenai.com" and path.endswith("/data/api.json") and "tokenplan" in parsed.query:
        return "qianwen"
    if parsed.hostname == "www.bigmodel.cn" and path.rstrip("/") == "/api/monitor/usage/quota/limit":
        return "zhipuCoding"
    if parsed.hostname == "www.minimaxi.com":
        return "minimax"
    if parsed.hostname == "console.volcengine.com" and path.endswith("GetCodingPlanUsage"):
        return "volcCoding"
    if parsed.hostname == "console.volcengine.com" and path.endswith(("GetAgentPlanUsageDetails", "GetAgentPlanAFPUsage")):
        return "volcAgent"
    raise ValueError("unable to infer source from URL")


KIMI_VERIFICATION_HEADERS = {"authorization", "cookie", "x-traffic-id"}
KIMI_IGNORED_HEADERS = {"connection", "content-length", "host"}
KIMI_REFRESH_URL = "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"
KIMI_REFRESH_IGNORED_HEADERS = KIMI_IGNORED_HEADERS | {"content-type"}
KIMI_DYNAMIC_HEADERS = {
    "origin",
    "referer",
    "r-timezone",
    "user-agent",
    "x-language",
    "x-msh-device-id",
    "x-msh-platform",
    "x-msh-session-id",
    "x-msh-version",
    "x-traffic-id",
}
KIMI_DEFAULT_REFRESH_HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "connect-protocol-version": "1",
    "origin": "https://www.kimi.com",
    "r-timezone": "Asia/Hong_Kong",
    "referer": "https://www.kimi.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "x-msh-platform": "web",
    "x-msh-version": "2.0.0",
}


def _normalize_curl_header_name(raw):
    return raw.split(":", 1)[0].strip().rstrip(";").strip().lower()


def _curl_header_entries(args):
    entries = []
    index = 1
    while index < len(args) - 1:
        token = args[index]
        if token in {"-H", "--header"}:
            raw = args[index + 1]
            name = _normalize_curl_header_name(raw)
            if name:
                entries.append((name, raw))
            index += 2
            continue
        if token in {"-b", "--cookie"}:
            entries.append(("cookie", f"Cookie: {args[index + 1]}"))
            index += 2
            continue
        if token in {"-A", "--user-agent"}:
            entries.append(("user-agent", f"User-Agent: {args[index + 1]}"))
            index += 2
            continue
        if token in ALLOWED_OPTIONS_WITH_VALUE:
            index += 2
            continue
        index += 1
    return entries


def _curl_header_value(raw):
    _, separator, value = raw.partition(":")
    return value.lstrip() if separator else ""


def _decode_jwt_payload(token):
    parts = str(token).split(".")
    if len(parts) != 3:
        return {}
    try:
        encoded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def kimi_refresh_headers_for_token(token, existing_headers=None):
    """Complete direct-token configuration without requiring a copied cURL."""
    headers = dict(KIMI_DEFAULT_REFRESH_HEADERS)
    if isinstance(existing_headers, dict):
        headers.update({str(name).lower(): str(value) for name, value in existing_headers.items()})
    payload = _decode_jwt_payload(token)
    claims = {
        "x-msh-device-id": payload.get("device_id"),
        "x-msh-session-id": payload.get("ssid"),
        "x-traffic-id": payload.get("sub"),
    }
    headers.update({name: str(value) for name, value in claims.items() if value not in (None, "")})
    return headers


def parse_kimi_refresh_curl(refresh_curl):
    """Extract the Kimi refresh token and safe request headers from a cURL."""
    refresh_url, refresh_args = parse_curl(refresh_curl)
    endpoint = urlparse(refresh_url)
    expected = urlparse(KIMI_REFRESH_URL)
    if (endpoint.scheme, endpoint.hostname, endpoint.port, endpoint.path) != (
        expected.scheme,
        expected.hostname,
        expected.port,
        expected.path,
    ):
        raise ValueError("Kimi RefreshToken cURL must target the RefreshToken endpoint")

    request, proxy = build_http_request(refresh_args)
    if proxy:
        raise ValueError("Kimi RefreshToken cURL must not contain a proxy")
    if request.method != "POST" or request.data is None:
        raise ValueError("Kimi RefreshToken cURL must contain a POST JSON body")
    try:
        payload = json.loads(request.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Kimi RefreshToken body must be valid JSON") from error
    if not isinstance(payload, dict) or not str(payload.get("refresh_token", "")).strip():
        raise ValueError("Kimi RefreshToken body must contain refresh_token")

    headers = {}
    for name, raw in _curl_header_entries(refresh_args):
        if name not in KIMI_REFRESH_IGNORED_HEADERS:
            headers[name] = _curl_header_value(raw)
    return str(payload["refresh_token"]).strip(), headers


def _replace_curl_headers(existing_curl, updates):
    """Replace selected headers in an existing parsed cURL without changing its body."""
    existing_url, existing_args = parse_curl(existing_curl)
    merged = [existing_args[0]]
    replaced = set()
    index = 1
    while index < len(existing_args) - 1:
        token = existing_args[index]
        if token in {"-H", "--header"}:
            raw = existing_args[index + 1]
            name = _normalize_curl_header_name(raw)
            if name in updates:
                if name not in replaced:
                    merged.extend(["-H", f"{name}: {updates[name]}"])
                    replaced.add(name)
            else:
                merged.extend([token, raw])
            index += 2
            continue
        if token in {"-b", "--cookie"}:
            if "cookie" in updates:
                if "cookie" not in replaced:
                    merged.extend(["-H", f"Cookie: {updates['cookie']}"])
                    replaced.add("cookie")
            else:
                merged.extend([token, existing_args[index + 1]])
            index += 2
            continue
        if token in {"-A", "--user-agent"}:
            if "user-agent" in updates:
                if "user-agent" not in replaced:
                    merged.extend(["-H", f"User-Agent: {updates['user-agent']}"])
                    replaced.add("user-agent")
            else:
                merged.extend([token, existing_args[index + 1]])
            index += 2
            continue
        if token in ALLOWED_OPTIONS_WITH_VALUE:
            merged.extend([token, existing_args[index + 1]])
            index += 2
            continue
        merged.append(token)
        index += 1
    for name, value in updates.items():
        if name not in replaced:
            merged.extend(["-H", f"{name}: {value}"])
    merged.append(existing_url)
    return " ".join(shlex.quote(arg) for arg in merged)


def _extract_json_value(payload, keys):
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _extract_json_value(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_json_value(value, keys)
            if found:
                return found
    return ""


def _response_error_message(body):
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    details = payload.get("details")
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            debug = detail.get("debug")
            if isinstance(debug, dict):
                reason = debug.get("reason")
                if isinstance(reason, str) and reason.strip():
                    return reason.strip()[:160]
            value = detail.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()[:160]
    for key in ("message", "error_description", "error", "msg", "code"):
        value = payload.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()[:160]
    return ""


def _set_cookie_pairs(headers):
    pairs = {}
    for value in headers or []:
        pair = str(value).split(";", 1)[0].strip()
        name, separator, cookie_value = pair.partition("=")
        if separator and name.strip():
            pairs[name.strip()] = cookie_value.strip()
    return pairs


def _merge_cookie_header(existing_cookie, set_cookie_headers):
    cookies = {}
    for part in str(existing_cookie or "").split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    for name, value in _set_cookie_pairs(set_cookie_headers).items():
        if value:
            cookies[name] = value
        else:
            cookies.pop(name, None)
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _kimi_subscription_headers(curl):
    _, args = parse_curl(curl)
    return {name: _curl_header_value(raw) for name, raw in _curl_header_entries(args)}


def refresh_kimi_access_token(definition):
    """Refresh Kimi credentials and return an updated subscription cURL definition."""
    refresh_token = str(definition.get("kimiRefreshToken", "")).strip()
    if not refresh_token:
        return 0, {}, "missing Kimi RefreshToken configuration"
    configured_headers = definition.get("kimiRefreshHeaders", {})
    headers = {
        str(name).lower(): str(value)
        for name, value in configured_headers.items()
        if isinstance(name, str) and name.lower() not in KIMI_REFRESH_IGNORED_HEADERS
    } if isinstance(configured_headers, dict) else {}
    headers["content-type"] = "application/json"
    body = json.dumps({"refresh_token": refresh_token}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(KIMI_REFRESH_URL, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=35) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            response_headers = response.headers.get_all("Set-Cookie", [])
            status = response.status
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        response_headers = error.headers.get_all("Set-Cookie", []) if error.headers else []
        return error.code, {}, f"Kimi RefreshToken HTTP {error.code}: {_response_error_message(response_body) or error.reason}"
    except URLError as error:
        return 1, {}, f"Kimi RefreshToken request failed: {error.reason}"

    if status != 200:
        return status, {}, f"Kimi RefreshToken HTTP {status}: {_response_error_message(response_body) or 'request failed'}"
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return status, {}, "Kimi RefreshToken returned invalid JSON"
    access_token = _extract_json_value(payload, {"access_token", "accesstoken", "token"})
    if not access_token:
        return status, {}, "Kimi RefreshToken response did not contain an access token"
    new_refresh_token = _extract_json_value(payload, {"refresh_token", "refreshtoken"})
    updated = dict(definition)
    updated["kimiRefreshToken"] = new_refresh_token or refresh_token
    subscription_headers = _kimi_subscription_headers(definition.get("curl", ""))
    updates = {"authorization": f"Bearer {access_token}"}
    updates.update({name: value for name, value in headers.items() if name in KIMI_DYNAMIC_HEADERS})
    cookie = _merge_cookie_header(subscription_headers.get("cookie", ""), response_headers)
    if cookie:
        updates["cookie"] = cookie
    updated["curl"] = _replace_curl_headers(definition.get("curl", ""), updates)
    return status, updated, ""


def merge_verification_curl(existing_curl, verification_curl, ignored_headers, required_prefixes, source_name):
    """Merge verification headers from a new cURL into an existing one.

    Args:
        existing_curl: The original cURL command to update.
        verification_curl: The new cURL command containing fresh headers.
        ignored_headers: Set of header names to skip (e.g. connection, content-length).
        required_prefixes: Tuple of header name prefixes that must be present (e.g. ("authorization", "cookie", "x-msh-")).
        source_name: Human-readable source name for error messages.
    """
    existing_url, existing_args = parse_curl(existing_curl)
    verification_url, verification_args = parse_curl(verification_curl)
    if infer_source(existing_curl) != infer_source(verification_curl):
        raise ValueError(f"both requests must target the same {source_name} endpoint")
    existing_endpoint = urlparse(existing_url)
    verification_endpoint = urlparse(verification_url)
    if (existing_endpoint.scheme, existing_endpoint.hostname, existing_endpoint.port, existing_endpoint.path) != (
        verification_endpoint.scheme,
        verification_endpoint.hostname,
        verification_endpoint.port,
        verification_endpoint.path,
    ):
        raise ValueError(f"new {source_name} request must target the existing endpoint")
    updates = {
        name: raw
        for name, raw in _curl_header_entries(verification_args)
        if name not in ignored_headers
    }
    if not updates or not any(name.startswith(required_prefixes) for name in updates):
        raise ValueError(f"new {source_name} request is missing verification headers")
    merged = [existing_args[0]]
    replaced = set()
    index = 1
    while index < len(existing_args) - 1:
        token = existing_args[index]
        if token in {"-H", "--header"}:
            raw = existing_args[index + 1]
            name = _normalize_curl_header_name(raw)
            if name in updates:
                if name not in replaced:
                    merged.extend(["-H", updates[name]])
                    replaced.add(name)
            else:
                merged.extend([token, raw])
            index += 2
            continue
        if token in {"-b", "--cookie"}:
            if "cookie" in updates:
                if "cookie" not in replaced:
                    merged.extend(["-H", updates["cookie"]])
                    replaced.add("cookie")
            else:
                merged.extend([token, existing_args[index + 1]])
            index += 2
            continue
        if token in {"-A", "--user-agent"}:
            if "user-agent" in updates:
                if "user-agent" not in replaced:
                    merged.extend(["-H", updates["user-agent"]])
                    replaced.add("user-agent")
            else:
                merged.extend([token, existing_args[index + 1]])
            index += 2
            continue
        if token in ALLOWED_OPTIONS_WITH_VALUE:
            merged.extend([token, existing_args[index + 1]])
            index += 2
            continue
        merged.append(token)
        index += 1
    for name, raw in _curl_header_entries(verification_args):
        if name in updates and name not in replaced:
            merged.extend(["-H", raw])
            replaced.add(name)
    merged.append(existing_args[-1])
    return " ".join(shlex.quote(arg) for arg in merged)


def merge_kimi_verification_curl(existing_curl, verification_curl):
    return merge_verification_curl(
        existing_curl,
        verification_curl,
        KIMI_IGNORED_HEADERS,
        ("authorization", "cookie", "x-msh-"),
        "Kimi",
    )


def merge_minimax_verification_curl(existing_curl, verification_curl):
    return merge_verification_curl(
        existing_curl,
        verification_curl,
        {"connection", "content-length", "host"},
        ("cookie", "authorization", "x-"),
        "MiniMax",
    )


def load_requests(path):
    value = load_snapshot(path)
    if not isinstance(value, dict):
        return {}
    migrated = {}
    needs_migration = False
    for key, definition in value.items():
        if not isinstance(definition, dict):
            continue
        if "source" not in definition and "curl" in definition:
            needs_migration = True
            account_id = f"acc_{uuid.uuid4().hex[:12]}"
            migrated[account_id] = {"source": key, "label": "", "curl": definition.get("curl", ""), "updatedAt": definition.get("updatedAt")}
        else:
            migrated[key] = definition
    if needs_migration:
        save_requests(path, migrated)
    return migrated


def save_requests(path, requests):
    save_snapshot(path, requests)


def build_http_request(args):
    url = args[-1]
    headers = {}
    body = None
    method = None
    use_get = False
    proxy = None
    index = 1
    while index < len(args) - 1:
        token = args[index]
        if token in {"-H", "--header"}:
            raw = args[index + 1]
            key, separator, value = raw.partition(":")
            if separator:
                headers[key.strip()] = value.strip()
            elif raw.strip().rstrip(";").strip():
                headers[raw.strip().rstrip(";").strip()] = ""
            else:
                raise ValueError("invalid header")
            index += 2
            continue
        if token in {"-b", "--cookie"}:
            headers["Cookie"] = args[index + 1]
            index += 2
            continue
        if token in {"-A", "--user-agent"}:
            headers["User-Agent"] = args[index + 1]
            index += 2
            continue
        if token in {"-x", "--proxy"}:
            proxy = args[index + 1]
            index += 2
            continue
        if token in {"-X", "--request"}:
            method = args[index + 1].upper()
            index += 2
            continue
        if token in {"-d", "--data", "--data-raw", "--data-binary"}:
            body = args[index + 1].encode("utf-8")
            index += 2
            continue
        if token in {"-G", "--get"}:
            use_get = True
        index += 1
    if use_get and body is not None:
        url += ("&" if "?" in url else "?") + body.decode("utf-8")
        body = None
        method = "GET"
    elif body is not None and method is None:
        method = "POST"
    return Request(url, data=body, headers=headers, method=method or "GET"), proxy


def execute_curl(command):
    _, args = parse_curl(command)
    request, proxy = build_http_request(args)
    try:
        opener = build_opener(ProxyHandler({"http": proxy, "https": proxy})) if proxy else None
        response_context = opener.open(request, timeout=35) if opener else urlopen(request, timeout=35)
        with response_context as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body, ""
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace"), f"HTTP {error.code}"
    except URLError as error:
        return 1, "", str(error.reason)


class DashboardHandler(SimpleHTTPRequestHandler):
    snapshot_path = Path(os.environ.get("SNAPSHOT_PATH", "/data/snapshot.json"))
    requests_path = Path(os.environ.get("REQUESTS_PATH", "/data/requests.json"))
    results_path = Path(os.environ.get("RESULTS_PATH", "/data/results.json"))
    credentials_path = Path(os.environ.get("CREDENTIALS_PATH", "/data/credentials.json"))
    order_path = Path(os.environ.get("ORDER_PATH", "/data/order.json"))

    def do_GET(self):
        if self.path == "/api/snapshot":
            self.send_json(load_snapshot(self.snapshot_path))
            return
        if self.path == "/api/requests":
            accounts = load_requests(self.requests_path)
            masked = {}
            for aid, acc in accounts.items():
                item = dict(acc)
                item.pop("proxy", None)
                kimi_refresh_configured = bool(item.get("kimiRefreshToken"))
                item.pop("kimiRefreshToken", None)
                item.pop("kimiRefreshHeaders", None)
                if acc.get("source") == "kimi":
                    item["hasKimiRefreshToken"] = kimi_refresh_configured
                if "sk" in item:
                    item["sk"] = mask_secret(item["sk"])
                    item["hasCreds"] = True
                if "refreshToken" in item:
                    item["refreshToken"] = mask_secret(item["refreshToken"])
                    item["hasCreds"] = True
                masked[aid] = item
            self.send_json(masked)
            return
        if self.path == "/api/results":
            self.send_json(load_results(self.results_path))
            return
        if self.path == "/api/order":
            self.send_json({"order": load_order(self.order_path)})
            return
        if self.path == "/api/credentials":
            creds = load_credentials(self.credentials_path)
            masked = {}
            for source, cred in creds.items():
                if isinstance(cred, dict):
                    masked[source] = {"accessKeyId": cred.get("accessKeyId", ""), "secretAccessKey": mask_secret(cred.get("secretAccessKey", "")), "configured": bool(cred.get("accessKeyId") and cred.get("secretAccessKey"))}
            self.send_json(masked)
            return
        if self.path in ("", "/", "/index.html"):
            html_path = Path("/srv/index.html")
            if html_path.exists():
                body = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        super().do_GET()

    def do_POST(self):
        if self.path not in {"/api/snapshot", "/api/requests", "/api/refresh", "/api/credentials", "/api/order"}:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 524288:
                raise ValueError("invalid payload size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("snapshot must be an object")
            if self.path == "/api/snapshot":
                save_snapshot(self.snapshot_path, payload)
                self.send_json({"ok": True})
                return
            if self.path == "/api/requests":
                account_id = str(payload.get("id", "")).strip()
                curl = str(payload.get("curl", "")).strip()
                label = str(payload.get("label", "")).strip()
                ak = str(payload.get("ak", "")).strip()
                sk_input = str(payload.get("sk", "")).strip()
                refresh_token = str(payload.get("refreshToken", "")).strip()
                proxy_input = str(payload.get("proxy", "")).strip()
                explicit_source = str(payload.get("source", "")).strip()
                requests = load_requests(self.requests_path)
                existing = requests.get(account_id, {}) if account_id else {}
                if "kimiRefreshToken" in payload:
                    if not account_id:
                        raise ValueError("id is required for Kimi RefreshToken updates")
                    if existing.get("source") != "kimi":
                        raise ValueError("account is not a Kimi account")
                    refresh_token_value = str(payload.get("kimiRefreshToken", "")).strip()
                    if not refresh_token_value:
                        raise ValueError("kimiRefreshToken is required")
                    updated = dict(existing)
                    updated["kimiRefreshToken"] = refresh_token_value
                    updated["kimiRefreshHeaders"] = kimi_refresh_headers_for_token(
                        refresh_token_value,
                        existing.get("kimiRefreshHeaders", {}),
                    )
                    updated["updatedAt"] = now_iso()
                    requests[account_id] = updated
                    save_requests(self.requests_path, requests)
                    self.send_json({"ok": True, "id": account_id, "source": "kimi", "updatedAt": updated["updatedAt"]})
                    return
                if "kimiRefreshCurl" in payload:
                    if not account_id:
                        raise ValueError("id is required for Kimi RefreshToken updates")
                    if existing.get("source") != "kimi":
                        raise ValueError("account is not a Kimi account")
                    refresh_curl = str(payload.get("kimiRefreshCurl", "")).strip()
                    if not refresh_curl:
                        raise ValueError("kimiRefreshCurl is required")
                    refresh_token_value, refresh_headers = parse_kimi_refresh_curl(refresh_curl)
                    updated = dict(existing)
                    updated["kimiRefreshToken"] = refresh_token_value
                    updated["kimiRefreshHeaders"] = refresh_headers
                    updated["updatedAt"] = now_iso()
                    requests[account_id] = updated
                    save_requests(self.requests_path, requests)
                    self.send_json({"ok": True, "id": account_id, "source": "kimi", "updatedAt": updated["updatedAt"]})
                    return
                if "kimiVerificationCurl" in payload:
                    if not account_id:
                        raise ValueError("id is required for Kimi verification updates")
                    if existing.get("source") != "kimi":
                        raise ValueError("account is not a Kimi account")
                    verification_curl = str(payload.get("kimiVerificationCurl", "")).strip()
                    if not verification_curl:
                        raise ValueError("kimiVerificationCurl is required")
                    updated = dict(existing)
                    updated["curl"] = merge_kimi_verification_curl(existing.get("curl", ""), verification_curl)
                    updated["updatedAt"] = now_iso()
                    requests[account_id] = updated
                    save_requests(self.requests_path, requests)
                    self.send_json({"ok": True, "id": account_id, "source": "kimi", "updatedAt": updated["updatedAt"]})
                    return
                if "minimaxVerificationCurl" in payload:
                    if not account_id:
                        raise ValueError("id is required for MiniMax verification updates")
                    if existing.get("source") != "minimax":
                        raise ValueError("account is not a MiniMax account")
                    verification_curl = str(payload.get("minimaxVerificationCurl", "")).strip()
                    if not verification_curl:
                        raise ValueError("minimaxVerificationCurl is required")
                    updated = dict(existing)
                    updated["curl"] = merge_minimax_verification_curl(existing.get("curl", ""), verification_curl)
                    updated["updatedAt"] = now_iso()
                    requests[account_id] = updated
                    save_requests(self.requests_path, requests)
                    self.send_json({"ok": True, "id": account_id, "source": "minimax", "updatedAt": updated["updatedAt"]})
                    return
                if not curl and existing:
                    curl = existing.get("curl", "")
                if curl:
                    source = infer_source(curl)
                    if not account_id and source in {NEWAPI_CODEX_USAGE_PATH, NEWAPI_CODEX_CREDITS_PATH}:
                        account_id = find_matching_newapi_account(curl, requests) or ""
                elif explicit_source in CREDENTIAL_SOURCES and not existing:
                    source = explicit_source
                    if source in VOLC_ACTIONS and not (ak and sk_input):
                        raise ValueError("ak and sk are required for volcengine accounts")
                    if source == "googleAi" and not refresh_token:
                        raise ValueError("refreshToken is required for google ai accounts")
                    curl = ""
                elif existing.get("source") in CREDENTIAL_SOURCES:
                    source = existing["source"]
                    curl = ""
                else:
                    raise ValueError("curl is required")
                account_id = account_id or f"acc_{uuid.uuid4().hex[:12]}"
                definition = {"source": source, "label": label, "curl": curl, "updatedAt": payload.get("updatedAt")}
                if source in VOLC_ACTIONS:
                    definition["ak"] = ak or existing.get("ak", "")
                    definition["sk"] = sk_input or existing.get("sk", "")
                if source == "googleAi":
                    definition["refreshToken"] = refresh_token or existing.get("refreshToken", "")
                    definition["proxy"] = proxy_input or existing.get("proxy", "")
                if source == "kimi" and existing.get("source") == "kimi":
                    definition["kimiRefreshToken"] = existing.get("kimiRefreshToken", "")
                    definition["kimiRefreshHeaders"] = existing.get("kimiRefreshHeaders", {})
                requests[account_id] = definition
                save_requests(self.requests_path, requests)
                self.send_json({"ok": True, "id": account_id, "source": source})
                return
            if self.path == "/api/credentials":
                source = str(payload.get("source", "volc")).strip()
                ak = str(payload.get("accessKeyId", "")).strip()
                sk = str(payload.get("secretAccessKey", "")).strip()
                creds = load_credentials(self.credentials_path)
                if not ak and not sk:
                    creds.pop(source, None)
                else:
                    creds[source] = {"accessKeyId": ak, "secretAccessKey": sk}
                save_credentials(self.credentials_path, creds)
                self.send_json({"ok": True, "source": source})
                return
            if self.path == "/api/order":
                order = payload.get("order")
                if not isinstance(order, list):
                    raise ValueError("order must be an array")
                cleaned = [str(item).strip() for item in order if isinstance(item, (str, int)) and str(item).strip()]
                save_order(self.order_path, cleaned)
                self.send_json({"ok": True, "order": cleaned})
                return
            results = {}
            cached_results = load_results(self.results_path)
            credentials = load_credentials(self.credentials_path)
            accounts = load_requests(self.requests_path)
            requests_changed = False
            for account_id, definition in accounts.items():
                source = definition.get("source", "")
                if should_skip_source(source, accounts):
                    continue
                try:
                    if source in VOLC_ACTIONS:
                        ak = definition.get("ak") or credentials.get("volc", {}).get("accessKeyId", "")
                        sk = definition.get("sk") or credentials.get("volc", {}).get("secretAccessKey", "")
                        if ak and sk:
                            code, stdout, stderr = execute_volcengine_openapi({"accessKeyId": ak, "secretAccessKey": sk}, VOLC_ACTIONS[source])
                        else:
                            code, stdout, stderr = execute_curl(definition.get("curl", ""))
                    elif source == "googleAi":
                        refresh_token = definition.get("refreshToken") or credentials.get("googleAi", {}).get("refreshToken", "")
                        proxy = definition.get("proxy") or os.environ.get("GOOGLE_AI_PROXY", "")
                        if refresh_token:
                            code, stdout, stderr = execute_google_ai({"refreshToken": refresh_token, "proxy": proxy})
                        else:
                            code, stdout, stderr = execute_curl(definition.get("curl", ""))
                    elif source == "kimi" and definition.get("kimiRefreshToken"):
                        code, refreshed_definition, stderr = refresh_kimi_access_token(definition)
                        if refreshed_definition:
                            accounts[account_id] = refreshed_definition
                            requests_changed = True
                            definition = refreshed_definition
                            code, stdout, curl_error = execute_curl(definition.get("curl", ""))
                            stderr = curl_error
                        else:
                            stdout = ""
                            if code == 200:
                                code = 502
                    else:
                        code, stdout, stderr = execute_curl(definition.get("curl", ""))
                    provider_ok = provider_response_ok(source, code, stdout)
                    if not provider_ok and is_success_status(code):
                        stderr = stderr or provider_response_error(source, stdout) or "provider returned an unsuccessful business response"
                    updated_at = now_iso() if provider_ok else None
                    result = {"ok": provider_ok, "status": code, "body": stdout, "error": stderr, "updatedAt": updated_at}
                    results[account_id] = result
                    if provider_ok:
                        cached_results[account_id] = result
                except (ValueError, OSError, TimeoutError) as error:
                    results[account_id] = {"ok": False, "status": None, "body": "", "error": str(error)}
            if requests_changed:
                save_requests(self.requests_path, accounts)
            save_results(self.results_path, cached_results)
            self.send_json(results)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self.send_error(400, str(error))

    def do_DELETE(self):
        if self.path != "/api/requests":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 524288:
                raise ValueError("invalid payload size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            account_id = str(payload.get("id", "")).strip()
            if not account_id:
                raise ValueError("id is required")
            requests = load_requests(self.requests_path)
            requests.pop(account_id, None)
            save_requests(self.requests_path, requests)
            results = load_results(self.results_path)
            results.pop(account_id, None)
            save_results(self.results_path, results)
            self.send_json({"ok": True, "id": account_id})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self.send_error(400, str(error))

    def send_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    os.chdir("/srv")
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "80"))), DashboardHandler)
    server.serve_forever()
