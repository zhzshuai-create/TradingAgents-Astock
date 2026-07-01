"""
从 CSV 生成教师信息整合报告 Markdown
"""
import csv, re
from pathlib import Path

CSV = Path(r"C:\Users\zhzsh\TradingAgents-astock\cdut_teachers.csv")
OUT = Path(r"C:\Users\zhzsh\TradingAgents-astock\cdut_teachers_report.md")

with open(CSV, "r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# ── 清洗 & 提取 ──
for r in rows:
    s = r.get("_summary", "") or ""

    # 硕导/博导
    r["is_ms"] = "硕导" if ("硕士生导师" in s or "硕导" in s) else ""
    r["is_phd"] = "博导" if ("博士生导师" in s or "博导" in s) else ""
    adv = []
    if r["is_phd"]: adv.append("博导")
    if r["is_ms"]: adv.append("硕导")
    r["advisor"] = "/".join(adv) if adv else "-"

    # 职称
    title = ""
    for t in ["教授", "副教授", "讲师", "助教"]:
        if t in s[:300]:
            title = t; break
    r["_title"] = title or "-"

    # 研究方向清洗
    research = (r.get("research", "") or "").replace("更多+", "").strip()
    research = re.sub(r"\s+", " ", research)
    if len(research) > 80:
        research = research[:80] + "…"
    r["_research"] = research or "-"

    # 邮箱
    r["_email"] = r.get("email", "").strip() or "-"

    # 摘要精简
    summary = re.sub(r"\s+", " ", s)
    r["_summary_short"] = summary[:200] if summary else "-"

# ── 研究方向聚类 ──
clusters = {
    "AI/机器学习/计算机视觉": [],
    "网络空间安全": [],
    "AI+地学/地球物理": [],
    "大数据/高性能计算": [],
    "其他": [],
}

for r in rows:
    txt = r["_research"] + " " + r.get("_summary_short", "")
    if any(kw in txt for kw in ["计算机视觉", "图像", "语音", "深度学习", "机器学习", "目标检测", "模式识别", "人工智能安全", "对抗", "可解释人工智能", "大模型", "联邦学习", "情感识别", "说话人"]):
        clusters["AI/机器学习/计算机视觉"].append(r)
    elif any(kw in txt for kw in ["网络安全", "信息安全", "密码", "入侵检测", "数字取证", "网络空间", "声像伪造"]):
        clusters["网络空间安全"].append(r)
    elif any(kw in txt for kw in ["地球物理", "地学", "地质", "滑坡", "岩土", "防灾", "遥感", "智能探测"]):
        clusters["AI+地学/地球物理"].append(r)
    elif any(kw in txt for kw in ["并行计算", "高性能计算", "大数据", "数据挖掘", "数值线性"]):
        clusters["大数据/高性能计算"].append(r)
    else:
        clusters["其他"].append(r)

# ── 生成 Markdown ──
md = []
md.append("# 成都理工大学 计算机与网络安全学院 — 导师信息总览\n")
md.append(f"**共 28 位教师** | 硕士生导师: {sum(1 for r in rows if r['is_ms'])} 位 | 博士生导师: {sum(1 for r in rows if r['is_phd'])} 位 | 教授/副教授: {sum(1 for r in rows if r['_title'] in ('教授','副教授'))} 位\n")
md.append(f"> 数据来源: faculty.cdut.edu.cn | 更新时间: 2026-06\n")

# ─── 对比表 ───
md.append("---\n")
md.append("## 一、快速对比表\n")
md.append("| # | 姓名 | 导师级别 | 职称 | 邮箱 | 研究方向 |")
md.append("| --- | --- | --- | --- | --- | --- |")
for i, r in enumerate(rows):
    md.append(f"| {i+1} | **{r['name']}** | {r['advisor']} | {r['_title']} | {r['_email']} | {r['_research']} |")

# ─── 研究方向聚类 ───
md.append("\n---\n")
md.append("## 二、按研究方向聚类\n")

for cluster_name, members in clusters.items():
    if not members:
        continue
    md.append(f"\n### {cluster_name}（{len(members)} 人）\n")
    md.append("| 姓名 | 导师级别 | 职称 | 邮箱 | 具体方向 |")
    md.append("| --- | --- | --- | --- | --- |")
    for r in members:
        md.append(f"| **{r['name']}** | {r['advisor']} | {r['_title']} | {r['_email']} | {r['_research']} |")

# ─── 个人详情卡 ───
md.append("\n---\n")
md.append("## 三、个人详情\n")

for i, r in enumerate(rows):
    md.append(f"\n### {i+1}. {r['name']}\n")
    md.append(f"- **导师级别**: {r['advisor']}")
    md.append(f"- **职称**: {r['_title']}")
    md.append(f"- **邮箱**: {r['_email']}")
    md.append(f"- **研究方向**: {r['_research']}")
    md.append(f"- **个人主页**: [{r['url']}]({r['url']})")
    if r.get("education"):
        md.append(f"- **学历**: {r['education']}")
    if r.get("office"):
        md.append(f"- **办公室**: {r['office']}")
    summary = r.get("_summary_short", "-")
    if len(summary) > 10:
        md.append(f"- **简介**: {summary}")
    md.append("")

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"Done → {OUT}")
print(f"共 {len(rows)} 位，{sum(1 for r in rows if r['is_ms'])} 硕导，{sum(1 for r in rows if r['is_phd'])} 博导")
