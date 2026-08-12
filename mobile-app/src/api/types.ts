// 与后端 server.py 的 SSE data 字段对齐。只列 v0.1 UI 用到的字段，
// 其余字段用 [key: string]: unknown 兜底，避免 TS 报错又不丢信息。

export type DirectionSlot = 'best' | 'now' | 'creative';

export interface PlanAnnotation {
  type: 'subject' | 'shooter';
  x: number; // 0-1 归一化（若模型输出像素坐标，SketchAnnotation 做容错）
  y: number;
  label?: string;
}

export interface Plan {
  name: string;
  prep?: string;
  subject: string;
  shooter: string;
  gear: string;
  enhance: string;
  result: string;
  why?: string;
  shot_size?: string;
  angle?: string;
  quick_edit?: { app?: string; goal?: string; steps?: string[] };
  img_gen_prompt?: string;
  annotations?: PlanAnnotation[];
  perspective?: string;
  [key: string]: unknown;
}

export interface Direction {
  id: DirectionSlot; // 后端字段是 id（best/now/creative），不是 slot
  style: string;
  kb_status?: string;
  style_promise: string;
  reason?: string;
  fit_rationale?: string;
  light_annotation?: string;
  device_annotation?: string;
  style_brief?: { essence?: string; color?: string; composition?: string; light?: string; mood?: string };
  photo_guide?: string;
  plans?: Plan[];
  [key: string]: unknown;
}

export interface ExifReadyData {
  exif?: { dimensions?: string; flash?: string; [k: string]: unknown };
  device_key?: string;
  device_name?: string;
  is_camera?: boolean;
  lens_options?: unknown;
  location_weather?: unknown;
  [key: string]: unknown;
}

export interface VisionReadyData {
  scene_type?: string;
  primary_subject?: string;
  people?: string;
  light?: { direction?: string; quality?: string; color_temp?: string; special?: string; level?: string; [k: string]: unknown };
  color?: { primary?: string; secondary?: string; accent?: string; [k: string]: unknown };
  space?: { foreground?: string; midground?: string; background?: string; depth?: string; anchors?: string; [k: string]: unknown };
  composition?: string;
  [key: string]: unknown;
}

export interface DirectionsReadyData {
  insight?: string;
  scene_tier?: string;
  directions: Direction[];
  fold_details?: unknown;
  source_tags?: unknown;
  session_id: string;
  [key: string]: unknown;
}

export interface CompleteData {
  success: boolean;
  elapsed?: number;
  tokens?: number;
  session_id: string;
  [key: string]: unknown;
}

export type AnalyzeEvent =
  | { event: 'progress'; phase: string; text: string }
  | { event: 'exif_ready'; data: ExifReadyData }
  | { event: 'vision_ready'; data: VisionReadyData }
  | { event: 'directions_ready'; data: DirectionsReadyData }
  | { event: 'complete'; data: CompleteData }
  | { event: 'cancelled'; data: { message?: string } }
  | { event: 'error'; data: { message: string } };
