"""无需外部脚本的本地接口文档。"""
from html import escape


def render_api_docs(schema):
    rows = []
    for path, operations in schema.get('paths', {}).items():
        for method, operation in operations.items():
            if method.lower() not in {'get', 'post', 'put', 'patch', 'delete'}:
                continue
            rows.append('<tr><td><b>' + escape(method.upper()) + '</b></td><td><code>' + escape(path) +
                        '</code></td><td>' + escape(operation.get('summary', '')) + '</td></tr>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LanCher Agent Lab · API</title><style>body{margin:0;padding:48px;background:#111416;color:#e6eceb;font:16px/1.7 system-ui,sans-serif}main{max-width:1100px;margin:auto}a{color:#84ddc0}h1{font-size:28px}p{color:#a2b2ae}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;border-bottom:1px solid #2c3432;padding:14px 12px}code{color:#b7ded0}b{color:#a3e8ca}</style>
<main><a href="/">← 返回工作台</a><h1>Agent Lab API</h1><p>本机接口。发送任务、审批和停止通过 HTTP；事件通过 SSE 增量接收。模型密钥不会返回给客户端。</p>
<p><a href="/openapi.json">查看完整 OpenAPI JSON（包含请求字段与返回结构）</a></p>
<table><thead><tr><th>方法</th><th>路径</th><th>操作</th></tr></thead><tbody>''' + ''.join(rows) + '</tbody></table></main></html>'
