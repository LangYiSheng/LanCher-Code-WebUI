"""从持久事件补充展示时间，不改写 SDK 消息或轨迹。"""


def completion_times(events):
    result = {}
    for event in events:
        if event.get('type') != 'message.updated':
            continue
        data = event.get('data', {})
        status = data.get('fields', {}).get('status')
        if status in {'complete', 'error', 'cancelled'} and event.get('timestamp'):
            result.setdefault(data['id'], event['timestamp'])
    return result


def present_messages(state, times):
    return {**state, 'messages': [
        {**message, 'completed_at': times.get(message['id'])}
        for message in state.get('messages', [])
    ]}
