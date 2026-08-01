"""
带拍 · 数据库模块 SQLite 替代 style_cache.json——支持结构化存储、语义去重、双向同步。

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
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "daipai.db")

# ============================================================
# 数据库初始化
# ============================================================

def get_db():
    """获取数据库连接（自动创建表）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL 模式只需设置一次（持久化到数据库），后续连接跳过
    if not hasattr(get_db, '_wal_checked'):
        conn.execute("PRAGMA journal_mode=WAL")
        get_db._wal_checked = True
    conn.execute("PRAGMA foreign_keys=ON")
    _init_tables(conn)
    return conn


def _init_tables(conn):
    """创建表（如果不存在）+ 一次性迁移"""
    # 迁移只跑一次（进程生命周期内），避免每次 get_db() 都重复执行
    if getattr(_init_tables, '_done', False):
        return
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
    CREATE INDEX IF NOT EXISTS idx_scene_matches_category ON scene_matches(scene_category);
    CREATE INDEX IF NOT EXISTS idx_scene_matches_tech ON scene_matches(technique_id);
    CREATE INDEX IF NOT EXISTS idx_techniques_verify ON techniques(verify_count);
    CREATE INDEX IF NOT EXISTS idx_styles_source ON styles(source_type);
    CREATE INDEX IF NOT EXISTS idx_techniques_source ON techniques(source_type);
    CREATE INDEX IF NOT EXISTS idx_knowledge_sync_status ON knowledge_sync(status);

    -- 使用统计与反馈
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

    -- AI API 调用日志
    CREATE TABLE IF NOT EXISTS api_call_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        call_type TEXT NOT NULL CHECK(call_type IN ('vision','directions','plans')),
        model TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        total_tokens INTEGER,
        duration_ms INTEGER,
        success INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- Web 搜索执行日志
    CREATE TABLE IF NOT EXISTS search_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        search_type TEXT NOT NULL CHECK(search_type IN ('style','location')),
        query_text TEXT,
        result_count INTEGER DEFAULT 0,
        result_quality TEXT DEFAULT '🔴',
        source_types TEXT,
        duration_ms INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_api_log_session ON api_call_log(session_id);
    CREATE INDEX IF NOT EXISTS idx_api_log_type ON api_call_log(call_type);
    CREATE INDEX IF NOT EXISTS idx_api_log_time ON api_call_log(created_at);
    CREATE INDEX IF NOT EXISTS idx_search_log_session ON search_log(session_id);
    CREATE INDEX IF NOT EXISTS idx_search_log_type ON search_log(search_type);

    -- AI 自由探索风格名日志
    CREATE TABLE IF NOT EXISTS style_exploration_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        style_name TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('selected','rejected')),
        reason TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_style_exploration_session ON style_exploration_log(session_id);
    CREATE INDEX IF NOT EXISTS idx_style_exploration_decision ON style_exploration_log(decision);
    """)
    conn.commit()

    # 迁移——search_log 加 results_summary 列（已有列则跳过）
    try:
        conn.execute("ALTER TABLE search_log ADD COLUMN results_summary TEXT")
        conn.commit()
        print("[DB] Migration: added results_summary column to search_log", file=sys.stderr, flush=True)
    except Exception:
        pass  # 列已存在

    # 迁移——scene_matches 加 scene_category 列
    try:
        conn.execute("ALTER TABLE scene_matches ADD COLUMN scene_category TEXT DEFAULT ''")
        conn.commit()
        print("[DB] Migration: added scene_category column to scene_matches", file=sys.stderr, flush=True)
    except Exception:
        pass

    # 迁移——search_log 加搜索监控列
    try:
        conn.execute("ALTER TABLE search_log ADD COLUMN keywords_used TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE search_log ADD COLUMN useful_data TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE search_log ADD COLUMN authenticity TEXT DEFAULT 'unknown'")
        conn.commit()
        print("[DB] Migration: added keywords_used/useful_data/authenticity to search_log", file=sys.stderr, flush=True)
    except Exception:
        pass

    # 迁移——search_log 加 discovery_hint 列
    try:
        conn.execute("ALTER TABLE search_log ADD COLUMN discovery_hint TEXT DEFAULT ''")
        conn.commit()
        print("[DB] Migration: added discovery_hint to search_log", file=sys.stderr, flush=True)
    except Exception:
        pass

    # 迁移——补建性能索引（已有则跳过）
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scene_matches_category ON scene_matches(scene_category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scene_matches_tech ON scene_matches(technique_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_techniques_verify ON techniques(verify_count)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_styles_source ON styles(source_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_techniques_source ON techniques(source_type)")
        conn.commit()
        print("[DB] Migration: added performance indexes", file=sys.stderr, flush=True)
    except Exception:
        pass

    # 迁移——style_exploration_log 加 promoted 列
    try:
        conn.execute("ALTER TABLE style_exploration_log ADD COLUMN promoted INTEGER DEFAULT 0")
        conn.commit()
        print("[DB] Migration: added promoted column to style_exploration_log", file=sys.stderr, flush=True)
    except Exception:
        pass

    _init_tables._done = True  # 标记迁移完成，后续 get_db() 调用跳过


# ============================================================
# 场景分类体系（——替代 LIKE 模糊匹配）
# ============================================================

SCENE_CATEGORY_RULES = [
    ("sports_venue", ["球场", "跑道", "泳池", "冰场", "健身房", "体育馆", "网球场", "篮球场", "足球场", "运动场", "球馆", "赛馆"]),
    ("f_and_b", ["咖啡厅", "咖啡馆", "咖啡", "餐厅", "酒吧", "茶馆", "便利店", "食堂", "甜品店", "奶茶", "饭店", "小食"]),
    ("transit_station", ["地铁站", "地铁", "火车站", "机场", "高铁站", "候车室", "公交站", "轻轨", "站台", "车厢"]),
    ("commercial", ["商场", "书店", "展览馆", "超市", "购物中心", "店铺", "商店", "展馆", "集市", "步行街"]),
    ("park_nature", ["公园", "森林", "草地", "花海", "植物园", "郊野", "登山", "山林", "草坪", "树林", "步道", "自然", "山岳"]),
    ("waterside", ["海边", "海滩", "河滨", "湖岸", "泳池边", "水库", "江边", "海岸", "湖畔", "河岸", "码头", "河流"]),
    ("urban_street", ["商业街", "马路", "街道", "巷弄", "霓虹街道", "路边", "街区", "街景", "老城", "夜市", "步行街", "胡同"]),
    ("cultural_site", ["博物馆", "寺庙", "园林", "图书馆", "美术馆", "古建筑", "祠堂", "古迹", "教堂", "故居", "遗址"]),
    ("residential", ["客厅", "卧室", "阳台", "小区", "居家", "住宅", "书房", "公寓", "宿舍", "晾衣"]),
    ("industrial_ruins", ["废弃工厂", "拆迁", "工地", "废墟", "旧厂房", "废弃", "烂尾楼"]),
    ("campus", ["学校", "操场", "教室", "大学", "教学楼", "校园"]),
    ("night_scene", ["夜景", "夜间", "夜晚", "夜", "霓虹", "灯会"]),
]


def extract_scene_category(scene_type, location_clues=''):
    """
    从场景类型文本中提取场景分类标签。
    返回类别名如 'sports_venue'，无匹配返回空字符串。
    """
    if not scene_type:
        return ""
    # 合并场景描述和位置线索
    text = f"{scene_type} {location_clues or ''}"
    # 清洗标注前缀
    text = text.replace("[观察]", "").replace("[推测]", "")

    best_category = ""
    best_score = 0

    for category, keywords in SCENE_CATEGORY_RULES:
        score = 0
        for kw in keywords:
            if kw in text:
                # 越长关键词权重越高
                score += len(kw) * 2
        if score > best_score:
            best_score = score
            best_category = category

    if best_score >= 4:  # 至少匹配到2字关键词
        return best_category
    # fallback: 根据室内/室外做粗分类
    if "室内" in scene_type:
        return "indoor_generic"
    elif "室外" in scene_type:
        return "outdoor_generic"
    return ""


# ============================================================
# 风格积累（替代 style_cache.json 的 accumulate_styles）
# ============================================================

def accumulate(scene_type, discovered_styles, techniques_used, scene_category='', authenticity='unknown'):
    """
    积累发现的风格和技法到数据库。
    自动去重：同名风格追加 verify_count。
    新增 scene_category 参数——按场景类别分组积累
    新增 authenticity 参数——real_community 来源额外 +1 verify_count
    """
    if not scene_type:
        return

    # 自动提取场景类别（如果调用方未传入）
    if not scene_category:
        scene_category = extract_scene_category(scene_type)

    conn = get_db()
    try:
        # 社区验证来源 → 更高初始 verify_count
        community_boost = 2 if authenticity == 'real_community' else 1

        for s in (discovered_styles or []):
            name = s.get('name', '').strip()
            if not name:
                continue
            source_type = s.get('source_type', 'inference')
            fit_rationale = s.get('fit_rationale', '')[:500]

            # upsert style + RETURNING id (vcommunity_boost + N+1 消除)
            row = conn.execute("""
                INSERT INTO styles (name, source_type, fit_rationale, verify_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    verify_count = verify_count + ?,
                    source_type = CASE WHEN excluded.source_type != 'inference' THEN excluded.source_type ELSE source_type END,
                    updated_at = datetime('now')
                RETURNING id
            """, (name, source_type, fit_rationale, community_boost, community_boost)).fetchone()
            style_id = row[0] if row else None
            if style_id is None:
                style_id = conn.execute("SELECT id FROM styles WHERE name=?", (name,)).fetchone()[0]

            # link to scene (with category)
            conn.execute("""
                INSERT INTO scene_matches (scene_type, style_id, match_type, scene_category)
                VALUES (?, ?, 'style', ?)
            """, (scene_type, style_id, scene_category))

        for t in (techniques_used or []):
            name = t.get('name', '').strip()
            if not name:
                continue
            source_type = t.get('source_type', 'tutorial')
            description = t.get('description', '')[:500]

            row = conn.execute("""
                INSERT INTO techniques (name, source_type, description, verify_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    verify_count = verify_count + ?,
                    updated_at = datetime('now')
                RETURNING id
            """, (name, source_type, description, community_boost, community_boost)).fetchone()
            tech_id = row[0] if row else None
            if tech_id is None:
                tech_id = conn.execute("SELECT id FROM techniques WHERE name=?", (name,)).fetchone()[0]

            conn.execute("""
                INSERT INTO scene_matches (scene_type, technique_id, match_type, scene_category)
                VALUES (?, ?, 'technique', ?)
            """, (scene_type, tech_id, scene_category))

        conn.commit()
        print(f"[DB] Accumulated to '{scene_type[:50]}' (cat={scene_category}): {len(discovered_styles or [])} styles, {len(techniques_used or [])} techniques",
              file=sys.stderr, flush=True)
    except Exception as e:
        conn.rollback()
        print(f"[DB] Accumulate error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def query_scene_context(scene_type, category=''):
    """
    查询同类型场景的历史积累（按场景类别精确匹配）。

    优先按 scene_category 精确匹配（如 'sports_venue'），
    同类场景共享风格/技法经验，不同类别不交叉污染。
    Fallback: LIKE 模糊匹配（兼容旧数据）。
    """
    if not scene_type:
        return ""

    # 自动提取类别
    if not category:
        category = extract_scene_category(scene_type)

    conn = get_db()
    try:
        params = []

        if category:
            # ── 场景类别精确匹配 ──
            where_clause = "sm.scene_category = ?"
            params = [category]

            # 同时统计同类场景总数
            total_rows = conn.execute("""
                SELECT COUNT(DISTINCT sm.scene_type) FROM scene_matches sm
                WHERE sm.scene_category = ?
            """, params).fetchone()[0]

            # 如果同类数据为空，fallback 到室内/室外粗分类
            if total_rows == 0:
                if category.startswith("indoor"):
                    fallback_cat = "indoor_generic"
                elif category.startswith("outdoor"):
                    fallback_cat = "outdoor_generic"
                else:
                    fallback_cat = ""
                if fallback_cat:
                    params = [fallback_cat]
                    where_clause = "sm.scene_category = ?"
                    total_rows = conn.execute("""
                        SELECT COUNT(DISTINCT sm.scene_type) FROM scene_matches sm
                        WHERE sm.scene_category = ?
                    """, params).fetchone()[0]
        else:
            # ── Fallback: LIKE 模糊匹配（旧行为）──
            keywords = scene_type.replace("[观察]", "").replace("[推测]", "").replace("—", " ").split()
            search_terms = [k for k in keywords if len(k) >= 2][:3]
            if not search_terms:
                return ""
            like_clauses = " OR ".join(["sm.scene_type LIKE ?" for _ in search_terms])
            where_clause = like_clauses
            params = [f"%{t}%" for t in search_terms]
            total_rows = conn.execute(f"""
                SELECT COUNT(DISTINCT sm.scene_type) FROM scene_matches sm
                WHERE {where_clause}
            """, params).fetchone()[0]

        if total_rows == 0:
            return ""

        rows = conn.execute(f"""
            SELECT DISTINCT s.name as style_name, s.source_type, s.verify_count,
                   sm.scene_type, sm.use_count
            FROM scene_matches sm
            JOIN styles s ON sm.style_id = s.id
            WHERE sm.match_type = 'style' AND ({where_clause})
            ORDER BY s.verify_count DESC
            LIMIT 10
        """, params).fetchall()

        tech_rows = conn.execute(f"""
            SELECT DISTINCT t.name as tech_name, t.source_type, t.verify_count, t.description
            FROM scene_matches sm
            JOIN techniques t ON sm.technique_id = t.id
            WHERE sm.match_type = 'technique' AND ({where_clause})
            ORDER BY t.verify_count DESC
            LIMIT 10
        """, params).fetchall()

        if not rows and not tech_rows:
            return ""

        cat_label = category or "未知"
        ctx = f"\n## 📚 历史积累（「{cat_label}」类场景，{total_rows} 次分析）\n"
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
        ctx += "\n## 🚨 验证过的经验：同类场景验证过的风格/技法优先推荐。除非有明确不匹配的理由（光线条件完全不同/设备不支持），否则至少采纳 1 个验证过的风格方向。\n"

        return ctx
    except Exception as e:
        print(f"[DB] Query error: {e}", file=sys.stderr, flush=True)
        return ""
    finally:
        conn.close()


def query_scene_techniques_for_plans(scene_type, category=''):
    """
    查询同类场景的高频验证技法，直接注入方案生成 prompt。
    与 query_scene_context 不同：
    - 只取技法（不含风格）
    - 包含 description 字段（具体怎么用）
    - 只返回 verify_count >= 2 的（至少被验证过 2 次）
    - 返回带强制使用指令的 prompt 文本
    """
    if not scene_type:
        return ""

    if not category:
        category = extract_scene_category(scene_type)

    conn = get_db()
    try:
        params = []
        if category:
            where_clause = "sm.scene_category = ?"
            params = [category]
        else:
            keywords = scene_type.replace("[观察]", "").replace("[推测]", "").replace("—", " ").split()
            search_terms = [k for k in keywords if len(k) >= 2][:3]
            if not search_terms:
                return ""
            like_clauses = " OR ".join(["sm.scene_type LIKE ?" for _ in search_terms])
            where_clause = like_clauses
            params = [f"%{t}%" for t in search_terms]

        tech_rows = conn.execute(f"""
            SELECT DISTINCT t.name, t.description, t.source_type, t.verify_count
            FROM scene_matches sm
            JOIN techniques t ON sm.technique_id = t.id
            WHERE sm.match_type = 'technique' AND ({where_clause})
              AND t.verify_count >= 2
            ORDER BY t.verify_count DESC
            LIMIT 8
        """, params).fetchall()

        if not tech_rows:
            return ""

        ctx = "\n## 📚 历史验证技法（同类场景多次验证——方案中必须利用）\n"
        ctx += "以下是同类场景中经过多次验证的拍摄技法。每次分析都在实际拍摄中确认有效。\n\n"
        for i, r in enumerate(tech_rows, 1):
            desc = r['description'] or ''
            ctx += f"{i}. **{r['name']}**（验证{r['verify_count']}次, {r['source_type']}）\n"
            if desc:
                ctx += f"   → {desc}\n"
        ctx += "\n## 🚨 硬性要求：至少从以上技法中采纳 1 个，融入方案的 subject/shooter/gear 中。"
        ctx += "这是同类场景验证过的经验，不是你猜的。如果某个技法确实不适用当前光线/设备，说明原因后可以跳过。\n"

        return ctx
    except Exception as e:
        print(f"[DB] Query techniques error: {e}", file=sys.stderr, flush=True)
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
            "exported_at": datetime.utcnow().isoformat(),
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
    """获取数据库统计信息（合并为单次查询）"""
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM styles) as styles,
                (SELECT COUNT(*) FROM techniques) as techniques,
                (SELECT COUNT(DISTINCT scene_type) FROM scene_matches) as scenes,
                (SELECT COUNT(*) FROM scene_matches) as total_matches,
                (SELECT COUNT(*) FROM knowledge_sync WHERE status='pending') as pending_sync,
                (SELECT COUNT(*) FROM usage_sessions) as usage_sessions,
                (SELECT COUNT(*) FROM plan_feedback) as feedback_entries,
                (SELECT COALESCE(SUM(count),0) FROM daily_usage WHERE usage_date=date('now')) as today_analyses
        """).fetchone()
        return {
            "styles": row['styles'],
            "techniques": row['techniques'],
            "scenes": row['scenes'],
            "total_matches": row['total_matches'],
            "pending_sync": row['pending_sync'],
            "usage_sessions": row['usage_sessions'],
            "feedback_entries": row['feedback_entries'],
            "today_analyses": row['today_analyses'],
        }
    finally:
        conn.close()


# ============================================================
# AI API 调用日志
# ============================================================

def log_api_call(session_id, call_type, model='', prompt_tokens=0,
                 completion_tokens=0, total_tokens=0, duration_ms=0, success=1):
    """记录一次豆包 API 调用"""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO api_call_log (session_id, call_type, model, prompt_tokens,
                                      completion_tokens, total_tokens, duration_ms, success)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (session_id, call_type, model, prompt_tokens, completion_tokens,
              total_tokens, duration_ms, success))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] API log error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def log_search(session_id, search_type, query_text='', result_count=0,
               result_quality='🔴', source_types=None, duration_ms=0,
               results_summary=None, keywords_used=None, useful_data=None,
               authenticity='unknown', discovery_hint=''):
    """记录一次 Web 搜索执行（+discovery_hint）"""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO search_log (session_id, search_type, query_text, result_count,
                                    result_quality, source_types, duration_ms, results_summary,
                                    keywords_used, useful_data, authenticity, discovery_hint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (session_id, search_type, query_text[:300], result_count,
              result_quality, source_types or '', duration_ms,
              (results_summary or '')[:500],
              (keywords_used or '')[:500],
              (useful_data or '')[:200],
              authenticity or 'unknown',
              (discovery_hint or '')[:200]))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] Search log error: {e}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def get_api_call_stats():
    """获取 AI API 调用统计数据（用范围查询替代 date() 包裹）"""
    conn = get_db()
    try:
        now = datetime.utcnow()
        today = now.strftime('%Y-%m-%d')
        today_start = f"{today} 00:00:00"
        today_end = f"{today} 23:59:59"
        seven_days_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

        # 今日汇总（范围查询利用 idx_api_log_time 索引）
        today_calls = conn.execute("""
            SELECT call_type, COUNT(*) as cnt,
                   COALESCE(SUM(total_tokens),0) as tokens,
                   COALESCE(AVG(duration_ms),0) as avg_ms
            FROM api_call_log WHERE created_at >= ? AND created_at <= ?
            GROUP BY call_type
        """, (today_start, today_end)).fetchall()

        # 总计
        total_calls = conn.execute(
            "SELECT COUNT(*) FROM api_call_log"
        ).fetchone()[0]
        total_tokens = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0) FROM api_call_log"
        ).fetchone()[0]

        # 最近 20 条明细
        recent = [dict(r) for r in conn.execute("""
            SELECT session_id, call_type, total_tokens, duration_ms, success, created_at
            FROM api_call_log ORDER BY id DESC LIMIT 20
        """).fetchall()]

        # 7天 token 趋势
        trend = [dict(r) for r in conn.execute("""
            SELECT date(created_at) as day, COUNT(*) as cnt,
                   COALESCE(SUM(total_tokens),0) as tokens
            FROM api_call_log WHERE created_at >= ?
            GROUP BY day ORDER BY day
        """, (seven_days_ago,)).fetchall()]

        return {
            "today_calls": [dict(r) for r in today_calls],
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "recent": recent,
            "trend": trend,
        }
    finally:
        conn.close()


def get_failed_api_logs(limit=20):
    """获取最近失败的 API 调用日志，含今日/总计统计"""
    conn = get_db()
    try:
        now = datetime.utcnow()
        today = now.strftime('%Y-%m-%d')
        today_start = f"{today} 00:00:00"
        today_end = f"{today} 23:59:59"

        recent = [dict(r) for r in conn.execute("""
            SELECT id, session_id, call_type, model, total_tokens, duration_ms, created_at
            FROM api_call_log WHERE success = 0
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()]

        today_fails = conn.execute("""
            SELECT COUNT(*) FROM api_call_log
            WHERE success = 0 AND created_at >= ? AND created_at <= ?
        """, (today_start, today_end)).fetchone()[0]

        total_fails = conn.execute(
            "SELECT COUNT(*) FROM api_call_log WHERE success = 0"
        ).fetchone()[0]

        return {
            "recent": recent,
            "today_fails": today_fails,
            "total_fails": total_fails,
        }
    finally:
        conn.close()


def get_search_stats():
    """获取 Web 搜索执行统计数据（用范围查询替代 date() 包裹）"""
    conn = get_db()
    try:
        now = datetime.utcnow()
        today = now.strftime('%Y-%m-%d')
        today_start = f"{today} 00:00:00"
        today_end = f"{today} 23:59:59"
        seven_days_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

        # 今日搜索（范围查询）
        today_searches = conn.execute("""
            SELECT search_type, COUNT(*) as cnt,
                   COALESCE(AVG(result_count),0) as avg_results,
                   AVG(CASE WHEN result_count > 0 THEN 1 ELSE 0 END) as hit_rate
            FROM search_log WHERE created_at >= ? AND created_at <= ?
            GROUP BY search_type
        """, (today_start, today_end)).fetchall()

        # 总计
        total_searches = conn.execute(
            "SELECT COUNT(*) FROM search_log"
        ).fetchone()[0]
        total_with_results = conn.execute(
            "SELECT COUNT(*) FROM search_log WHERE result_count > 0"
        ).fetchone()[0]

        # 最近 30 条
        recent = [dict(r) for r in conn.execute("""
            SELECT session_id, search_type, query_text, result_count,
                   result_quality, source_types, duration_ms, results_summary,
                   keywords_used, useful_data, authenticity, created_at
            FROM search_log ORDER BY id DESC LIMIT 30
        """).fetchall()]

        # 7天搜索趋势
        trend = [dict(r) for r in conn.execute("""
            SELECT date(created_at) as day, COUNT(*) as cnt,
                   SUM(CASE WHEN result_count > 0 THEN 1 ELSE 0 END) as with_results
            FROM search_log WHERE created_at >= ?
            GROUP BY day ORDER BY day
        """, (seven_days_ago,)).fetchall()]

        # 真实性分布
        auth_dist = [dict(r) for r in conn.execute("""
            SELECT authenticity, COUNT(*) as cnt
            FROM search_log WHERE authenticity != 'unknown'
            GROUP BY authenticity ORDER BY cnt DESC
        """).fetchall()]

        # 有用数据命中率
        useful_total = conn.execute(
            "SELECT COUNT(*) FROM search_log WHERE useful_data != ''"
        ).fetchone()[0]

        return {
            "today_searches": [dict(r) for r in today_searches],
            "total_searches": total_searches,
            "total_with_results": total_with_results,
            "recent": recent,
            "trend": trend,
            "auth_dist": auth_dist,
            "useful_total": useful_total,
        }
    finally:
        conn.close()


def log_style_exploration(session_id, style_name, decision, reason=''):
    """记录 AI 自由探索风格名的选取/舍弃决定

    Args:
        session_id: 会话 ID
        style_name: 探索到的风格名
        decision: 'selected' 或 'rejected'
        reason: 选取或舍弃的理由
    """
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO style_exploration_log (session_id, style_name, decision, reason)
            VALUES (?, ?, ?, ?)
        """, (session_id, style_name[:200], decision, reason[:500]))
        conn.commit()
    finally:
        conn.close()


def get_style_exploration_stats():
    """获取 AI 风格探索统计数据"""
    conn = get_db()
    try:
        now = datetime.utcnow()
        today = now.strftime('%Y-%m-%d')
        today_start = f"{today} 00:00:00"
        today_end = f"{today} 23:59:59"

        total = conn.execute(
            "SELECT COUNT(*) FROM style_exploration_log"
        ).fetchone()[0]
        selected = conn.execute(
            "SELECT COUNT(*) FROM style_exploration_log WHERE decision='selected'"
        ).fetchone()[0]
        rejected = conn.execute(
            "SELECT COUNT(*) FROM style_exploration_log WHERE decision='rejected'"
        ).fetchone()[0]
        today_total = conn.execute(
            "SELECT COUNT(*) FROM style_exploration_log WHERE created_at >= ? AND created_at <= ?",
            (today_start, today_end)
        ).fetchone()[0]

        # 最近 50 条（排除测试数据，标注是否已在知识库）
        recent = [dict(r) for r in conn.execute("""
            SELECT e.id, e.session_id, e.style_name, e.decision, e.reason, e.promoted, e.created_at,
                   CASE WHEN s.name IS NOT NULL THEN 1 ELSE 0 END as in_kb
            FROM style_exploration_log e
            LEFT JOIN styles s ON s.name = e.style_name
            WHERE e.session_id != 'test-debug'
            ORDER BY e.id DESC LIMIT 50
        """).fetchall()]

        # 高频选取的风格 Top
        top_selected = [dict(r) for r in conn.execute("""
            SELECT style_name, COUNT(*) as cnt
            FROM style_exploration_log WHERE decision='selected'
            GROUP BY style_name ORDER BY cnt DESC LIMIT 15
        """).fetchall()]

        # 高频舍弃的风格 Top
        top_rejected = [dict(r) for r in conn.execute("""
            SELECT style_name, COUNT(*) as cnt
            FROM style_exploration_log WHERE decision='rejected'
            GROUP BY style_name ORDER BY cnt DESC LIMIT 15
        """).fetchall()]

        # 7 天趋势
        seven_days_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        trend = [dict(r) for r in conn.execute("""
            SELECT date(created_at) as day, decision, COUNT(*) as cnt
            FROM style_exploration_log WHERE created_at >= ?
            GROUP BY day, decision ORDER BY day
        """, (seven_days_ago,)).fetchall()]

        return {
            "total": total,
            "selected": selected,
            "rejected": rejected,
            "today_total": today_total,
            "recent": recent,
            "top_selected": top_selected,
            "top_rejected": top_rejected,
            "trend": trend,
        }
    finally:
        conn.close()


def promote_exploration_to_style(exploration_id):
    """将 AI 探索到的风格入库为正式风格

    从 style_exploration_log 提取 style_name 和 reason，
    自动整理写入 styles 表，标记探索记录为已入库。
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT style_name, decision, reason FROM style_exploration_log WHERE id=?",
            (exploration_id,)
        ).fetchone()
        if not row:
            return {"success": False, "error": "探索记录不存在"}

        style_name = row['style_name']
        reason = row['reason'] or ''
        # 取 reason 前 120 字作为 one_liner
        one_liner = (reason[:120] + '…') if len(reason) > 120 else (reason or '')

        # 写入 styles 表（ON CONFLICT 累加 verify_count）
        conn.execute("""
            INSERT INTO styles (name, one_liner, source_type, fit_rationale, verify_count)
            VALUES (?, ?, 'ai_exploration', ?, 1)
            ON CONFLICT(name) DO UPDATE SET
                verify_count = verify_count + 1,
                fit_rationale = CASE WHEN excluded.fit_rationale != ''
                    THEN excluded.fit_rationale ELSE fit_rationale END,
                one_liner = CASE WHEN excluded.one_liner != ''
                    THEN excluded.one_liner ELSE one_liner END,
                updated_at = datetime('now')
        """, (style_name, one_liner, reason[:500]))

        # 标记探索记录为已入库
        conn.execute(
            "UPDATE style_exploration_log SET promoted=1 WHERE id=?",
            (exploration_id,)
        )
        conn.commit()
        print(f"[DB] Promoted exploration #{exploration_id} '{style_name}' → styles table",
              file=sys.stderr, flush=True)
        return {"success": True, "name": style_name}
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def delete_exploration(exploration_id):
    """删除一条 AI 风格探索记录"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM style_exploration_log WHERE id=?", (exploration_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"[DB] Delete exploration error: {e}", file=sys.stderr, flush=True)
        return False
    finally:
        conn.close()


def get_style_technique_panel():
    """获取风格/技法发现面板数据"""
    conn = get_db()
    try:
        today = datetime.utcnow().strftime('%Y-%m-%d')
        total_styles = conn.execute("SELECT COUNT(*) FROM styles").fetchone()[0]
        styles_by_source = [dict(r) for r in conn.execute("""
            SELECT source_type, COUNT(*) as cnt FROM styles GROUP BY source_type ORDER BY cnt DESC
        """).fetchall()]
        top_styles = [dict(r) for r in conn.execute("""
            SELECT name, source_type, verify_count, created_at
            FROM styles ORDER BY verify_count DESC LIMIT 15
        """).fetchall()]
        styles_today = conn.execute(
            "SELECT COUNT(*) FROM styles WHERE date(created_at)=?", (today,)
        ).fetchone()[0]

        # 技法统计
        total_techniques = conn.execute("SELECT COUNT(*) FROM techniques").fetchone()[0]
        top_techniques = [dict(r) for r in conn.execute("""
            SELECT name, source_type, verify_count, created_at
            FROM techniques ORDER BY verify_count DESC LIMIT 10
        """).fetchall()]
        techniques_today = conn.execute(
            "SELECT COUNT(*) FROM techniques WHERE date(created_at)=?", (today,)
        ).fetchone()[0]

        # 场景类型分布
        scene_dist = [dict(r) for r in conn.execute("""
            SELECT scene_type, COUNT(*) as match_count
            FROM scene_matches GROUP BY scene_type ORDER BY match_count DESC LIMIT 10
        """).fetchall()]

        return {
            "total_styles": total_styles,
            "styles_today": styles_today,
            "styles_by_source": styles_by_source,
            "top_styles": top_styles,
            "total_techniques": total_techniques,
            "techniques_today": techniques_today,
            "top_techniques": top_techniques,
            "scene_dist": scene_dist,
        }
    finally:
        conn.close()


def get_pending_discoveries():
    """
    获取待审核的搜索发现——优先展示 discovery_hint。
    """
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute("""
            SELECT id, session_id, query_text, result_count, result_quality,
                   source_types, keywords_used, useful_data, authenticity,
                   results_summary, discovery_hint, created_at
            FROM search_log
            WHERE authenticity IN ('real_community', 'mixed')
              AND useful_data != ''
              AND useful_data NOT LIKE '%[promoted]%'
              AND created_at >= date('now', '-30 days')
            ORDER BY id DESC LIMIT 50
        """).fetchall()]

        results = []
        for row in rows:
            # 优先用 discovery_hint，回退到 results_summary 截断
            hint = (row.get('discovery_hint') or row.get('results_summary') or '')[:200]
            results.append({
                **row,
                'has_techniques': False,
                'extracted_hint': hint,
            })

        return results
    finally:
        conn.close()


def promote_search_to_technique(search_log_id, technique_name, description, source_type='community',
                                scene_category='', verify_count=3):
    """
    将搜索发现提升为正式技法（管理面板审批通过）。
    写入 techniques 表 + scene_matches 表。
    """
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO techniques (name, source_type, description, verify_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                verify_count = verify_count + ?,
                source_type = CASE WHEN excluded.source_type = 'tutorial' THEN ? ELSE excluded.source_type END,
                updated_at = datetime('now')
        """, (technique_name, source_type, description, verify_count, verify_count, source_type))

        tech_id = conn.execute(
            "SELECT id FROM techniques WHERE name=?", (technique_name,)
        ).fetchone()
        if tech_id and scene_category:
            conn.execute("""
                INSERT OR IGNORE INTO scene_matches (scene_type, technique_id, match_type, scene_category)
                VALUES (?, ?, 'technique', ?)
            """, (scene_category, tech_id[0], scene_category))

        # 标记已处理
        conn.execute("""
            UPDATE search_log SET useful_data = useful_data || ' [promoted]'
            WHERE id = ?
        """, (search_log_id,))

        conn.commit()
        print(f"[DB] Promoted search #{search_log_id} → technique '{technique_name}' (cat={scene_category})",
              file=sys.stderr, flush=True)
        return True
    except Exception as e:
        conn.rollback()
        print(f"[DB] Promote error: {e}", file=sys.stderr, flush=True)
        return False
    finally:
        conn.close()


# ============================================================
# 知识库种子数据——用 verified/real_world 内容初始化风格技法表
# ============================================================

def seed_from_knowledge_base():
    """
    从知识库中提取有可靠来源的风格/技法，写入数据库作为种子数据。
    仅运行一次——检测已有 knowledge_base / cross_media 来源的记录后跳过。
    返回写入数量。
    """
    conn = get_db()
    try:
        # 从 knowledge_base 导入（避免循环导入）
        try:
            from knowledge_base import STYLE_ONE_LINERS, CROSS_MEDIA_STYLE_ONE_LINERS, VERIFIED_TECHNIQUES
        except ImportError:
            print("[DB] Seed: Cannot import from knowledge_base", file=sys.stderr, flush=True)
            return 0

        count_styles = 0
        count_techs = 0

        # ── Phase 1: 种子风格（style-recipes → knowledge_base）──
        existing_kb = conn.execute(
            "SELECT COUNT(*) FROM styles WHERE source_type = 'knowledge_base'"
        ).fetchone()[0]
        if existing_kb > 0:
            print(f"[DB] Seed: {existing_kb} knowledge_base styles already exist, skipping phase 1", file=sys.stderr, flush=True)
        else:
            for name, one_liner in STYLE_ONE_LINERS.items():
                conn.execute("""
                    INSERT OR IGNORE INTO styles (name, one_liner, source_type, fit_rationale, verify_count)
                    VALUES (?, ?, 'knowledge_base', ?, 10)
                """, (name, one_liner, f"知识库种子：{one_liner[:200]}"))
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    count_styles += 1

        # ── Phase 2: 种子跨媒介风格（cross-media-styles → cross_media）──
        existing_cm = conn.execute(
            "SELECT COUNT(*) FROM styles WHERE source_type = 'cross_media'"
        ).fetchone()[0]
        if existing_cm > 0:
            print(f"[DB] Seed: {existing_cm} cross_media styles already exist, skipping phase 2", file=sys.stderr, flush=True)
        else:
            for name, one_liner in CROSS_MEDIA_STYLE_ONE_LINERS.items():
                conn.execute("""
                    INSERT OR IGNORE INTO styles (name, one_liner, source_type, fit_rationale, verify_count)
                    VALUES (?, ?, 'cross_media', ?, 8)
                """, (name, one_liner, f"跨媒介风格：导演/画派/互联网美学 → {one_liner[:200]}"))
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    count_styles += 1

        # ── Phase 3: 种子技法 ──
        existing_tech = conn.execute(
            "SELECT COUNT(*) FROM techniques WHERE source_type = 'knowledge_base'"
        ).fetchone()[0]
        if existing_tech > 0:
            print(f"[DB] Seed: {existing_tech} knowledge_base techniques already exist, skipping phase 3", file=sys.stderr, flush=True)
        else:
            for tech in (VERIFIED_TECHNIQUES or []):
                conn.execute("""
                    INSERT OR IGNORE INTO techniques (name, source_type, description, verify_count)
                    VALUES (?, 'knowledge_base', ?, 10)
                """, (tech['name'], tech.get('description', '')))
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    count_techs += 1

        conn.commit()
        print(f"[DB] Seed: inserted {count_styles} styles + {count_techs} techniques",
              file=sys.stderr, flush=True)
        return count_styles + count_techs
    except Exception as e:
        conn.rollback()
        print(f"[DB] Seed error: {e}", file=sys.stderr, flush=True)
        return 0
    finally:
        conn.close()


# ============================================================
# 实战技法种子——来自社交媒体验证的高频场景技法
# ============================================================

PRACTICAL_TECHNIQUES = [
    # ── 美食/咖啡厅 (f_and_b) ──
    {"name": "窗边侧光拍食物质感", "source_type": "social_media",
     "description": "食物放窗边，光从侧面来（不是顶灯不是闪光灯）。侧光产生立体阴影让蛋糕层次、咖啡油脂、沙拉纹理全部清晰可见。正面光拍出来像外卖App图片。",
     "scene_category": "f_and_b"},
    {"name": "45°俯拍桌面ins风", "source_type": "social_media",
     "description": "手机完全平行于桌面从正上方拍。画面里不仅要有食物，还要有桌面材质（木纹/大理石）、餐具、一只手入镜。不超过3个东西——盘子+杯子+手就够了。开九宫格，盘子放上交叉点。",
     "scene_category": "f_and_b"},
    {"name": "手持食物特写拍出刚做好感", "source_type": "social_media",
     "description": "一只手拿食物/杯子举到胸口高度。背景是咖啡厅环境虚化。用2×镜头靠近拍，杯子边缘可能被人像模式吃掉——先用普通模式拍一张保底。",
     "scene_category": "f_and_b"},
    {"name": "趁热拍食物状态最好", "source_type": "social_media",
     "description": "刚上桌时热菜有蒸汽、咖啡有油脂、沙拉还脆。等聊完天再拍就晚了。先拍再吃，不要先用筷子翻。",
     "scene_category": "f_and_b"},
    {"name": "食物做减法桌面清理", "source_type": "social_media",
     "description": "拍照前把纸巾/账单/手机/钥匙拿走——画面里只留食物+餐具+1-2个装饰物。颜色越多越廉价，越少越高级。不要用滤镜预设——食物照片的滤镜感=塑料感，原生色彩+稍微提亮就够了。",
     "scene_category": "f_and_b"},

    # ── 情侣互拍 (urban_street + commercial) ──
    {"name": "蹲下低机位显高拍法", "source_type": "social_media",
     "description": "男生给女生拍照最常见翻车：站着从上往下拍→拍成1米5。正确做法：蹲下来，手机与对方腰部齐平甚至更低，画面下边缘刚好切到脚，头顶留1/3空白。透视原理：镜头越低，腿离镜头越近→腿被拉长。",
     "scene_category": "urban_street"},
    {"name": "侧身回头连拍抓自然表情", "source_type": "social_media",
     "description": "让TA往前走，然后喊名字回头——真的走真的回头，连拍。摆拍的回头90%不自然。身体和镜头成45°时身体轮廓最修长。这个姿势同时解决了表情僵硬+体型显胖两个问题。",
     "scene_category": "urban_street"},
    {"name": "坐姿只坐1/3显腿细", "source_type": "social_media",
     "description": "坐椅子/台阶边缘只坐1/3，大腿不压平（压平的大腿比站立宽30%）。腿往前伸脚尖朝下点地，一只前一只后。手机与胸口同高平拍。",
     "scene_category": "commercial"},
    {"name": "窗边半剪影高级感拍法", "source_type": "social_media",
     "description": "人物站在窗边背对窗户，从室内往外拍。点击屏幕上窗户最亮处，画面自动变暗→人物变成半剪影。不需要表情管理、不需要化妆、不需要后期——光线本身做了一切。窗框给画面加了天然框架结构。",
     "scene_category": "commercial"},
    {"name": "走路跟拍连拍自然感", "source_type": "social_media",
     "description": "人物在前面正常走，摄影师在后面跟。手指按住快门不放连拍，走10步选最好的。走路的动作让全身处于自然状态——手在摆、头发在飘、裙摆在动。这种'活着的照片'比任何摆拍都有生命力。",
     "scene_category": "urban_street"},
    {"name": "道具互动转移注意力拍自然表情", "source_type": "social_media",
     "description": "给TA一个道具（咖啡杯/花/书/手机/宠物）让TA和道具互动。人的注意力一次只能放一个地方——在想'这个咖啡好香'时表情自然，在想'我的表情对不对'时一定僵。两只手都被占用的道具最好——身体姿态更放松。",
     "scene_category": "urban_street"},

    # ── 闺蜜/多人合影 (urban_street + park_nature) ──
    {"name": "三角形站位代替一排站", "source_type": "social_media",
     "description": "3-4人不要站成一排——一排=所有人到镜头距离相同=扁平无层次=谁站最边上谁显胖（边缘畸变）。三角形站位：1人前（坐/蹲）+2人后（站），每个人都有自己到镜头的距离。后面的人侧身站不要正面。",
     "scene_category": "urban_street"},
    {"name": "阶梯高度差让每个人都能看到脸", "source_type": "social_media",
     "description": "5人以上：找台阶/坡道/沙发+椅子+地面制造高度差，每排至少差30cm。前排坐地、中排蹲/半蹲、后排站。没有高度差的合影=后面的人只剩一颗头。手机退后3-5步用1×主摄不要超广角。",
     "scene_category": "urban_street"},
    {"name": "互动散落不盯镜头拍电影感", "source_type": "social_media",
     "description": "不让所有人看镜头——全都看镜头=毕业照，有人不看=生活感。让她们一起干杯/一起看手机/一起指一个方向。连拍不喊1-2-3。拍照者成为'不存在的观察者'。",
     "scene_category": "park_nature"},
    {"name": "V字型时尚站位", "source_type": "social_media",
     "description": "中间的人靠后，两边的人往前探形成V字。不是对称的——一边比另一边更靠前随意。大家身体都微微转向中间那个人。手机高度和后面那人的眼睛齐平。这是时尚杂志拍群像的经典站法。",
     "scene_category": "urban_street"},

    # ── 单人旅行/打卡 (cultural_site + park_nature) ──
    {"name": "大景小人大法拍出旅行感", "source_type": "social_media",
     "description": "退远——至少离人物10步以上。人物占画面5-15%，站在画面下1/3处，上方2/3留给环境。用1×主摄不要超广角（超广角会让远景变平）。让人物做简单动作——举手/侧身/跳跃增加趣味。这类照片收藏率最高——让人想去。",
     "scene_category": "cultural_site"},
    {"name": "手机架设代替自拍杆", "source_type": "social_media",
     "description": "找任何和你腰部差不多高的平面（栏杆/桌子/窗台/花坛/背包叠起来），手机竖着靠在水杯/背包上——不是平放是靠起来有角度。倒计时3秒够退一步，10秒够走远。退3-5步到画面里做自然动作。用1×主摄不要0.5×。",
     "scene_category": "cultural_site"},
    {"name": "镜子反射创意打卡", "source_type": "social_media",
     "description": "利用镜子/玻璃窗/水面/墨镜镜片——一个画面里同时看到反射+实景。手机靠近反光面从侧面拍，让反射占画面1/3-1/2。手机不要出现在镜子里。这种双重空间感不像普通游客照。",
     "scene_category": "cultural_site"},
    {"name": "延时视频取帧法零失败", "source_type": "social_media",
     "description": "录30秒-1分钟视频（不是拍照），在画面里自然地做一件事（走路/转身/撩头发/看风景）。事后从视频截最好一帧。30秒视频=900帧=900次选择机会，总有一帧完美的。视频截帧画质略差但发朋友圈完全够用。",
     "scene_category": "park_nature"},

    # ── 显瘦显高通用 (all outdoor) ──
    {"name": "侧身45°立刻显瘦", "source_type": "social_media",
     "description": "正面站立=身体宽度=画面最大宽度。侧身45°=身体宽度≈正面70%。同时侧身制造身体前后层次（胸-腰-臀），轮廓线更有变化。重心放后腿，前腿微曲脚尖点地，肩膀往后展开。",
     "scene_category": "urban_street"},
    {"name": "高机位俯拍显脸小自拍法", "source_type": "social_media",
     "description": "手机举到额头以上（不是眼睛高度），从上往下拍。下巴微收眼睛往上看手机。俯拍=下巴离镜头最近→脸下半部分变小→下颌线更明显→显脸小。拿手机的手往前伸——手臂不贴身显细。另一只手撩头发或放下巴旁加画面层次。",
     "scene_category": "urban_street"},
    {"name": "暗调光影遮肉瘦身法", "source_type": "social_media",
     "description": "不靠姿势靠光线。站在明暗交界处——身体正面在暗处，侧面轮廓有一道光（轮廓光）。光=视觉焦点，暗=视觉退后。身体大部分在暗处→观众只能看到轮廓看不到具体宽度。点击屏幕最亮处让画面变暗。",
     "scene_category": "urban_street"},
    {"name": "低机位脚下少留白显腿长", "source_type": "social_media",
     "description": "手机在被拍者腰部到胸口高度（不是拍照者眼睛高度），微微仰拍。画面下边缘贴近脚底——脚下不要留大片空地。透视原理：镜头越低→脚离镜头越近（相对于头）→腿部占比越大。这就是为什么摄影师拍照总蹲着。",
     "scene_category": "urban_street"},

    # ── 氛围增色通用技法 ──
    {"name": "降曝光营造氛围感", "source_type": "social_media",
     "description": "点击屏幕最亮处→画面暗1-2档。暗=氛围，亮=记录。让光线穿过东西再进入镜头（窗帘/树叶/玻璃/雾气）→光线被柔化后有空气感。画面不需要什么都看清楚——暗的地方就让它暗着，那是氛围。",
     "scene_category": "urban_street"},
    {"name": "色彩做减法≤3色显高级", "source_type": "social_media",
     "description": "画面里颜色不超过3个色系。颜色越多越热闹越廉价，越少越安静越高级。穿纯色衣服（白/卡其/浅蓝等低饱和度色），背景干净的优先（白墙/蓝天/纯色窗帘）。保留皮肤纹理质感不磨皮——磨皮=塑料感=廉价感。",
     "scene_category": "urban_street"},
    {"name": "逆光发丝光金边效果", "source_type": "social_media",
     "description": "人物背对阳光，光线穿过头发→发丝边缘发光像漫画高光效果。同时脸在暗处→皮肤瑕疵自动被遮掉。这是朋友圈被问'什么相机'最多的技巧。日落前1小时是拍发丝光的最佳时段。",
     "scene_category": "park_nature"},
    {"name": "前景虚化制造电影感", "source_type": "social_media",
     "description": "找一片叶子/一朵花/一杯水放在镜头前5-10cm→自动变模糊。这个模糊是故意的不是拍砸了。它让画面有了'透过什么在看'的感觉——就像电影镜头。前景占画面1/3-1/2，焦点在远处人物上。",
     "scene_category": "park_nature"},
    {"name": "光影交界法自动瘦身", "source_type": "social_media",
     "description": "站在明暗交界处——脸在亮处身体在暗处。树荫边缘/窗边/路灯下都行。光线本身帮你瘦了身体+打了面光。手机点击屏幕最亮处锁定曝光。一张照片同时解决瘦身+氛围两个需求。",
     "scene_category": "urban_street"},
    {"name": "阴天是天然柔光箱拍人像最佳", "source_type": "social_media",
     "description": "云层把太阳直射光散射为漫射光——没有刺眼影子，光线从四面八方均匀照过来。这是最好的天然美颜灯——拍人像皮肤最干净最柔和。晴天反而容易拍出脸上硬阴影。阴天≠不适合拍照，阴天=不需要找角度光就对了。",
     "scene_category": "park_nature"},
    {"name": "黄金时刻拍什么都不用修", "source_type": "verified",
     "description": "日出后1小时和日落前1小时——太阳角度低，光线穿过更厚大气层，蓝光被过滤只剩暖金色。这时候拍照不用加滤镜就是天然暖色调。色温约3000-4000K。这是摄影界公认的最出片时段。",
     "scene_category": "park_nature"},

    # ── 姿势引导核心技法 ──
    {"name": "手有道具不悬空解决姿势僵硬", "source_type": "social_media",
     "description": "手不知道放哪=最常见拍照焦虑。给手一个任务：拿咖啡杯/撩头发/扶帽檐/插口袋。拇指必须露外面——全插进去像手消失了。两只手不同动作=画面更丰富。空手=焦虑，手有任务=自然。",
     "scene_category": "urban_street"},
    {"name": "走路代替站着解决表情僵硬", "source_type": "social_media",
     "description": "走路时身体在动——手在摆、头发在飘、衣服在动。这些动的元素让照片有了生命力。站着不动时身体会自动紧张进入'被观察'状态。连拍模式下走10步选最好的那张。比任何摆拍站姿都有生命力。",
     "scene_category": "urban_street"},
    {"name": "不看镜头更自然有故事感", "source_type": "social_media",
     "description": "看镜头=和观众对视→有社交压力。不看镜头=观众变成路过的观察者→可以安静地看。看远方/看地面/看手里的东西/闭上眼睛——任何一个方向都比盯着镜头自然。这个技巧解决90%的表情僵硬。",
     "scene_category": "urban_street"},
    {"name": "伸脖子收下巴显瘦显气质", "source_type": "social_media",
     "description": "拍照时放松肩膀向后拉，头微微前伸一点——颈项立刻显瘦一圈。下巴微侧向镜头让轮廓线条更突出。不要过度收下巴（反而挤出双下巴），也不要过度抬下巴（鼻孔朝天）。这个微调立刻提升气质。",
     "scene_category": "urban_street"},
    {"name": "人像模式虚化背景突出主体", "source_type": "tutorial",
     "description": "手机人像模式模拟大光圈虚化。人物与背景保持1米以上距离→虚化更明显。选纯色背景增强识别。如果头发边缘被虚化吃掉→后期调低虚化强度。这是手机拍人像最常用也最有效的功能。",
     "scene_category": "urban_street"},

    # ── 避雷技法 ──
    {"name": "按快门前扫一眼背景避开杂物戳头", "source_type": "social_media",
     "description": "最常见的毁片原因：电线杆从头顶长出来/垃圾桶入镜/路人抢镜。按快门之前花1秒扫一眼画面四角和人物背景——移动站位或让人物挪一步就能避开。拍完再P背景杂物很难P干净。",
     "scene_category": "urban_street"},
    {"name": "数码变焦硬拉不如走近拍", "source_type": "tutorial",
     "description": "手指放大画面=数码变焦=裁切=画质变渣。走两步靠近用光学变焦（1×/2×/3×按钮）。光学变焦画质无损，数码变焦只是裁切。实在不能走近→用2×或3×原生光学焦段，不要用手指滑动放大。",
     "scene_category": "urban_street"},
    {"name": "禁用闪光灯直打找窗边自然光", "source_type": "social_media",
     "description": "手机闪光灯直打=油光满面+红眼+大白脸。室内暗时先找窗边/路灯/台灯/手机屏幕反光——任何自然光源都比直闪好。必须补光时→开另一台手机的手电筒从侧面照。晚上用人像模式夜景模式代替闪光灯。",
     "scene_category": "urban_street"},
    {"name": "逆光不补光脸全黑要拉小太阳", "source_type": "social_media",
     "description": "逆光拍人最常见的翻车：背景正常脸全黑。解决方法：点击屏幕人脸→出现小太阳图标→手指向上滑动提亮1-2档。逆光不是不能拍——逆光是最出片的氛围光——只是需要提亮暗部。",
     "scene_category": "park_nature"},
    {"name": "正午顶光别硬拍移到树荫下", "source_type": "verified",
     "description": "正午11-15点太阳在头顶正上方→眼窝黑洞、鼻子下浓重阴影、额头反光。不是光线不好——是光的方向不对。移到树荫/建筑阴影/走廊下，光线立刻变柔。或者等黄金时刻（日出后/日落前1小时）再拍。",
     "scene_category": "park_nature"},
    {"name": "连拍代替单张告别闭眼和表情崩坏", "source_type": "social_media",
     "description": "按住快门不放=连拍模式→每秒10-30张。拍动态/表情/回头/跳跃时用连拍，事后再选最好的那张。1张单拍=1次机会，连拍3秒=30-90次机会。拍小孩/宠物/运动时这是必备技能。",
     "scene_category": "urban_street"},
    {"name": "擦干净镜头最简单的画质提升", "source_type": "tutorial",
     "description": "手机镜头常年有指纹和油污——这是照片发灰发雾的第一大原因。用眼镜布或棉质衣角擦，不要用手指/纸巾擦。每次拍照前养成习惯花2秒擦一下。这个动作对画质的提升超过任何参数设置。",
     "scene_category": "urban_street"},
]


def seed_practical_techniques():
    """
    写入社交媒体验证的高频场景技法。
    门控：检测已有 social_media 来源的记录后跳过。
    返回写入数量。
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT COUNT(*) FROM techniques WHERE source_type = 'social_media'"
        ).fetchone()[0]
        if existing > 0:
            print(f"[DB] Seed practical: {existing} social_media techniques already exist, skipping",
                  file=sys.stderr, flush=True)
            return 0

        count_techs = 0
        count_matches = 0

        for tech in PRACTICAL_TECHNIQUES:
            # upsert technique + RETURNING id (v消除 N+1 查询)
            row = conn.execute("""
                INSERT INTO techniques (name, source_type, description, verify_count)
                VALUES (?, ?, ?, 5)
                ON CONFLICT(name) DO UPDATE SET
                    description = CASE WHEN LENGTH(excluded.description) > LENGTH(techniques.description)
                                  THEN excluded.description ELSE techniques.description END,
                    source_type = excluded.source_type,
                    updated_at = datetime('now')
                RETURNING id
            """, (tech['name'], tech['source_type'], tech['description'])).fetchone()
            tech_id = row[0] if row else None
            if tech_id is None:
                tech_id = conn.execute(
                    "SELECT id FROM techniques WHERE name=?", (tech['name'],)
                ).fetchone()[0]
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                count_techs += 1
            conn.execute("""
                INSERT OR IGNORE INTO scene_matches (scene_type, technique_id, match_type, scene_category)
                VALUES (?, ?, 'technique', ?)
            """, (tech['scene_category'], tech_id, tech['scene_category']))
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                count_matches += 1

        conn.commit()
        print(f"[DB] Seed practical: inserted {count_techs} techniques + {count_matches} scene_matches",
              file=sys.stderr, flush=True)
        return count_techs + count_matches
    except Exception as e:
        conn.rollback()
        print(f"[DB] Seed practical error: {e}", file=sys.stderr, flush=True)
        return 0
    finally:
        conn.close()


# ============================================================
# 拍照姿势技法——来自 Valenzuela/Barnbaum 教材
# ============================================================

POSING_TECHNIQUES = [
    # ── 站姿基础 ──
    {"name": "重心单腿站姿——两条腿永远不做同一件事", "source_type": "verified",
     "description": "重心放后腿，前腿微曲膝盖微靠内侧→放松自然。重心放前腿→主动有活力。双腿均匀→僵硬。操作指令：'把重心放一条腿上，另一条腿自然弯着——像等公交车不是站军姿。' 来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},
    {"name": "脊柱S曲线展开——侧身30-45度对镜头", "source_type": "verified",
     "description": "正对镜头时脊柱S曲线被压扁成直线→显宽。让脊柱轴线与相机成30-45度角→S曲线在画面中展开→自然身体轮廓。操作指令：'脚不动，上半身往左转一点...对，再回来一点。' 来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},
    {"name": "肩部后展开锁骨——深呼吸吐气法", "source_type": "verified",
     "description": "最快打开锁骨的方法：'深呼吸一口气，保持这个姿势吐出来。' 吐气=肩部肌肉自然下沉→锁骨自动打开→姿势瞬间变好。不需要说'肩膀后转'。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},

    # ── 手部管理 ──
    {"name": "手有任务不悬空——给手一个明确指令", "source_type": "verified",
     "description": "手不知道放哪=最常见拍照焦虑。给手一个任务：拿咖啡/撩头发/扶帽檐/插口袋（拇指必须露外面）。双手不同动作=画面更丰富。手夹腿间=手消失=身体线条断开。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},
    {"name": "腋下关节留白——手臂与躯干留2-3指空隙", "source_type": "verified",
     "description": "手臂紧贴身体=腋下无三角空隙=视觉上胳膊变粗一倍。任何姿势都要确保腋下/膝盖内侧/手肘内侧有'呼吸空间'。这不是体重问题，是几何问题。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},
    {"name": "手掌不直接对镜头——转45度看手背", "source_type": "verified",
     "description": "手掌面积大，正对镜头时视觉上过大→抢走面部注意力。转手45°让镜头看手背或侧面。手指不全并也不全张——自然微曲，像轻轻握着一颗葡萄。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},

    # ── 坐姿 ──
    {"name": "只坐椅子边缘1/3——大腿悬空保持形状", "source_type": "verified",
     "description": "坐满时大腿压扁展开显粗→坐边缘大腿悬空保持形状。腿向镜头方向延伸（不缩在椅子下）。脚踝交叉>膝盖交叉（膝盖交叉大腿展开面积太大）。从侧面拍坐姿通常比正面好看。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "commercial"},
    {"name": "地面坐姿双腿不对称——不用两条腿做一样的事", "source_type": "verified",
     "description": "地面5种基本坐姿：屈膝抱腿(温暖)/双腿侧放(优雅)/盘腿(冥想)/手撑身后仰(享受)/一侧屈一侧伸(最自然)。核心：双腿永远不对称。正面+低角度拍=亲密感，侧面拍=脊柱曲线最佳。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "park_nature"},

    # ── 表情引导 ──
    {"name": "不让被拍者'做表情'——让TA'做一件事'", "source_type": "verified",
     "description": "不要说'笑！'→假笑。说'他刚才说了个冷笑话，你在忍住不笑'→忍笑=真实微表情。不要说'自然点！'→更紧张。说'你慢慢往前走三步，中间回头看我一秒'→有任务→注意力从被拍转移→自然。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},
    {"name": "偷拍比摆拍自然——调参数法放松被拍者", "source_type": "verified",
     "description": "告诉被拍者'我先调一下参数'→他们放松→你实际上在拍。拍完一分钟后说'好了'→在对方松一口气的反应中再抓一张（通常是最好的那张）。来源：Valenzuela《拍出绝世美姿》",
     "scene_category": "urban_street"},

    # ── 眼神方向 ──
    {"name": "眼神方向决定故事感——不看镜头更自然", "source_type": "verified",
     "description": "看镜头=连接自信。看远方=叙事故事感'她在想什么'。看下方/闭眼=内省安静。看手中东西=生活感不刻意。回头看=动态邀请'跟我来'。不看镜头=观众变成路过观察者→可以安静地看→最自然。来源：Valenzuela/Barnbaum",
     "scene_category": "urban_street"},

    # ── 动态抓拍 ──
    {"name": "回头连拍——0.5-1秒黄金窗口", "source_type": "verified",
     "description": "让TA往前走→喊名字回头→连拍。回头后0.5-1秒是最佳窗口（'刚看到你'的自然状态），1秒后表情从'刚看到你'变成'在看镜头'→刻意。第一个回头帧通常最好。同时解决表情僵硬+体型显胖两个问题。来源：Valenzuela",
     "scene_category": "urban_street"},
    {"name": "走路代替站着——第2-5步是最佳抓拍窗口", "source_type": "verified",
     "description": "走路时身体在动→手在摆、头发在飘、衣服在动→生命力。第1步=启动不自然，第2-5步=进入节奏最佳，5步后开始想'还要走多远'。站着不动时身体自动紧张进入'被观察'状态。连拍选脚离地的帧>脚着地的帧。来源：Valenzuela",
     "scene_category": "urban_street"},

    # ── 摄影师导演力 ──
    {"name": "教学三明治——示范→执行→反馈", "source_type": "verified",
     "description": "第一步示范5秒：'你看我做一遍'（视觉示范比语言快3倍）。第二步执行+观察10秒。第三步反馈5秒：'对就这样...再放松一点点'（先肯定再微调，永远不在快门前说否定词）。来源：Valenzuela教学法",
     "scene_category": "urban_street"},
    {"name": "指令降级链——L1叙事→L2感受→L3物理", "source_type": "verified",
     "description": "同一姿势意图备3层指令。L1叙事：'像刚打完一局坐下来喘口气'（适合有经验者）。L2感受：'叹一口大气——叹气完那一瞬间的感觉'（适合多数人）。L3物理：'膝盖收起来手搭膝盖下巴微抬'（适合紧张者）。L1失败1次→立即降级，不在同层级重复3次。来源：Valenzuela",
     "scene_category": "urban_street"},
]


def seed_posing_techniques():
    """
    写入教材验证的拍照姿势技法（Valenzuela/Barnbaum）。
    门控：检测已有 verified 来源的姿势技法后跳过。
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT COUNT(*) FROM techniques WHERE source_type = 'verified' AND name LIKE '%坐姿%'"
        ).fetchone()[0]
        if existing > 0:
            print(f"[DB] Seed posing: {existing} verified posing techniques already exist, skipping",
                  file=sys.stderr, flush=True)
            return 0

        count_techs = 0
        count_matches = 0

        for tech in POSING_TECHNIQUES:
            row = conn.execute("""
                INSERT INTO techniques (name, source_type, description, verify_count)
                VALUES (?, ?, ?, 8)
                ON CONFLICT(name) DO UPDATE SET
                    description = CASE WHEN LENGTH(excluded.description) > LENGTH(techniques.description)
                                  THEN excluded.description ELSE techniques.description END,
                    source_type = excluded.source_type,
                    updated_at = datetime('now')
                RETURNING id
            """, (tech['name'], tech['source_type'], tech['description'])).fetchone()
            tech_id = row[0] if row else None
            if tech_id is None:
                tech_id = conn.execute("SELECT id FROM techniques WHERE name=?", (tech['name'],)).fetchone()[0]
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                count_techs += 1

            conn.execute("""
                INSERT OR IGNORE INTO scene_matches (scene_type, technique_id, match_type, scene_category)
                VALUES (?, ?, 'technique', ?)
            """, (tech['scene_category'], tech_id, tech['scene_category']))
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                count_matches += 1

        conn.commit()
        print(f"[DB] Seed posing: inserted {count_techs} techniques + {count_matches} scene_matches",
              file=sys.stderr, flush=True)
        return count_techs + count_matches
    except Exception as e:
        conn.rollback()
        print(f"[DB] Seed posing error: {e}", file=sys.stderr, flush=True)
        return 0
    finally:
        conn.close()


# ============================================================
# 每日使用限制
# ============================================================

def check_and_increment_usage(ip_address, daily_limit=10):
    """
    检查并增加每日使用计数。
    返回 (allowed: bool, used: int, limit: int)
    """
    conn = get_db()
    try:
        today = datetime.utcnow().strftime('%Y-%m-%d')
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
        today = datetime.utcnow().strftime('%Y-%m-%d')
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
# 配额申请
# ============================================================

def submit_quota_request(ip_address):
    """提交配额申请。返回 (ok, message)"""
    conn = get_db()
    try:
        today = datetime.utcnow().strftime('%Y-%m-%d')
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
        today = datetime.utcnow().strftime('%Y-%m-%d')
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
# 使用会话统计
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
# 方案反馈
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
> 更新时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC

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
