"""离线实验使用的真实标准库后端与 HTTP 集成测试。"""

APP = r'''"""一个可直接运行的 Todo JSON API；仅依赖 Python 标准库。"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit


class TodoHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            return self.reply(200, {"status": "ok"})
        if path == "/todos":
            with self.server.lock:
                items = [dict(item) for item in self.server.todos.values()]
            return self.reply(200, {"items": items})
        if path.startswith("/todos/"):
            try:
                identity = int(path.removeprefix("/todos/"))
            except ValueError:
                return self.reply(404, {"error": "not_found"})
            with self.server.lock:
                item = self.server.todos.get(identity)
                item = dict(item) if item else None
            return self.reply(200, item) if item else self.reply(404, {"error": "not_found"})
        return self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if urlsplit(self.path).path != "/todos":
            return self.reply(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                self.close_connection = True
                return self.reply(400, {"error": "invalid_body"})
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return self.reply(400, {"error": "invalid_body"})
        except (ValueError, UnicodeError):
            return self.reply(400, {"error": "invalid_body"})
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            return self.reply(400, {"error": "invalid_title"})
        with self.server.lock:
            identity = self.server.next_id
            self.server.next_id += 1
            item = {"id": identity, "title": title.strip(), "completed": False}
            self.server.todos[identity] = item
        return self.reply(201, item)

    def do_PATCH(self):
        path = urlsplit(self.path).path
        try:
            identity = int(path.removeprefix("/todos/")) if path.startswith("/todos/") else -1
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                self.close_connection = True
                return self.reply(400, {"error": "invalid_body"})
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or type(payload.get("completed")) is not bool:
                return self.reply(400, {"error": "invalid_completed"})
        except (ValueError, UnicodeError):
            return self.reply(400, {"error": "invalid_body"})
        with self.server.lock:
            item = self.server.todos.get(identity)
            if item is not None:
                item["completed"] = payload["completed"]
                item = dict(item)
        return self.reply(200, item) if item else self.reply(404, {"error": "not_found"})

    def do_DELETE(self):
        path = urlsplit(self.path).path
        try:
            identity = int(path.removeprefix("/todos/")) if path.startswith("/todos/") else -1
        except ValueError:
            return self.reply(404, {"error": "not_found"})
        with self.server.lock:
            item = self.server.todos.pop(identity, None)
        return self.reply(200, {"deleted": identity}) if item else self.reply(404, {"error": "not_found"})


def serve(host="127.0.0.1", port=8080):
    server = ThreadingHTTPServer((host, port), TodoHandler)
    server.todos = {}
    server.next_id = 1
    server.lock = Lock()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Todo HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = serve(args.host, args.port)
    print(json.dumps({"host": args.host, "port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
'''

BUGGY_APP = APP.replace('return self.reply(201, item)', 'return self.reply(200, item)')

TESTS = r'''"""真实 HTTP 请求验证状态码、CRUD 与输入边界。"""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class TodoAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.process = subprocess.Popen(
            [sys.executable, "-u", str(root / "app.py"), "--port", "0"],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            startup = json.loads(cls.process.stdout.readline())
            cls.url = "http://127.0.0.1:" + str(startup["port"])
        except Exception:
            cls.process.terminate()
            cls.process.wait(timeout=5)
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.process.stdout.close()
        cls.process.stderr.close()

    def request(self, method, path, payload=None, raw=None):
        data = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        request = Request(self.url + path, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read().decode())

    def test_health(self):
        self.assertEqual(self.request("GET", "/health"), (200, {"status": "ok"}))

    def test_create_read_update_delete(self):
        status, item = self.request("POST", "/todos", {"title": "  完成实验  "})
        self.assertEqual(status, 201)
        self.assertEqual(item["title"], "完成实验")
        self.assertFalse(item["completed"])
        identity = item["id"]
        status, detail = self.request("GET", f"/todos/{identity}")
        self.assertEqual(status, 200)
        self.assertEqual(detail, item)
        status, listing = self.request("GET", "/todos")
        self.assertEqual(status, 200)
        self.assertIn(item, listing["items"])
        status, updated = self.request("PATCH", f"/todos/{identity}", {"completed": True})
        self.assertEqual(status, 200)
        self.assertTrue(updated["completed"])
        self.assertEqual(self.request("DELETE", f"/todos/{identity}"),
                         (200, {"deleted": identity}))
        self.assertEqual(self.request("GET", f"/todos/{identity}")[0], 404)
        self.assertEqual(self.request("DELETE", f"/todos/{identity}")[0], 404)

    def test_validation(self):
        for payload in ({}, {"title": ""}, {"title": " "}, {"title": 123},
                        {"title": "x" * 201}, []):
            with self.subTest(payload=payload):
                self.assertEqual(self.request("POST", "/todos", payload)[0], 400)
        self.assertEqual(self.request("POST", "/todos", raw=b"{invalid")[0], 400)
        self.assertEqual(self.request("PATCH", "/todos/1", {"completed": "yes"})[0], 400)

    def test_unknown_routes(self):
        self.assertEqual(self.request("GET", "/unknown")[0], 404)
        self.assertEqual(self.request("GET", "/todos/invalid")[0], 404)
        self.assertEqual(self.request("POST", "/unknown", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
'''

README = '''# Todo API 实验项目

这是由 LanCher Code Agent 工具写入的 Python 标准库后端，无第三方依赖。

## 启动

python app.py --host 127.0.0.1 --port 8080

## API

- GET /health：服务状态。
- GET /todos：列出任务。
- POST /todos：创建任务，JSON 字段 title 为非空文本，最多 200 字符。
- GET /todos/{id}：读取任务。
- PATCH /todos/{id}：更新 completed 布尔值。
- DELETE /todos/{id}：删除任务。

创建成功返回 201；错误输入返回 400；不存在的资源返回 404。
状态暂存在内存中，重启后清空。

## 测试

python -m unittest discover -s tests -v

Agent Lab 的“运行测试”工具会复制可见项目文件到只读临时快照，并在禁止联网的 Docker 容器内执行此命令。测试临时文件只能写入容量受限的 /tmp。
'''

SAMPLE_FILES = {"app.py": APP, "tests/test_api.py": TESTS, "README.md": README}
