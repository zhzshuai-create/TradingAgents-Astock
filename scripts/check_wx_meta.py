"""检查微信备份元数据文件"""
import os

BASE = r"C:\Users\zhzsh\xwechat_files\Backup\wxid_h3liy623j67m22\8b16c2accf76c1a4d21a0ec69fa4fcf8"

for fname in ["alt_name.dat", "backup.attr"]:
    path = os.path.join(BASE, fname)
    with open(path, "rb") as f:
        data = f.read()
    print(f"=== {fname} ({len(data)} bytes) ===")
    print(f"  hex: {data.hex()}")
    # 尝试 UTF-8
    try:
        s = data.decode("utf-8")
        print(f"  UTF-8: {s}")
    except:
        print(f"  (not UTF-8)")
    # 尝试 GBK
    try:
        s = data.decode("gbk")
        print(f"  GBK: {s}")
    except:
        pass
    print()
