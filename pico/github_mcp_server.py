import json
import sys

from . import github_tools


SERVER_INFO = {"name": "pico-github-mcp", "version": "0.1.0"}


TOOLS = [
    {
        "name": "github_get_file",
        "description": "Download a UTF-8 file from a GitHub repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository in owner/name form."},
                "path": {"type": "string", "description": "File path inside the repository."},
                "ref": {"type": "string", "description": "Branch, tag, or commit SHA."},
            },
            "required": ["repo", "path"],
        },
    },
    {
        "name": "github_create_branch",
        "description": "Create a GitHub branch from another branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository in owner/name form."},
                "branch": {"type": "string", "description": "New branch name."},
                "from_branch": {"type": "string", "description": "Source branch name."},
            },
            "required": ["repo", "branch"],
        },
    },
    {
        "name": "github_update_file",
        "description": "Create or update a UTF-8 file on a GitHub branch with one commit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository in owner/name form."},
                "path": {"type": "string", "description": "File path inside the repository."},
                "content": {"type": "string", "description": "Full replacement file content."},
                "branch": {"type": "string", "description": "Target branch name."},
                "message": {"type": "string", "description": "Commit message."},
                "sha": {"type": "string", "description": "Optional current blob SHA."},
            },
            "required": ["repo", "path", "content", "branch", "message"],
        },
    },
    {
        "name": "github_create_pr",
        "description": "Create a GitHub pull request from head into base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository in owner/name form."},
                "title": {"type": "string", "description": "Pull request title."},
                "head": {"type": "string", "description": "Head branch name."},
                "base": {"type": "string", "description": "Base branch name."},
                "body": {"type": "string", "description": "Pull request body."},
            },
            "required": ["repo", "title", "head"],
        },
    },
]


def _text(payload):
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _tool_result(payload):
    return {"content": [{"type": "text", "text": _text(payload)}]}


def call_tool(name, arguments):
    args = arguments or {}
    if name == "github_get_file":
        result = github_tools.get_file(
            repo=args["repo"],
            path=args["path"],
            ref=args.get("ref", ""),
        )
        return _tool_result(
            {
                "repo": result["repo"],
                "path": result["path"],
                "ref": result.get("ref", "") or "",
                "sha": result["sha"],
                "content": result["content"],
            }
        )
    if name == "github_create_branch":
        return _tool_result(
            github_tools.create_branch(
                repo=args["repo"],
                branch=args["branch"],
                from_branch=args.get("from_branch", "main"),
            )
        )
    if name == "github_update_file":
        return _tool_result(
            github_tools.update_file(
                repo=args["repo"],
                path=args["path"],
                content=args["content"],
                branch=args["branch"],
                message=args["message"],
                sha=args.get("sha", ""),
            )
        )
    if name == "github_create_pr":
        return _tool_result(
            github_tools.create_pr(
                repo=args["repo"],
                title=args["title"],
                head=args["head"],
                base=args.get("base", "main"),
                body=args.get("body", ""),
            )
        )
    raise ValueError(f"unknown GitHub MCP tool: {name}")


def handle(message):
    method = message.get("method", "")
    if method == "initialize":
        return {
            "protocolVersion": message.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = message.get("params", {})
        return call_tool(params.get("name", ""), params.get("arguments", {}))
    raise ValueError(f"unsupported MCP method: {method}")


def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
            result = handle(message)
            if "id" in message:
                send({"jsonrpc": "2.0", "id": message["id"], "result": result or {}})
        except Exception as exc:
            request_id = None
            try:
                request_id = json.loads(raw).get("id")
            except Exception:
                pass
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(exc)},
                }
            )


if __name__ == "__main__":
    main()
