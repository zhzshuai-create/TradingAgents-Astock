"""
生成导师信息 PDF 报告
使用 fpdf2 + 系统中文字体
"""
import csv, re
from pathlib import Path
from fpdf import FPDF

CSV = Path(r"C:\Users\zhzsh\TradingAgents-astock\cdut_teachers.csv")
OUT = Path(r"C:\Users\zhzsh\Desktop\cdut_teachers_report.pdf")
FONT = r"C:\Windows\Fonts\simhei.ttf"  # 黑体

# ── 加载数据 ──
with open(CSV, "r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# 清洗
for r in rows:
    s = r.get("_summary", "") or ""
    r["is_ms"] = "硕导" if ("硕士生导师" in s or "硕导" in s) else ""
    r["is_phd"] = "博导" if ("博士生导师" in s or "博导" in s) else ""
    adv = []
    if r["is_phd"]: adv.append("博导")
    if r["is_ms"]: adv.append("硕导")
    r["advisor"] = "/".join(adv) if adv else "—"
    # 职称
    title = ""
    for t in ["教授", "副教授", "讲师", "助教"]:
        if t in s[:300]: title = t; break
    r["_title"] = title or "—"
    # 研究方向
    research = (r.get("research", "") or "").replace("更多+", "").strip()
    research = re.sub(r"\s+", " ", research)
    r["_research"] = research or "—"
    # 邮箱
    r["_email"] = r.get("email", "").strip() or "—"

# ── 研究方向聚类 ──
clusters = {
    "AI / 机器学习 / 计算机视觉": [],
    "网络空间安全": [],
    "AI + 地学 / 地球物理": [],
    "大数据 / 高性能计算": [],
    "其他方向": [],
}
for r in rows:
    txt = r["_research"] + " " + (r.get("_summary", "") or "")
    if any(kw in txt for kw in ["计算机视觉","图像","语音","深度学习","机器学习","目标检测","模式识别","人工智能安全","对抗","可解释人工智能","大模型","联邦学习","情感识别","说话人"]):
        clusters["AI / 机器学习 / 计算机视觉"].append(r)
    elif any(kw in txt for kw in ["网络安全","信息安全","密码","入侵检测","数字取证","网络空间","声像伪造"]):
        clusters["网络空间安全"].append(r)
    elif any(kw in txt for kw in ["地球物理","地学","地质","滑坡","岩土","防灾","遥感","智能探测"]):
        clusters["AI + 地学 / 地球物理"].append(r)
    elif any(kw in txt for kw in ["并行计算","高性能计算","大数据","数据挖掘","数值线性"]):
        clusters["大数据 / 高性能计算"].append(r)
    else:
        clusters["其他方向"].append(r)


# ── PDF 构建 ──
class PDF(FPDF):
    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.add_font("CN", "", FONT)
        self.add_font("CN", "B", FONT)  # 粗体用同一个字体
        self.set_auto_page_break(True, 18)

    def header(self):
        if self.page_no() > 1:
            self.set_font("CN", "", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 6, "成都理工大学 计算机与网络安全学院 · 导师信息", align="C")
            self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("CN", "", 7)
        self.set_text_color(160, 160, 160)
        self.cell(0, 10, f"第 {self.page_no()} 页", align="C")

    def section_title(self, text):
        self.set_font("CN", "B", 14)
        self.set_text_color(255, 90, 31)
        self.cell(0, 10, text)
        self.ln(11)
        self.set_draw_color(255, 90, 31)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, text):
        self.set_font("CN", "B", 11)
        self.set_text_color(60, 60, 60)
        self.cell(0, 8, text)
        self.ln(9)

    def body_text(self, text):
        self.set_font("CN", "", 9)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, text)

    def teacher_card(self, r):
        """紧凑卡片"""
        self.set_font("CN", "B", 10)
        self.set_text_color(30, 30, 30)
        name_line = r["name"]
        if r["advisor"] != "—":
            name_line += f"  [{r['advisor']}]"
        if r["_title"] != "—":
            name_line += f"  {r['_title']}"
        self.cell(0, 7, name_line)
        self.ln(7)

        items = []
        if r["_email"] != "—":
            items.append(f"邮箱: {r['_email']}")
        if r["_research"] != "—":
            research = r["_research"]
            if len(research) > 100:
                research = research[:100] + "…"
            items.append(f"方向: {research}")

        self.set_font("CN", "", 8)
        self.set_text_color(80, 80, 80)
        for item in items:
            self.cell(0, 5, f"  {item}")
            self.ln(5)
        self.ln(3)


pdf = PDF()
pdf.set_margin(12)

# ═══ 封面 ═══
pdf.add_page()
pdf.ln(50)
pdf.set_font("CN", "B", 28)
pdf.set_text_color(255, 90, 31)
pdf.cell(0, 14, "导师信息报告", align="C")
pdf.ln(16)
pdf.set_font("CN", "B", 16)
pdf.set_text_color(40, 40, 40)
pdf.cell(0, 10, "成都理工大学", align="C")
pdf.ln(10)
pdf.cell(0, 10, "计算机与网络安全学院（示范性软件学院）", align="C")
pdf.ln(20)
pdf.set_font("CN", "", 10)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 8, f"共 28 位教师 | 19 位硕导 | 4 位博导 | 7 位教授/副教授", align="C")
pdf.ln(8)
pdf.cell(0, 8, f"数据来源: faculty.cdut.edu.cn | 2026-06", align="C")

# ═══ 统计概览 ═══
pdf.add_page()
pdf.section_title("一、统计概览")
pdf.ln(2)

stats = [
    f"教师总数: 28 位",
    f"硕士生导师: 19 位",
    f"博士生导师: 4 位 (李冬芬、王洪辉、唐小川、朱星)",
    f"教授/副教授: 7 位",
    f"有邮箱: 20 位",
    f"有研究方向: 24 位",
]
for s in stats:
    pdf.set_font("CN", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(8, 7, "•")
    pdf.cell(0, 7, s)
    pdf.ln(7)

pdf.ln(4)

# ═══ 研究方向分布 ═══
pdf.section_title("二、按研究方向聚类")
pdf.ln(2)

for cname, members in clusters.items():
    if not members:
        continue
    pdf.sub_title(f"{cname}（{len(members)} 人）")
    for r in members:
        pdf.teacher_card(r)
    pdf.ln(2)

# ═══ 完整名单 ═══
pdf.add_page()
pdf.section_title("三、完整导师名单")

# 紧凑表格
col_w = [8, 22, 22, 20, 55, 59]  # 序号, 姓名, 导师级别, 职称, 邮箱, 方向
headers = ["#", "姓名", "导师级别", "职称", "邮箱", "研究方向"]
pdf.set_font("CN", "B", 8)
pdf.set_fill_color(255, 245, 240)
for i, h in enumerate(headers):
    pdf.cell(col_w[i], 7, h, border=1, fill=True, align="C")
pdf.ln()

for idx, r in enumerate(rows):
    if pdf.get_y() > 265:
        pdf.add_page()
        pdf.set_font("CN", "B", 8)
        pdf.set_fill_color(255, 245, 240)
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 7, h, border=1, fill=True, align="C")
        pdf.ln()

    pdf.set_font("CN", "", 7.5)
    pdf.set_text_color(40, 40, 40)
    data = [
        str(idx+1),
        r["name"],
        r["advisor"],
        r["_title"],
        r["_email"][:25],
        r["_research"][:45],
    ]
    for i, d in enumerate(data):
        pdf.cell(col_w[i], 6.5, d, border=1, align="C" if i == 0 else "L")
    pdf.ln()

# ═══ 保存 ═══
pdf.output(str(OUT))
print(f"PDF 已生成 → {OUT}")
print(f"共 {pdf.pages_count} 页")
