"""在线模型端到端验收，不使用演示 Provider。"""
import json
import sys
import time
from pathlib import Path

import httpx

BASE = 'http://127.0.0.1:8765'
ROOT = Path(__file__).resolve().parent.parent
PROMPT = '''请直接调用工具逐个实现文件，不要长篇推理或先规划所有代码，每个响应最多一个文件。请从零编写一个只使用 Python 标准库的记账 HTTP 后端，保存为 app.py，并编写 tests/test_api.py 和 README.md。
接口要求：GET /health 返回状态；GET /entries 返回记账条目数组；POST /entries 接收 {title,amount}，title 非空、amount 为大于零的数字且不接受 bool，成功返回 201；GET /summary 返回总金额；DELETE /entries/<id> 删除条目；无效数据返回 400，未知路径和不存在 id 返回 404。存储可放内存。
测试用 unittest，通过真实 HTTP 请求启动临时端口服务器，至少 6 项测试覆盖成功、输入校验、汇总和删除。测试不能只比较模板字符串。只用实验工具读写相对路径，不需要 Shell 和安装依赖。已有文件先完整读取。
完成后必须调用 run_tests 在 Docker 执行测试，失败要修复再测试。审批会由验收宿主处理。最终只报告实际测试结果，不推测通过。请直接实现，不停在方案。'''


def main():
    with httpx.Client(base_url=BASE, timeout=30) as client:
        status = client.get('/api/status').json()
        if not status['live_available'] or not status['docker_available']:
            raise RuntimeError('在线模型或 Docker 未就绪')
        session = client.post('/api/sessions', json={'title':'在线验收 · 记账后端','mode':'live','model':(sys.argv[1] if len(sys.argv)>1 else status['default_live_model'])})
        session.raise_for_status()
        identity = session.json()['id']
        print('LIVE_SESSION', identity, flush=True)
        submitted = client.post(f'/api/sessions/{identity}/turns', json={'prompt':PROMPT})
        submitted.raise_for_status()
        deadline = time.monotonic() + 420
        seen = set()
        last_state = None
        while time.monotonic() < deadline:
            detail = client.get(f'/api/sessions/{identity}').json()
            if detail['status'] != last_state:
                print('STATE', detail['status'], flush=True)
                last_state = detail['status']
            for event in detail['events']:
                if event['sequence'] in seen:
                    continue
                seen.add(event['sequence'])
                if event['kind'] == 'tool_call_started':
                    call = event.get('tool_call') or {}
                    print('TOOL', call.get('tool_name'), str(call.get('arguments',{}).get('path','')), flush=True)
                if event['kind'] == 'tool_result_received':
                    result = event.get('tool_result') or {}
                    if result.get('tool_name') == 'run_tests':
                        print('TEST_RESULT', result.get('is_error'), result.get('content','')[:2500], flush=True)
            for request in detail['pending_permissions']:
                outcome = 'allow' if request['tool_name'] == 'run_tests' else 'deny'
                response = client.post(f"/api/sessions/{identity}/permissions/{request['request_id']}", json={'outcome':outcome})
                response.raise_for_status()
            if detail['status'] in {'completed','failed','cancelled'}:
                break
            time.sleep(0.7)
        else:
            client.post(f'/api/sessions/{identity}/stop').raise_for_status()
            raise RuntimeError('在线验收超时，任务已停止')
        tests = []
        for event in detail['events']:
            result = event.get('tool_result') or {}
            if event['kind'] == 'tool_result_received' and result.get('tool_name') == 'run_tests':
                try:
                    tests.append(json.loads(result['content']))
                except ValueError:
                    pass
        passed = bool(detail['status']=='completed' and tests and tests[-1].get('ok'))
        evidence = {'passed':passed,'session_id':identity,'mode':'live','model':detail['model'],
                    'sdk_commit':status['sdk_commit'],'status':detail['status'],'files':detail['files'],
                    'tests':tests,'result':detail.get('result'),'events_count':len(detail['events'])}
        (ROOT/'data'/'live-acceptance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print('LIVE_PASSED',passed,'FILES',len(detail['files']),'EVENTS',len(detail['events']),flush=True)
        print('FINAL', (detail.get('result') or {}).get('text','')[:1800], flush=True)
        return 0 if passed else 1


if __name__=='__main__':
    sys.exit(main())

