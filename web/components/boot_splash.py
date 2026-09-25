"""首屏启动遮罩 — 盖住 Streamlit 首帧渲染完成之前的那段等待.

为什么这个模块能起作用: Streamlit 边执行脚本边通过 websocket 增量下发元素, 所以在
重导入(sidebar 的 agent 图链约 3.2s)之前 yield 的元素会立刻上屏. 实测遮罩约 456ms
出现, 能覆盖整个阻塞窗口.

约束:
  - render_boot_mask() 必须是脚本里第一个产生元素的调用(紧跟 set_page_config)
  - start_boot_watchdog() 必须紧跟其后, 两者之间不得有任何重导入
  - 本模块不得导入任何重依赖, 否则它自己就成了要遮罩的那段等待
  - 节奏全在 CSS/JS, Python 侧不 sleep、不逐帧 rerun

为什么要两个 iframe 而不是一个:
  render_boot_mask 走 st.markdown, 而 Streamlit 会把 markdown 里的 <script> 剥掉,
  所以任何 JS 都必须由 components.html 承载. 但脚本末尾那个 iframe 只有在脚本跑到
  末尾时才存在 —— 一旦首屏渲染中途抛异常, 遮罩就永远盖着白屏. 因此在开头再放一个
  看门狗 iframe, 它负责装 hide() 和兜底定时器, 末尾的 finish_boot() 只负责报"内容好了".
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

# 遮罩最短可见时长. 节点点亮→汇聚的完整时间线在 2.9s 结束(见下方 CSS 的 delay),
# 下限取 2800ms 是为了让动画播完再放行; 冷启动首帧实测 2.1-4.6s, 多数情况下
# 真正决定放行时刻的仍是内容就绪, 这个下限只约束"内容比动画还快"的场景.
MIN_VISIBLE_MS = 2800

# 兜底上限: 脚本卡死/抛异常时最迟这么久放行. 取 6s 是因为第三次基线实测首帧 4630ms.
FALLBACK_MS = 6000

# 淡出时长, 与 CSS 里的 transition 保持一致
_FADE_MS = 350

_MASK_CSS = """
<style>
#boot-mask {
  position: fixed; inset: 0; z-index: 2147483000;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 1.4rem;
  background: #ffffff; color: #1a1a1a;
  font-family: "Source Sans Pro", sans-serif, "Microsoft YaHei";
  /* 60s 无限动画同时承担两个职责: 前 0.6%(约 360ms)做淡入, 之后它的 currentTime
     就是"遮罩已可见多久"的精确时钟 —— hide() 靠它算最短可见时长, 不需要 Python 侧
     记录任何时间戳. 周期取 60s 是为了在遮罩的生命周期内不会循环回闪. */
  animation: boot-life 60s linear infinite;
}
html.dark #boot-mask { background: #0e1117; color: #fafafa; }

@keyframes boot-life {
  from { opacity: 0; }
  0.6% { opacity: 1; }
  to   { opacity: 1; }
}

#boot-mask .boot-wordmark {
  font-size: 1.5rem; font-weight: 700; letter-spacing: 0.14em;
}
#boot-mask .boot-wordmark span { color: #e85d04; }
#boot-mask .boot-sub {
  font-size: 0.8rem; letter-spacing: 0.22em; opacity: 0.55;
  margin-top: -0.9rem;
}

/* ── 7 个分析师节点: 逐个点亮(0.55s 起, 间隔 0.16s), 2.0s 一起向决策节点汇聚 ──
   每个节点只带一个 --i, 点亮 delay 与汇聚位移都由它算出来, HTML 里不写死坐标.
   列宽固定, 汇聚的横向位移才是可算的: 第 i 列中心到行中心 = (3 - i) * 列宽. */
#boot-mask .boot-nodes {
  --col: 76px;
  display: grid;
  grid-template-columns: repeat(7, var(--col));
  margin-top: 0.6rem;
}
#boot-mask .boot-node,
#boot-mask .boot-decision {
  display: flex; flex-direction: column; align-items: center; gap: 0.3rem;
}
#boot-mask .boot-node {
  opacity: 0;
  /* boot-node-go 只写 to 关键帧且不回填 backwards: 它的隐式起点 = 下层动画
     (boot-node-in 的 forwards 填充)的结果, 所以汇聚是从"已点亮"的位置出发的. */
  animation:
    boot-node-in 0.32s ease-out calc(0.55s + var(--i) * 0.16s) both,
    boot-node-go 0.5s cubic-bezier(0.5, 0, 0.75, 0.4) 2s forwards;
}
@keyframes boot-node-in {
  from { opacity: 0; transform: translateY(8px) scale(0.85); }
  to   { opacity: 1; transform: none; }
}
@keyframes boot-node-go {
  to {
    opacity: 0;
    transform: translateX(calc((3 - var(--i)) * var(--col)))
               translateY(38px) scale(0.5);
  }
}
#boot-mask .boot-node-ico { font-size: 1.15rem; line-height: 1; }
#boot-mask .boot-node-name {
  font-size: 0.68rem; letter-spacing: 0.08em; opacity: 0.7; white-space: nowrap;
}

#boot-mask .boot-decision {
  position: relative;
  opacity: 0;
  animation: boot-decision-in 0.5s cubic-bezier(0.2, 0.9, 0.3, 1.35) 2.15s forwards;
}
@keyframes boot-decision-in {
  from { opacity: 0; transform: scale(0.55); }
  60%  { opacity: 1; }
  to   { opacity: 1; transform: scale(1); }
}
#boot-mask .boot-decision .boot-node-name { opacity: 0.9; font-size: 0.74rem; }
#boot-mask .boot-ring {
  position: absolute; top: -7px; left: 50%; width: 26px; height: 26px;
  margin-left: -13px; border-radius: 50%;
  border: 1px solid #e85d04; opacity: 0;
  animation: boot-ring 0.9s ease-out 2.3s forwards;
}
@keyframes boot-ring {
  0%   { opacity: 0.7; transform: scale(0.6); }
  100% { opacity: 0;   transform: scale(2.1); }
}

/* 不确定态进度条: 不显示百分比. 首帧耗时极差 2.2-4.6s(2.1 倍), 假进度会被看穿.
   动画时间线 2.9s 结束后, 它是"还在加载"的唯一提示. */
#boot-mask .boot-track {
  width: min(240px, 46vw); height: 2px;
  background: rgba(128, 128, 128, 0.18);
  border-radius: 2px; overflow: hidden;
}
#boot-mask .boot-bar {
  width: 38%; height: 100%; border-radius: 2px;
  background: #e85d04;
  animation: boot-slide 1.15s ease-in-out infinite;
}
@keyframes boot-slide {
  0%   { transform: translateX(-105%); }
  100% { transform: translateX(320%); }
}

#boot-mask.boot-out {
  animation: none;
  opacity: 0 !important;
  transition: opacity 0.35s ease-out;
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  #boot-mask { animation: none; opacity: 1; }
  #boot-mask .boot-node { animation: none; opacity: 1; }
  #boot-mask .boot-decision { animation: none; opacity: 1; }
  #boot-mask .boot-ring { display: none; }
  #boot-mask .boot-bar { animation: none; width: 100%; opacity: 0.5; }
}
</style>
"""

_MASK_HTML = """
<div id="boot-mask" aria-hidden="true">
  <div class="boot-wordmark">AStock <span>Pro</span></div>
  <div class="boot-sub">AI MULTI-AGENT</div>
  <div class="boot-nodes">
    <div class="boot-node" style="--i:0"><span class="boot-node-ico">📊</span><span class="boot-node-name">技术</span></div>
    <div class="boot-node" style="--i:1"><span class="boot-node-ico">💬</span><span class="boot-node-name">情绪</span></div>
    <div class="boot-node" style="--i:2"><span class="boot-node-ico">📰</span><span class="boot-node-name">舆情</span></div>
    <div class="boot-node" style="--i:3"><span class="boot-node-ico">📋</span><span class="boot-node-name">基本面</span></div>
    <div class="boot-node" style="--i:4"><span class="boot-node-ico">🏛️</span><span class="boot-node-name">政策</span></div>
    <div class="boot-node" style="--i:5"><span class="boot-node-ico">🔥</span><span class="boot-node-name">游资</span></div>
    <div class="boot-node" style="--i:6"><span class="boot-node-ico">🔒</span><span class="boot-node-name">解禁</span></div>
  </div>
  <div class="boot-decision">
    <span class="boot-ring"></span>
    <span class="boot-node-ico">👔</span>
    <span class="boot-node-name">投资决策</span>
  </div>
  <div class="boot-track"><div class="boot-bar"></div></div>
</div>
"""

# 每个 components.html 都是独立沙箱 iframe, 互相看不见对方的变量, 所以共享状态挂在
# window.parent 上. 两个 iframe 谁先执行都不确定, 下面两段都按"对方可能还没来"写.
_PRELUDE = "var W = window.parent; var B = W.__astockBoot || (W.__astockBoot = {});"

_WATCHDOG_JS = f"""
<script>
(function () {{
  {_PRELUDE}
  var doc = W.document;

  if (!B.hide) {{
    B.hide = function () {{
      if (B.hidden || B.timer) return;
      var mask = doc.getElementById('boot-mask');
      if (!mask) {{ B.hidden = true; return; }}

      var shown = 1e9;
      if (mask.getAnimations) {{
        var a = mask.getAnimations();
        if (a.length && typeof a[0].currentTime === 'number') shown = a[0].currentTime;
      }}
      var wait = Math.max(0, {MIN_VISIBLE_MS} - shown);

      B.timer = setTimeout(function () {{
        B.hidden = true;
        if (B.fallback) {{ clearTimeout(B.fallback); B.fallback = null; }}
        if (mask.getAnimations) {{
          mask.getAnimations().forEach(function (x) {{ x.cancel(); }});
        }}
        mask.classList.add('boot-out');
        /* 只做 display:none, 不摘节点: 这个 div 是 React 管的, 手动 remove 会让
           后续 rerun 的 reconciliation 对不上, 而 display:none 在视觉上等价. */
        setTimeout(function () {{ mask.style.display = 'none'; }}, {_FADE_MS} + 60);
      }}, wait);
    }};
  }}

  if (B.ready) {{ B.hide(); }}
  else if (!B.fallback) {{
    /* 计时起点是看门狗 iframe 执行的时刻(实测约 460ms), 不是遮罩上屏那一刻,
       所以真实上限是 FALLBACK_MS + 约 460ms. 兜底值本来就不需要精确. */
    B.fallback = setTimeout(function () {{ B.fallback = null; B.hide(); }}, {FALLBACK_MS});
  }}
}})();
</script>
"""

_FINISH_JS = f"""
<script>
(function () {{
  {_PRELUDE}
  B.ready = true;
  if (B.hide) B.hide();
}})();
</script>
"""


def render_boot_mask() -> None:
    """注入遮罩. 必须是脚本里第一个产生元素的调用."""
    st.markdown(_MASK_CSS + _MASK_HTML, unsafe_allow_html=True)


def start_boot_watchdog() -> None:
    """装 hide() 与兜底定时器. 必须紧跟 render_boot_mask()."""
    components.html(_WATCHDOG_JS, height=0)


def finish_boot() -> None:
    """脚本末尾调用: 报告"内容已就绪", 触发补满最短时长后的淡出."""
    components.html(_FINISH_JS, height=0)
