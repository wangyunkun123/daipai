#!/usr/bin/env python3
"""
直出相机 - EXIF 提取工具
从照片中提取 GPS、拍摄时间、镜头朝向、设备型号

用法：
  python3 exif-extract.py <image_path>
输出 JSON：
  {
    "gps": {"lat": 39.9320, "lon": 116.4540},
    "datetime": "2026-07-22T15:23:00",
    "orientation": 267.0,  // 镜头朝向角度（如有）
    "device": "iPhone 17 Pro",
    "has_gps": true
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
        # 正则提取 度/分/秒 和可能的方向字母
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

            # 方向判断：优先用嵌入的方向字母，其次用 ref 参数
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
             '-GPSLatitude', '-GPSLatitudeRef',
             '-GPSLongitude', '-GPSLongitudeRef',
             '-GPSImgDirection', '-GPSImgDirectionRef',
             '-DateTimeOriginal', '-CreateDate',
             '-Make', '-Model',
             '-Orientation',
             '-ImageWidth', '-ImageHeight',
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
    output = {"gps": None, "datetime": None, "orientation": None, "device": None, "has_gps": False}

    # GPS
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

    # 拍摄时间
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

    # 镜头朝向
    direction = raw.get('GPSImgDirection')
    if direction:
        try:
            output['orientation'] = float(direction)
        except Exception:
            pass

    # 设备型号
    make = raw.get('Make', '')
    model = raw.get('Model', '')
    if make and model:
        output['device'] = f"{make} {model}".strip()
    elif model:
        output['device'] = model.strip()

    # 图片尺寸
    w = raw.get('ImageWidth')
    h = raw.get('ImageHeight')
    if w and h:
        output['dimensions'] = f"{w}x{h}"

    return output


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "用法: python3 exif-extract.py <image_path>"}, ensure_ascii=False))
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
