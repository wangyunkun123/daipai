#!/usr/bin/env python3
"""
带拍 - 太阳位置计算工具
计算指定时间地点的太阳方位角、高度角、黄金时刻、蓝调时刻

用法：
  python3 suncalc.py <lat> <lon> [datetime]
  python3 suncalc.py 39.9320 116.4540 "2026-07-22T15:23:00"

输出 JSON，包含：
  - 此刻太阳方位角/高度角
  - 日出/日落/黄金时刻/蓝调时刻时间窗口
  - 未来 3 小时的太阳轨迹（每 15 分钟）
  - 拍摄/用光建议
"""

import json
import sys
from datetime import datetime, timedelta
from math import sin, cos, acos, asin, atan2, degrees, radians, pi


# 简化的太阳位置算法（精度 ±0.5°，足敷摄影用途）
# 基于 NOAA Solar Calculator 公式


def julian_day(dt):
    """计算儒略日"""
    y, m, d = dt.year, dt.month, dt.day
    if m <= 2:
        y -= 1
        m += 12
    a = int(y / 100)
    b = 2 - a + int(a / 4)
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24 + b - 1524.5
    return jd


def equation_of_time(jc):
    """计算均时差（Equation of Time），单位：分钟"""
    # 太阳几何平均经度
    gml = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    # 太阳几何平均近点角
    gma = radians(357.52911 + jc * (35999.05029 - 0.0001537 * jc))
    # 地球轨道离心率
    eo = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    # 太阳中心方程
    c = sin(gma) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + sin(2 * gma) * (0.019993 - 0.000101 * jc) + sin(3 * gma) * 0.000289
    # 太阳真实经度
    stl = radians(gml + c)
    # 太阳赤经（简化）
    ra = degrees(stl)  # 近似——完整版需 atan2(cos(ε)sin(stl), cos(stl))
    # EoT = 4 * (gml - 2.5*sin(2*gml)... 简化公式
    eot = 4 * (gml - ra)  # 分钟
    # 使用更准确的简化公式修正
    b = radians(360 / 365 * (jc * 36525 - 81))
    eot = 9.87 * sin(2 * b) - 7.53 * cos(b) - 1.5 * sin(b)
    return eot  # 分钟


def auto_utc_offset(lon):
    """根据经度自动推断时区偏移"""
    # 中国全境使用 UTC+8
    if 73 <= lon <= 135:
        return 8
    # 通用推断
    return round(lon / 15)


def sun_position(lat, lon, dt, utc_offset=None):
    """计算太阳位置（方位角、高度角）

    参数：
      lat, lon: 纬度和经度（十进制度数）
      dt: 当地时间（datetime 对象，naive = 本地时间）
      utc_offset: 时区偏移小时数。None=根据经度自动推断

    返回：
      {"azimuth": 方位角°, "altitude": 高度角°, "declination": 赤纬°}
    """
    if utc_offset is None:
        utc_offset = auto_utc_offset(lon)

    # 将本地时间转为 UTC
    from datetime import timezone, timedelta
    dt_utc = dt.replace(tzinfo=timezone(timedelta(hours=utc_offset))).astimezone(timezone.utc)
    dt_utc = dt_utc.replace(tzinfo=None)

    jd = julian_day(dt_utc)
    jc = (jd - 2451545.0) / 36525.0

    # 太阳几何平均经度
    gml = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    # 太阳几何平均近点角
    gma = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    # 太阳中心方程
    c = sin(radians(gma)) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + \
        sin(radians(2 * gma)) * (0.019993 - 0.000101 * jc) + \
        sin(radians(3 * gma)) * 0.000289
    # 太阳真实经度
    stl = gml + c
    # 太阳赤纬
    dec = degrees(asin(sin(radians(23.44)) * sin(radians(stl))))

    # === 时角计算（修复） ===
    # 标准子午线：时区中心经线
    std_meridian = utc_offset * 15.0
    # 均时差（分钟）
    eot = equation_of_time(jc)
    # 时间修正（小时）：经度差 + 均时差
    time_correction = (std_meridian - lon) / 15.0 + eot / 60.0
    # 真太阳时
    solar_time = dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + time_correction
    # 时角：真太阳时离正午的角度（15°/小时）
    ha_deg = (solar_time - 12.0) * 15.0

    lat_rad = radians(lat)
    dec_rad = radians(dec)

    # 太阳高度角
    # sin(alt) = sin(lat)sin(dec) + cos(lat)cos(dec)cos(ha)
    alt_rad = asin(
        sin(lat_rad) * sin(dec_rad) +
        cos(lat_rad) * cos(dec_rad) * cos(radians(ha_deg))
    )
    altitude = degrees(alt_rad)

    # 太阳方位角
    # cos(az) = (sin(dec) - sin(lat)sin(alt)) / (cos(lat)cos(alt))
    az_num = sin(dec_rad) - sin(lat_rad) * sin(alt_rad)
    az_den = cos(lat_rad) * cos(alt_rad)
    if abs(az_den) < 1e-10:
        azimuth = 0.0
    else:
        az_val = acos(max(-1.0, min(1.0, az_num / az_den)))
        azimuth = degrees(az_val)
        # 上午（时角 < 0）方位角从北顺时针；下午（时角 > 0）取 360-az
        if ha_deg > 0:
            azimuth = 360.0 - azimuth

    return {
        "azimuth": round(azimuth, 1),
        "altitude": round(altitude, 1),
        "declination": round(dec, 2)
    }


def golden_hour(lat, lon, dt, utc_offset=None):
    """计算黄金时刻和蓝调时刻

    基于太阳高度角：日出日落=0°，民用晨昏=-6°
    """
    if utc_offset is None:
        utc_offset = auto_utc_offset(lon)

    # 使用 UTC 正午计算太阳赤纬
    from datetime import timezone, timedelta as dt_timedelta
    local_noon = dt.replace(hour=12, minute=0, second=0, microsecond=0)
    dt_utc = local_noon.replace(tzinfo=timezone(dt_timedelta(hours=utc_offset))).astimezone(timezone.utc)
    dt_utc = dt_utc.replace(tzinfo=None)

    jd = julian_day(dt_utc)
    jc = (jd - 2451545.0) / 36525.0

    gml = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    gma = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    c = sin(radians(gma)) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + \
        sin(radians(2 * gma)) * (0.019993 - 0.000101 * jc) + \
        sin(radians(3 * gma)) * 0.000289
    stl = gml + c
    dec = degrees(asin(sin(radians(23.44)) * sin(radians(stl))))

    lat_rad = radians(lat)
    dec_rad = radians(dec)

    # 太阳高度角为 0 时的时角（考虑大气折射 ~0.833°）
    ha0_num = sin(radians(-0.833)) - sin(lat_rad) * sin(dec_rad)
    ha0_den = cos(lat_rad) * cos(dec_rad)
    if abs(ha0_den) < 0.001:
        return None  # 极昼/极夜
    ha0 = degrees(acos(max(-1.0, min(1.0, ha0_num / ha0_den))))

    # 均时差修正
    eot = equation_of_time(jc)  # 分钟
    # 标准子午线修正（小时）
    std_meridian = utc_offset * 15.0
    lon_correction = (std_meridian - lon) / 15.0

    # 太阳正午（本地时间）
    solar_noon = 12.0 + lon_correction + eot / 60.0

    # 日出日落（本地时间，小时制）
    sunrise_local = solar_noon - ha0 / 15.0
    sunset_local = solar_noon + ha0 / 15.0

    # 转换为 datetime
    def hours_to_time(h):
        h = h % 24
        hh = int(h)
        mm = int((h - hh) * 60)
        return dt.replace(hour=max(0, min(23, hh)), minute=max(0, min(59, mm)), second=0)

    sunrise = hours_to_time(sunrise_local)
    sunset = hours_to_time(sunset_local)

    # 黄金时刻（日落前 30 分钟 - 日落后 15 分钟）
    golden_start = sunset - timedelta(minutes=30)
    golden_end = sunset + timedelta(minutes=15)

    # 蓝调时刻（日落后 15 分钟 - 日落后 30 分钟）
    blue_start = sunset + timedelta(minutes=15)
    blue_end = sunset + timedelta(minutes=30)

    return {
        "sunrise": sunrise.strftime('%H:%M'),
        "sunset": sunset.strftime('%H:%M'),
        "golden_hour": f"{golden_start.strftime('%H:%M')} - {golden_end.strftime('%H:%M')}",
        "golden_start": golden_start.strftime('%H:%M'),
        "golden_end": golden_end.strftime('%H:%M'),
        "blue_hour": f"{blue_start.strftime('%H:%M')} - {blue_end.strftime('%H:%M')}",
        "blue_start": blue_start.strftime('%H:%M'),
        "blue_end": blue_end.strftime('%H:%M'),
    }


def trajectory(lat, lon, dt, utc_offset=None):
    """计算未来 3 小时太阳轨迹（每 15 分钟一个点）"""
    if utc_offset is None:
        utc_offset = auto_utc_offset(lon)
    points = []
    for i in range(13):  # 0, 15, 30, ... 180 分钟
        t = dt + timedelta(minutes=i * 15)
        pos = sun_position(lat, lon, t, utc_offset)
        points.append({
            "time": t.strftime('%H:%M'),
            "altitude": pos['altitude'],
            "azimuth": pos['azimuth'],
        })
    return points


def describe_light(altitude, azimuth):
    """用自然语言描述当前光线状态"""
    desc = []

    # 高度角描述
    if altitude < 0:
        desc.append("太阳在地平线下——夜间或蓝调时刻前")
    elif altitude < 6:
        desc.append("黄金时刻或蓝调时刻——光线最柔美的时间窗口")
    elif altitude < 20:
        desc.append("低角度暖光——光线柔和偏暖、影子很长")
    elif altitude < 45:
        desc.append("中角度——自然光、适合大多数场景")
    elif altitude < 70:
        desc.append("高角度——光线偏硬、阴影较短")
    else:
        desc.append("正午顶光——眼窝和鼻子下方会有深阴影，建议移到阴影中")

    # 方位角描述
    if 0 <= azimuth < 45:
        desc.append("太阳在北方（少见——如在南半球）")
    elif 45 <= azimuth < 135:
        desc.append("太阳在东方——上午光线")
    elif 135 <= azimuth < 225:
        desc.append("太阳在南方——正午前后")
    elif 225 <= azimuth < 315:
        desc.append("太阳在西方——下午光线、即将日落")
    else:
        desc.append("太阳在北方——傍晚")

    return "；".join(desc)


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "用法: python3 suncalc.py <lat> <lon> [datetime]"}, ensure_ascii=False))
        sys.exit(1)

    lat = float(sys.argv[1])
    lon = float(sys.argv[2])

    if len(sys.argv) >= 4:
        try:
            dt = datetime.fromisoformat(sys.argv[3])
        except ValueError:
            dt = datetime.strptime(sys.argv[3], '%Y:%m:%d %H:%M:%S')
    else:
        dt = datetime.now()

    utc_offset = auto_utc_offset(lon)

    pos = sun_position(lat, lon, dt, utc_offset)
    gh = golden_hour(lat, lon, dt, utc_offset)
    traj = trajectory(lat, lon, dt, utc_offset)
    light_desc = describe_light(pos['altitude'], pos['azimuth'])

    # 未来 1 小时光线变化趋势
    future = sun_position(lat, lon, dt + timedelta(hours=1), utc_offset)
    alt_change = future['altitude'] - pos['altitude']
    if alt_change > 1:
        trend = "上升（→光线变硬/影子变短）"
    elif alt_change < -1:
        trend = "下降（→光线变软变暖/影子变长/接近黄金时刻）"
    else:
        trend = "稳定"

    output = {
        "now": {
            "time": dt.strftime('%Y-%m-%d %H:%M'),
            "sun_azimuth": pos['azimuth'],
            "sun_altitude": pos['altitude'],
            "description": light_desc,
        },
        "events": gh,
        "next_hour_trend": trend,
        "trajectory_3h": traj,
        "advice": {
            "now": "可直接拍摄" if pos['altitude'] > 0 else "需要夜景模式或补光",
            "best_window": gh['golden_hour'] if gh else "未知",
            "note": "黄金时刻光暖/软/有方向性——适合所有风格。蓝调时刻适合电影感/极简/Lofi直闪",
        }
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
