from copy import deepcopy
from datetime import datetime

from webui.message_presentation import completion_times, present_messages
from test_integration import action, chat, complete, detail, project, submit
from provider_helpers import Reply


def test_completion_times_keep_first_terminal_transition_without_mutating_events():
    events = [
        {'type': 'message.updated', 'timestamp': '2026-10-13T00:01:00Z', 'data': {'id': 'a', 'fields': {'status': 'streaming'}}},
        {'type': 'message.updated', 'timestamp': '2026-10-13T00:02:00Z', 'data': {'id': 'a', 'fields': {'status': 'complete'}}},
        {'type': 'message.updated', 'timestamp': '2026-10-13T00:03:00Z', 'data': {'id': 'a', 'fields': {'status': 'complete'}}},
        {'type': 'message.updated', 'timestamp': '2026-10-13T00:04:00Z', 'data': {'id': 'b', 'fields': {'status': 'cancelled'}}},
    ]
    before = deepcopy(events)
    assert completion_times(events) == {'a': '2026-10-13T00:02:00Z', 'b': '2026-10-13T00:04:00Z'}
    assert events == before


def test_presentation_adds_timing_only_to_response_copy():
    state = {'messages': [{'id': 'a', 'content': '回答'}, {'id': 'b', 'content': '旧记录'}]}
    result = present_messages(state, {'a': '2026-10-13T00:02:00Z'})
    assert result['messages'][0]['completed_at'] == '2026-10-13T00:02:00Z'
    assert result['messages'][1]['completed_at'] is None
    assert 'completed_at' not in state['messages'][0]


def test_real_sdk_completion_time_survives_owner_release_and_resume(client, isolated, provider):
    _, _, workspace = isolated
    (workspace / 'example.txt').write_text('验收内容', encoding='utf-8')
    provider.plans['折叠验收'] = [
        Reply(text='先检查文件。', tools=[('read_file', {'path': 'example.txt'})]),
        Reply(text='最终回答。'),
    ]
    identity = chat(client, project(client, workspace))
    submit(client, identity, '折叠验收')
    state = complete(client, identity)
    message = next(item for item in state['messages'] if item['role'] == 'assistant')
    assert message['status'] == 'complete'
    assert datetime.fromisoformat(message['completed_at']) >= datetime.fromisoformat(message['timestamp'])
    assert [entry['text'] for entry in message['trace']['entries'] if entry['kind'] == 'text'] == ['先检查文件。', '最终回答。']
    action(client, identity, 'release')
    restored = detail(client, identity)['messages'][-1]
    assert restored['completed_at']
    assert restored['completed_at'] == message['completed_at']
    assert restored['trace'] == message['trace']
    action(client, identity, 'model', model_ref='test/two')
    resumed = detail(client, identity)['messages'][-1]
    assert resumed['completed_at'] == restored['completed_at']
