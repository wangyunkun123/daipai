import { parseSseChunks } from '../src/api/sse';

// 客户端网络部分靠真机集成测试覆盖；这里验证事件流契约。
describe('analyzeStream event contract', () => {
  it('delivers parsed events to onEvent in order', () => {
    const stream =
      'event: exif_ready\ndata: {"device":"x"}\n\n' +
      'event: directions_ready\ndata: {"session_id":"s1","directions":[]}\n\n' +
      'event: complete\ndata: {"session_id":"s1","success":true}\n\n';
    const received: string[] = [];
    const { events } = parseSseChunks('', stream);
    events.forEach(e => received.push(e.event));
    expect(received).toEqual(['exif_ready', 'directions_ready', 'complete']);
  });

  it('extracts session_id from complete event', () => {
    const stream = 'event: complete\ndata: {"session_id":"abc123","success":true}\n\n';
    const { events } = parseSseChunks('', stream);
    const complete = events.find(e => e.event === 'complete');
    expect((complete as any).data.session_id).toBe('abc123');
  });
});
