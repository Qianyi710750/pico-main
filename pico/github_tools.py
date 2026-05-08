import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_GITHUB_API_BASE = "https://api.github.com"


def github_token():
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT") or os.environ.get("GH_PAT") or ""


def github_api_base():
    return os.environ.get("GITHUB_API_BASE", DEFAULT_GITHUB_API_BASE).rstrip("/")


def parse_repo(repo):
    value = str(repo or "").strip().strip("/")
    if not value or "/" not in value:
        raise ValueError("repo must look like 'owner/name'")
    owner, name = value.split("/", 1)
    owner = owner.strip()
    name = name.strip()
    if not owner or not name or "/" in name:
        raise ValueError("repo must look like 'owner/name'")
    return owner, name


def _request(method, path, payload=None, token=None):
    token = token if token is not None else github_token()
    if not token:
        raise RuntimeError("missing GitHub token; set GITHUB_TOKEN, GITHUB_PAT, or GH_PAT")

    url = github_api_base() + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "pico-local-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach GitHub API: {exc}") from exc

    if not body.strip():
        return {}
    return json.loads(body)


def _contents_path(owner, name, path, ref=None):
    encoded_path = urllib.parse.quote(str(path).strip().lstrip("/"), safe="/")
    query = ""
    if ref:
        query = "?ref=" + urllib.parse.quote(str(ref), safe="")
    return f"/repos/{owner}/{name}/contents/{encoded_path}{query}"


def get_file(repo, path, ref=""):
    owner, name = parse_repo(repo)
    data = _request("GET", _contents_path(owner, name, path, ref=ref or None))
    if data.get("type") != "file":
        raise RuntimeError(f"GitHub path is not a file: {path}")
    encoding = data.get("encoding", "")
    content = data.get("content", "")
    if encoding != "base64":
        raise RuntimeError(f"unsupported GitHub content encoding: {encoding}")
    text = base64.b64decode(content.encode("ascii")).decode("utf-8", errors="replace")
    return {
        "repo": f"{owner}/{name}",
        "path": data.get("path", path),
        "ref": ref,
        "sha": data.get("sha", ""),
        "content": text,
    }


def create_branch(repo, branch, from_branch="main"):
    owner, name = parse_repo(repo)
    source = _request("GET", f"/repos/{owner}/{name}/git/ref/heads/{urllib.parse.quote(str(from_branch), safe='')}")
    sha = source.get("object", {}).get("sha", "")
    if not sha:
        raise RuntimeError(f"could not resolve source branch: {from_branch}")
    payload = {
        "ref": f"refs/heads/{branch}",
        "sha": sha,
    }
    data = _request("POST", f"/repos/{owner}/{name}/git/refs", payload)
    return {
        "repo": f"{owner}/{name}",
        "branch": branch,
        "from_branch": from_branch,
        "sha": data.get("object", {}).get("sha", sha),
        "url": data.get("url", ""),
    }


def update_file(repo, path, content, branch, message, sha=""):
    owner, name = parse_repo(repo)
    if not sha:
        try:
            existing = get_file(repo, path, ref=branch)
            sha = existing.get("sha", "")
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            sha = ""

    payload = {
        "message": str(message),
        "content": base64.b64encode(str(content).encode("utf-8")).decode("ascii"),
        "branch": str(branch),
    }
    if sha:
        payload["sha"] = sha
    data = _request("PUT", _contents_path(owner, name, path), payload)
    commit = data.get("commit", {})
    return {
        "repo": f"{owner}/{name}",
        "path": path,
        "branch": branch,
        "commit_sha": commit.get("sha", ""),
        "html_url": commit.get("html_url", ""),
        "content_sha": data.get("content", {}).get("sha", ""),
    }


def create_pr(repo, title, head, base="main", body=""):
    owner, name = parse_repo(repo)
    payload = {
        "title": str(title),
        "head": str(head),
        "base": str(base),
        "body": str(body or ""),
    }
    data = _request("POST", f"/repos/{owner}/{name}/pulls", payload)
    return {
        "repo": f"{owner}/{name}",
        "number": data.get("number"),
        "title": data.get("title", title),
        "html_url": data.get("html_url", ""),
        "state": data.get("state", ""),
    }
