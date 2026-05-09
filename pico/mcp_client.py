import atexit
import json
import subprocess
import sys
from threading import Lock


class StdioMCPClient:
    def __init__(self, command, args=None, env=None, name="mcp-server"):
        self.command = command
        self.args = list(args or [])
        self.env = env
        self.name = name
        self.process = None
        self.next_id = 1
        self.lock = Lock()

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.env,
        )
        atexit.register(self.close)
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pico", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})

    def close(self):
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except Exception:
            pass

    def notify(self, method, params=None):
        self.start()
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        self._write(message)

    def request(self, method, params=None):
        self.start() if method != "initialize" else None
        with self.lock:
            request_id = self.next_id
            self.next_id += 1
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            while True:
                response = self._read()
                if response.get("id") != request_id:
                    continue
                if "error" in response:
                    error = response["error"]
                    raise RuntimeError(f"MCP {self.name} error: {error.get('message', error)}")
                return response.get("result", {})

    def _write(self, message):
        if self.process is None or self.process.stdin is None:
            raise RuntimeError(f"MCP {self.name} is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def _read(self):
        if self.process is None or self.process.stdout is None:
            raise RuntimeError(f"MCP {self.name} is not running")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f"MCP {self.name} stopped unexpectedly")
        return json.loads(line)

    def list_tools(self):
        return self.request("tools/list").get("tools", [])

    def call_tool(self, name, arguments):
        result = self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )
        content = result.get("content", [])
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text", "")))
        return "\n".join(text for text in texts if text).strip()


class GitHubMCPClient(StdioMCPClient):
    def __init__(self):
        super().__init__(
            command=sys.executable,
            args=["-m", "pico.github_mcp_server"],
            name="github",
        )
