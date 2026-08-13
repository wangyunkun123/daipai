import EventSource from 'react-native-sse';
import RNFS from 'react-native-fs';
import { config } from './config';
import { parseSseChunks } from './sse';
import type { AnalyzeEvent, Plan } from './types';

/**
 * 读取 VisionCamera 拍下的临时照片文件，转 base64。
 * iOS path 形如 file:///var/.../IMG.JPG；去掉 file:// 前缀给 RNFS。
 */
export async function readPhotoAsBase64(filePath: string): Promise<string> {
  const clean = filePath.replace('file://', '');
  return RNFS.readFile(clean, 'base64');
}

export interface AnalyzeParams {
  photoBase64: string;
  device?: string;
  lens?: string;
}

const ANALYZE_TIMEOUT_MS = 180000; // 2 分钟总超时，防止 Promise 永不 settle

/**
 * 发起分析，通过 onEvent 回调流式交付 SSE 事件。
 * complete 事件后 resolve sessionId。
 * 出错时 reject（含 SSE error 事件、超时和网络错误）。
 */
export function analyzeStream(
  params: AnalyzeParams,
  onEvent: (e: AnalyzeEvent) => void,
): Promise<{ sessionId: string }> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${config.baseURL}/app/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        photo: params.photoBase64,
        device: params.device ?? undefined,
        lens: params.lens ?? undefined,
        app_token: config.appToken,
      }),
      // react-native-sse：无活动超时（毫秒）。后端 30-90s 无响应属正常，
      // 3 分钟兜底；不要用 timeoutBeforeConnection（那是"连接前空等"）。
      timeout: 180000,
    });

    let settled = false;
    let lastChunk = '';

    // 总超时兜底：后端长时间无 complete（模型慢/掉线）时强制结束
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      es.close();
      reject(new Error('分析超时，请稍后重试'));
    }, ANALYZE_TIMEOUT_MS);

    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      es.close();
      fn();
    };

    // react-native-sse 按事件名分发；每个事件名都可能是流式 chunk，
    // 统一合成 SSE 帧走增量解析器，保证与真机字节流行为一致。
    const handleRaw = (eventName: string, rawData: string) => {
      if (settled) return;
      const synthetic = `event: ${eventName}\ndata: ${rawData}\n\n`;
      const { events, remainder } = parseSseChunks(lastChunk, synthetic);
      lastChunk = remainder;
      for (const e of events) {
        onEvent(e);
        if (e.event === 'complete') {
          settle(() => resolve({ sessionId: e.data.session_id }));
        } else if (e.event === 'error') {
          settle(() => reject(new Error(e.data.message)));
        }
      }
    };

    const EVENT_NAMES = [
      'progress',
      'exif_ready',
      'vision_ready',
      'directions_ready',
      'complete',
      'cancelled',
      'error',
    ] as const;
    for (const name of EVENT_NAMES) {
      // react-native-sse 的类型签名只认固定 EventType，实际支持任意事件名，
      // 这里用 any 断言绕过类型限制。
      (es.addEventListener as any)(name, (e: any) => handleRaw(name, e?.data ?? ''));
    }
    // 未命名事件（message）同样接收
    (es.addEventListener as any)('message', (e: any) => handleRaw('message', e?.data ?? ''));

    es.addEventListener('error', (e: any) => {
      if (settled) return;
      settle(() => reject(new Error(e?.message ?? '网络连接失败，请检查网络后重试')));
    });
  });
}

/**
 * 拉取某个方向的方案列表。v0.1 复用现有 IP 配额，不传 app token。
 * 后端返回 { success, plans, direction_id, device }。
 */
export async function fetchPlans(params: {
  sessionId: string;
  directionId: string;
  device?: string;
  lens?: string;
}): Promise<Plan[]> {
  const res = await fetch(`${config.baseURL}/analyze/plans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: params.sessionId,
      direction_id: params.directionId,
      device: params.device ?? undefined,
      lens: params.lens ?? undefined,
    }),
  });
  if (!res.ok) {
    throw new Error(`方案拉取失败 (${res.status})`);
  }
  const json = await res.json();
  // 后端返回 { success, plans: [...] }；兼容直接数组
  return Array.isArray(json) ? json : (json.plans ?? []);
}
