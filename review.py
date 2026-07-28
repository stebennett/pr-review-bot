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
import fnmatch
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
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
    "cache": True,
    "context": True,
    "max_context_chars": 83000,
    "max_tarball_bytes": 50_000_000,
    "max_context_files": 25,
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

    def file(self, repo: str, path: str, ref: str | None = None) -> str | None:
        """Fetch a file's contents, or None if it does not exist."""
        h = dict(self._h, Accept="application/vnd.github.v3.raw")
        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        if ref:
            url += f"?ref={ref}"
        try:
            return _http("GET", url, headers=h, raw=True)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def open_tarball(self, repo: str, sha: str):
        """An open response streaming the repo tarball at `sha`."""
        req = urllib.request.Request(
            f"{GITHUB_API}/repos/{repo}/tarball/{sha}", method="GET", headers=self._h
        )
        return urllib.request.urlopen(req, timeout=180)


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
# Context pack
#
# The lens doctrine (doctrine/lenses/_shared.md, ## Method) tells a lens to read
# around the diff for "context the hunk alone hides". Upstream that was a worktree
# plus Read/Grep/Glob; here it is this section, which pushes the same information
# into the prompt deterministically. No model call is involved in any of it.
# ─────────────────────────────────────────────────────────────────────────────

MAX_SOURCE_BYTES = 512 * 1024  # above this a file is generated or vendored, not reviewable
BINARY_SNIFF_BYTES = 8 * 1024
WINDOW_PAD = 60
MAX_HIT_CHARS = 240  # a rendered grep hit line; see grep_repo


# ── Truncation, in one place ─────────────────────────────────────────────────
#
# Every cut in the pack — a whole section against its budget, or one embedded
# document against what is left of one — goes through this pair. Two properties
# hold for all of them at once because there is only one implementation:
# truncation is always marked in-band, and a cut never leaves a markdown fence
# open.
#
# The second property is why this is shared rather than per-section. The pack is
# concatenated ahead of the lens brief and LENS_TAIL (see build_lens_prompt), so
# a fence left open by a cut does not merely spoil its own section: it swallows
# everything after it — the remaining sections, the lens name, the brief, and
# the tail's "every finding must anchor to a `path:line`" instruction — into one
# quoted code block. A lens reading its own instructions as quoted content is
# the worst failure this file can produce, and it used to be one budget and one
# ordinary fenced PR body away.

# A run of 3+ backticks alone on its line, optionally with an info string.
# CommonMark: an opener may carry an info string, a closer may not, and a closer
# must be at least as long as the opener it closes — so fences are tracked by
# run length, never by counting occurrences.
FENCE_LINE_RE = re.compile(r"^ {0,3}(`{3,})([^`]*)$")


def _open_fence(text: str) -> str | None:
    """The fence `text` leaves open, or None if every fence in it is closed.

    A document's own longer fence must not be read as a closer for a shorter
    one, which is exactly what a naive "count the ``` lines" check gets wrong —
    and `_fence()` deliberately emits longer wrappers, so the pack is full of
    them.
    """
    open_len = 0
    for line in text.split("\n"):
        m = FENCE_LINE_RE.match(line)
        if m is None:
            continue
        run, info = len(m.group(1)), m.group(2).strip()
        if open_len == 0:
            open_len = run          # an opener may carry an info string
        elif run >= open_len and not info:
            open_len = 0
    return "`" * open_len if open_len else None


def truncation_markers(full: str | None = None) -> tuple[str, ...]:
    """The in-band truncation ladder, most to least informative.

    A caller with something specific to say passes it as `full`; every caller
    then degrades through the same shorter forms, and finally to nothing at all
    — which only a limit of 0 ever reaches, since "…" costs one character. This
    is one ladder rather than the three near-copies it replaces.
    """
    return ((full,) if full else ()) + ("\n… truncated …\n", "…", "")


def _capped(text: str, limit: int, markers: tuple[str, ...]) -> str:
    """`text` cut to at most `limit` characters, marked, fence-balanced.

    The cut decides which fence is open and closing that fence costs
    characters, which moves the cut — so this iterates to a fixed point rather
    than assuming one pass settles it. It terminates: every iteration that does
    not return shrinks `body` strictly (the slice bound it takes is below the
    length it just failed), and the empty string leaves nothing open.

    The closing fence goes *before* the marker so the marker stays readable
    prose rather than the last line of a quoted block, and the whole thing
    still fits `limit` — a fence is never closed by overrunning the budget.
    """
    if limit <= 0:
        return ""
    marker = next(m for m in markers if len(m) <= limit)  # "" always qualifies
    body = text[: limit - len(marker)]
    while True:
        fence = _open_fence(body)
        if fence is None:
            return body + marker
        close = f"\n{fence}\n"
        if len(body) + len(close) + len(marker) <= limit:
            return body + close + marker
        body = body[: max(0, limit - len(marker) - len(close))]


def path_matches(path: str, patterns: list[str]) -> bool:
    """True if `path` matches any glob in `patterns`.

    `ignore_paths` has been in DEFAULTS since the first commit and read nowhere;
    this is its first consumer. Patterns are matched against the full path and
    against the bare filename, so both `*.lock` and `**/generated/**` behave the
    way someone writing that config would expect.
    """
    name = path.rsplit("/", 1)[-1]
    for pat in patterns:
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(name, pat):
            return True
        # `**/x/**` is the conventional way to write "any directory named x",
        # which fnmatch has no special handling for.
        if pat.startswith("**/") and pat.endswith("/**") and f"/{pat.strip('*/')}/" in f"/{path}":
            return True
    return False


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_SNIFF_BYTES]


def merge_ranges(ranges: list[tuple[int, int]], pad: int) -> list[tuple[int, int]]:
    """Pad each range by `pad` lines and merge those that now overlap."""
    padded = sorted((max(1, lo - pad), hi + pad) for lo, hi in ranges)
    out: list[tuple[int, int]] = []
    for lo, hi in padded:
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def windowed(text: str, ranges: list[tuple[int, int]]) -> str:
    """Render only `ranges` of `text`, line-numbered, with elisions marked.

    Line numbers matter: without them a lens cannot relate what it reads here to
    the diff's line numbers. Elisions are stated explicitly so unseen code is
    visibly unseen rather than silently absent.
    """
    lines = text.splitlines()
    chunks: list[str] = []
    cursor = 1
    for lo, hi in ranges:
        lo, hi = max(1, lo), min(len(lines), hi)
        if lo > cursor:
            chunks.append(f"… {lo - cursor} lines elided …")
        chunks.extend(f"{n}: {lines[n - 1]}" for n in range(lo, hi + 1))
        cursor = hi + 1
    if cursor <= len(lines):
        chunks.append(f"… {len(lines) - cursor + 1} lines elided …")
    return "\n".join(chunks)


def read_source(root: Path | None, gh, repo: str, sha: str, rel: str) -> str | None:
    """A changed file's text at head, from the checkout or the degraded API path."""
    if root is not None:
        p = root / rel
        try:
            if not p.is_file() or p.stat().st_size > MAX_SOURCE_BYTES:
                return None
            data = p.read_bytes()
        except OSError:
            return None
        return None if is_binary(data) else data.decode("utf-8", "replace")
    if gh is None:
        return None
    try:
        text = gh.file(repo, rel, ref=sha)
    except Exception:  # noqa: BLE001 - a file we cannot read degrades the pack only
        return None
    if text is None or len(text.encode()) > MAX_SOURCE_BYTES or is_binary(text.encode()[:BINARY_SNIFF_BYTES]):
        return None
    return text


def _whole_file_body(rel: str, text: str) -> str:
    """`rel` rendered in full — still through `windowed()`, so it is numbered
    exactly like a windowed file rather than being a visually distinct shape."""
    lines = text.splitlines()
    return f"### {rel}\n```\n{windowed(text, [(1, len(lines))])}\n```\n"


def _file_body(rel: str, text: str, file_ranges: list[tuple[int, int]], pad: int) -> str:
    """One file's rendered section, each touched range padded by `pad` lines.

    Always rendered through `windowed()` — a whole file is just the window
    that happens to cover every line — so every line carries a real line
    number and a lens never has to guess whether it is looking at a file or a
    window into one. A `pad` at or above the file's line count covers
    everything, so it renders as the whole file, elision-free.
    """
    lines = text.splitlines()
    if pad >= len(lines):
        return _whole_file_body(rel, text)
    return f"### {rel}\n```\n{windowed(text, merge_ranges(file_ranges, pad))}\n```\n"


def _file_tiers(rel: str, text: str | None, file_ranges: list[tuple[int, int]]) -> list[tuple[int, str]]:
    """`(pad, body)` rungs for one file in ascending cost and ascending content:
    the tightest window around the diff, the ±`WINDOW_PAD` window, the whole file.

    A rung that costs no less than a richer one is not a rung at all — for a
    file whose diff touches most of its own body the padded window and the
    whole file render identically, and for a file with many one-line hunks the
    elision markers can cost more than the lines they replace. Dropping those
    keeps the ladder strictly monotone, which is what lets the allocator below
    treat "next rung" as unambiguously "more context for more characters".

    A file that could not be read has one rung: the placeholder saying so.
    """
    if text is None:
        return [(0, f"### {rel}\n(skipped: unreadable, binary, or over {MAX_SOURCE_BYTES} bytes)\n")]
    line_count = len(text.splitlines())
    rungs = [(line_count, _whole_file_body(rel, text))]
    for pad in (WINDOW_PAD, 0):
        if pad >= line_count:
            continue
        body = _file_body(rel, text, file_ranges, pad)
        if len(body) < len(rungs[-1][1]):
            rungs.append((pad, body))
    rungs.reverse()
    return rungs


def _stretch(
    rel: str, text: str, file_ranges: list[tuple[int, int]], pad: int, room: int
) -> str | None:
    """The widest padding above `pad` whose rendering still fits `room` chars.

    The rungs above are deliberately coarse — three of them — so a file often
    stops one rung short of what the budget could actually afford, and the
    difference is thrown away. This searches the padding between the rungs for
    the widest window that still fits, which is what turns "no further rung
    fits" into a filled budget rather than an abandoned one.

    The search assumes wider padding costs more, which is very nearly but not
    exactly true (an elision marker can cost more than the one line it hides),
    so the *returned* candidate is always one whose real rendered length was
    measured against `room` — never an estimate, and never a rendering that
    was not itself checked.
    """
    lo, hi = pad, len(text.splitlines())
    best: str | None = None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        body = _file_body(rel, text, file_ranges, mid)
        if len(body) <= room:
            best, lo = body, mid
        else:
            hi = mid - 1
    return best


def _trailer_groups(
    ignored: list[str], cap_dropped: list[str], budget_dropped: list[str], *, with_names: bool
) -> list[str]:
    """The up-to-three labelled "not shown" groups, only the non-empty ones.

    `with_names=False` renders just the counts, no per-path bullet list — the
    fallback when even the full trailer cannot fit the budget on its own.
    """
    def group(items: list[str], label: str) -> str | None:
        if not items:
            return None
        text = f"### {len(items)} {label}\n"
        if with_names:
            text += "\n".join(f"- {p}" for p in items) + "\n"
        return text

    groups = [
        group(ignored, "file(s) excluded by ignore_paths"),
        group(cap_dropped, "further changed file(s) not shown (file cap)"),
        group(budget_dropped, "further changed file(s) not shown (budget)"),
    ]
    return [g for g in groups if g is not None]


def pack_changed_files(
    root: Path | None, gh, repo: str, sha: str,
    ranges: dict[str, list[tuple[int, int]]], cfg: dict, acc: "Accounting",
) -> str:
    """Every changed file at head, whole where it fits and windowed where it does not.

    Allocation is by upgrade, not by division. Every earlier attempt to hand
    each file a share of the budget up front foundered on the same rock:
    rendering is discrete — a tight window, a padded window, the whole file —
    so a file whose share fell a little short of its padded window fell all
    the way back to its tight one, and the difference was never handed back to
    anybody. With enough files everyone landed on that floor at once and most
    of the budget went unspent. So instead:

    1. Every file starts at its cheapest rung, the tight window around its own
       hunks. If even that does not fit, whole files are evicted until it does
       — never a half-rendered one, and every eviction is named in the trailer.
    2. While budget remains, the highest-priority file that can afford its next
       rung takes it, and the scan restarts from the top. This only ever adds,
       so it cannot overrun, and it spends on the busiest files first.
    3. What the coarse rungs leave behind — often most of the budget, since one
       rung can cost thousands of characters — is spent by widening the
       highest-priority file that is not yet whole to the widest window that
       still fits (`_stretch`).

    Every decision measures a real rendered string; nothing is estimated from
    raw file size, which is a different number entirely once line numbers,
    elisions and the fence wrapper are counted. Nothing is ever handed to
    `Accounting` in a state that could still overrun: `acc.add` truncating this
    section at a raw offset would cut a file body in half, which is worse than
    dropping the file cleanly and naming it, so the trailer is measured
    alongside the bodies at every step.
    """
    if not ranges:
        return ""

    limit = max(0, cfg.get("max_context_files", 25))
    ignore = cfg.get("ignore_paths") or []
    ordered = sorted(ranges, key=lambda p: (-len(ranges[p]), p))
    ignored = [p for p in ordered if path_matches(p, ignore)]
    eligible = [p for p in ordered if p not in ignored]
    chosen = eligible[:limit]
    cap_dropped = eligible[limit:]

    header = (
        "## Changed files at head\n\n"
        "Context only. These are the touched files as they stand at the PR head, so you can "
        "see what each hunk sits inside. A finding still anchors to a diff line, never to a "
        "line you first saw here.\n\n"
    )
    budget = acc.limits["changed_files"]

    # Read each chosen file once and build its rung ladder. Everything after
    # this point is arithmetic on strings that already exist.
    texts: dict[str, str | None] = {}
    tiers: dict[str, list[tuple[int, str]]] = {}
    for rel in chosen:
        texts[rel] = read_source(root, gh, repo, sha, rel)
        tiers[rel] = _file_tiers(rel, texts[rel], ranges[rel])

    shown: list[str] = []                                  # stays in priority order
    rung = {rel: 0 for rel in chosen}
    bodies = {rel: tiers[rel][0][1] for rel in chosen}
    budget_dropped: list[str] = []

    def measure() -> int:
        """What the section would come to right now — bodies, trailer and the
        newlines `"\\n".join` puts between them — without building it."""
        groups = _trailer_groups(ignored, cap_dropped, budget_dropped, with_names=True)
        sizes = [len(bodies[r]) for r in shown] + [len(g) for g in groups]
        return len(header) + sum(sizes) + max(0, len(sizes) - 1)

    # 1. Make the floor fit, by admitting whole files in priority order and
    #    turning away the ones that no longer fit — never a half-rendered file,
    #    and everything turned away is named.
    #
    #    Admitting in priority order is what makes this right, and the reason
    #    is worth stating: it keeps the highest-priority file it possibly can,
    #    then the next, and so on, so the set it ends up with is the best one
    #    available in priority terms. Choosing an evictee instead — even the
    #    "cheapest eviction that ends the overflow" — only ever considers
    #    removing ONE file, so when no single small file covers the overflow
    #    the one large file does, and the busiest file in the pull request gets
    #    dropped in favour of twenty files with one trivial hunk each. That is
    #    precisely backwards: hunk count orders these files because the
    #    most-changed file is the most useful thing a reviewer can be shown.
    #    Admission also handles the case that motivated the old rule without
    #    needing a special case for it — a file whose diff touches its entire
    #    body cannot be windowed, so it is simply too big to admit at its turn,
    #    and the shrinkable files behind it are admitted in its place.
    for rel in chosen:
        shown.append(rel)
        if measure() > budget:
            shown.pop()
            budget_dropped.append(rel)
    # Each later refusal adds a line to the trailer, which can put an already
    # admitted section back over by a few dozen characters. Give back from the
    # bottom of the priority order until it fits; every file handed back frees
    # more than the bullet naming it costs, so this cannot spin.
    while shown and measure() > budget:
        budget_dropped.append(shown.pop())
    budget_dropped.sort(key=chosen.index)

    # Every refusal above was judged against the trailer as it stood at the
    # time, and each later refusal lengthened it — so a file turned away early
    # may have been turned away for room that the give-back has since handed
    # back, and naming a file in the trailer is far cheaper than showing it.
    # Offer what is left to the refused files in priority order until nobody
    # else fits. Each round only ever moves a file from the drop list into the
    # section, and never the other way, so this settles.
    readmitted = True
    while readmitted:
        readmitted = False
        for rel in list(budget_dropped):
            budget_dropped.remove(rel)
            shown.append(rel)
            shown.sort(key=chosen.index)
            if measure() <= budget:
                readmitted = True
            else:
                shown.remove(rel)
                budget_dropped.append(rel)
        budget_dropped.sort(key=chosen.index)

    # 2. Upgrade greedily, highest priority first, restarting the scan after
    #    every upgrade so the busiest file keeps first claim on what is left.
    upgraded = True
    while upgraded:
        upgraded = False
        current = measure()
        for rel in shown:
            nxt = rung[rel] + 1
            if nxt >= len(tiers[rel]):
                continue
            if current + len(tiers[rel][nxt][1]) - len(bodies[rel]) <= budget:
                rung[rel], bodies[rel] = nxt, tiers[rel][nxt][1]
                upgraded = True
                break

    # 3. Spend what the gaps between rungs left behind.
    for rel in shown:
        text = texts[rel]
        if text is None:
            continue
        pad = tiers[rel][rung[rel]][0]
        if pad >= len(text.splitlines()):
            continue                                       # already whole
        room = budget - measure() + len(bodies[rel])
        wider = _stretch(rel, text, ranges[rel], pad, room)
        if wider is not None:
            bodies[rel] = wider

    groups = _trailer_groups(ignored, cap_dropped, budget_dropped, with_names=True)
    assembled = header + "\n".join([bodies[r] for r in shown] + groups)
    if len(assembled) > budget:
        # Only reachable with nothing shown at all: the loop above evicts until
        # the section fits or there is nothing left to evict, and a budget too
        # small even for the header plus a drop-list is still a budget this
        # section must not overrun. Degrade the trailer in strictly smaller
        # stages rather than let Accounting slice it mid-line.
        groups = _trailer_groups(ignored, cap_dropped, budget_dropped, with_names=False)
        assembled = header + "\n".join([bodies[r] for r in shown] + groups)
    if len(assembled) > budget:
        assembled = header if len(header) <= budget else ""

    if not shown and not ignored and not cap_dropped and not budget_dropped:
        return ""
    return acc.add("changed_files", assembled)


HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,(?P<oldc>\d+))? \+(?P<new>\d+)(?:,(?P<newc>\d+))? @@")


def _strip_prefix(target: str) -> str | None:
    """`a/src/foo.py` -> `src/foo.py`; `/dev/null` -> None."""
    if target == "/dev/null":
        return None
    return target[2:] if target[:2] in ("a/", "b/") else target


def _hunks(diff: str) -> list[tuple[str | None, str | None, int, int, list[str]]]:
    """One (new_path, old_path, old_start, new_start, body) tuple per hunk.

    Both paths are tracked, not just the `+++` one: a deleted file has
    `+++ /dev/null` and no RIGHT side, but GitHub still accepts a LEFT comment on
    it, so its `--- a/path` is the only way to anchor there.
    """
    out: list[tuple[str | None, str | None, int, int, list[str]]] = []
    new_path: str | None = None
    old_path: str | None = None
    header: re.Match | None = None
    body: list[str] = []

    def close() -> None:
        if header is not None:
            out.append(
                (new_path, old_path, int(header.group("old")), int(header.group("new")), list(body))
            )

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            # A new file entry closes the previous file's last hunk. Entries
            # with no `--- `/`+++ ` at all — pure renames, mode-only changes,
            # binary files — must not let their metadata lines (`similarity
            # index …`, `rename from …`, `Binary files … differ`) be swallowed
            # as context into whatever hunk was still open.
            close()
            header, body = None, []
            continue
        if line.startswith("index "):
            continue
        if line.startswith("--- "):
            # The `---` line opens a new file, so it also closes the previous
            # file's last hunk — while old_path/new_path still name that file.
            close()
            header, body = None, []
            old_path = _strip_prefix(line[4:].strip())
            continue
        if line.startswith("+++ "):
            new_path = _strip_prefix(line[4:].strip())
            continue
        m = HUNK_RE.match(line)
        if m:
            close()
            header, body = m, []
            continue
        if header is not None and not line.startswith("\\"):
            # `\ No newline at end of file` is neither an added, removed, nor
            # context line — it must not consume a line number on either side.
            body.append(line)
    close()
    return out


# Extensions this reviews as code for the purposes of symbol extraction and the
# repo-wide grep. A generous but finite list: a repo whose code lives entirely
# under an unlisted extension loses this context section outright, which is a
# safe degradation (the pack still ships, just thinner) rather than a crash —
# but it is a real limitation worth knowing about rather than a fully general
# answer to "what is source code".
CODE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".cs", ".swift", ".scala", ".c", ".h", ".cpp", ".hpp", ".cc", ".sh",
}


def _suffix(rel: str) -> str:
    """The lowercased extension of a relpath's basename, `""` if it has none."""
    base = rel.rsplit("/", 1)[-1]
    return f".{base.rsplit('.', 1)[-1].lower()}" if "." in base else ""


def _module_stem(rel: str) -> str:
    """A changed file's importer needle: its basename, minus the language
    extension and, separately, a trailing `.test`/`.spec` marker.

    Stripping only the final extension leaves `.test`/`.spec` glued onto the
    stem for the very common `name.test.ts` / `name.spec.js` convention, and a
    needle like `HandicapHero.test` can only ever match a literal mention of
    the test file's own name — never a real `import HandicapHero`. Both
    markers are stripped so the needle is the name real code actually imports.
    """
    base = rel.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    for marker in (".test", ".spec"):
        if stem.lower().endswith(marker):
            stem = stem[: -len(marker)]
            break
    return stem


# Definition-shaped lines across the languages this reviews in practice. Deliberately
# language-agnostic and deliberately imprecise: over-matching is bounded by the hit
# ceiling and the budget, whereas a per-language parser would be a dependency.
DEF_RE = re.compile(
    r"\b(?:def|class|func|fn|type|interface|struct|"
    r"function|export\s+(?:const|function|class|type|interface|default)|const|let|var)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)

# Names too generic for a grep to say anything useful about.
SYMBOL_STOPLIST = {
    "value", "values", "index", "result", "results", "data", "item", "items", "name",
    "names", "self", "this", "true", "false", "null", "none", "type", "types", "main",
    "test", "tests", "error", "errors", "config", "options", "params", "args", "kwargs",
    "string", "number", "object", "array", "list", "dict", "props", "state", "default",
}
MIN_SYMBOL_LEN = 4
MAX_SYMBOLS = 20
MAX_HITS_PER_SYMBOL = 3
SYMBOL_HIT_CEILING = 40


def changed_symbols(diff: str) -> list[str]:
    """Definition-shaped identifiers on the diff's added and removed lines.

    These are the names whose call sites a reviewer would grep for. Order is
    first-seen so the result is deterministic across runs.

    Extraction is skipped entirely for a hunk's added lines when its new path
    is not code-shaped (and likewise for removed lines against its old path) —
    `_hunks()` already tracks which file each line belongs to, so this reuses
    it rather than scanning raw diff text blind to file boundaries. Without
    that attribution, `DEF_RE`'s `type <name>` alternative fires on ordinary
    English prose in a markdown diff ("... type explaining the split ..."),
    which burns slots in the 20-symbol cap on words no grep will ever find.
    """
    seen: list[str] = []
    for new_path, old_path, _old, _new, body in _hunks(diff):
        added_ok = new_path is not None and _suffix(new_path) in CODE_SUFFIXES
        removed_ok = old_path is not None and _suffix(old_path) in CODE_SUFFIXES
        for line in body:
            if line.startswith("+"):
                if not added_ok:
                    continue
            elif line.startswith("-"):
                if not removed_ok:
                    continue
            else:
                continue
            for m in DEF_RE.finditer(line[1:]):
                name = m.group("name")
                if len(name) < MIN_SYMBOL_LEN or name.lower() in SYMBOL_STOPLIST:
                    continue
                if name not in seen:
                    seen.append(name)
    return seen[:MAX_SYMBOLS]


def walk_source(root: Path, cfg: dict):
    """Yield (relpath, text) for every readable, code-shaped text file under `root`.

    Restricted to `CODE_SUFFIXES` so the repo-wide grep searches source, not
    prose: an unrestricted walk turns every markdown file that happens to
    mention a changed identifier — a design doc, a kanban board, a changelog —
    into an indistinguishable "hit" alongside a genuine call site.
    """
    ignore = cfg.get("ignore_paths") or []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/.git/" in f"/{rel}":
            continue
        if _suffix(rel) not in CODE_SUFFIXES:
            continue
        if path_matches(rel, ignore):
            continue
        try:
            if path.stat().st_size > MAX_SOURCE_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if is_binary(data):
            continue
        yield rel, data.decode("utf-8", "replace")


def _clip_hit(line: str) -> str:
    """One grep hit line, stripped and clipped to MAX_HIT_CHARS with a marker."""
    line = line.strip()
    if len(line) <= MAX_HIT_CHARS:
        return line
    return line[:MAX_HIT_CHARS] + " … (line clipped)"


def grep_repo(
    root: Path, needles: list[str], cfg: dict, *, exclude: set[str], max_hits: int
) -> dict[str, list[tuple[str, int, str]]]:
    """needle -> up to `max_hits` (relpath, lineno, line) matches outside `exclude`.

    A needle exceeding SYMBOL_HIT_CEILING total matches is dropped entirely rather
    than sampled: a name that appears everywhere tells a reviewer nothing and would
    crowd out one that appears twice in the file that matters.

    Each hit line is clipped to MAX_HIT_CHARS. `walk_source` admits any
    code-suffixed file up to MAX_SOURCE_BYTES, and a minified or generated `.js`
    is one line half a megabyte long — a single such hit would spend the whole
    call-sites budget by itself, and no reviewer could read it anyway. The clip
    is marked so the line is not mistaken for the whole of it.
    """
    if not needles:
        return {}
    counts = {n: 0 for n in needles}
    hits: dict[str, list[tuple[str, int, str]]] = {n: [] for n in needles}
    for rel, text in walk_source(root, cfg):
        if rel in exclude:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for needle in needles:
                if needle in line:
                    counts[needle] += 1
                    if len(hits[needle]) < max_hits:
                        hits[needle].append((rel, lineno, _clip_hit(line)))
    return {n: h for n, h in hits.items() if h and counts[n] <= SYMBOL_HIT_CEILING}


def pack_call_sites(
    root: Path | None, diff: str, ranges: dict[str, list[tuple[int, int]]],
    cfg: dict, acc: "Accounting",
) -> str:
    """Call sites of changed symbols, and importers of changed modules."""
    if root is None:
        return ""

    changed = set(ranges)
    symbols = changed_symbols(diff)
    # Importers are cheaper and more precise than symbol matching, so they run even
    # when nothing definition-shaped changed.
    #
    # Iterated over `ranges` itself, not `set(ranges)`: `ranges` is an
    # insertion-ordered dict, so this is deterministic across runs, while a
    # set's iteration order depends on CPython's per-process string-hash
    # randomisation. With more module stems than fit under MAX_SYMBOLS once
    # combined with `symbols`, which stems survive the cap must not depend on
    # hash seed — the same diff and checkout must always produce the same
    # section, or `--save`-based before/after comparisons (see CLAUDE.md) can't
    # tell a real change from seed noise, and an unchanged PR re-review misses
    # the prompt cache.
    modules = []
    for rel in ranges:
        stem = _module_stem(rel)
        if len(stem) >= MIN_SYMBOL_LEN and stem.lower() not in SYMBOL_STOPLIST:
            modules.append(stem)

    needles = list(dict.fromkeys(symbols + modules))[:MAX_SYMBOLS]
    found = grep_repo(root, needles, cfg, exclude=changed, max_hits=MAX_HITS_PER_SYMBOL)
    if not found:
        return ""

    parts = []
    for needle, hits in found.items():
        rendered = "\n".join(f"{rel}:{lineno}: {line}" for rel, lineno, line in hits)
        parts.append(f"### `{needle}`\n```\n{rendered}\n```\n")

    header = (
        "## Call sites and importers outside the diff\n\n"
        "Context only, found by grep over the checkout. Use these to judge whether a "
        "changed signature, return shape or invariant breaks something the diff does not "
        "show. Matching is textual, so a hit may be unrelated — read it before relying on "
        "it, and anchor any finding to the diff line that causes the problem.\n\n"
    )
    return acc.add("call_sites", header + "\n".join(parts))


# In precedence order. README is a fallback only: it is usually description rather
# than instruction, and it is often long enough to crowd out the real conventions.
CONVENTION_FILES = ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md")
TREE_KEEP_DEPTH = 2


def _fence(text: str) -> str:
    """A backtick fence strictly longer than any run of backticks in `text`.

    Markdown closes a fenced block at the first line that is itself a run of
    backticks at least as long as the one that opened it. A fixed 3-backtick
    wrapper is therefore closed early by any embedded document that contains
    its own 3-or-more-backtick block — routine in a CLAUDE.md/AGENTS.md that
    documents fenced examples — after which the rest of the document, and
    its own `#`/`##` headings, spill out unfenced into the prompt at the
    same structural level as the pack's own section headings. The fence
    must outrun whatever the longest run in the content actually is, not
    merely upgrade from three backticks to four.
    """
    runs = re.findall(r"`+", text)
    longest = max((len(r) for r in runs), default=0)
    return "`" * max(3, longest + 1)


def _truncate_inline(text: str, limit: int) -> str:
    """One embedded document cut to at most `limit` characters, marked in band.

    The same `_capped` every section budget goes through, on the same marker
    ladder — a document-scale echo of `Accounting.add`. Used instead of a bare
    `text[:limit]` so a truncated document still visibly says so, exactly like
    a truncated section does.

    The caller wraps the result in a `_fence()` longer than any run in the
    *whole* document, so no cut here can close that wrapper; the fence
    balancing `_capped` does inside the cut costs nothing and keeps the
    property unconditional rather than conditional on that wrapper.
    """
    return _capped(text, limit, truncation_markers())


def pack_conventions(root: Path | None, ranges: dict[str, list[tuple[int, int]]], acc: "Accounting") -> str:
    """The conventions documents governing the changed directories.

    Collects every `CONVENTION_FILES` match from each changed file's own
    directory up to the repo root, across every touched branch, then orders
    the result by *distance*: for each candidate directory, the fewest
    levels down to the nearest changed directory beneath it (0 for a file
    that sits directly in a changed directory), ascending. Ties — including
    the common case of two different branches each holding a file in their
    own changed directory — are broken by `(-depth, path)`, deeper first,
    for a stable, deterministic order rather than a meaningful one.
    `Accounting.add` truncates from the tail, so this is what a budget
    squeeze sacrifices last: the file nearest to *some* change, not merely
    the file living at the deepest absolute path. Absolute depth alone was
    tried first and is wrong across branches — a file two directories above
    a deeply-nested change can outrank a file sitting right next to a
    shallower one, which is backwards; distance-to-nearest-change is what
    the "most specific guidance survives" guarantee actually requires.
    Root is never truly favoured or disfavoured by this rule on its own
    merits — it wins only when it is, in fact, the nearest convention file
    to every touched branch (e.g. a repo with no nested convention files at
    all), which is the correct outcome in that case.

    Sorting on a tuple key rather than relying on insertion order also means
    the result cannot depend on set/dict iteration order, which is otherwise
    seeded per-process and would make the pack non-deterministic across runs.

    README is added only when nothing in `CONVENTION_FILES` was found
    anywhere: it is usually description rather than instruction, and is often
    long enough on its own to crowd out the real thing under the budget.

    Each document is wrapped in its own `_fence()`-sized delimiter (see
    `pack_changed_files`, which does the same for file bodies): a convention
    document's own `#`/`##` headings must stay visibly inside a quoted block
    rather than reading as more prompt structure at the same level as this
    section's own `## Repo conventions` heading.

    Each block is truncated against the remaining budget *before* its
    closing fence is written, document by document, rather than fencing
    everything and handing the whole lot to `Accounting.add` in one shot: a
    plain character-count cut has no notion of a fence, so it can land
    inside one and leave it open — and everything `build_context` appends
    after this section would then read as quoted content for the rest of
    the pack. `acc.add` is still called exactly once, at the very end, as
    the final authority on the budget (covering, for instance, a budget too
    small even for the header alone).
    """
    if root is None:
        return ""

    # Every directory a changed file lives directly in ("" for one at the
    # repo root), unioned with every ancestor of each up to "" itself — the
    # full set of prefixes worth checking for a convention file, for every
    # touched branch at once.
    own_dirs = {rel.rsplit("/", 1)[0] if "/" in rel else "" for rel in ranges} or {""}
    prefixes: set[str] = {""}
    for d in own_dirs:
        parts = d.split("/") if d else []
        for depth in range(len(parts), -1, -1):
            prefixes.add("/".join(parts[:depth]))

    def depth_of(prefix: str) -> int:
        return 0 if not prefix else prefix.count("/") + 1

    def is_ancestor(prefix: str, d: str) -> bool:
        return prefix == "" or d == prefix or d.startswith(prefix + "/")

    def distance_of(prefix: str) -> int:
        # Every prefix here was built as an ancestor of at least one own_dir
        # (see the loop above), so this is never an empty min().
        return min(depth_of(d) - depth_of(prefix) for d in own_dirs if is_ancestor(prefix, d))

    wanted: list[str] = []
    for prefix in sorted(prefixes, key=lambda p: (distance_of(p), -depth_of(p), p)):
        for name in CONVENTION_FILES:
            rel = f"{prefix}/{name}" if prefix else name
            if (root / rel).is_file() and rel not in wanted:
                wanted.append(rel)

    if not wanted and (root / "README.md").is_file():
        wanted.append("README.md")
    if not wanted:
        return ""

    header = (
        "## Repo conventions\n\n"
        "Context only. These are this repo's own stated rules and are what "
        "\"consistent with the codebase\" means here — they outrank your own preferences.\n\n"
    )

    budget = max(0, acc.limits.get("conventions", 0))
    used = len(header)
    blocks: list[str] = []
    truncated_a_document = False
    for rel in wanted:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fence = _fence(text)
        sep = "\n" if blocks else ""
        heading = f"### {rel}\n"
        # Everything in the block except the body itself: the separator,
        # the heading, both fence lines, and the newline after the body.
        overhead = len(sep) + len(heading) + 2 * len(fence) + 3
        remaining = budget - used - overhead
        if remaining <= 0:
            truncated_a_document = True
            break
        if len(text) > remaining:
            text = _truncate_inline(text, remaining)
            truncated_a_document = True
        block = f"{sep}{heading}{fence}\n{text}\n{fence}\n"
        blocks.append(block)
        used += len(block)
        if truncated_a_document:
            break

    text_out = header + "".join(blocks)
    if truncated_a_document:
        acc.truncated.add("conventions")
        # A document whose *own* body was cut already carries its own
        # in-band marker (from `_truncate_inline`), but a document dropped
        # outright — its wrapper alone didn't fit what was left — leaves no
        # trace at all without this: a trailing, unfenced note, sized to
        # whatever budget remains after the last block that did fit.
        room = budget - len(text_out)
        full = f"\n… truncated: conventions exceeded its {budget}-character budget …\n"
        for marker in truncation_markers(full):
            if len(marker) <= room:
                text_out += marker
                break
    return acc.add("conventions", text_out)


def pack_tree(root: Path | None, ranges: dict[str, list[tuple[int, int]]], cfg: dict, acc: "Accounting") -> str:
    """A pruned path listing: full detail near the change, shallow elsewhere.

    This is what lets a lens notice the repo already has the helper the PR
    reimplements. Pruned rather than flat-truncated, because an alphabetical
    cut at N characters keeps everything under `a/` and nothing under `s/`.

    Deliberately not built from `walk_source`: that walk is restricted to
    `CODE_SUFFIXES` for the call-site grep's benefit (prose false-positives),
    but a listing whose whole purpose is "what does this repo already have"
    should not silently drop `README.md`, `Makefile`, and every config file —
    those are exactly the paths that tell a lens whether something already
    exists. So this walks the tree itself, reusing the same `.git` and
    `ignore_paths` exclusions, but no suffix filter and no file contents (a
    path listing never needs to read a file's bytes).
    """
    if root is None:
        return ""

    near = {rel.rsplit("/", 1)[0] for rel in ranges if "/" in rel}
    ignore = cfg.get("ignore_paths") or []
    keep: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/.git/" in f"/{rel}":
            continue
        if path_matches(rel, ignore):
            continue
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if parent in near or rel.count("/") < TREE_KEEP_DEPTH:
            keep.append(rel)

    if not keep:
        return ""
    header = (
        "## Path tree (pruned)\n\n"
        "Context only. Full listing for directories the diff touches, shallow "
        "elsewhere. Use it to check whether something already exists before "
        "calling it missing.\n\n"
    )
    return acc.add("tree", header + "```\n" + "\n".join(sorted(keep)) + "\n```\n")


def diff_paths(diff: str) -> dict[str, list[tuple[int, int]]]:
    """path -> RIGHT-side (start, end) inclusive line ranges the diff touches.

    Deleted files are absent: there is no head-side file to read for them.
    """
    out: dict[str, list[tuple[int, int]]] = {}
    for new_path, _old_path, _old, new, body in _hunks(diff):
        if new_path is None:
            continue
        span = sum(1 for ln in body if not ln.startswith("-"))
        if span:
            out.setdefault(new_path, []).append((new, new + span - 1))
    return out


def diff_anchors(diff: str) -> set[tuple[str, int, str]]:
    """(path, line, side) triples GitHub will accept as an inline comment anchor.

    A comment on a line the diff does not touch makes GitHub reject the ENTIRE
    review with a 422, which is why this exists — see post_review's fallback.
    """
    anchors: set[tuple[str, int, str]] = set()
    for new_path, old_path, old, new, body in _hunks(diff):
        old_n, new_n = old, new
        for line in body:
            if line.startswith("+"):
                if new_path:
                    anchors.add((new_path, new_n, "RIGHT"))
                new_n += 1
            elif line.startswith("-"):
                if old_path:
                    anchors.add((old_path, old_n, "LEFT"))
                old_n += 1
            else:
                if new_path:
                    anchors.add((new_path, new_n, "RIGHT"))
                if old_path:
                    anchors.add((old_path, old_n, "LEFT"))
                old_n += 1
                new_n += 1
    return anchors


def anchor_violations(envelopes: list[dict], diff: str) -> list[tuple[str, dict]]:
    """Findings anchored outside the diff, as (lens, finding) pairs.

    Doctrine etiquette rule 4 forbids these, and giving a lens surrounding code
    makes them tempting. They are REPORTED, never dropped: a real bug cited at a
    slightly wrong line is worth more than a clean log, and post_review already
    folds inline comments into the body when GitHub rejects them with a 422.
    The count is the signal for whether the pack is eroding lens discipline.
    """
    anchors = diff_anchors(diff)
    return [
        (env["lens"], f)
        for env in envelopes
        for f in env.get("findings") or []
        if (f["path"], f["line"], f["side"]) not in anchors
    ]


# Fractions of max_context_chars, not absolute sizes, so one config knob scales the
# whole pack. Must sum to 1.0 — tests/test_context.py asserts it. Slack in an
# underfilled part is deliberately NOT reallocated: that is a tuning-time
# optimisation with no evidence behind it yet.
CONTEXT_SHARES = {
    "changed_files": 0.48,
    "call_sites": 0.18,
    "conventions": 0.14,
    "requirements": 0.13,
    "tree": 0.07,
}


def budgets(total: int) -> dict[str, int]:
    # A negative or zero total must behave exactly like an all-zero budget,
    # never a negative one — Accounting.add() relies on every limit being
    # non-negative to keep its own guarantee.
    return {part: max(0, int(total * share)) for part, share in CONTEXT_SHARES.items()}


class Accounting:
    """Enforces per-part budgets and records what each part actually used.

    Truncation is always marked in-band: a lens that cannot tell a truncated
    section from a complete one will treat absence as evidence, which is exactly
    the failure the porting note warns about. Only a limit of exactly 0 — which
    cannot carry so much as a single character of signal — is ever silent.
    """

    def __init__(self, limits: dict[str, int]) -> None:
        # budgets() already clamps, but Accounting may be constructed directly
        # (as the tests do), so a negative limit is clamped here too rather
        # than trusted.
        self.limits = {part: max(0, limit) for part, limit in limits.items()}
        self.used = {part: 0 for part in self.limits}
        self.truncated: set[str] = set()

    def add(self, part: str, text: str) -> str:
        limit = max(0, self.limits[part])
        if len(text) <= limit:
            self.used[part] = len(text)
            return text
        self.truncated.add(part)
        # `_capped` owns both halves of this: the marker ladder (the marker
        # itself costs characters, so at a small enough limit it shrinks and
        # finally disappears — only at limit 0, which cannot hold even one
        # character, per this class's contract above) and the guarantee that a
        # section handed here fenced does not go back out with its fence open.
        # Sections that fence their content — call sites, the path tree, an
        # embedded conventions document, every changed-file body — all arrive
        # through this one method, so they are all covered by that guarantee at
        # once rather than each carrying its own fence arithmetic.
        full = f"\n\n… truncated: {part} exceeded its {limit}-character budget …\n"
        out = _capped(text, limit, truncation_markers(full))
        self.used[part] = len(out)
        return out

    def report(self) -> None:
        for part, limit in self.limits.items():
            used = self.used[part]
            flag = " TRUNCATED" if part in self.truncated else ""
            state = "empty" if used == 0 else f"{used}/{limit} chars"
            log(f"    context {part}: {state}{flag}")


def stream_capped(response, dest: Path, cap: int) -> bool:
    """Stream `response` to `dest`, aborting past `cap` bytes. True if complete.

    The tarball size is not known before the download starts, so the cap is
    enforced as it arrives. On abort the partial file is removed — a truncated
    archive is worse than none, because it extracts a plausible-looking subset.
    """
    written = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    return True
                written += len(chunk)
                if written > cap:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    return False
                fh.write(chunk)
    except Exception:  # noqa: BLE001 - a failed download degrades the pack, never the review
        dest.unlink(missing_ok=True)
        return False


def extract_checkout(archive: Path, dest: Path) -> Path | None:
    """Extract a GitHub tarball and return its single top-level directory.

    `filter="data"` is what refuses absolute paths, traversal entries, symlinks
    out of the tree and device files. It is stdlib from 3.12, which is why no
    dependency is needed here.
    """
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest, filter="data")
    except Exception as exc:  # noqa: BLE001
        vlog(f"    context: could not extract {archive.name}: {exc}")
        return None
    tops = [p for p in dest.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else dest


def fetch_checkout(gh: GitHub, repo: str, sha: str, dest: Path, cap: int) -> Path | None:
    """A read-only checkout at `sha`, or None if it could not be obtained."""
    archive = dest / "src.tar.gz"
    try:
        with gh.open_tarball(repo, sha) as resp:
            if not stream_capped(resp, archive, cap):
                log(f"  context: tarball for {repo}@{sha[:7]} exceeded {cap} bytes; degrading")
                return None
    except Exception as exc:  # noqa: BLE001
        log(f"  context: could not fetch tarball for {repo}@{sha[:7]} ({exc}); degrading")
        return None
    return extract_checkout(archive, dest / "tree")


class Context:
    """What the lenses get beyond the diff. `pack` is "" when there is nothing."""

    def __init__(self, requirements: str) -> None:
        self.pack = ""
        self.requirements = requirements
        self.notes: list[str] = []
        self.root: Path | None = None


# `#42`, `Closes #42`, and full issue/PR URLs including cross-repo ones. The
# negative lookbehind keeps anchors from parsing as references, and the digit
# class (leading digit 1-9, never 0) rules out the common hex-colour shapes —
# a GitHub issue number is never 0 and never written with a leading zero, so
# `#000000`, `#0` and `#00042` never match at all. A same-shaped false positive
# that slips through anyway (a bare six-digit number like `#123456`, which is
# indistinguishable from a real large issue number by pattern alone) is left
# to the 404 it gets when resolve_requirements() tries to fetch it — that
# fetch-and-skip is the deliberate backstop for this pattern, not an accident.
# A reference inside a markdown code span (`` `#42` ``) is also left matching
# on purpose: it may well be a genuine reference, and the same backstop makes
# an imprecise match harmless either way.
ISSUE_REF_RE = re.compile(
    r"https?://github\.com/(?P<orepo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<onum>[1-9]\d{0,6})"
    r"|(?<![\w#])#(?P<num>[1-9]\d{0,6})\b"
)
MAX_LINKED_ISSUES = 5


def issue_refs(text: str, repo: str) -> list[tuple[str, int]]:
    """(repo, number) pairs referenced by `text`, deduplicated, first-seen order."""
    out: list[tuple[str, int]] = []
    for m in ISSUE_REF_RE.finditer(text or ""):
        ref = (m.group("orepo"), int(m.group("onum"))) if m.group("orepo") else (repo, int(m.group("num")))
        if ref not in out:
            out.append(ref)
    return out[:MAX_LINKED_ISSUES]


def resolve_requirements(gh, repo: str, pr: dict, acc: Accounting) -> str:
    """The PR body plus its linked issues and any human conversation comments.

    Requirements resolution was `pr.get("body")`, which meant the requirements lens
    judged conformity against whatever the author chose to write. This is the one
    pack part that also reaches the adjudicator, exactly as the plain body does
    today — see doctrine/agents/pr-review-verdict.md.

    Every GitHub failure degrades to what we already had. A thinner requirements
    string is worth far more than a failed review.
    """
    body = (pr.get("body") or "").strip()
    parts = [body] if body else ["(none stated — judge against the PR title alone)"]

    if gh is not None:
        for ref_repo, number in issue_refs(f"{pr.get('title', '')}\n{body}", repo):
            try:
                issue = gh.get(f"/repos/{ref_repo}/issues/{number}")
            except Exception as exc:  # noqa: BLE001
                vlog(f"    context: could not fetch {ref_repo}#{number}: {exc}")
                continue
            parts.append(
                f"### Linked issue {ref_repo}#{number}: {issue.get('title', '')}\n"
                f"{(issue.get('body') or '(empty)').strip()}"
            )

        try:
            comments = gh.get(f"/repos/{repo}/issues/{pr['number']}/comments")
        except Exception as exc:  # noqa: BLE001
            vlog(f"    context: could not fetch PR comments: {exc}")
            comments = []
        human = [
            c for c in comments
            if (c.get("user") or {}).get("type") != "Bot"
            and not ((c.get("user") or {}).get("login", "")).endswith("[bot]")
        ]
        if human:
            rendered = "\n\n".join(
                f"**{(c.get('user') or {}).get('login', '?')}**: {(c.get('body') or '').strip()}"
                for c in human
            )
            parts.append("### Human comments on this PR\n" + rendered)

    return acc.add("requirements", "\n\n".join(parts))


def _checkout_matches_diff(root: Path, diff: str) -> bool:
    """True unless `root` is provably not a checkout of the repo this diff belongs to.

    `is_dir()` alone proves nothing — `--worktree` is a free-form path, and a
    real directory that happens to not be this repo (or a checkout of some
    unrelated repo, or `/tmp`) would otherwise be trusted exactly as much as
    a correct one: every part of the pack that reads from `root` would then
    manufacture confident, unrelated context — a path tree of files that
    aren't this repo's, "call sites" grepped out of code that was never
    touched by this diff.

    Checked against the diff's changed paths that existed *before* the
    diff — a hunk with a real `old_path` (not `/dev/null`) names a file that
    must already be present in any correct checkout of the repo, however
    stale, whether this diff went on to modify, rename, or delete it. That
    is deliberately the *old* name, not the new one: a rename-with-
    modification's `old_path` is the file a correct pre-rename checkout
    still has, while its `new_path` is not there yet — collecting `new_path`
    instead would falsely reject a perfectly good, merely not-yet-renamed
    checkout. A plain modification is unaffected either way, since its
    `old_path` and `new_path` are the same string.

    A PR that only adds new files, or only renames without modifying
    content (which produces no hunk at all, so no old_path either),
    supplies no such path: nothing here can prove or disprove the checkout
    in that case, so it is left alone rather than rejected on no evidence
    at all — a false rejection would silently thin an otherwise-good pack.

    Two known gaps, both inherent to a single-path check under the
    stdlib-only constraint (no proper git identity available without a
    real clone): a diff touching only one pre-existing path that happens
    to be absent from an otherwise-correct checkout is rejected outright
    (no redundancy in a singleton `any()`), and a checkout of a *different*
    repository that happens to share a common filename (`README.md`,
    `src/index.ts`) with a touched path is wrongly accepted (one match is
    all this looks for).
    """
    existing = {old for new, old, *_ in _hunks(diff) if old is not None}
    if not existing:
        return True
    return any((root / rel).is_file() for rel in existing)


@contextmanager
def build_context(
    gh: GitHub | None,
    repo: str,
    pr: dict,
    diff: str,
    cfg: dict,
    *,
    enabled: bool,
    worktree: str | None = None,
):
    """Assemble the pack, owning the temp checkout for exactly one PR.

    Never raises on a pack failure: a review with a thin pack is worth far more
    than no review, so every path here degrades and records why in `notes`.

    That guarantee covers *acquiring* the checkout, not just packing it. It used
    to start at the pack-assembly `try` and leave everything above it bare, which
    made the failures most likely in the real deployment the ones that were not
    covered: `tempfile.TemporaryDirectory` raising OSError on a pod with a
    read-only root filesystem or a full disk failed every review of every pass,
    and so did a `max_tarball_bytes` missing from a repo's config. Both are
    exactly the "thin pack beats no review" case the guarantee exists for.

    `yield ctx` is deliberately *outside* the guard: an exception the caller's
    `with` body raises arrives here at the yield, and swallowing that would
    silently discard a failed review rather than degrade a pack.
    """
    ctx = Context(pr.get("body") or "(none stated — judge against the PR title alone)")
    if not enabled:
        ctx.notes.append("context disabled")
        yield ctx
        return

    tmp: tempfile.TemporaryDirectory | None = None
    try:
        try:
            if worktree:
                root = Path(worktree).expanduser().resolve()
                ctx.root = root if root.is_dir() else None
                if ctx.root is None:
                    ctx.notes.append(f"--worktree {worktree} is not a directory")
            elif gh is not None:
                tmp = tempfile.TemporaryDirectory(prefix="pr-reviewer-")
                head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or repo
                ctx.root = fetch_checkout(
                    gh, head_repo, pr["head"]["sha"], Path(tmp.name), cfg["max_tarball_bytes"]
                )
                if ctx.root is None:
                    ctx.notes.append("no checkout; changed files fetched per-file")
            else:
                ctx.notes.append("no checkout available (offline without --worktree)")

            if ctx.root is not None and not _checkout_matches_diff(ctx.root, diff):
                ctx.notes.append(
                    f"checkout at {ctx.root} matches none of the diff's pre-existing changed "
                    "paths; treating as no checkout"
                )
                ctx.root = None

            acc = Accounting(budgets(cfg["max_context_chars"]))
            ctx.requirements = resolve_requirements(gh, repo, pr, acc)
            sections: list[str] = []
            ranges = diff_paths(diff)
            sections.append(pack_changed_files(
                ctx.root, gh, repo, pr["head"]["sha"], ranges, cfg, acc))
            sections.append(pack_call_sites(ctx.root, diff, ranges, cfg, acc))
            sections.append(pack_conventions(ctx.root, ranges, acc))
            sections.append(pack_tree(ctx.root, ranges, cfg, acc))
            ctx.pack = "\n".join(s for s in sections if s)
            acc.report()
        except Exception as exc:  # noqa: BLE001 - anything here degrades the pack, never the review
            ctx.notes.append(f"context assembly failed ({exc}); pack left empty")
            ctx.pack, ctx.root = "", None

        for note in ctx.notes:
            log(f"    context note: {note}")
        yield ctx
    finally:
        # `tmp` is still None when TemporaryDirectory itself was what failed.
        if tmp is not None:
            tmp.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# The pass
# ─────────────────────────────────────────────────────────────────────────────


# The deployment-specific tail. Doctrine stays verbatim upstream, so caveats about
# this deployment live here and in the porting note — see CLAUDE.md.
LENS_TAIL = (
    "You have no tools in this deployment. Everything you get to see is in this "
    "prompt: the diff above is your diff of record, and the context sections that "
    "follow it — changed files at head, call sites, repo conventions, the path tree — "
    "are your substitute for a worktree. Read around the diff there.\n\n"
    "Where a context section is absent, or carries a truncation marker such as "
    "`… 340 lines elided …`, that is code you have not seen. Do not speculate about "
    "it. If a finding depends on something you cannot see, either omit it or file it "
    "as advisory and say in `consequence` that it is unverified.\n\n"
    "Context informs a finding; it never locates one. Every finding must anchor to a "
    "`path:line` the diff itself touches — a line you found only by reading the "
    "context sections is not a valid anchor. Return only the JSON envelope."
)


def build_lens_prompt(
    lens: str, pr: dict, repo: str, diff: str, requirements: str, pack: str
) -> tuple[list[dict], list[dict]]:
    """Three blocks: shared doctrine | shared content | lens-specific tail.

    Blocks 1 and 2 are the cacheable prefix, and they MUST be byte-identical
    across the three lenses — one lens-dependent character anywhere in them and
    all three calls miss the cache. That is why the lens name and the lens brief
    are in block 3 and nowhere else, and why nothing here may be reordered for
    readability. tests/test_prompting.py enforces it.
    """
    doctrine = "\n\n".join([DOC("agents/pr-review-lens.md"), DOC("lenses/_shared.md")])
    shared = (
        f"pr: {pr['number']}\n"
        f"target_repo: {repo}\n\n"
        f"## PR title\n{pr.get('title', '')}\n\n"
        f"## PR body\n{pr.get('body') or '(empty)'}\n\n"
        f"## Resolved requirements\n{requirements}\n\n"
        f"## Prior recommendations\n{pr.get('_prior_body') or '(none — this is round 1)'}\n\n"
        f"## Diff (`gh pr diff` canonical rendering)\n```diff\n{diff}\n```\n"
    )
    if pack:
        shared += f"\n{pack}\n"
    tail = f"lens: {lens}\n\n{DOC(f'lenses/{lens}.md')}\n\n{LENS_TAIL}"
    return [seg(doctrine, cache=True)], [seg(shared, cache=True), seg(tail)]


def run_lens(
    lens: str, pr: dict, repo: str, diff: str, requirements: str, pack: str, model: str
) -> dict:
    system, user = build_lens_prompt(lens, pr, repo, diff, requirements, pack)
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


def dispatch_lenses(lenses: tuple[str, ...], runner, *, stagger: bool) -> list[dict]:
    """Run every lens, returning envelopes in `lenses` order.

    With `stagger`, the first lens runs alone so that it writes the shared cache
    prefix, and the rest then read it. Three cold parallel calls would each pay
    the cache-write premium and none would read — worse than not caching at all.
    The cost is wall clock: one lens-latency becomes two.

    `runner` must not raise for a merely-failed lens; run_panel wraps it so a
    failure becomes a needs-input envelope instead of losing the whole panel.
    """
    head: tuple[str, ...] = ()
    tail = lenses
    if stagger and len(lenses) > 1:
        head, tail = lenses[:1], lenses[1:]

    results = {lens: runner(lens) for lens in head}

    if tail:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tail)) as pool:
            futures = {pool.submit(runner, lens): lens for lens in tail}
            for fut in concurrent.futures.as_completed(futures):
                results[futures[fut]] = fut.result()

    return [results[lens] for lens in lenses]


def run_panel(pr: dict, repo: str, diff: str, ctx: Context, opts: argparse.Namespace) -> dict | None:
    """The first lens runs alone to write the cache prefix; the rest follow in
    parallel once it has (see dispatch_lenses). Then adjudication.
    None means there was nothing to adjudicate.
    """
    lenses = tuple(opts.lens) if opts.lens else LENSES
    log(f"  dispatching {len(lenses)} lens(es) over {diff_size(diff)} changed lines")

    def runner(lens: str) -> dict:
        # A failed lens must not lose the other two, so the envelope is
        # synthesised here rather than allowed to escape dispatch_lenses.
        try:
            return run_lens(lens, pr, repo, diff, ctx.requirements, ctx.pack, opts.model_lens)
        except Exception as exc:  # noqa: BLE001
            log(f"    lens:{lens} FAILED: {exc}")
            return {"lens": lens, "status": "needs-input", "findings": [], "notes": f"failed: {exc}"}

    stagger = CACHE_ENABLED and len(lenses) > 1
    if stagger:
        log(f"  staggering: {lenses[0]} first to write the cache, then {len(lenses) - 1} in parallel")
    envelopes = dispatch_lenses(lenses, runner, stagger=stagger)

    if all(e["status"] == "needs-input" for e in envelopes):
        log("  all lenses failed — nothing to adjudicate")
        return None

    total = sum(len(e["findings"]) for e in envelopes)
    log(f"  panel returned {total} finding(s); adjudicating")

    violations = anchor_violations(envelopes, diff)
    if violations:
        log(f"  WARNING: {len(violations)} finding(s) anchored outside the diff (kept, not dropped):")
        for lens, f in violations:
            log(f"    lens:{lens} {f['path']}:{f['line']} {f['side']} — {f['claim'][:80]}")
    else:
        log("  anchors: all findings anchor inside the diff")

    # The adjudicator sees the lens envelopes, the PR body, the prior review and the
    # resolved requirements — never the diff, and never ctx.pack. That is structural:
    # doctrine/agents/pr-review-verdict.md explains why. Do not "fix" this.
    verdict = adjudicate(pr, repo, envelopes, ctx.requirements, opts.model_verdict)

    if opts.save:
        out = Path(opts.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"repo": repo, "pr": pr["number"], "pack": ctx.pack,
                 "requirements": ctx.requirements, "envelopes": envelopes, "verdict": verdict},
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

    global CACHE_ENABLED
    CACHE_ENABLED = resolve_cache(opts, cfg)

    with build_context(
        gh, repo, pr, diff, cfg,
        enabled=cfg.get("context", True) and not opts.no_context,
        worktree=opts.worktree,
    ) as ctx:
        verdict = run_panel(pr, repo, diff, ctx, opts)
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
    global CACHE_ENABLED
    CACHE_ENABLED = resolve_cache(opts)
    cfg = dict(DEFAULTS)
    with build_context(
        None, opts.repo_name or "local/local", pr, diff, cfg,
        enabled=not opts.no_context,
        worktree=opts.worktree,
    ) as ctx:
        verdict = run_panel(pr, opts.repo_name or "local/local", diff, ctx, opts)
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
    p.add_argument("--no-cache", action="store_true",
                   help="disable prompt caching and revert to a single parallel lens wave")
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
    p.add_argument("--no-context", action="store_true",
                   help="disable the context pack (review from the diff alone)")
    p.add_argument("--worktree", metavar="PATH",
                   help="read context from a local checkout instead of fetching a tarball")
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


def resolve_cache(opts: argparse.Namespace, cfg: dict | None = None) -> bool:
    """Caching is on unless the CLI or the target repo's config turns it off.

    The CLI wins, so --no-cache is always an effective escape hatch regardless of
    what a target repo asks for.
    """
    if opts.no_cache:
        return False
    return bool((cfg or DEFAULTS).get("cache", True))


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
