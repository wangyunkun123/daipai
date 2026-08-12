import { open } from 'react-native-quick-sqlite';

// 本地数据库连接（单例）。quick-sqlite 同步 API，无需 await。
const db = open({ name: 'daipai.db' });

export function initDb(): void {
  db.execute(`
    CREATE TABLE IF NOT EXISTS sessions (
      session_id TEXT PRIMARY KEY,
      photo_path TEXT,
      device TEXT,
      exif_json TEXT,
      vision_json TEXT,
      directions_json TEXT,
      created_at INTEGER NOT NULL
    );
  `);
}

export interface SessionRow {
  session_id: string;
  photo_path: string | null;
  device: string | null;
  exif_json: string | null;
  vision_json: string | null;
  directions_json: string | null;
  created_at: number;
}

export async function saveSession(s: SessionRow): Promise<void> {
  db.execute(
    `INSERT OR REPLACE INTO sessions
     (session_id, photo_path, device, exif_json, vision_json, directions_json, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      s.session_id,
      s.photo_path,
      s.device,
      s.exif_json,
      s.vision_json,
      s.directions_json,
      s.created_at,
    ],
  );
}

export async function getSession(sessionId: string): Promise<SessionRow | null> {
  const res = db.execute('SELECT * FROM sessions WHERE session_id = ?', [sessionId]);
  return (res.rows?._array?.[0] as SessionRow | undefined) ?? null;
}

export async function getRecentSessions(limit = 20): Promise<SessionRow[]> {
  const res = db.execute(
    'SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?',
    [limit],
  );
  return (res.rows?._array as SessionRow[]) ?? [];
}
