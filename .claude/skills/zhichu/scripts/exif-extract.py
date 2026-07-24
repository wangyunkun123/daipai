#!/usr/bin/env python3
"""
直出相机 - EXIF 提取工具 v2.1
从照片中提取 GPS、拍摄时间、镜头朝向、设备型号、拍摄参数

用法：
  python3 exif-extract.py <image_path>
输出 JSON：
  {
    "gps": {"lat": 39.9320, "lon": 116.4540},
    "datetime": "2026-07-22T15:23:00",
    "orientation": 267.0,          // 镜头朝向角度（如有）
    "device": "iPhone 17 Pro",
    "has_gps": true,
    "shooting_params": {            // 🆕 v2.1 拍摄参数
      "focal_length_35mm": 24,      // 35mm 等效焦距
      "iso": 200,                   // 感光度
      "exposure_time": "1/120",     // 快门速度
      "aperture": 1.8,              // 光圈值
      "flash": false,               // 闪光灯是否触发
      "brightness": 8.5,            // 测光亮度
      "white_balance": "Auto",      // 白平衡
      "exposure_program": "Auto",   // 曝光程序
      "metering_mode": "Multi-segment", // 测光模式
      "image_orientation": "Landscape"  // 横拍/竖拍
    },
    "dimensions": "4032x3024"
  }
"""

import json
import sys
import subprocess
from datetime import datetime


def dms_to_decimal(dms_str, ref):
    """将 EXIF 的度分秒字符串转换为十进制

    支持两种格式：
    - 逗号分隔: "40,52,34.05" + ref="N"
    - exiftool JSON 格式: "40 deg 52' 34.05\\" N"
    - exiftool 有时直接输出十进制数字: "40.876125"
    """
    import re

    try:
        s = str(dms_str).strip()

        # 格式 1: 纯数字（已经是十进制）
        try:
            val = float(s)
            if ref and str(ref).strip() in ('S', 'W'):
                val = -val
            return round(val, 6)
        except ValueError:
            pass

        # 格式 2: exiftool JSON 格式 "40 deg 52' 34.05\" N"
        match = re.match(
            r"([\d.]+)\s*deg\s*([\d.]+)'?\s*([\d.]+)\"?\s*([NSEWnsew]?)",
            s
        )
        if match:
            deg = float(match.group(1))
            min_val = float(match.group(2))
            sec = float(match.group(3))
            embedded_ref = match.group(4).upper() if match.group(4) else ''

            decimal = deg + min_val / 60 + sec / 3600

            direction = embedded_ref if embedded_ref else str(ref).strip().upper()
            if direction in ('S', 'W'):
                decimal = -decimal

            return round(decimal, 6)

        # 格式 3: 逗号分隔 "40,52,34.05"
        parts = s.split(',')
        if len(parts) == 3:
            deg = float(parts[0].strip())
            min_val = float(parts[1].strip())
            sec = float(parts[2].strip())
            decimal = deg + min_val / 60 + sec / 3600
            if ref and str(ref).strip() in ('S', 'W'):
                decimal = -decimal
            return round(decimal, 6)

        return None
    except Exception:
        return None


def extract_exif(image_path):
    """使用 exiftool 提取 EXIF 数据"""
    try:
        result = subprocess.run(
            ['exiftool', '-j',
             # GPS
             '-GPSLatitude', '-GPSLatitudeRef',
             '-GPSLongitude', '-GPSLongitudeRef',
             '-GPSImgDirection', '-GPSImgDirectionRef',
             # 时间
             '-DateTimeOriginal', '-CreateDate',
             # 设备
             '-Make', '-Model',
             # 基础图片信息
             '-Orientation',
             '-ImageWidth', '-ImageHeight',
             # 🆕 v2.1 拍摄参数
             '-FocalLength', '-FocalLengthIn35mmFormat',
             '-ISO',
             '-ExposureTime', '-ShutterSpeedValue',
             '-FNumber', '-ApertureValue',
             '-Flash',
             '-BrightnessValue',
             '-WhiteBalance',
             '-ExposureProgram',
             '-MeteringMode',
             '-LensModel', '-LensID',
             '-ExposureCompensation',
             '-SceneCaptureType',
             # 🆕 v2.1 额外 GPS 精度
             '-GPSAltitude', '-GPSDOP',
             '-GPSDateStamp', '-GPSTimeStamp',
             image_path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"error": f"exiftool 错误: {result.stderr.strip()}"}
        data = json.loads(result.stdout)[0]
        return data
    except FileNotFoundError:
        return {"error": "exiftool 未安装。请运行: brew install exiftool"}
    except json.JSONDecodeError:
        return {"error": f"exiftool 输出解析失败: {result.stdout[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def parse_exif(raw):
    """解析 exiftool 输出为标准化 JSON"""
    output = {
        "gps": None, "datetime": None, "orientation": None,
        "device": None, "has_gps": False,
        "shooting_params": {}  # 🆕 v2.1
    }

    # ========== GPS ==========
    lat = raw.get('GPSLatitude')
    lat_ref = raw.get('GPSLatitudeRef')
    lon = raw.get('GPSLongitude')
    lon_ref = raw.get('GPSLongitudeRef')

    if lat and lon:
        lat_dec = dms_to_decimal(str(lat), lat_ref or 'N')
        lon_dec = dms_to_decimal(str(lon), lon_ref or 'E')
        if lat_dec is not None and lon_dec is not None:
            output['gps'] = {"lat": lat_dec, "lon": lon_dec}
            output['has_gps'] = True

    # 🆕 GPS 精度
    dop = raw.get('GPSDOP')
    if dop is not None:
        output['gps_accuracy'] = float(dop) if dop else None

    # ========== 拍摄时间 ==========
    dt = raw.get('DateTimeOriginal') or raw.get('CreateDate')
    if dt:
        try:
            for fmt in ('%Y:%m:%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y:%m:%d %H:%M:%S%z'):
                try:
                    parsed = datetime.strptime(str(dt).split('+')[0].split('-')[0].strip(), fmt)
                    output['datetime'] = parsed.isoformat()
                    break
                except ValueError:
                    continue
        except Exception:
            output['datetime'] = str(dt)

    # ========== 镜头朝向 ==========
    direction = raw.get('GPSImgDirection')
    if direction:
        try:
            output['orientation'] = float(direction)
        except Exception:
            pass

    # ========== 设备型号 ==========
    make = raw.get('Make', '')
    model = raw.get('Model', '')
    if make and model:
        output['device'] = f"{make} {model}".strip()
    elif model:
        output['device'] = model.strip()

    # ========== 🆕 v2.1 拍摄参数 ==========
    sp = output['shooting_params']

    # 焦距（35mm 等效优先）
    focal_35 = raw.get('FocalLengthIn35mmFormat')
    focal_raw = raw.get('FocalLength')
    if focal_35:
        try:
            sp['focal_length_35mm'] = round(float(focal_35))
        except Exception:
            sp['focal_length_raw'] = str(focal_raw) if focal_raw else None
    elif focal_raw:
        sp['focal_length_raw'] = str(focal_raw)

    # ISO（光线条件的硬证据——比 AI 视觉识别更客观）
    iso = raw.get('ISO')
    if iso is not None:
        try:
            sp['iso'] = int(float(iso))
        except Exception:
            sp['iso'] = str(iso)

    # 快门速度（手持稳定性 + 运动模糊预判）
    exp_time = raw.get('ExposureTime')
    if exp_time is not None:
        try:
            et = float(exp_time)
            if et >= 1:
                sp['exposure_time'] = f"{et:.0f}s"
            else:
                sp['exposure_time'] = f"1/{1/et:.0f}s"
            sp['exposure_time_sec'] = round(et, 5)
        except Exception:
            sp['exposure_time'] = str(exp_time)

    # 光圈值
    fnum = raw.get('FNumber') or raw.get('ApertureValue')
    if fnum is not None:
        try:
            sp['aperture'] = round(float(fnum), 1)
        except Exception:
            pass

    # 🚨 闪光灯（关键——如果触发，自然光分析需要修正）
    flash = raw.get('Flash')
    if flash is not None:
        # exiftool 可能返回数字字符串，也可能返回 "Off, Did not fire" 等文本
        try:
            flash_val = int(float(flash))
        except (ValueError, TypeError):
            flash_str = str(flash).lower()
            flash_fired = 'fired' in flash_str and 'did not fire' not in flash_str and 'off' not in flash_str
            flash_val = 1 if flash_fired else 0
        else:
            # Flash 值说明（EXIF 标准）：
            # 0 = 未触发, 1 = 触发, 5 = 触发但未检测到返回光,
            # 9 = 强制触发, 13 = 强制触发+未检测到返回光,
            # 16 = 关闭, 24 = 自动未触发, 25 = 自动触发,
            # 其他 = 触发（含防红眼等变体）
            flash_fired = bool(flash_val & 1)  # bit 0 = 是否触发
        sp['flash'] = {
            "fired": flash_fired,
            "raw_value": str(flash),
            "note": "⚠️ 闪光灯触发——光质分析需考虑人工补光" if flash_fired else None
        }

    # 测光亮度（相机内置测光表读数——比 AI 视觉更客观）
    brightness = raw.get('BrightnessValue')
    if brightness is not None:
        try:
            sp['brightness'] = round(float(brightness), 1)
        except Exception:
            pass

    # 白平衡（用户意图信号——Auto vs Manual 暗示用户是否在主动控制色彩）
    wb = raw.get('WhiteBalance')
    if wb is not None:
        wb_map = {0: "Auto", 1: "Manual"}
        try:
            wb_val = int(float(wb))
            sp['white_balance'] = wb_map.get(wb_val, str(wb_val))
        except Exception:
            sp['white_balance'] = str(wb)

    # 曝光程序（用户水平信号——Auto/P/A/S/M）
    exp_prog = raw.get('ExposureProgram')
    if exp_prog is not None:
        prog_map = {
            0: "Not Defined", 1: "Manual", 2: "Program AE",
            3: "Aperture-priority AE", 4: "Shutter-speed priority AE",
            5: "Creative (Slow)", 6: "Action (High-speed)",
            7: "Portrait", 8: "Landscape", 9: "Bulb"
        }
        try:
            sp['exposure_program'] = prog_map.get(int(float(exp_prog)), str(exp_prog))
        except Exception:
            sp['exposure_program'] = str(exp_prog)

    # 测光模式
    metering = raw.get('MeteringMode')
    if metering is not None:
        meter_map = {
            0: "Unknown", 1: "Average", 2: "Center-weighted average",
            3: "Spot", 4: "Multi-spot", 5: "Multi-segment",
            6: "Partial", 255: "Other"
        }
        try:
            sp['metering_mode'] = meter_map.get(int(float(metering)), str(metering))
        except Exception:
            sp['metering_mode'] = str(metering)

    # 🆕 镜头型号
    lens = raw.get('LensModel') or raw.get('LensID')
    if lens:
        sp['lens_model'] = str(lens).strip()

    # 🆕 曝光补偿
    exp_comp = raw.get('ExposureCompensation')
    if exp_comp is not None:
        try:
            sp['exposure_compensation'] = float(exp_comp)
        except Exception:
            pass

    # 🆕 横拍/竖拍判断
    orientation_tag = raw.get('Orientation')
    if orientation_tag is not None:
        try:
            ot = int(float(orientation_tag))
            if ot in (1, 2):
                sp['image_orientation'] = "Landscape"  # 横拍
            elif ot in (6, 8):
                sp['image_orientation'] = "Portrait"   # 竖拍
        except Exception:
            pass

    # ========== 图片尺寸 ==========
    w = raw.get('ImageWidth')
    h = raw.get('ImageHeight')
    if w and h:
        output['dimensions'] = f"{w}x{h}"

    # ========== 🆕 拍摄参数摘要 ==========
    sp = output['shooting_params']
    if sp:
        notes = []

        # 低光信号：ISO >= 800
        iso_val = sp.get('iso')
        if isinstance(iso_val, int) and iso_val >= 800:
            notes.append(f"ISO {iso_val} → 低光环境，需注意噪点和稳定性")

        # 慢快门信号：< 1/60s
        et_sec = sp.get('exposure_time_sec')
        if et_sec and et_sec < 1/60:
            notes.append(f"快门 {sp.get('exposure_time')} → 建议稳定支撑或利用防抖")

        # 闪光灯信号
        flash_info = sp.get('flash', {})
        if flash_info.get('fired'):
            notes.append(flash_info.get('note', ''))

        # 白平衡信号
        if sp.get('white_balance') == 'Manual':
            notes.append("手动白平衡——用户在主动控制色彩")

        if notes:
            sp['_analysis_notes'] = notes

    return output


def main():
    if len(sys.argv) < 2:
        print(json.dumps(
            {"error": "用法: python3 exif-extract.py <image_path>"},
            ensure_ascii=False
        ))
        sys.exit(1)

    image_path = sys.argv[1]
    raw = extract_exif(image_path)
    if 'error' in raw:
        print(json.dumps(raw, ensure_ascii=False))
        sys.exit(1)

    parsed = parse_exif(raw)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
