#!/usr/bin/env python3
"""
带拍 - 光线时域调度引擎 v3.7
综合太阳位置 + 地点信息 + 天气（可选）→ 输出未来几小时拍摄时间线

用法：
  python3 light-schedule.py '<exif_json>' '<sun_json>' '<location_json>' [weather_json]

  通常由 SKILL.md 的工作流自动调用，接收前序脚本的 JSON 输出。
  也可以手动传入 JSON 字符串测试。

输出：
  JSON 拍摄时间线——什么时间适合拍什么风格，每个时间窗口的可执行性
"""

import json
import sys
from datetime import datetime, timedelta


def parse_input(exif_str, sun_str, loc_str):
    """解析前序脚本的输出"""
    exif = json.loads(exif_str) if isinstance(exif_str, str) else exif_str
    sun = json.loads(sun_str) if isinstance(sun_str, str) else sun_str
    loc = json.loads(loc_str) if isinstance(loc_str, str) else loc_str
    return exif, sun, loc


def determine_light_quality(altitude, haze=0):
    """根据太阳高度角判断光质"""
    if altitude < 0:
        return "无日光", "需要夜景模式或补光"
    elif altitude < 6:
        return "极致软光", "黄金/蓝调时刻——所有风格都可用，光暖+软+有方向性"
    elif altitude < 20:
        return "软光偏暖", "低角度暖光——长阴影、柔和过渡。人像/静物最佳"
    elif altitude < 45:
        return "中硬光", "自然光——适合大多数场景。略有硬度但不刺眼"
    elif altitude < 70:
        return "硬光", "偏硬——阴影明显。适合纪实/Grunge。柔美人像需移阴影中"
    else:
        return "顶光硬光", "正午顶光——眼窝阴影。移阴影中或低头/侧头。何藩式光影几何可用"


def build_schedule(exif, sun, loc):
    """构建拍摄时间线"""
    now = datetime.now()
    trajectory = sun.get('trajectory_3h', [])
    events = sun.get('events', {})
    indoor = loc.get('indoor_likely', False)
    place_type = loc.get('type', '未知')

    # 为每个 15 分钟时间点匹配可用风格
    style_by_light = {
        "极致软光": {
            "all": ["日系清新", "梦幻柔美", "电影感", "胶片复古", "安静真实", "极简高级", "微观微距"],
            "best": "所有风格可用——黄金时刻是全天最佳拍摄窗口",
            "exec": "🟢"
        },
        "软光偏暖": {
            "all": ["日系清新", "安静真实", "胶片复古", "极简高级", "梦幻柔美", "微观微距"],
            "best": "人像/静物——低角度暖光让皮肤和材质都好看",
            "exec": "🟢"
        },
        "中硬光": {
            "all": ["安静真实", "极简高级", "胶片复古", "微观微距", "纪实粗粝", "电影感"],
            "best": "自然光通用窗口——大多数题材可拍",
            "exec": "🟢"
        },
        "硬光": {
            "all": ["纪实粗粝", "Grunge", "极简高级", "Lofi直闪", "杂志时尚"],
            "restricted": ["日系清新（需移阴影）", "梦幻柔美（不适）", "安静真实（光线偏硬但可通过构图补偿）"],
            "best": "硬光+侧光=纹理质感最佳",
            "exec": "🟡"
        },
        "顶光硬光": {
            "all": ["极简高级", "Grunge", "纪实粗粝", "Lofi直闪", "黑白"],
            "restricted": ["日系清新（不可用）", "梦幻柔美（不可用）", "安静真实（低头/侧头可用）"],
            "best": "移到阴影中等软光（阴影中 = 人工软光窗口）；或拍何藩式光影几何",
            "exec": "🟡"
        },
        "无日光": {
            "all": ["Lofi直闪", "电影感", "纪实粗粝", "Grunge"],
            "restricted": ["日系清新", "极简高级", "安静真实（需补光或夜景模式）"],
            "best": "蓝调时刻/夜景——人造光源成为主角",
            "exec": "🟠"
        },
    }

    schedule = []

    for point in trajectory:
        alt = point['altitude']
        azi = point['azimuth']
        quality, desc = determine_light_quality(alt)

        styles = style_by_light.get(quality, style_by_light["中硬光"])

        entry = {
            "time": point['time'],
            "sun_alt": alt,
            "sun_azi": azi,
            "light_quality": quality,
            "light_desc": desc,
            "available_styles": styles.get("all", []),
            "restricted_styles": styles.get("restricted", []),
            "tip": styles.get("best", ""),
            "executability": styles.get("exec", "🟢"),
        }

        # 室内调整
        if indoor and alt > 0:
            entry["indoor_note"] = "室内——光线通过窗户。站到窗边即可获得此光线方向"

        schedule.append(entry)

    # 特殊时间窗口标记
    golden_start = events.get('golden_start', '')
    golden_end = events.get('golden_end', '')
    blue_start = events.get('blue_start', '')
    blue_end = events.get('blue_end', '')

    # 找出最佳拍摄窗口
    best_windows = []
    for entry in schedule:
        time_str = entry['time']
        if golden_start <= time_str <= golden_end:
            best_windows.append(f"✨ 黄金时刻 {time_str} —— {entry['light_desc']}")
        elif blue_start <= time_str <= blue_end:
            best_windows.append(f"💙 蓝调时刻 {time_str} —— {entry['light_desc']}")

    return {
        "location": {
            "name": loc.get('name', '未知'),
            "type": place_type,
            "city": loc.get('city', ''),
            "indoor": indoor,
        },
        "current_light": schedule[0] if schedule else None,
        "best_windows": best_windows[:5],
        "events": {
            "golden_hour": events.get('golden_hour', '未知'),
            "blue_hour": events.get('blue_hour', '未知'),
        },
        "timeline": schedule,
        "summary": generate_summary(schedule, indoor, place_type),
    }


def generate_summary(schedule, indoor, place_type):
    """生成一句话总结"""
    if not schedule:
        return "光线数据不可用"

    now_light = schedule[0]['light_quality']
    now_alt = schedule[0]['sun_alt']

    # 找未来最好的光线窗口
    best = None
    for s in schedule:
        if s['light_quality'] in ('极致软光', '软光偏暖'):
            best = s
            break

    summary = f"当前：{now_light}（太阳高度 {now_alt}°）"
    if best:
        summary += f"。{best['time']} 光线变软变暖——最佳拍摄窗口"
    if indoor:
        summary += "。室内场景：站到窗边可利用此光线方向"
    summary += f"。场所类型：{place_type}"

    return summary


def main():
    if len(sys.argv) < 4:
        print(json.dumps({
            "error": "用法: python3 light-schedule.py '<exif_json>' '<sun_json>' '<location_json>'",
            "note": "exif_json 来自 exif-extract.py 输出，sun_json 来自 suncalc.py 输出，location_json 来自 reverse-geocode.py 输出"
        }, ensure_ascii=False))
        sys.exit(1)

    try:
        exif, sun, loc = parse_input(sys.argv[1], sys.argv[2], sys.argv[3])
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON 解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    result = build_schedule(exif, sun, loc)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
