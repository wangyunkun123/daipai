"""
带拍 · 数据库模块 v1.0
SQLite 替代 style_cache.json——支持结构化存储、语义去重、双向同步。

表结构：
- styles: 风格发现记录（场景→风格匹配）
- techniques: 技法发现记录（场景→技法匹配）
- scene_matches: 场景分析记录（聚合统计）
- knowledge_sync: Claude端↔服务器端同步记录
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "daipai.db")

# ============================================================
# 数据库初始化
# ============================================================

def get_db():
    """获取数据库连接（自动创建表）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_tables(conn)
    return conn


def _init_tables(conn):
    """创建表（如果不存在）"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS styles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        one_liner TEXT,
        source_type TEXT DEFAULT 'inference',
        fit_rationale TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        verify_count INTEGER DEFAULT 1,
        UNIQUE(name)
    );

    CREATE TABLE IF NOT EXISTS techniques (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        source_type TEXT DEFAULT 'tutorial',
        description TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        verify_count INTEGER DEFAULT 1,
        UNIQUE(name)
    );

    CREATE TABLE IF NOT EXISTS scene_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scene_type TEXT NOT NULL,
        style_id INTEGER REFERENCES styles(id),
        technique_id INTEGER REFERENCES techniques(id),
        match_type TEXT NOT NULL CHECK(match_type IN ('style', 'technique')),
        created_at TEXT DEFAULT (datetime('now')),
        use_count INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS knowledge_sync (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL CHECK(source IN ('claude', 'server')),
        entity_type TEXT NOT NULL CHECK(entity_type IN ('style', 'technique', 'technique_router', 'style_router')),
        entity_name TEXT NOT NULL,
        entity_data TEXT,
        synced_at TEXT DEFAULT (datetime('now')),
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'applied', 'rejected')),
        UNIQUE(source, entity_type, entity_name)
    );

    CREATE INDEX IF NOT EXISTS idx_scene_matches_scene ON scene_matches(scene_type);
    CREATE INDEX IF NOT EXISTS idx_scene_matches_style ON scene_matches(style_id);
    CREATE INDEX IF NOT EXISTS idx_knowledge_sync_status ON knowledge_sync(status);

    -- v3.5: 使用统计与反馈
    CREATE TABLE IF NOT EXISTS daily_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_address TEXT NOT NULL,
        usage_date TEXT NOT NULL DEFAULT (date('now')),
        count INTEGER DEFAULT 1,
        extra_quota INTEGER DEFAULT 0,
        UNIQUE(ip_address, usage_date)
    );

    CREATE TABLE IF NOT EXISTS quota_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_address TEXT NOT NULL,
        request_date TEXT NOT NULL DEFAULT (date('now')),
        created_at TEXT DEFAULT (datetime('now')),
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        granted_amount INTEGER DEFAULT 5,
        resolved_at TEXT
    );

    CREATE TABLE IF NOT EXISTS usage_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL UNIQUE,
        timestamp TEXT DEFAULT (datetime('now')),
        ip_address TEXT,
        device_key TEXT,
        device_name TEXT,
        scene_type TEXT,
        scene_tier TEXT,
        direction_count INTEGER DEFAULT 0,
        selected_direction_id TEXT,
        selected_direction_label TEXT,
        selected_style TEXT,
        plan_count INTEGER DEFAULT 0,
        duration_seconds REAL DEFAULT 0,
        completed INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS plan_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        direction_id TEXT NOT NULL,
        plan_index INTEGER NOT NULL,
        rating TEXT NOT NULL CHECK(rating IN ('like', 'dislike')),
        reason TEXT DEFAULT '',
        reason_text TEXT DEFAULT '',
        scene_type TEXT,
        style TEXT,
        device_key TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(session_id, direction_id, plan_index)
    );

    CREATE INDEX IF NOT EXISTS idx_daily_usage_ip ON daily_usage(ip_address, usage_date);
    CREATE INDEX IF NOT EXISTS idx_quota_requests_status ON quota_requests(status);
    CREATE INDEX IF NOT EXISTS idx_usage_sessions_time ON usage_sessions(timestamp);
    CREATE INDEX IF NOT EXISTS idx_plan_feedback_created ON plan_feedback(created_at);
    """)
    conn.commit()


# ============================================================
# 风格积累（替代 style_cache.json 的 accumulate_styles）
# ============================================================

def accumulate(scene_type, discovered_styles, techniques_used):
    """
    积累发现的风格和技法到数据库。
    自动去重：同名风格追加 verify_count。
    """
    if not scene_type:
        return

    conn = get_db()
    try:
        for s in (discovered_styles or []):
            name = s.get('name', '').strip()
            if not name:
                continue
            source_type = s.get('source_type', 'inference')
            fit_rationale = s.get('fit_rationale', '')[:500]

            # upsert style
            conn.execute("""
                INSERT INTO styles (name, source_type, fit_rationale, verify_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(name) DO UPDATE SET
                    verify_count = verify_count + 1,
                    source_type = CASE WHEN excluded.source_type != 'inference' THEN excluded.source_type ELSE source_type END,
                    updated_at = datetime('now')
            """, (name, source_type, fit_rationale))

            # link to scene
            style_id = conn.execute("SELECT id FROM styles WHERE name=?", (name,)).fetchone()[0]
            conn.execute("""
                INSERT INTO scene_matches (scene_type, style_id, match_type)
                VALUES (?, ?, 'style')
            """, (scene_type, style_id))

        for t in (techniques_used or []):
            name = t.get('name', '').strip()
            if not name:
                continue
            source_type = t.get('source_type', 'tutorial')
            description = t.get('description', '')[:500]

            conn.execute("""
                INSERT INTO techniques (name, source_type, description, verify_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(name) DO UPDATE SET
                    verify_count = verify_count + 1,
                    updated_at = datetime('now')
            """, (name, source_type, description))

            tech_id = conn.execute("SELECT id FROM techniques WHERE name=?", (name,)).fetchone()[0]
            conn.execute("""
                INSERT INTO scene_matches (scene_type, technique_id, match_type)
                VALUES (?, ?, 'technique')
            """, (scene_type, tech_id))

        conn.commit()
        print(f"[DB] Accumulated to '{scene_type[:50]}': {len(discovered_styles or [])} styles, {len(techniques_used or [])} techniques",
              file=sys.stderr, flush=True)
    except Exception as e:
        conn.rollback()
        print(f"[DB] Accumulate error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def query_scene_context(scene_type):
    """
    查询同类型场景的历史积累（替代 style_cache.json 的 get_style_context）。
    模糊匹配场景类型。
    """
    if not scene_type:
        return ""

    conn = get_db()
    try:
        # 模糊匹配：找包含关键词的场景
        keywords = scene_type.replace("[观察]", "").replace("[推测]", "").replace("—", " ").split()
        # 取前3个有意义的词
        search_terms = [k for k in keywords if len(k) >= 2][:3]

        if not search_terms:
            return ""

        # 构建 LIKE 查询
        like_clauses = " OR ".join(["scene_type LIKE ?" for _ in search_terms])
        params = [f"%{t}%" for t in search_terms]

        rows = conn.execute(f"""
            SELECT DISTINCT s.name as style_name, s.source_type, s.verify_count,
                   sm.scene_type, sm.use_count
            FROM scene_matches sm
            JOIN styles s ON sm.style_id = s.id
            WHERE sm.match_type = 'style' AND ({like_clauses})
            ORDER BY s.verify_count DESC
            LIMIT 10
        """, params).fetchall()

        tech_rows = conn.execute(f"""
            SELECT DISTINCT t.name as tech_name, t.source_type, t.verify_count, t.description
            FROM scene_matches sm
            JOIN techniques t ON sm.technique_id = t.id
            WHERE sm.match_type = 'technique' AND ({like_clauses})
            ORDER BY t.verify_count DESC
            LIMIT 10
        """, params).fetchall()

        if not rows and not tech_rows:
            return ""

        total = conn.execute(f"""
            SELECT COUNT(DISTINCT sm.scene_type) FROM scene_matches sm
            WHERE {like_clauses}
        """, params).fetchone()[0]

        ctx = f"\n## 📚 历史积累（相似场景 {total} 次分析）\n"
        if rows:
            ctx += "### 过往匹配的风格\n"
            seen = set()
            for r in rows:
                if r['style_name'] not in seen:
                    seen.add(r['style_name'])
                    ctx += f"- {r['style_name']}（{r['source_type']}, 验证{r['verify_count']}次）\n"
        if tech_rows:
            ctx += "### 过往使用的技法\n"
            seen = set()
            for r in tech_rows:
                if r['tech_name'] not in seen:
                    seen.add(r['tech_name'])
                    ctx += f"- {r['tech_name']}（{r['source_type']}, 验证{r['verify_count']}次）\n"
        ctx += "\n可以参考以上积累，但不强制使用。如果场景特征不匹配，忽略即可。\n"

        return ctx
    except Exception as e:
        print(f"[DB] Query error: {e}", file=sys.stderr, flush=True)
        return ""
    finally:
        conn.close()


# ============================================================
# Claude ↔ 服务器同步
# ============================================================

def export_for_claude():
    """
    导出数据库内容为 JSON，供 Claude 端读取。
    返回 {"styles": [...], "techniques": [...], "exported_at": "..."}
    """
    conn = get_db()
    try:
        styles = [dict(r) for r in conn.execute(
            "SELECT name, one_liner, source_type, fit_rationale, verify_count FROM styles WHERE verify_count >= 2 ORDER BY verify_count DESC"
        ).fetchall()]

        techniques = [dict(r) for r in conn.execute(
            "SELECT name, source_type, description, verify_count FROM techniques WHERE verify_count >= 2 ORDER BY verify_count DESC"
        ).fetchall()]

        return {
            "styles": styles,
            "techniques": techniques,
            "exported_at": datetime.now().isoformat(),
            "total_scenes": conn.execute("SELECT COUNT(DISTINCT scene_type) FROM scene_matches").fetchone()[0],
            "total_matches": conn.execute("SELECT COUNT(*) FROM scene_matches").fetchone()[0],
        }
    finally:
        conn.close()


def import_from_claude(data):
    """
    从 Claude 端导入数据到数据库。
    data 格式与 export_for_claude 输出格式相同。
    """
    if not data:
        return 0

    conn = get_db()
    count = 0
    try:
        for s in data.get('styles', []):
            name = s.get('name', '').strip()
            if not name:
                continue
            conn.execute("""
                INSERT INTO knowledge_sync (source, entity_type, entity_name, entity_data, status)
                VALUES ('claude', 'style', ?, ?, 'pending')
                ON CONFLICT(source, entity_type, entity_name) DO UPDATE SET
                    entity_data = excluded.entity_data,
                    synced_at = datetime('now')
            """, (name, json.dumps(s, ensure_ascii=False)))
            count += 1

        for t in data.get('techniques', []):
            name = t.get('name', '').strip()
            if not name:
                continue
            conn.execute("""
                INSERT INTO knowledge_sync (source, entity_type, entity_name, entity_data, status)
                VALUES ('claude', 'technique', ?, ?, 'pending')
                ON CONFLICT(source, entity_type, entity_name) DO UPDATE SET
                    entity_data = excluded.entity_data,
                    synced_at = datetime('now')
            """, (name, json.dumps(t, ensure_ascii=False)))
            count += 1

        conn.commit()
        print(f"[DB] Imported {count} items from Claude", file=sys.stderr, flush=True)
    except Exception as e:
        conn.rollback()
        print(f"[DB] Import error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()
    return count


def apply_pending_sync():
    """应用来自 Claude 端的待处理同步条目到主表"""
    conn = get_db()
    count = 0
    try:
        pending = conn.execute(
            "SELECT * FROM knowledge_sync WHERE source='claude' AND status='pending'"
        ).fetchall()

        for row in pending:
            data = json.loads(row['entity_data']) if row['entity_data'] else {}
            if row['entity_type'] == 'style':
                conn.execute("""
                    INSERT INTO styles (name, source_type, fit_rationale, verify_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(name) DO UPDATE SET
                        source_type = CASE WHEN excluded.source_type != 'inference' THEN excluded.source_type ELSE styles.source_type END,
                        updated_at = datetime('now')
                """, (row['entity_name'], data.get('source_type', 'inference'), data.get('fit_rationale', '')))
            elif row['entity_type'] == 'technique':
                conn.execute("""
                    INSERT INTO techniques (name, source_type, description, verify_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(name) DO UPDATE SET
                        updated_at = datetime('now')
                """, (row['entity_name'], data.get('source_type', 'tutorial'), data.get('description', '')))

            conn.execute("UPDATE knowledge_sync SET status='applied' WHERE id=?", (row['id'],))
            count += 1

        conn.commit()
        if count:
            print(f"[DB] Applied {count} pending sync items from Claude", file=sys.stderr, flush=True)
    except Exception as e:
        conn.rollback()
        print(f"[DB] Sync apply error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()
    return count


def get_db_stats():
    """获取数据库统计信息"""
    conn = get_db()
    try:
        return {
            "styles": conn.execute("SELECT COUNT(*) FROM styles").fetchone()[0],
            "techniques": conn.execute("SELECT COUNT(*) FROM techniques").fetchone()[0],
            "scenes": conn.execute("SELECT COUNT(DISTINCT scene_type) FROM scene_matches").fetchone()[0],
            "total_matches": conn.execute("SELECT COUNT(*) FROM scene_matches").fetchone()[0],
            "pending_sync": conn.execute("SELECT COUNT(*) FROM knowledge_sync WHERE status='pending'").fetchone()[0],
            "usage_sessions": conn.execute("SELECT COUNT(*) FROM usage_sessions").fetchone()[0],
            "feedback_entries": conn.execute("SELECT COUNT(*) FROM plan_feedback").fetchone()[0],
            "today_analyses": conn.execute("SELECT COALESCE(SUM(count),0) FROM daily_usage WHERE usage_date=date('now')").fetchone()[0],
        }
    finally:
        conn.close()


# ============================================================
# v3.5: 每日使用限制
# ============================================================

def check_and_increment_usage(ip_address, daily_limit=10):
    """
    检查并增加每日使用计数。
    返回 (allowed: bool, used: int, limit: int)
    """
    conn = get_db()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        row = conn.execute(
            "SELECT count, extra_quota FROM daily_usage WHERE ip_address=? AND usage_date=?",
            (ip_address, today)
        ).fetchone()

        if row:
            used = row['count']
            extra = row['extra_quota']
            effective_limit = daily_limit + extra
            if used >= effective_limit:
                return (False, used, effective_limit)
            conn.execute(
                "UPDATE daily_usage SET count = count + 1 WHERE ip_address=? AND usage_date=?",
                (ip_address, today)
            )
        else:
            effective_limit = daily_limit
            conn.execute(
                "INSERT INTO daily_usage (ip_address, usage_date, count) VALUES (?, ?, 1)",
                (ip_address, today)
            )

        conn.commit()
        return (True, (row['count'] if row else 0) + 1, effective_limit)
    except Exception as e:
        conn.rollback()
        print(f"[DB] Usage check error: {e}", file=sys.stderr, flush=True)
        return (True, 0, daily_limit)  # 出错时放行
    finally:
        conn.close()


def get_daily_usage(ip_address):
    """获取某 IP 今天的用量"""
    conn = get_db()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        row = conn.execute(
            "SELECT count, extra_quota FROM daily_usage WHERE ip_address=? AND usage_date=?",
            (ip_address, today)
        ).fetchone()
        if row:
            return {"used": row['count'], "extra": row['extra_quota']}
        return {"used": 0, "extra": 0}
    finally:
        conn.close()


# ============================================================
# v3.5: 配额申请
# ============================================================

def submit_quota_request(ip_address):
    """提交配额申请。返回 (ok, message)"""
    conn = get_db()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        # 检查是否已有待处理的申请
        existing = conn.execute(
            "SELECT id, status FROM quota_requests WHERE ip_address=? AND request_date=? AND status='pending'",
            (ip_address, today)
        ).fetchone()
        if existing:
            return (False, "已有待处理的申请，请耐心等待")

        conn.execute(
            "INSERT INTO quota_requests (ip_address, request_date) VALUES (?, ?)",
            (ip_address, today)
        )
        conn.commit()
        return (True, "申请已提交")
    except Exception as e:
        conn.rollback()
        return (False, str(e))
    finally:
        conn.close()


def get_quota_request_status(ip_address):
    """查询某 IP 今天的申请状态"""
    conn = get_db()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        row = conn.execute(
            "SELECT status FROM quota_requests WHERE ip_address=? AND request_date=? ORDER BY created_at DESC LIMIT 1",
            (ip_address, today)
        ).fetchone()
        if row:
            return row['status']
        return None  # 没申请过
    finally:
        conn.close()


def get_pending_quota_requests():
    """获取所有待审批的申请"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT qr.id, qr.ip_address, qr.created_at, qr.request_date,
                      COALESCE(du.count, 0) as used_count, COALESCE(du.extra_quota, 0) as extra
               FROM quota_requests qr
               LEFT JOIN daily_usage du ON du.ip_address = qr.ip_address AND du.usage_date = qr.request_date
               WHERE qr.status = 'pending'
               ORDER BY qr.created_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def approve_quota_request(request_id, action, amount=5):
    """批准或拒绝配额申请"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM quota_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            conn.close()
            return (False, "申请不存在")

        status = 'approved' if action == 'approve' else 'rejected'
        conn.execute(
            "UPDATE quota_requests SET status=?, resolved_at=datetime('now'), granted_amount=? WHERE id=?",
            (status, amount, request_id)
        )

        if action == 'approve':
            # 增加额外配额
            conn.execute(
                """INSERT INTO daily_usage (ip_address, usage_date, count, extra_quota)
                   VALUES (?, ?, 0, ?)
                   ON CONFLICT(ip_address, usage_date) DO UPDATE SET extra_quota = extra_quota + ?""",
                (row['ip_address'], row['request_date'], amount, amount)
            )

        conn.commit()
        return (True, f"已{status}")
    except Exception as e:
        conn.rollback()
        return (False, str(e))
    finally:
        conn.close()


# ============================================================
# v3.5: 使用会话统计
# ============================================================

def save_usage_session(session_id, ip_address, device_key, device_name,
                        scene_type, scene_tier, direction_count):
    """记录新的分析会话"""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO usage_sessions (session_id, ip_address, device_key, device_name,
                                        scene_type, scene_tier, direction_count, completed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (session_id, ip_address, device_key, device_name,
              (scene_type or '')[:200], scene_tier or '', direction_count or 0))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] Save usage error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def update_usage_session(session_id, direction_id=None, direction_label=None,
                          style=None, plan_count=0, duration_seconds=0, completed=1):
    """更新会话——方案生成后调用"""
    conn = get_db()
    try:
        conn.execute("""
            UPDATE usage_sessions SET
                selected_direction_id = ?,
                selected_direction_label = ?,
                selected_style = ?,
                plan_count = ?,
                duration_seconds = ?,
                completed = ?
            WHERE session_id = ?
        """, (direction_id, direction_label, style, plan_count,
              duration_seconds, completed, session_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] Update usage error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()


# ============================================================
# v3.5: 方案反馈
# ============================================================

DISLIKE_REASONS = {
    'too_slow': '⏱️ 时间太久了',
    'style_not_match': '🎨 风格不喜欢',
    'plan_not_good': '📋 方案不喜欢',
    'guidance_unclear': '🤔 操作引导不清晰',
    'want_image_gen': '🖼️ 需要生图直接示意',
    'other': '💬 其他',
}


def save_feedback(session_id, direction_id, plan_index, rating,
                   reason='', reason_text='', scene_type=None, style=None, device_key=None):
    """保存或更新方案反馈。rating='none' 时删除反馈"""
    conn = get_db()
    try:
        if rating == 'none':
            conn.execute("""
                DELETE FROM plan_feedback
                WHERE session_id = ? AND direction_id = ? AND plan_index = ?
            """, (session_id, direction_id, plan_index))
        else:
            conn.execute("""
                INSERT INTO plan_feedback (session_id, direction_id, plan_index, rating,
                                           reason, reason_text, scene_type, style, device_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, direction_id, plan_index) DO UPDATE SET
                    rating = excluded.rating,
                    reason = excluded.reason,
                    reason_text = excluded.reason_text,
                    updated_at = datetime('now')
            """, (session_id, direction_id, plan_index, rating,
                  reason or '', (reason_text or '')[:500],
                  (scene_type or '')[:200], style or '', device_key or ''))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] Save feedback error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def get_feedback_stats():
    """获取反馈统计数据"""
    conn = get_db()
    try:
        total_likes = conn.execute(
            "SELECT COUNT(*) FROM plan_feedback WHERE rating='like'"
        ).fetchone()[0]
        total_dislikes = conn.execute(
            "SELECT COUNT(*) FROM plan_feedback WHERE rating='dislike'"
        ).fetchone()[0]

        # 踩的原因分布
        reason_rows = conn.execute(
            "SELECT reason, COUNT(*) as cnt FROM plan_feedback WHERE rating='dislike' AND reason!='' GROUP BY reason ORDER BY cnt DESC"
        ).fetchall()
        reasons = [{"reason": r['reason'], "label": DISLIKE_REASONS.get(r['reason'], r['reason']), "count": r['cnt']} for r in reason_rows]

        # 最近 50 条反馈
        recent = conn.execute("""
            SELECT pf.*, us.scene_type as us_scene_type, us.device_name
            FROM plan_feedback pf
            LEFT JOIN usage_sessions us ON pf.session_id = us.session_id
            ORDER BY pf.updated_at DESC LIMIT 50
        """).fetchall()

        # 7 天使用趋势
        trend = conn.execute("""
            SELECT usage_date, SUM(count) as total
            FROM daily_usage
            WHERE usage_date >= date('now', '-7 days')
            GROUP BY usage_date ORDER BY usage_date ASC
        """).fetchall()

        return {
            "total_likes": total_likes,
            "total_dislikes": total_dislikes,
            "reasons": reasons,
            "recent": [dict(r) for r in recent],
            "trend": [dict(r) for r in trend],
        }
    finally:
        conn.close()


def export_feedback_markdown():
    """导出反馈报告为 Markdown"""
    stats = get_feedback_stats()
    total = stats['total_likes'] + stats['total_dislikes']
    like_pct = round(stats['total_likes'] / total * 100) if total > 0 else 0

    md = f"""# 带拍 · 反馈报告
> 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 📊 概览
- 总反馈数：{total} 条
- 👍 满意：{stats['total_likes']} 条（{like_pct}%）
- 👎 不满意：{stats['total_dislikes']} 条（{100 - like_pct}%）

## 👎 不满意原因分布
"""
    if stats['reasons']:
        for i, r in enumerate(stats['reasons'], 1):
            md += f"{i}. {r['label']} — {r['count']}次\n"
    else:
        md += "暂无数据\n"

    md += "\n## 📝 近期反馈\n"
    md += "| 时间 | 场景 | 风格 | 方案 | 评价 | 原因 |\n"
    md += "|------|------|------|------|------|------|\n"
    for f in stats['recent'][:30]:
        time_str = (f.get('updated_at') or '')[:16]
        scene = (f.get('scene_type') or f.get('us_scene_type') or '-')[:15]
        style = (f.get('style') or '-')[:12]
        plan = f"#{f['plan_index'] + 1}"
        rating = '👍' if f['rating'] == 'like' else '👎'
        reason_label = DISLIKE_REASONS.get(f.get('reason', ''), f.get('reason', ''))
        reason_str = reason_label if f['rating'] == 'dislike' else '-'
        if f.get('reason_text'):
            reason_str += f" ({f['reason_text'][:30]})"
        md += f"| {time_str} | {scene} | {style} | {plan} | {rating} | {reason_str} |\n"

    if stats['trend']:
        md += "\n## 📈 7天使用趋势\n"
        md += "| 日期 | 分析次数 |\n"
        md += "|------|----------|\n"
        for t in stats['trend']:
            md += f"| {t['usage_date']} | {t['total']} |\n"

    return md


# ============================================================
# 从旧 JSON 缓存迁移
# ============================================================

def migrate_from_json(json_path=None):
    """从 style_cache.json 迁移数据到 SQLite"""
    if json_path is None:
        json_path = os.path.join(os.path.dirname(__file__), "style_cache.json")

    if not os.path.exists(json_path):
        print(f"[DB] No JSON cache to migrate at {json_path}", file=sys.stderr, flush=True)
        return 0

    try:
        with open(json_path, 'r') as f:
            old_cache = json.load(f)
    except Exception as e:
        print(f"[DB] Failed to read JSON cache: {e}", file=sys.stderr, flush=True)
        return 0

    count = 0
    for scene_type, entry in old_cache.items():
        styles = entry.get('styles', [])
        techniques = entry.get('techniques', [])

        for s in styles:
            name = s.get('name', '').strip()
            if not name:
                continue
            accumulate(scene_type, [s], [])

        for t in techniques:
            name = t.get('name', '').strip()
            if not name:
                continue
            accumulate(scene_type, [], [t])

        count += 1
        print(f"[DB] Migrated scene: {scene_type[:50]}...", file=sys.stderr, flush=True)

    print(f"[DB] Migration complete: {count} scenes from JSON → SQLite", file=sys.stderr, flush=True)
    return count


# ============================================================
# 自检
# ============================================================
if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "init":
        conn = get_db()
        print("✅ 数据库初始化完成")
        print(f"  路径: {DB_PATH}")
        conn.close()

    elif cmd == "migrate":
        n = migrate_from_json()
        print(f"✅ 迁移完成: {n} 个场景")

    elif cmd == "stats":
        stats = get_db_stats()
        print("📊 数据库统计:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    elif cmd == "export":
        data = export_for_claude()
        print(json.dumps(data, ensure_ascii=False, indent=2))

    elif cmd == "apply":
        n = apply_pending_sync()
        print(f"✅ 应用了 {n} 条待同步记录")

    else:
        print(f"用法: python3 {sys.argv[0]} <init|migrate|stats|export|apply>")
