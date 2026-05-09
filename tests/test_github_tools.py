import base64
import json
from unittest.mock import patch

from pico import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from pico.github_mcp_server import handle
from pico.mcp_client import GitHubMCPClient
from pico import github_tools


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def build_agent(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return MiniAgent(
        model_client=FakeModelClient([]),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
    )


def test_github_tools_are_registered_with_expected_risk(tmp_path):
    agent = build_agent(tmp_path)

    assert agent.tools["github_get_file"]["risky"] is False
    assert agent.tools["github_create_branch"]["risky"] is True
    assert agent.tools["github_update_file"]["risky"] is True
    assert agent.tools["github_create_pr"]["risky"] is True


def test_github_mcp_server_lists_github_tools():
    result = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = [tool["name"] for tool in result["tools"]]

    assert names == [
        "github_get_file",
        "github_create_branch",
        "github_update_file",
        "github_create_pr",
    ]


def test_github_mcp_client_lists_tools_over_stdio():
    client = GitHubMCPClient()
    try:
        names = [tool["name"] for tool in client.list_tools()]
    finally:
        client.close()

    assert "github_get_file" in names
    assert "github_create_pr" in names


def test_pico_github_tool_runner_calls_mcp(tmp_path):
    agent = build_agent(tmp_path)

    with patch("pico.tools._github_mcp_call") as fake_call:
        fake_call.return_value = json.dumps(
            {
                "repo": "octo/demo",
                "path": "README.md",
                "ref": "main",
                "sha": "readme-sha",
                "content": "hello through mcp\n",
            }
        )
        result = agent.run_tool(
            "github_get_file",
            {
                "repo": "octo/demo",
                "path": "README.md",
                "ref": "main",
            },
        )

    fake_call.assert_called_once_with(
        agent,
        "github_get_file",
        {
            "repo": "octo/demo",
            "path": "README.md",
            "ref": "main",
        },
    )
    assert "hello through mcp" in result


def test_github_get_file_downloads_and_decodes_content():
    captured = {}
    encoded = base64.b64encode("hello github\n".encode("utf-8")).decode("ascii")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        return FakeResponse(
            {
                "type": "file",
                "path": "README.md",
                "sha": "sha-readme",
                "encoding": "base64",
                "content": encoded,
            }
        )

    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp-test"}, clear=True), patch(
        "urllib.request.urlopen",
        fake_urlopen,
    ):
        result = github_tools.get_file("octo/demo", "README.md", ref="main")

    assert result["content"] == "hello github\n"
    assert result["sha"] == "sha-readme"
    assert captured["url"] == "https://api.github.com/repos/octo/demo/contents/README.md?ref=main"
    assert captured["timeout"] == 60
    assert captured["headers"]["Authorization"] == "Bearer ghp-test"


def test_github_update_file_uses_existing_sha_and_commits_to_branch():
    calls = []
    encoded = base64.b64encode("old\n".encode("utf-8")).decode("ascii")

    def fake_urlopen(request, timeout):
        del timeout
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        calls.append((request.method, request.full_url, body))
        if request.method == "GET":
            return FakeResponse(
                {
                    "type": "file",
                    "path": "README.md",
                    "sha": "old-sha",
                    "encoding": "base64",
                    "content": encoded,
                }
            )
        return FakeResponse(
            {
                "content": {"sha": "new-content-sha"},
                "commit": {"sha": "commit-sha", "html_url": "https://github.com/octo/demo/commit/commit-sha"},
            }
        )

    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp-test"}, clear=True), patch(
        "urllib.request.urlopen",
        fake_urlopen,
    ):
        result = github_tools.update_file(
            repo="octo/demo",
            path="README.md",
            content="new\n",
            branch="pico/update-readme",
            message="Update README",
        )

    assert result["commit_sha"] == "commit-sha"
    assert calls[0][0] == "GET"
    assert calls[1][0] == "PUT"
    assert calls[1][2]["branch"] == "pico/update-readme"
    assert calls[1][2]["message"] == "Update README"
    assert calls[1][2]["sha"] == "old-sha"
    assert base64.b64decode(calls[1][2]["content"]).decode("utf-8") == "new\n"


def test_github_tool_validation_rejects_bad_repo_and_path(tmp_path):
    agent = build_agent(tmp_path)

    bad_repo = agent.run_tool("github_get_file", {"repo": "missing-slash", "path": "README.md"})
    bad_path = agent.run_tool("github_get_file", {"repo": "octo/demo", "path": "../secret.txt"})

    assert "repo must look like 'owner/name'" in bad_repo
    assert "path must not contain '..' segments" in bad_path
