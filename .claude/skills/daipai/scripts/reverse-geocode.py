#!/usr/bin/env python3
"""
带拍 - 反向地理编码工具 v3.7
将 GPS 坐标转换为人类可读的地点名称

用法：
  python3 reverse-geocode.py <lat> <lon>
输出 JSON：
  {
    "name": "三里屯太古里",
    "type": "商业区",
    "city": "北京",
    "indoor_likely": false,
    "landmark": true
  }

注意：
  完整版需要接入高德/百度地图 API。当前版本提供基础框架——
  通过 Apple MapKit（macOS 原生）获取地点信息。
  如需精确 POI 信息，可替换为高德 API 调用。
"""

import json
import sys
import subprocess
import urllib.request
import urllib.parse


def apple_maps_lookup(lat, lon):
    """
    使用 macOS 原生 CoreLocation 命令获取地点信息
    需要先编译一个简单的 CLI 工具，或使用快捷指令
    备用方案：MapKit JS 或高德 API
    """
    # 尝试使用 shortcuts 命令调用 Apple Maps 获取位置
    # 这是 macOS 特有的临时方案
    try:
        # 使用 Apple 的 reverse geocoding（无官方 CLI）
        # 备用：使用 MapKit JS API
        url = f"https://maps-api.apple.com/v1/search?q={lat},{lon}&limit=1"
        # Apple Maps 需要 JWT 认证——改用免费方案
        pass
    except Exception:
        pass

    return None


def nominatim_lookup(lat, lon):
    """
    使用 OpenStreetMap Nominatim 免费 API
    注意：有频率限制（1 req/s），需要 User-Agent
    """
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1&accept-language=zh"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'GuidPic/1.0 (photography-app; contact@guidepic.com)'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data
    except Exception as e:
        return {"error": str(e)}


def parse_location(osm_data):
    """解析 Nominatim 结果为标准格式"""
    if 'error' in osm_data:
        return osm_data

    address = osm_data.get('address', {})
    name = osm_data.get('name', '') or osm_data.get('display_name', '').split(',')[0].strip()

    # 判断场所类型
    osm_type = osm_data.get('type', '')
    category = osm_data.get('category', '')
    place_type = '未知'

    type_map = {
        'cafe': '咖啡馆', 'restaurant': '餐厅', 'bar': '酒吧',
        'hotel': '酒店', 'park': '公园', 'museum': '博物馆',
        'library': '图书馆', 'shop': '商店', 'mall': '商场',
        'office': '办公楼', 'residential': '住宅区', 'house': '住宅',
        'apartments': '公寓', 'university': '大学', 'school': '学校',
        'hospital': '医院', 'station': '车站', 'airport': '机场',
        'church': '教堂', 'temple': '寺庙',
    }

    for key, val in type_map.items():
        if key in str(osm_type).lower() or key in str(category).lower():
            place_type = val
            break
        if key in str(address).lower():
            place_type = val
            break

    if place_type == '未知' and 'road' in address:
        place_type = '街道'
    if place_type == '未知' and 'building' in address:
        place_type = '建筑'

    # 室内/室外判断
    indoor_types = ['咖啡馆', '餐厅', '酒吧', '酒店', '博物馆', '图书馆', '商店', '商场', '办公楼', '住宅', '公寓', '医院', '学校']
    indoor_likely = place_type in indoor_types

    return {
        "name": name,
        "type": place_type,
        "city": address.get('city', address.get('town', address.get('county', ''))),
        "district": address.get('suburb', address.get('district', '')),
        "indoor_likely": indoor_likely,
        "landmark": osm_data.get('addresstype', '') in ('tourism', 'amenity', 'historic'),
        "display_name": osm_data.get('display_name', ''),
    }


def main():
    if len(sys.argv) < 3:
        # 无参数模式：读取 stdin 的 JSON（来自 exif-extract.py 的管道输入）
        print(json.dumps({"error": "用法: python3 reverse-geocode.py <lat> <lon>"}, ensure_ascii=False))
        sys.exit(1)

    lat = float(sys.argv[1])
    lon = float(sys.argv[2])

    osm_data = nominatim_lookup(lat, lon)
    result = parse_location(osm_data)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
