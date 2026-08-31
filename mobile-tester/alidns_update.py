"""阿里云云解析 A 记录切换工具（guidepic.cn → 大陆服务器）
用法: AK_ID=... AK_SECRET=... python3 alidns_update.py
将 guidepic.cn / www.guidepic.cn 的 A 记录指向 123.56.229.172。
"""
import os
import sys

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkalidns.request.v20150109 import (
    DescribeDomainRecordsRequest,
    UpdateDomainRecordRequest,
)

AK_ID = os.environ.get("AK_ID", "")
AK_SECRET = os.environ.get("AK_SECRET", "")
REGION = "cn-hangzhou"
DOMAIN = "guidepic.cn"
TARGET_IP = "123.56.229.172"  # 大陆服务器


def main():
    if not AK_ID or not AK_SECRET:
        sys.exit("缺少 AK_ID / AK_SECRET 环境变量")
    client = AcsClient(AK_ID, AK_SECRET, REGION)

    # 1. 列出当前记录
    req = DescribeDomainRecordsRequest.DescribeDomainRecordsRequest()
    req.set_DomainName(DOMAIN)
    try:
        resp = client.do_action_with_exception(req)
    except (ClientException, ServerException) as e:
        sys.exit(f"查询记录失败（检查 AK 权限/域名归属）: {e}")
    import json
    data = json.loads(resp)
    records = data.get("DomainRecords", {}).get("Record", [])
    a_records = [r for r in records if r.get("Type") == "A"]
    print(f"{DOMAIN} 当前 A 记录:")
    for r in a_records:
        print(f"  RR={r.get('RR'):<12} 值={r.get('Value'):<18} RecordId={r.get('RecordId')} 状态={r.get('Status')}")

    # 2. 更新 @ 和 www
    targets = {r.get("RecordId"): r for r in a_records if r.get("RR") in ("@", "www")}
    if not targets:
        sys.exit("未找到 @ 或 www 的 A 记录，请检查")
    for rid, r in targets.items():
        if r.get("Value") == TARGET_IP:
            print(f"  RR={r.get('RR')} 已是指向 {TARGET_IP}，跳过")
            continue
        upd = UpdateDomainRecordRequest.UpdateDomainRecordRequest()
        upd.set_RecordId(rid)
        upd.set_RR(r.get("RR"))
        upd.set_Type("A")
        upd.set_Value(TARGET_IP)
        upd.set_TTL(int(r.get("TTL", 600)))
        try:
            client.do_action_with_exception(upd)
            print(f"  ✅ RR={r.get('RR')}: {r.get('Value')} → {TARGET_IP}")
        except (ClientException, ServerException) as e:
            print(f"  ❌ RR={r.get('RR')} 更新失败: {e}")


if __name__ == "__main__":
    main()
