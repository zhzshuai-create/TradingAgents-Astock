"""解析 WeChat Backup RMFH 格式聊天文件"""
import os

BASE = r"C:\Users\zhzsh\xwechat_files\Backup\wxid_h3liy623j67m22\8b16c2accf76c1a4d21a0ec69fa4fcf8\files\1\ffe0cb5d8f1ce788ff9321c047c08210fa36d52f4bdce58e5c125e7eaf3f5e90"

d = os.path.join(BASE, "ChatPackage")
files = sorted(os.listdir(d))
latest = files[-1]

with open(os.path.join(d, latest), "rb") as f:
    data = f.read()

print(f"文件: {latest}")
print(f"大小: {len(data)} bytes")
print(f"Header: {data[:16].hex()}")

# 提取所有可读文本
texts = []
for i in range(len(data) - 20):
    printable = sum(1 for j in range(min(40, len(data)-i)) if 32 <= data[i+j] < 127)
    if printable >= 30:
        chunk = data[i:min(i+300, len(data))]
        try:
            s = chunk.decode("utf-8", errors="replace")
        except:
            s = chunk.decode("latin-1")
        if len(s) > 5:
            texts.append(s)
        i += 50

print(f"\n找到 {len(texts)} 个文本片段:\n")
for t in texts[:30]:
    # 只显示有意义的中文/英文内容
    clean = "".join(c for c in t if c.isprintable() or c in "\n\r\t")
    if any("\u4e00" <= c <= "\u9fff" for c in clean) or any(c.isalpha() for c in clean):
        print(f"  [{clean[:150]}]")
        print()
