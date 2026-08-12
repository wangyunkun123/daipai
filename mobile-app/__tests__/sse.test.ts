import { parseSseChunks } from '../src/api/sse';

describe('parseSseChunks', () => {
  it('parses a single complete event', () => {
    const raw = 'event: exif_ready\ndata: {"device":"iPhone 15 Pro"}\n\n';
    const { events, remainder } = parseSseChunks('', raw);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('exif_ready');
    expect(remainder).toBe('');
  });

  it('buffers a partial chunk across calls', () => {
    const first = parseSseChunks('', 'event: progress\ndata: {"phase":"exif"');
    expect(first.events).toHaveLength(0);
    expect(first.remainder).toContain('phase');

    const second = parseSseChunks(first.remainder, ',"text":"读取中"}\n\n');
    expect(second.events).toHaveLength(1);
    expect(second.events[0].event).toBe('progress');
    expect((second.events[0] as any).text).toBe('读取中');
  });

  it('parses multiple events in one chunk', () => {
    const raw =
      'event: exif_ready\ndata: {}\n\n' +
      'event: vision_ready\ndata: {}\n\n';
    const { events } = parseSseChunks('', raw);
    expect(events.map(e => e.event)).toEqual(['exif_ready', 'vision_ready']);
  });

  it('emits error event for malformed JSON without throwing', () => {
    const raw = 'event: exif_ready\ndata: {not json}\n\n';
    const { events } = parseSseChunks('', raw);
    expect(events[0].event).toBe('error');
  });

  it('handles real backend progress payload with text field', () => {
    const raw = 'event: progress\ndata: {"phase":"directions","text":"正在生成风格方向..."}\n\n';
    const { events } = parseSseChunks('', raw);
    expect(events[0].event).toBe('progress');
    expect((events[0] as any).phase).toBe('directions');
    expect((events[0] as any).text).toContain('风格方向');
  });
});
