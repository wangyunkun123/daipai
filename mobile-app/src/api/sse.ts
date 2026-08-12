import type { AnalyzeEvent } from './types';

/**
 * 增量 SSE 解析器。网络块可能在任意位置断开，
 * 所以保留 remainder 缓冲，跨 chunk 拼接。
 *
 * SSE 协议：事件以空行 \n\n 分隔；事件内行格式为
 * "field: value"。我们只关心 event 和 data。
 */
export function parseSseChunks(
  prevRemainder: string,
  chunk: string,
): { events: AnalyzeEvent[]; remainder: string } {
  const events: AnalyzeEvent[] = [];
  const buffer = prevRemainder + chunk;

  // 以空行分帧。最后一帧可能不完整，留到 remainder。
  const parts = buffer.split('\n\n');
  const remainder = parts.pop() ?? '';

  for (const rawFrame of parts) {
    let eventName = 'message';
    let dataStr = '';
    for (const line of rawFrame.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataStr += line.slice(5).trim();
      }
    }
    if (!dataStr) continue;

    let data: unknown;
    try {
      data = JSON.parse(dataStr);
    } catch {
      events.push({
        event: 'error',
        data: { message: `SSE JSON 解析失败: ${dataStr.slice(0, 80)}` },
      });
      continue;
    }

    switch (eventName) {
      case 'progress':
        events.push({
          event: 'progress',
          phase: (data as any)?.phase ?? '',
          text: (data as any)?.text ?? '',
        });
        break;
      case 'exif_ready':
        events.push({ event: 'exif_ready', data: data as any });
        break;
      case 'vision_ready':
        events.push({ event: 'vision_ready', data: data as any });
        break;
      case 'directions_ready':
        events.push({ event: 'directions_ready', data: data as any });
        break;
      case 'complete':
        events.push({ event: 'complete', data: data as any });
        break;
      case 'cancelled':
        events.push({ event: 'cancelled', data: data as any });
        break;
      case 'error':
        events.push({
          event: 'error',
          data: { message: (data as any)?.message ?? '未知错误' },
        });
        break;
      default:
        // 忽略未知事件（如 ping），不报错
        break;
    }
  }

  return { events, remainder };
}
