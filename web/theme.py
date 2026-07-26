"""
全站样式单一真相源（Single Source of Truth）
============================================
样式宪法：
  1. 值只在此文件 TOKENS::START ~ TOKENS::END 包裹区内定义一次，其余位置禁裸 hex/px。
  2. 组件只写 class 名，不拼值；用 var(--*) 引用。
  3. 换主题 = 只改 :root 和 html.dark 的 TOKENS 区。

三层结构：
  值层     TOKENS::START … TOKENS::END  所有变量（亮 + 暗）
  组合层   .card / .tag / .row / .topbar / .input  可复用 class
  覆盖层   Streamlit data-testid 选择器  收敛框架默认间距
"""

# ============================================================================
# TOKENS::START — 全站唯一值定义点（亮色主题）
# ============================================================================

LIGHT_TOKENS = """
/* ===== BRAND ===== */
--brand:       #e85d04;
--brand-soft:  #fff5f0;
--brand-hover: #d9480f;

/* ===== SIGNAL — 状态标签三色 ===== */
--buy:        #22c55e;
--buy-soft:   #f0fdf4;
--sell:       #ef4444;
--sell-soft:  #fef2f2;
--hold:       #f59e0b;
--hold-soft:  #fffbeb;
--na:         #6b7280;
--na-soft:    #f5f5f5;

/* ===== SURFACE — 背景层级 ===== */
--bg:      #f8f9fa;
--surface: #ffffff;
--line:    #dee2e6;

/* ===== TEXT — 文字层级 ===== */
--text:  #1a1a1a;
--muted: #6b7280;

/* ===== UP / DOWN / WARN — 涨跌警示 ===== */
--up:   #e03131;
--down: #2f9e44;
--warn: #f08c00;

/* ===== SPACING — 8px 网格 ===== */
--space-xs:  4px;
--space-sm:  8px;
--space-md:  16px;
--space-lg:  24px;
--space-xl:  32px;
--space-2xl: 40px;

/* ===== FONT SIZE — 字号阶梯 ===== */
--font-xs:  0.65rem;
--font-sm:  0.75rem;
--font-md:  0.85rem;
--font-lg:  1.05rem;
--font-xl:  1.35rem;
--font-2xl: 2rem;

/* ===== RADIUS ===== */
--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;

/* ===== SHADOW ===== */
--shadow-card:  0 1px 4px rgba(0,0,0,0.06);
--shadow-hover: 0 2px 8px rgba(0,0,0,0.10);

/* ===== HAIRLINE — 描边豁免 ===== */
--hairline: 1px;

/* ===== COMPONENT: 侧栏 toggle 按钮 ===== */
--toggle-bg:     #f8f9fa;
--toggle-border: #d0d0d0;
--toggle-icon:   #333333;

/* ===== COMPONENT: 主题切换按钮 ===== */
--theme-switch-bg:  #e9ecef;
--theme-btn-light:  #ffffff;
--theme-btn-dark:   #111111;
--theme-btn-light-text: #333333;
--theme-btn-dark-text:  #ffffff;

/* ===== COMPONENT: Trading Signal 深色 banner（固定暗色，豁免）===== */
--banner-start:  #1a1a2e;
--banner-end:    #16213e;
--banner-border: #333333;
--banner-label:  #888888;
--banner-text:   #f5f1eb;

/* ===== COMPONENT: 主 Banner 药丸标签 ===== */
--pill-bg:     #fff5f0;
--pill-border: #ffccb0;

/* ===== UTILITY: 按钮白色文字 ===== */
--btn-text: #ffffff;

/* ===== Streamlit dark header background ===== */
--st-header-dark: #1c1816;
"""

# ============================================================================
# TOKENS zone — 暗色主题覆盖
# ============================================================================

DARK_TOKENS = """
/* ===== BRAND ===== */
--brand:       #f0883e;
--brand-soft:  #3d2a1a;
--brand-hover: #ffa94d;

/* ===== SIGNAL — 暗色适配 ===== */
--buy:        #4ade80;
--buy-soft:   #0a2a12;
--sell:       #f87171;
--sell-soft:  #2a0a0a;
--hold:       #fbbf24;
--hold-soft:  #2a2000;
--na:         #9ca3af;
--na-soft:    #1a1a1a;

/* ===== SURFACE ===== */
--bg:      #1c1816;
--surface: #252120;
--line:    #383330;

/* ===== TEXT ===== */
--text:  #ede4dc;
--muted: #a3968a;

/* ===== UP / DOWN / WARN ===== */
--up:   #ff6b6b;
--down: #51cf66;
--warn: #fbbf24;

/* ===== COMPONENT: toggle ===== */
--toggle-bg:     #2d2927;
--toggle-border: #383330;
--toggle-icon:   #ede4dc;

/* ===== COMPONENT: 主题切换 ===== */
--theme-switch-bg:  #2d2927;
--theme-btn-light:  #ffffff;
--theme-btn-dark:   #111111;

/* ===== COMPONENT: 主 Banner 药丸标签 ===== */
--pill-bg:     #3d2a1a;
--pill-border: #5c3a20;

/* ===== Streamlit dark header background ===== */
--st-header-dark: #1c1816;

/* ===== Step 3 补漏：暗色模式缺失变量 ===== */
/* SHADOW — 暗色需更深的阴影 */
--shadow-card:  0 1px 4px rgba(0,0,0,0.25);
--shadow-hover: 0 2px 8px rgba(0,0,0,0.40);

/* HAIRLINE — 1px 不变 */
--hairline: 1px;

/* UTILITY — 按钮文字 */
--btn-text: #ffffff;

/* TRADING SIGNAL BANNER — 固定暗色主题，与亮色同值 */
--banner-start:  #1a1a2e;
--banner-end:    #16213e;
--banner-border: #333333;
--banner-label:  #888888;
--banner-text:   #f5f1eb;

/* THEME TOGGLE — 主题切换按钮文字色 */
--theme-btn-light-text: #333333;
--theme-btn-dark-text:  #ffffff;
"""

# ============================================================================
# TOKENS::END
# ============================================================================

# ============================================================================
# 组合层（COMBINATION）— 可复用 class
# ============================================================================

COMBINATION_CSS = """
/* ── 卡片容器 ── */
.card {
    background: var(--surface);
    border: var(--hairline) solid var(--line);
    border-radius: var(--radius-lg);
    padding: var(--space-md);
    box-shadow: var(--shadow-card);
    transition: box-shadow 0.2s ease;
}
.card:hover {
    box-shadow: var(--shadow-hover);
}
.card__title {
    font-weight: 700;
    font-size: var(--font-lg);
    color: var(--text);
    margin-bottom: var(--space-sm);
}

/* ── KPI 卡片（紧凑）── */
.metric-card {
    background: var(--surface);
    border-radius: var(--radius-md);
    padding: var(--space-sm) var(--space-md);
    box-shadow: var(--shadow-card);
    text-align: center;
}
.metric-card .label {
    font-size: var(--font-sm);
    color: var(--muted);
    margin-bottom: 4px;
}
.metric-card .value {
    font-size: var(--font-xl);
    font-weight: 700;
    color: var(--text);
}
.metric-card .sub {
    font-size: var(--font-xs);
    color: var(--muted);
}

/* ── 状态标签（描边胶囊，三色）── */
.tag {
    display: inline-block;
    font-size: var(--font-sm);
    font-weight: 700;
    padding: 2px var(--space-sm);
    border-radius: 6px;
    white-space: nowrap;
    border: var(--hairline) solid;
}
.tag--buy {
    color: var(--buy);
    background: var(--buy-soft);
    border-color: var(--buy);
}
.tag--sell {
    color: var(--sell);
    background: var(--sell-soft);
    border-color: var(--sell);
}
.tag--hold {
    color: var(--hold);
    background: var(--hold-soft);
    border-color: var(--hold);
}
.tag--na {
    color: var(--na);
    background: var(--na-soft);
    border-color: var(--na);
}

/* ── 左侧列表行 ── */
.row {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) 0;
}
.row__meta {
    color: var(--muted);
    font-size: var(--font-sm);
}

/* ── 顶栏容器 ── */
.topbar {
    display: flex;
    align-items: center;
    gap: var(--space-md);
}

/* ── 输入框统一规范 ── */
.input {
    border: var(--hairline) solid var(--line);
    border-radius: var(--radius-sm);
    background: var(--surface);
    color: var(--text);
    padding: var(--space-sm) var(--space-md);
    font-size: var(--font-md);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.input:focus {
    border-color: var(--brand);
    box-shadow: 0 0 0 2px var(--brand-soft);
    outline: none;
}

/* ── 强势股卡片 ── */
.stock-card {
    background: var(--surface);
    border-radius: var(--radius-md);
    padding: var(--space-sm) var(--space-md);
    box-shadow: var(--shadow-card);
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-size: var(--font-md);
}
.stock-card .code {
    font-weight: 700;
    color: var(--text);
    min-width: 55px;
}
.stock-card .name {
    color: var(--muted);
    min-width: 65px;
}
.stock-card .pct {
    font-weight: 700;
    min-width: 55px;
}
.stock-card .reason {
    color: var(--muted);
    font-size: var(--font-sm);
    flex: 1;
}

/* ── Banner 区域容器 ── */
.banner {
    text-align: center;
    margin-top: var(--space-md);
    margin-bottom: var(--space-lg);
    padding: var(--space-md) 0;
}

/* ── Banner 主标题 ── */
.banner__title {
    font-size: var(--font-2xl);
    font-weight: 900;
    color: var(--text);
    margin-bottom: var(--space-xs);
}

/* ── 品牌 Logo 文字 ── */
.brand-logo {
    font-size: var(--font-lg);
    font-weight: 800;
    color: var(--brand);
    letter-spacing: -0.02em;
}

/* ── 主 Banner 药丸 ── */
.banner__pill {
    display: inline-block;
    font-size: var(--font-xs);
    color: var(--brand);
    background: var(--pill-bg);
    margin-top: var(--space-sm);
    padding: 3px 12px;
    border-radius: 10px;
    border: var(--hairline) solid var(--pill-border);
}

/* ── 底部声明 ── */
.footer-note {
    text-align: center;
    color: var(--muted);
    font-size: var(--font-sm);
    padding: var(--space-lg) 0 var(--space-sm) 0;
    border-top: var(--hairline) solid var(--line);
}
"""

# ============================================================================
# 覆盖层（OVERRIDE）— 收敛 Streamlit 框架间距（只改视觉量）
# ============================================================================

OVERRIDE_CSS = """
/* ── 字体 ── */
html, body, [class*="css"] {
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Inter', sans-serif;
}

/* ── 页面底色 ── */
.stApp {
    background: var(--bg);
}

/* ── 主内容区间距收敛 ── */
[data-testid="stAppViewContainer"] > .block-container {
    padding-top: var(--space-md) !important;
    padding-bottom: var(--space-md) !important;
}
/* 仅顶层垂直 block 收敛间距，避免波及卡片/表单内部 */
[data-testid="stAppViewContainer"] > .block-container > [data-testid="stVerticalBlock"] {
    gap: var(--space-sm) !important;
}

/* ── 侧栏 ── */
section[data-testid="stSidebar"] {
    background: var(--bg);
    border-right: var(--hairline) solid var(--line);
}

/* ── 标题 ── */
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
    color: var(--text) !important;
}

/* ── 正文 ── */
.stApp p, .stApp span, .stApp li, .stApp td, .stApp th {
    color: var(--text);
}
.stApp .stMarkdown {
    color: var(--text);
}
.stApp [data-testid="stCaptionContainer"] {
    color: var(--muted) !important;
}

/* ── 水平线 ── */
.stApp hr {
    border-color: var(--line) !important;
}

/* ── 指标卡片 ── */
.stApp [data-testid="stMetric"] {
    background: var(--surface);
    border-radius: var(--radius-md);
    padding: var(--space-sm);
}
.stMetric label {
    color: var(--muted) !important;
    font-size: var(--font-sm) !important;
}
.stMetric [data-testid="stMetricValue"] {
    color: var(--brand) !important;
    font-weight: 700 !important;
}

/* ── 主按钮 ── */
button[kind="primary"] {
    background: linear-gradient(135deg, var(--brand), var(--brand-hover)) !important;
    border: none !important;
    font-weight: 700 !important;
    color: var(--btn-text) !important;
    transition: all 0.2s ease !important;
}
button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
}
button[kind="secondary"] {
    background: var(--surface) !important;
    border: var(--hairline) solid var(--line) !important;
    color: var(--text) !important;
    transition: all 0.2s ease !important;
}
button[kind="secondary"]:hover {
    background: var(--brand-soft) !important;
    border-color: var(--brand) !important;
    color: var(--brand) !important;
}

/* ── 下载按钮 ── */
div[data-testid="stDownloadButton"] button {
    background: var(--surface) !important;
    border: var(--hairline) solid var(--brand) !important;
    color: var(--brand) !important;
}
div[data-testid="stDownloadButton"] button:hover {
    background: var(--brand-soft) !important;
}

/* ── 进度条 ── */
.stProgress > div > div > div {
    background: linear-gradient(90deg, var(--brand), var(--brand-hover)) !important;
}

/* ── 输入框 ── */
input[data-testid="stTextInputRootElement"] input, .stTextInput input {
    background: var(--surface) !important;
    border-color: var(--line) !important;
    color: var(--text) !important;
}
.stTextInput input:focus {
    border-color: var(--brand) !important;
    box-shadow: 0 0 0 2px var(--brand-soft) !important;
}

/* ── 选择框 ── */
.stApp [data-baseweb="select"] {
    background: var(--surface);
    color: var(--text);
}
.stApp [data-baseweb="input"] {
    background: var(--surface);
    color: var(--text);
}
.stApp [data-baseweb="popover"] {
    background: var(--surface);
}

/* ── 单选按钮 ── */
.stApp [data-baseweb="radio"] * {
    color: var(--text) !important;
}
.stTabs [data-baseweb="tab"] {
    color: var(--muted) !important;
}
.stTabs [aria-selected="true"] {
    color: var(--brand) !important;
    border-bottom-color: var(--brand) !important;
}

/* ── 折叠面板 ── */
.stExpander {
    border: var(--hairline) solid var(--line) !important;
    border-radius: var(--radius-md) !important;
}
.stExpander summary {
    color: var(--text) !important;
    background: var(--surface) !important;
}
.stExpander summary:hover {
    color: var(--brand) !important;
    background: var(--brand-soft) !important;
}
.stExpander summary svg {
    fill: var(--text) !important;
}
.stApp [data-testid="stExpander"] {
    background: var(--surface) !important;
    border-color: var(--line) !important;
}
.stApp [data-testid="stExpander"] summary {
    color: var(--text) !important;
    background: var(--surface) !important;
}
.stApp [data-testid="stExpander"] summary svg {
    fill: var(--text) !important;
}
.stApp [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    color: var(--text) !important;
    background: var(--bg) !important;
}

/* ── 表格 ── */
.stApp .stDataFrame, .stApp [data-testid="stTable"] {
    background: var(--surface);
}
.stApp .stDataFrame td, .stApp .stDataFrame th {
    color: var(--text) !important;
}
.stApp [data-testid="stTable"] td {
    color: var(--text);
}

/* ── 告警/通知 ── */
.stApp .stAlert {
    background: var(--surface) !important;
    color: var(--text) !important;
}
.stApp [data-testid="stNotification"] {
    background: var(--surface);
    color: var(--text);
}

/* ── 表单 ── */
.stApp [data-testid="stForm"] {
    background: var(--surface);
    border-color: var(--line);
}
/* 搜索框提交按钮：去掉外层容器框 */
[data-testid="stFormSubmitButton"] {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
}
.stApp [data-testid="stFormSubmitButton"] button {
    background: var(--brand) !important;
    color: var(--btn-text) !important;
    border: none !important;
}
.stApp [data-testid="stFormSubmitButton"] button:hover {
    background: var(--brand-hover) !important;
}

/* ── 复选框 ── */
.stApp [data-baseweb="checkbox"] * {
    color: var(--text) !important;
}

/* ── Markdown 扩展 ── */
.stApp .stMarkdown code {
    color: var(--brand) !important;
    background: var(--brand-soft) !important;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 0.9em;
}
.stApp .stMarkdown pre {
    background: var(--bg) !important;
    border: var(--hairline) solid var(--line);
    border-radius: var(--radius-md);
    padding: var(--space-md);
}
.stApp .stMarkdown pre code {
    background: transparent !important;
    color: var(--text) !important;
    padding: 0;
}
.stApp .stMarkdown blockquote {
    border-left: 3px solid var(--brand);
    padding: var(--space-sm) var(--space-md);
    margin: var(--space-sm) 0;
    background: var(--bg);
    color: var(--text);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.stApp .stMarkdown table {
    background: var(--surface);
    border-collapse: collapse;
    width: 100%;
}
.stApp .stMarkdown th {
    background: var(--bg);
    color: var(--text);
    padding: var(--space-sm) var(--space-md);
    border: var(--hairline) solid var(--line);
    font-weight: 600;
}
.stApp .stMarkdown td {
    color: var(--text);
    padding: 6px var(--space-md);
    border: var(--hairline) solid var(--line);
}

/* ── Chrome 隐藏 ── */
footer,
div[data-testid="stDecoration"],
button[data-testid="stBaseButton-header"],
div[data-testid="stStatusWidget"],
div[data-testid="stToolbarActions"],
div[data-testid="stAppDeployButton"],
span[data-testid="stMainMenu"] {
    display: none !important;
}

/* ── Header / Toolbar 透明 ── */
header[data-testid="stHeader"] {
    background: transparent !important;
    box-shadow: none !important;
}
div[data-testid="stToolbar"] {
    background: transparent !important;
}

/* ── 侧栏折叠按钮保持可点击 ── */
button[data-testid="stSidebarCollapseButton"],
button[data-testid="collapsedControl"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    background: var(--surface) !important;
    border: var(--hairline) solid var(--line) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text) !important;
    z-index: 999999 !important;
}
button[data-testid="stSidebarCollapseButton"]:hover,
button[data-testid="collapsedControl"]:hover {
    background: var(--brand-soft) !important;
    border-color: var(--brand) !important;
    color: var(--brand) !important;
}

/* ── 侧栏内 Markdown ── */
.stApp [data-testid="stSidebar"] .stMarkdown {
    color: var(--text);
}

/* ── Tab ── */
.stApp [role="tab"] {
    color: var(--muted) !important;
}
.stApp [aria-selected="true"][role="tab"] {
    color: var(--brand) !important;
}

/* ── Tag ── */
.stApp [data-baseweb="tag"] {
    background: var(--brand-soft) !important;
    color: var(--brand) !important;
}
"""

# ============================================================================
# Dark mode Streamlit-specific overrides
# ============================================================================

DARK_STREAMLIT = """
html.dark .stApp [data-testid="stHeader"] { background: var(--st-header-dark) !important; }
html.dark .stApp [data-testid="stToolbar"] { background: var(--st-header-dark) !important; }
html.dark .stApp .stMarkdown a { color: var(--brand) !important; }
html.dark .stApp [data-testid="stSidebar"] .stMarkdown * { color: var(--text) !important; }
html.dark .stApp h1, html.dark .stApp h2, html.dark .stApp h3,
html.dark .stApp h4, html.dark .stApp h5, html.dark .stApp h6 {
    color: var(--text) !important;
}
html.dark .stApp p, html.dark .stApp span:not([class*="metric"]) {
    color: var(--text) !important;
}
html.dark .stApp [data-testid="stMetricValue"] {
    color: var(--brand) !important;
}
html.dark .stApp [data-testid="stMetricLabel"] {
    color: var(--muted) !important;
}
html.dark .stApp [data-testid="stCaptionContainer"] {
    color: var(--muted) !important;
}
html.dark .stApp hr { border-color: var(--line) !important; }
html.dark .stApp [data-baseweb="input"] {
    background: var(--surface) !important;
    color: var(--text) !important;
    border-color: var(--line) !important;
}
html.dark .stApp [data-baseweb="input"] input {
    color: var(--text) !important;
}
html.dark .stApp [data-baseweb="input"] input::placeholder {
    color: var(--muted) !important;
}
html.dark .stApp [data-baseweb="select"] {
    background: var(--surface) !important;
    color: var(--text) !important;
    border-color: var(--line) !important;
}
html.dark .stApp [data-baseweb="select"] * {
    color: var(--text) !important;
}
html.dark .stApp [data-baseweb="popover"] {
    background: var(--surface) !important;
}
html.dark .stApp [data-baseweb="popover"] * {
    color: var(--text) !important;
}
html.dark .stApp [data-testid="stExpander"] {
    background: var(--surface) !important;
    border-color: var(--line) !important;
}
html.dark .stApp [data-testid="stExpander"] summary {
    color: var(--text) !important;
}
html.dark .stApp .stDataFrame {
    background: var(--surface) !important;
}
html.dark .stApp .stDataFrame td, html.dark .stApp .stDataFrame th {
    color: var(--text) !important;
}
html.dark .stApp [data-testid="stTable"] td, html.dark .stApp [data-testid="stTable"] th {
    color: var(--text) !important;
}
html.dark .stApp .stAlert {
    background: var(--surface) !important;
    color: var(--text) !important;
}
html.dark .stApp [data-baseweb="radio"] * {
    color: var(--text) !important;
}
html.dark .stApp [data-baseweb="checkbox"] * {
    color: var(--text) !important;
}
html.dark .stApp [data-testid="stForm"] {
    background: var(--surface) !important;
    border-color: var(--line) !important;
}
html.dark .stApp [data-testid="stNotification"] {
    background: var(--surface) !important;
    color: var(--text) !important;
}
html.dark .stApp [role="tab"] {
    color: var(--muted) !important;
}
html.dark .stApp [aria-selected="true"][role="tab"] {
    color: var(--brand) !important;
}
html.dark .stApp [data-baseweb="tag"] {
    background: var(--brand-soft) !important;
    color: var(--brand) !important;
}
html.dark [data-testid="stFormSubmitButton"] {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
}
html.dark .stApp [data-testid="stFormSubmitButton"] button {
    background: var(--brand) !important;
    color: var(--btn-text) !important;
    border: none !important;
}
html.dark .stApp [data-testid="stFormSubmitButton"] button:hover {
    background: var(--brand-hover) !important;
}
"""

# ============================================================================
# 全文拼接
# ============================================================================

CSS = f"""
/* ═══════════════════════════════════════════════════════════════
   TOKENS::START — 值层：亮色主题
   ═══════════════════════════════════════════════════════════════ */
html.light {{
{LIGHT_TOKENS}
}}

/* ═══════════════════════════════════════════════════════════════
   TOKENS — 值层：暗色主题覆盖
   ═══════════════════════════════════════════════════════════════ */
html.dark {{
{DARK_TOKENS}
}}

/* ═══════════════════════════════════════════════════════════════
   TOKENS::END
   ═══════════════════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════════
   组合层 — 可复用 class
   ═══════════════════════════════════════════════════════════════ */
{COMBINATION_CSS}

/* ═══════════════════════════════════════════════════════════════
   覆盖层 — Streamlit 框架选择器
   边界：只改视觉量（颜色/间距/圆角/阴影/字号）
   ═══════════════════════════════════════════════════════════════ */
{OVERRIDE_CSS}

/* ═══════════════════════════════════════════════════════════════
   暗色模式 — Streamlit 原生控件逐选择器覆盖
   ═══════════════════════════════════════════════════════════════ */
{DARK_STREAMLIT}
"""

# Exported for app.py: single import, two strings
# Usage:
#   from web.theme import CSS
#   st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
