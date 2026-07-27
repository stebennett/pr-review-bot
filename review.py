#!/usr/bin/env python3
"""pr-reviewer — three-lens pull request review via OpenRouter.

A port of the Claude Code plugin `pr-reviewer` (stebennett/nyx-claude#39) to a
plain script. The doctrine is unchanged and lives beside this file in
``doctrine/``; what changed is that only the parts needing judgement call a
model. Everything else — candidate selection, triage, round counting, posting —
is code, because it was always an algorithm that happened to be written in
English for an agent runtime.

Four model calls per PR: three lenses in parallel, then one adjudication.
Each names its own model, so the cheap/strong split the plugin was authored
with is preserved.

v1 is review-only: it never merges and never pushes.

Dependencies: the Python standard library. Nothing else — no gh, no git, no jq,
no pip install. The `openssl` CLI is needed only for GitHub App auth; a plain
token needs nothing.

Runs two ways, identically:

  in-cluster   python3 review.py                  # driven entirely by env vars
  locally      python3 review.py owner/repo#42 --force -v

Quick local start
-----------------
    export GH_TOKEN=$(gh auth token)
    export OPENROUTER_API_KEY=sk-or-...
    python3 review.py owner/repo#42 -v          # dry run: prints, posts nothing

Nothing is ever posted unless you pass --post. See --help for the rest.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

GITHUB_API = "https://api.github.com"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
LENSES = ("requirements", "correctness", "craft")

HERE = Path(__file__).resolve().parent

# Recovered from prior review bodies to establish the round number and the SHA
# last reviewed. Authored by the adjudicator per doctrine/verdict.md.
MARKER_RE = re.compile(
    r"<!--\s*pr-reviewer:\s*verdict=(?P<verdict>[a-z-]+)\s+"
    r"round=(?P<round>\d+)\s+sha=(?P<sha>[0-9a-f]+)\s*-->"
)

# owner/repo#42 | owner/repo | https://github.com/owner/repo/pull/42 | git@... | 42
TARGET_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)?"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?"
    r"(?:(?:/pull/|#)(?P<pr>\d+))?/?$"
)

DEFAULTS = {
    "renovate_authors": ["renovate[bot]"],
    "exclude_authors": [],
    "require_label": None,
    "max_reviews_per_pass": 3,
    "max_rounds": 3,
    "max_review_lines": 3000,
    "ignore_paths": ["*.lock", "package-lock.json", "**/generated/**"],
}

VERBOSE = False

# Prefix caching is on by default and backed out by --no-cache or `"cache": false`.
# It is a cost optimisation only: with it off, every call is a normal uncached call.
CACHE_ENABLED = True


def log(msg: str) -> None:
    print(msg, flush=True)


def vlog(msg: str) -> None:
    if VERBOSE:
        print(msg, flush=True)


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    raise SystemExit(f"FATAL: {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Local convenience: .env
# ─────────────────────────────────────────────────────────────────────────────


def load_dotenv(path: Path) -> None:
    """Populate os.environ from a KEY=VALUE file. Existing vars always win.

    Purely a local convenience — in-cluster the env comes from secretKeyRef and
    no .env file exists.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()

        # `export FOO=bar` is what you get from pasting a shell snippet.
        if key.startswith("export "):
            key = key[len("export "):].strip()

        if val[:1] in ("'", '"'):
            # Quoted: take the quoted span and discard any trailing comment.
            quote = val[0]
            end = val.find(quote, 1)
            val = val[1:end] if end > 0 else val[1:]
        elif "#" in val:
            # Unquoted: a `#` starts a comment. Without this, a line like
            #   OPENROUTER_API_KEY=sk-or-v1-abc   # my key
            # yields a key with the comment glued on, and the provider rejects
            # it with an error that names the header rather than the value.
            val = val.split("#", 1)[0].strip()

        if key:
            os.environ.setdefault(key, val)
    vlog(f"loaded env from {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _app_jwt(app_id: str, pem: str) -> str:
    """Sign an RS256 JWT with the openssl CLI.

    RS256 is RSASSA-PKCS1-v1_5 over SHA-256, which is exactly what
    ``openssl dgst -sha256 -sign`` produces — so no Python crypto dependency is
    needed, which is what keeps the container image a stock python:slim.
    """
    now = int(time.time())
    header = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64u(
        json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode()

    # 1Password stores the PEM with literal \n escapes; restore real newlines.
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
        fh.write(pem.replace("\\n", "\n"))
        key_path = fh.name
    try:
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=signing_input,
            capture_output=True,
        )
    except FileNotFoundError:
        os.unlink(key_path)
        die("the openssl CLI is required for GitHub App auth (or set GH_TOKEN instead)")
    finally:
        if os.path.exists(key_path):
            os.unlink(key_path)
    if proc.returncode != 0:
        die(f"openssl failed to sign the App JWT: {proc.stderr.decode()[:400]}")
    return f"{header}.{payload}.{_b64u(proc.stdout)}"


def resolve_token() -> tuple[str, str]:
    """Return (token, kind) where kind is 'app' or 'token'.

    Prefers a GitHub App installation token — reviews must post as the App's
    bot, because GitHub rejects an APPROVE or REQUEST_CHANGES review submitted
    by the PR's own author, so an App-authored PR can only be reviewed by the
    App itself.

    Falls back to GH_TOKEN / GITHUB_TOKEN, then to `gh auth token`, which is
    what makes local testing painless. With a personal token you are a normal
    user: fine for reading and for reviewing other people's PRs, but GitHub
    will reject an approving review on your own.
    """
    app_id = os.environ.get("GITHUB_APP_ID", "").strip()
    install_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "").strip()
    pem = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").strip()
    if app_id and install_id and pem:
        jwt = _app_jwt(app_id, pem)
        resp = _http(
            "POST",
            f"{GITHUB_API}/app/installations/{install_id}/access_tokens",
            headers={"Authorization": f"Bearer {jwt}", "Accept": "application/vnd.github+json"},
        )
        return json.loads(resp)["token"], "app"

    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        tok = os.environ.get(var, "").strip()
        if tok:
            vlog(f"using {var}")
            return tok, "token"

    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            vlog("using `gh auth token`")
            return out.stdout.strip(), "token"
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    die(
        "no GitHub credentials. Set GH_TOKEN (or run `gh auth login`), or provide "
        "GITHUB_APP_ID + GITHUB_APP_INSTALLATION_ID + GITHUB_APP_PRIVATE_KEY."
    )


# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────


def _http(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    timeout: int = 120,
    raw: bool = False,
) -> str:
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as exc:
        # The body is a one-shot stream, so read it here and stash it on the
        # exception — a caller that catches the re-raised HTTPError cannot read
        # it a second time and would otherwise see an empty error detail.
        try:
            detail = exc.read().decode()[:600]
        except Exception:  # noqa: BLE001 - a body we cannot read must not mask the HTTP error
            detail = ""
        exc.detail = detail  # type: ignore[attr-defined]
        if raw:
            raise
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc


class GitHub:
    def __init__(self, token: str) -> None:
        self._h = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-reviewer",
        }

    def get(self, path: str) -> Any:
        return json.loads(_http("GET", f"{GITHUB_API}{path}", headers=self._h))

    def post(self, path: str, body: Any) -> Any:
        out = _http("POST", f"{GITHUB_API}{path}", headers=self._h, body=body)
        return json.loads(out) if out else {}

    def diff(self, repo: str, number: int) -> str:
        h = dict(self._h, Accept="application/vnd.github.v3.diff")
        return _http("GET", f"{GITHUB_API}/repos/{repo}/pulls/{number}", headers=h)

    def file(self, repo: str, path: str) -> str | None:
        """Fetch a file's contents, or None if it does not exist."""
        h = dict(self._h, Accept="application/vnd.github.v3.raw")
        try:
            return _http("GET", f"{GITHUB_API}/repos/{repo}/contents/{path}", headers=h, raw=True)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


def whoami(gh: GitHub, kind: str) -> str:
    """The login our reviews post as — how prior rounds are recognised."""
    override = os.environ.get("GITHUB_APP_BOT_LOGIN", "").strip()
    if override:
        return override
    if kind == "app":
        app = gh.get("/app")
        return f"{app['slug']}[bot]"
    return gh.get("/user")["login"]


# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter
# ─────────────────────────────────────────────────────────────────────────────


class _Heartbeat:
    """Prints an elapsed-time line every 30s while a request is in flight.

    A non-streaming completion sends nothing until it is finished, so three
    lenses running in parallel produce total silence for however long the
    slowest takes. Without this the script is indistinguishable from hung, and
    the only recourse is to kill it and lose the work already paid for.
    """

    INTERVAL = 30.0

    def __init__(self, label: str) -> None:
        self._label = label
        self._done = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        waited = 0.0
        while not self._done.wait(self.INTERVAL):
            waited += self.INTERVAL
            log(f"    {self._label}: still waiting, {waited:.0f}s elapsed")

    def stop(self) -> None:
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=1)


def describe_key(key: str) -> str:
    """A redacted description of the API key, for diagnosing a 401.

    Never prints the key. Names the properties that actually break auth — the
    ones you cannot see by looking at your own .env file.
    """
    problems = []
    if not key.startswith("sk-or-"):
        problems.append(f"does not start with 'sk-or-' (starts with {key[:6]!r})")
    if any(c.isspace() for c in key):
        problems.append("contains whitespace")
    if "#" in key:
        problems.append("contains '#' — an unstripped inline comment?")
    if key[:1] in ("'", '"') or key[-1:] in ("'", '"'):
        problems.append("is wrapped in quotes")
    shape = f"key: {len(key)} chars, starts {key[:8]!r}, ends {key[-4:]!r}"
    return shape + ("; " + "; ".join(problems) if problems else "; shape looks normal")


def seg(text: str, *, cache: bool = False) -> dict:
    """One message content block. `cache` marks a cacheable prefix ending here.

    Markers are omitted entirely when caching is disabled, rather than sent with a
    falsey value — a provider that does not understand `cache_control` should never
    see the key at all.
    """
    block = {"type": "text", "text": text}
    if cache and CACHE_ENABLED:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def _blocks(content: str | list[dict]) -> list[dict]:
    return [seg(content)] if isinstance(content, str) else content


def completion_payload(
    model: str, system: str | list[dict], user: str | list[dict], schema: dict, label: str
) -> dict:
    """The request body, split out from `openrouter` so it can be tested without HTTP."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _blocks(system)},
            {"role": "user", "content": _blocks(user)},
        ],
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": label.replace("-", "_").replace(":", "_"),
                "strict": True,
                "schema": schema,
            },
        },
        # Without this, OpenRouter may route to a provider that does not support
        # response_format and SILENTLY IGNORES it — the model then returns prose,
        # json.loads fails, and the retry loop pays for another full generation
        # before failing the same way. Restrict routing to providers that honour
        # every parameter we send.
        "provider": {"require_parameters": True},
    }


def strip_fence(text: str) -> str:
    """Unwrap a markdown fence a provider wrapped its JSON object in.

    `require_parameters` is meant to route only to providers that honour
    `response_format`, and mostly it does — but a provider can honour it and
    still emit a fenced object anyway. Without this, json.loads fails and the
    retry ladder pays for an entire extra generation to fail the same way.
    Observed in the Task 1 baseline run, not defensive programming.

    Only an outermost wrapper is removed: a lens finding legitimately quotes
    fenced code inside a string value, and that must survive untouched.
    """
    t = text.strip()
    if not t.startswith("```"):
        return t
    t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    if t.rstrip().endswith("```"):
        t = t.rstrip()[:-3]
    return t.strip()


def openrouter(
    model: str,
    system: str | list[dict],
    user: str | list[dict],
    schema: dict,
    *,
    label: str,
) -> dict:
    """One structured-output completion. Returns the parsed object.

    All the default models advertise `structured_outputs`, so the response is
    schema-constrained rather than parsed out of prose. Transport errors are
    retried; a schema violation is not, because it will simply recur.
    """
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        die("OPENROUTER_API_KEY is not set")

    payload = completion_payload(model, system, user, schema, label)
    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://github.com/stebennett/home-lab-k8s",
        "X-Title": "pr-reviewer",
    }

    timeout = int(os.environ.get("REQUEST_TIMEOUT", "300"))

    def _text(content: str | list[dict]) -> str:
        return content if isinstance(content, str) else "".join(b["text"] for b in content)

    approx_tokens = (len(_text(system)) + len(_text(user))) // 4
    last: Exception | None = None

    for attempt in range(3):
        heartbeat = _Heartbeat(f"{label} ({model})")
        try:
            log(f"    {label}: sending ~{approx_tokens} tokens to {model} (timeout {timeout}s)")
            started = time.time()
            heartbeat.start()
            try:
                raw = _http("POST", OPENROUTER_API, headers=headers, body=payload, timeout=timeout, raw=True)
            except urllib.error.HTTPError as exc:
                detail = getattr(exc, "detail", "")[:400]
                # 4xx other than rate-limiting is a bad key, a bad model slug or
                # a malformed request. Retrying burns time and, on a paid
                # endpoint, sometimes money — to arrive at the same answer.
                if exc.code == 401:
                    die(
                        f"{label}: OpenRouter rejected the credentials (HTTP 401): {detail}\n"
                        f"       {describe_key(key)}\n"
                        "       OpenRouter says 'Missing Authentication header' for a key it\n"
                        "       cannot parse, not only for an absent one — so this usually means\n"
                        "       the value is mangled rather than missing. Check for a trailing\n"
                        "       inline comment or stray quotes in .env, and that the key is an\n"
                        "       OpenRouter key (sk-or-...), not one for another provider."
                    )
                if exc.code < 500 and exc.code != 429:
                    die(f"{label}: OpenRouter rejected the request (HTTP {exc.code}): {detail}")
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
            body = json.loads(raw)
            if "error" in body and "choices" not in body:
                raise RuntimeError(f"openrouter error: {json.dumps(body['error'])[:300]}")
            if "choices" not in body:
                raise RuntimeError(f"no choices in response: {json.dumps(body)[:300]}")
            content = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens", 0)
            discount = body.get("cache_discount")
            heartbeat.stop()
            log(
                f"    {label}: response in {time.time() - started:.0f}s from "
                f"{body.get('provider', model)} "
                f"(in={usage.get('prompt_tokens', '?')} out={usage.get('completion_tokens', '?')} "
                f"cached={cached} discount={discount if discount is not None else '-'})"
            )
            vlog(f"    {label} raw content:\n{content}")
            try:
                return json.loads(strip_fence(content))
            except json.JSONDecodeError as exc:
                # The provider ignored response_format and returned prose.
                # require_parameters should prevent this; show what came back
                # rather than retrying blind, because a silent retry costs
                # another full generation to fail identically.
                raise RuntimeError(
                    f"response was not JSON despite response_format "
                    f"(provider={body.get('provider', '?')}): {content[:300]!r}"
                ) from exc
        except Exception as exc:  # noqa: BLE001 - retry any transport/parse failure
            # Stop the heartbeat before the backoff sleep, or it keeps
            # reporting "still waiting" while we are merely sleeping.
            heartbeat.stop()
            last = exc
            if attempt < 2:
                backoff = 5 * (attempt + 1)
                log(f"    {label}: attempt {attempt + 1} failed after "
                    f"{time.time() - started:.0f}s ({exc}); retrying in {backoff}s")
                time.sleep(backoff)
        finally:
            heartbeat.stop()
    raise RuntimeError(f"{label}: all {attempt + 1} attempts failed: {last}")


# ─────────────────────────────────────────────────────────────────────────────
# Schemas — mirror doctrine/lenses/_shared.md and doctrine/verdict.md
# ─────────────────────────────────────────────────────────────────────────────

FINDING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "path", "line", "side", "severity", "claim",
        "consequence", "failure_scenario", "fix", "addressed_prior",
    ],
    "properties": {
        "path": {"type": "string"},
        "line": {"type": "integer"},
        "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
        "severity": {"type": "string", "enum": ["blocking", "advisory"]},
        "claim": {"type": "string"},
        "consequence": {"type": "string"},
        # Required by the doctrine only for blocking correctness findings;
        # null elsewhere. Strict schemas cannot mark a field optional, so it is
        # nullable instead.
        "failure_scenario": {"type": ["string", "null"]},
        "fix": {"type": "string"},
        "addressed_prior": {"type": "boolean"},
    },
}

LENS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["lens", "status", "findings", "notes"],
    "properties": {
        "lens": {"type": "string", "enum": list(LENSES)},
        "status": {"type": "string", "enum": ["complete", "needs-input"]},
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "notes": {"type": "string"},
    },
}

VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reason", "body", "comments", "blocker_count"],
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "request-changes", "park"]},
        "reason": {"type": "string"},
        "body": {"type": "string"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "line", "side", "body"],
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
                    "body": {"type": "string"},
                },
            },
        },
        "blocker_count": {"type": "integer"},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Doctrine
# ─────────────────────────────────────────────────────────────────────────────


class Doctrine:
    """Loads the prompt content. Defaults to ./doctrine beside this file, so a
    checkout of this directory works with no configuration."""

    def __init__(self, root: Path) -> None:
        self.root = root
        if not root.is_dir():
            die(f"doctrine directory not found: {root} (pass --doctrine, or set DOCTRINE_DIR)")

    def __call__(self, rel: str) -> str:
        path = self.root / rel
        if not path.is_file():
            die(f"missing doctrine file: {path}")
        return path.read_text(encoding="utf-8")


DOC: Doctrine


# ─────────────────────────────────────────────────────────────────────────────
# Selection and triage
# ─────────────────────────────────────────────────────────────────────────────


def parse_target(raw: str) -> tuple[str, int | None]:
    """'owner/repo#42' / a PR URL / 'owner/repo' -> (repo, pr_number|None)."""
    m = TARGET_RE.match(raw.strip())
    if not m:
        die(f"cannot parse target {raw!r} — expected owner/repo, owner/repo#42, or a PR URL")
    pr = m.group("pr")
    return f"{m.group('owner')}/{m.group('repo')}", int(pr) if pr else None


def repo_config(gh: GitHub, repo: str) -> dict:
    """Per-repo overrides from .claude/pr-reviewer.json in the target repo."""
    cfg = dict(DEFAULTS)
    raw = gh.file(repo, ".claude/pr-reviewer.json")
    if raw:
        try:
            cfg.update(json.loads(raw))
            log("  config: .claude/pr-reviewer.json applied")
        except json.JSONDecodeError as exc:
            log(f"  config: .claude/pr-reviewer.json is invalid ({exc}); using defaults")
    return cfg


def prior_rounds(gh: GitHub, repo: str, number: int, bot_login: str) -> tuple[int, str | None, str | None]:
    """Return (rounds_done, last_reviewed_sha, last_body) from our own reviews."""
    reviews = gh.get(f"/repos/{repo}/pulls/{number}/reviews")
    ours = [r for r in reviews if (r.get("user") or {}).get("login") == bot_login]
    rounds, sha, body = 0, None, None
    for r in ours:
        m = MARKER_RE.search(r.get("body") or "")
        if m:
            rounds = max(rounds, int(m.group("round")))
            sha, body = m.group("sha"), r.get("body")
    if ours and rounds == 0:
        rounds = len(ours)  # reviewed before, but marker missing or malformed
    return rounds, sha, body


def diff_size(diff: str) -> int:
    return sum(1 for ln in diff.splitlines() if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")))


def select(
    gh: GitHub, repo: str, cfg: dict, bot_login: str, *, only_pr: int | None, force: bool
) -> list[dict]:
    """Choose which PRs to review.

    ``only_pr`` is single-PR mode: naming a PR is an instruction to review it,
    so the throughput and preference filters are bypassed — but drafts and
    Renovate authors are absolute and are never bypassed, because a draft has
    not been offered for review and a Renovate PR belongs to the renovator
    skill, which must never contend with this one over the same PR.

    ``force`` additionally bypasses the already-reviewed and max_rounds skips.
    That exists for local iteration, where re-reviewing the same PR repeatedly
    is the entire point.
    """
    if only_pr is not None:
        pulls = [gh.get(f"/repos/{repo}/pulls/{only_pr}")]
    else:
        pulls = gh.get(f"/repos/{repo}/pulls?state=open&per_page=100")

    excluded = {a.lower() for a in cfg["renovate_authors"] + cfg["exclude_authors"]}
    picked: list[dict] = []

    for pr in pulls:
        n, author = pr["number"], (pr.get("user") or {}).get("login", "")
        title = pr.get("title", "")

        if pr.get("draft"):
            log(f"  #{n} skip: draft (never bypassed)")
            continue
        if author.lower() in {a.lower() for a in cfg["renovate_authors"]}:
            log(f"  #{n} skip: Renovate PR by {author} — belongs to the renovator skill")
            continue

        if only_pr is None:
            if author.lower() in excluded:
                log(f"  #{n} skip: excluded author {author}")
                continue
            if cfg["require_label"]:
                labels = {l["name"] for l in pr.get("labels", [])}
                if cfg["require_label"] not in labels:
                    log(f"  #{n} skip: missing required label {cfg['require_label']}")
                    continue

        head_sha = pr["head"]["sha"]
        rounds, seen_sha, last_body = prior_rounds(gh, repo, n, bot_login)

        if not force:
            if seen_sha and head_sha.startswith(seen_sha):
                log(f"  #{n} skip: already reviewed at {seen_sha} (--force to re-review)")
                continue
            if rounds >= cfg["max_rounds"]:
                log(f"  #{n} skip: {rounds} rounds already (max_rounds={cfg['max_rounds']})")
                continue

        pr["_rounds"], pr["_prior_body"] = rounds, last_body
        picked.append(pr)
        log(f"  #{n} queued: {title[:70]} (round {rounds + 1})")

        if only_pr is None and len(picked) >= cfg["max_reviews_per_pass"]:
            log(f"  stopping selection at max_reviews_per_pass={cfg['max_reviews_per_pass']}")
            break

    return picked


# ─────────────────────────────────────────────────────────────────────────────
# The pass
# ─────────────────────────────────────────────────────────────────────────────


def run_lens(lens: str, pr: dict, repo: str, diff: str, requirements: str, model: str) -> dict:
    system = "\n\n".join([
        DOC("agents/pr-review-lens.md"),
        DOC("lenses/_shared.md"),
        DOC(f"lenses/{lens}.md"),
    ])
    user = (
        f"lens: {lens}\n"
        f"pr: {pr['number']}\n"
        f"target_repo: {repo}\n\n"
        f"## PR title\n{pr.get('title', '')}\n\n"
        f"## PR body\n{pr.get('body') or '(empty)'}\n\n"
        f"## Resolved requirements\n{requirements}\n\n"
        f"## Prior recommendations\n{pr.get('_prior_body') or '(none — this is round 1)'}\n\n"
        f"## Diff (`gh pr diff` canonical rendering)\n```diff\n{diff}\n```\n\n"
        "You have no worktree and no tools in this deployment: review from the diff "
        "alone. Where your doctrine tells you to consult the worktree for surrounding "
        "context, you cannot — so do not speculate about code you cannot see. If a "
        "finding depends on something outside the diff, either omit it or file it as "
        "advisory and say in `consequence` that it is unverified. Return only the JSON "
        "envelope."
    )
    return openrouter(model, system, user, LENS_SCHEMA, label=f"lens:{lens}")


def adjudicate(pr: dict, repo: str, envelopes: list[dict], requirements: str, model: str) -> dict:
    system = "\n\n".join([DOC("agents/pr-review-verdict.md"), DOC("verdict.md")])
    short_sha = pr["head"]["sha"][:7]
    user = (
        f"pr: {pr['number']}\n"
        f"target_repo: {repo}\n"
        f"pr_title: {pr.get('title', '')}\n"
        f"round: {pr['_rounds'] + 1}\n"
        f"head_sha: {short_sha}\n\n"
        f"## PR body\n{pr.get('body') or '(empty)'}\n\n"
        f"## Resolved requirements\n{requirements}\n\n"
        f"## Prior recommendations\n{pr.get('_prior_body') or '(none — this is round 1)'}\n\n"
        f"## Lens envelopes\n```json\n{json.dumps(envelopes, indent=2)}\n```\n\n"
        f"The hidden marker's first line must be exactly:\n"
        f"<!-- pr-reviewer: verdict=<your verdict> round={pr['_rounds'] + 1} sha={short_sha} -->\n\n"
        "Note this deployment never merges: an `approve` verdict posts an approving "
        "review and stops. Do not tell the author their PR is being merged."
    )
    return openrouter(model, system, user, VERDICT_SCHEMA, label="verdict")


EVENT = {"approve": "APPROVE", "request-changes": "REQUEST_CHANGES", "park": "COMMENT"}


def show_review(verdict: dict, prefix: str) -> None:
    log(f"  {prefix} {EVENT[verdict['verdict']]} with {len(verdict.get('comments') or [])} inline comment(s)")
    log("  ---- review body ----")
    for line in verdict["body"].splitlines():
        log(f"  | {line}")
    for c in verdict.get("comments") or []:
        log(f"  | [{c['path']}:{c['line']} {c['side']}] {c['body'][:200]}")
    log("  ---- end ----")


def post_review(gh: GitHub, repo: str, number: int, verdict: dict, *, post: bool) -> None:
    if not post:
        show_review(verdict, "DRY RUN — would post")
        return

    body, comments = verdict["body"], (verdict.get("comments") or [])
    event = EVENT[verdict["verdict"]]
    payload: dict[str, Any] = {"body": body, "event": event}
    if comments:
        payload["comments"] = comments
    try:
        gh.post(f"/repos/{repo}/pulls/{number}/reviews", payload)
        log(f"  posted {event} with {len(comments)} inline comment(s)")
    except RuntimeError as exc:
        # GitHub rejects the whole review if any comment anchors to a line the
        # diff does not touch. Losing the review over a bad line number is far
        # worse than losing the inline rendering, so fold them into the body.
        if "422" not in str(exc) or not comments:
            raise
        log(f"  inline comments rejected ({str(exc)[:120]}); retrying with body-only")
        rendered = "\n".join(
            f"\n---\n**`{c['path']}:{c['line']}`**\n\n{c['body']}" for c in comments
        )
        gh.post(
            f"/repos/{repo}/pulls/{number}/reviews",
            {"body": body + "\n\n## Inline findings\n" + rendered, "event": event},
        )
        log(f"  posted {event} with {len(comments)} finding(s) inlined into the body")


def run_panel(pr: dict, repo: str, diff: str, requirements: str, opts: argparse.Namespace) -> dict | None:
    """Three lenses in parallel, then adjudication. None if nothing to adjudicate."""
    lenses = tuple(opts.lens) if opts.lens else LENSES
    log(f"  dispatching {len(lenses)} lens(es) over {diff_size(diff)} changed lines")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(lenses)) as pool:
        futures = {
            pool.submit(run_lens, lens, pr, repo, diff, requirements, opts.model_lens): lens
            for lens in lenses
        }
        envelopes = []
        for fut in concurrent.futures.as_completed(futures):
            lens = futures[fut]
            try:
                envelopes.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                log(f"    lens:{lens} FAILED: {exc}")
                envelopes.append(
                    {"lens": lens, "status": "needs-input", "findings": [], "notes": f"failed: {exc}"}
                )

    if all(e["status"] == "needs-input" for e in envelopes):
        log("  all lenses failed — nothing to adjudicate")
        return None

    total = sum(len(e["findings"]) for e in envelopes)
    log(f"  panel returned {total} finding(s); adjudicating")
    verdict = adjudicate(pr, repo, envelopes, requirements, opts.model_verdict)

    if opts.save:
        out = Path(opts.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"repo": repo, "pr": pr["number"], "envelopes": envelopes, "verdict": verdict},
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"  saved envelopes + verdict to {out}")

    # The doctrine makes these hard consistency rules: a mismatch means the
    # adjudication is unsound, not merely oddly worded.
    if verdict["verdict"] == "approve" and verdict["blocker_count"] != 0:
        raise RuntimeError(f"approve with blocker_count={verdict['blocker_count']}")
    if verdict["verdict"] == "request-changes" and verdict["blocker_count"] < 1:
        raise RuntimeError("request-changes with blocker_count=0")
    if not verdict["body"].lstrip().startswith("<!-- pr-reviewer:"):
        raise RuntimeError("verdict body does not start with the hidden marker")

    return verdict


def review_pr(gh: GitHub, repo: str, pr: dict, cfg: dict, opts: argparse.Namespace) -> str:
    number = pr["number"]
    log(f"\n  → #{number} {pr.get('title', '')[:70]}")
    diff = gh.diff(repo, number)
    lines = diff_size(diff)

    if lines > cfg["max_review_lines"] and not opts.force:
        log(f"  #{number} too large: {lines} changed lines > {cfg['max_review_lines']}")
        park_body = (
            f"<!-- pr-reviewer: verdict=park round={pr['_rounds'] + 1} "
            f"sha={pr['head']['sha'][:7]} -->\n\n"
            f"## Parked — too large to review\n\n"
            f"This PR changes **{lines} lines**, above the `max_review_lines` ceiling "
            f"of {cfg['max_review_lines']}. Split it into smaller PRs and I will "
            f"review each one.\n"
        )
        if not opts.post:
            log("  DRY RUN — would post a 'too large' park comment")
        else:
            gh.post(f"/repos/{repo}/pulls/{number}/reviews", {"event": "COMMENT", "body": park_body})
        return "parked (too large)"

    # Requirements resolution is the plugin's step 6. Without issue-linking this
    # is the PR body itself, which is what the lenses check conformity against.
    requirements = pr.get("body") or "(none stated — judge against the PR title alone)"

    verdict = run_panel(pr, repo, diff, requirements, opts)
    if verdict is None:
        return "skipped (could not review)"

    post_review(gh, repo, number, verdict, post=opts.post)
    return f"{verdict['verdict']} ({verdict['blocker_count']} blocking) — {verdict['reason']}"


# ─────────────────────────────────────────────────────────────────────────────
# Offline mode
# ─────────────────────────────────────────────────────────────────────────────


def review_diff_file(opts: argparse.Namespace) -> int:
    """Review a diff from disk. No GitHub, no token, nothing posted.

    The cheapest way to iterate on doctrine and prompts:
        gh pr diff 42 > /tmp/x.diff
        python3 review.py --diff-file /tmp/x.diff --lens craft -v
    """
    diff = Path(opts.diff_file).read_text(encoding="utf-8")
    pr = {
        "number": 0,
        "title": opts.title or "(local diff)",
        "body": opts.body or "",
        "head": {"sha": "0000000"},
        "_rounds": 0,
        "_prior_body": None,
    }
    log(f"offline review of {opts.diff_file} ({diff_size(diff)} changed lines)")
    verdict = run_panel(pr, opts.repo_name or "local/local", diff, pr["body"] or "(none stated)", opts)
    if verdict is None:
        return 1
    show_review(verdict, "OFFLINE —")
    return 0


# ─────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review.py",
        description="Three-lens pull request review via OpenRouter. Review-only: never merges or pushes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  export GH_TOKEN=$(gh auth token); export OPENROUTER_API_KEY=sk-or-...

  review.py owner/repo#42 -v            one PR, dry run, verbose
  review.py owner/repo#42 --force       re-review even if already reviewed
  review.py owner/repo                  a queue pass over that repo's open PRs
  review.py owner/repo#42 --post        actually post the review
  review.py --diff-file x.diff          no GitHub at all; iterate on prompts
  review.py --lens craft --diff-file x.diff -v      one lens, cheapest loop

Nothing is posted unless --post is given (or DRY_RUN=0 in the environment).
With no target, falls back to $TARGET_REPOS — that is how it runs in-cluster.
""",
    )
    p.add_argument("targets", nargs="*", help="owner/repo, owner/repo#42, or a PR URL")
    p.add_argument("--post", action="store_true", help="actually post reviews (default: dry run)")
    p.add_argument("--dry-run", action="store_true", help="force dry run, overriding DRY_RUN=0")
    p.add_argument("-f", "--force", action="store_true",
                   help="bypass already-reviewed, max_rounds and max_review_lines skips")
    p.add_argument("--lens", action="append", choices=list(LENSES),
                   help="run only this lens (repeatable); default all three")
    p.add_argument("--model-lens", default=os.environ.get("MODEL_LENS", "z-ai/glm-5.2"))
    p.add_argument("--model-verdict", default=os.environ.get("MODEL_VERDICT", "deepseek/deepseek-v4-pro"))
    p.add_argument("--doctrine", default=os.environ.get("DOCTRINE_DIR") or str(HERE / "doctrine"),
                   help="doctrine directory (default: ./doctrine beside this script)")
    p.add_argument("--timeout", type=int, default=int(os.environ.get("REQUEST_TIMEOUT", "300")),
                   metavar="SECS", help="per-model-request timeout (default 300)")
    p.add_argument("--save", metavar="FILE", help="write envelopes + verdict as JSON")
    p.add_argument("--env-file", default=str(HERE / ".env"), help="KEY=VALUE file to load (default: ./.env)")
    p.add_argument("-v", "--verbose", action="store_true", help="log raw model output")
    off = p.add_argument_group("offline mode (no GitHub, no token)")
    off.add_argument("--diff-file", metavar="PATH", help="review a diff from disk")
    off.add_argument("--title", help="PR title to accompany --diff-file")
    off.add_argument("--body", help="PR body / requirements to accompany --diff-file")
    off.add_argument("--repo-name", help="repo name to show in prompts with --diff-file")
    return p


def resolve_post(opts: argparse.Namespace) -> bool:
    """Posting requires an explicit opt-in, from either the CLI or the env.

    The default is dry run in both. In-cluster the CronJob sets DRY_RUN
    explicitly, so this only decides what happens when nobody said.
    """
    if opts.dry_run:
        return False
    if opts.post:
        return True
    return os.environ.get("DRY_RUN", "").strip().lower() in ("0", "false", "no")


def main(argv: list[str] | None = None) -> int:
    global VERBOSE, DOC

    opts = build_parser().parse_args(argv)
    VERBOSE = opts.verbose
    load_dotenv(Path(opts.env_file))
    os.environ["REQUEST_TIMEOUT"] = str(opts.timeout)
    DOC = Doctrine(Path(opts.doctrine).expanduser().resolve())
    opts.post = resolve_post(opts)

    if opts.diff_file:
        return review_diff_file(opts)

    raw_targets = opts.targets or [
        t.strip() for t in os.environ.get("TARGET_REPOS", "").split(",") if t.strip()
    ]
    if not raw_targets:
        die("no target. Pass owner/repo[#42], or set TARGET_REPOS. See --help.")
    targets = [parse_target(t) for t in raw_targets]

    token, kind = resolve_token()
    gh = GitHub(token)
    bot_login = whoami(gh, kind)

    log(f"authenticated as {bot_login} ({'GitHub App' if kind == 'app' else 'user token'})")
    log(f"models: lens={opts.model_lens} verdict={opts.model_verdict}")
    log(f"mode: {'POSTING REVIEWS' if opts.post else 'dry run — nothing will be posted'}")
    if opts.post and kind == "token":
        log("  note: GitHub rejects APPROVE/REQUEST_CHANGES on your own PRs from a user token")

    failures = 0
    for repo, only_pr in targets:
        log(f"\n=== {repo}{f'#{only_pr}' if only_pr else ''} ===")
        try:
            cfg = repo_config(gh, repo)
            candidates = select(gh, repo, cfg, bot_login, only_pr=only_pr, force=opts.force)
        except Exception as exc:  # noqa: BLE001
            log(f"  FAILED to select candidates: {exc}")
            failures += 1
            continue

        if not candidates:
            log("  nothing to review")
            continue

        for pr in candidates:
            try:
                log(f"  #{pr['number']} -> {review_pr(gh, repo, pr, cfg, opts)}")
            except Exception as exc:  # noqa: BLE001
                # One bad PR must not abort the pass; the next run retries it.
                log(f"  #{pr['number']} FAILED: {exc}")
                failures += 1

    log(f"\npass complete ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
