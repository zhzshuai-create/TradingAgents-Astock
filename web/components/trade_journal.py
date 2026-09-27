"""交易日志模式 — 以 iframe 嵌入独立的 trade-journal Streamlit 应用 (localhost:8502)。

零侵入: 本模块不读写 trade-journal 的任何代码或数据 (data/ 隐私隔离由其自身负责),
仅通过 URL 回显。8502 未启动时原地自动拉起(懒加载); 失败回落到手动引导, 不白屏。
主题联动: 跨端口 iframe 属跨源, 通过 postMessage 把平台亮/暗主题同步给日志应用
(日志侧监听器: trade-journal/app.py::_inject_theme_listener)。
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from web import journal_service

# 主题联动桥：轮询平台父页的实时主题（rope 切换只改 html class，不触发 rerun），
# 变化即 postMessage 给 8502 日志 iframe。srcdoc 桥 iframe 与父页同源，
# 可读父文档 html class（与 app.py 主题加载器同一访问模式）。
#
# M1 修复要点：日志 iframe 元素虽先于本桥挂载，但其内部 Streamlit 冷启动需数秒、
# 监听器注册更晚 —— 首帧消息必然丢失。对策双管：
#   a) send() 失败（iframe 未就绪）不更新 last，下个 tick 继续重发；
#   b) 握手：日志侧就绪后主动发 astock-theme-request，桥立即回送当前主题
#      （桥监听挂在 window.parent 即平台主窗口上，与 postMessage 目标同层）。
_THEME_BRIDGE_JS = """
<script>
(function(){
  function currentTheme() {
    try {
      var cls = window.parent.document.documentElement.className || '';
      if (cls.indexOf('dark') >= 0) return 'dark';
      if (cls.indexOf('light') >= 0) return 'light';
    } catch (e) {}
    try { return localStorage.getItem('astock-theme') || 'light'; } catch (e) { return 'light'; }
  }
  function findJournal() {
    return window.parent.document.querySelector('iframe[src*=":8502"]');
  }
  function send(theme) {
    var f = findJournal();
    if (f && f.contentWindow) {
      f.contentWindow.postMessage({type: 'astock-theme', theme: theme}, '*');
      return true;
    }
    return false;
  }
  var last = null;
  setInterval(function() {
    var t = currentTheme();
    if (t !== last) { if (send(t)) { last = t; } }
  }, 600);
  // 握手：日志侧就绪后发 astock-theme-request，立即回送当前主题
  try {
    window.parent.addEventListener('message', function(ev){
      var d = ev.data || {};
      if (d.type === 'astock-theme-request') send(currentTheme());
    });
  } catch (e) {}
})();
</script>
"""


def render_journal_mode() -> None:
    st.subheader("📖 交易日志 · 复盘看板")
    st.caption(
        "这是独立运行的 trade-journal 应用 (localhost:8502), 以 iframe 嵌入。"
        "资金曲线点击联动、持仓周期/仓位集中度/收益分布等指标都在下方。"
        "亮/暗主题跟随平台自动同步。"
        "⚠️ 若日志区出现乱码, 多为系统代理劫持了本地端口 — 请在代理软件中将"
        " 127.0.0.1 / localhost 加入绕过名单。"
    )
    if not journal_service.journal_alive():
        with st.spinner("首次打开, 正在启动交易日志服务…"):
            proc = journal_service.start_journal()
            if proc is None or not journal_service.wait_ready():
                # M5: 拉起失败不遗留半死进程占住 8502, 先回收再提示
                if proc is not None:
                    proc.terminate()
                st.warning(
                    f"⚠️ 交易日志服务自动启动失败 ({journal_service.JOURNAL_URL})。\n\n"
                    "请手动启动后回到本页刷新：\n"
                    "- 一键同时启动平台+日志: 运行平台根目录的 `run_all.bat`\n"
                    "- 或单独启动日志: 在 `trade-journal/` 下运行 `run.bat` (已固定 8502 端口)"
                )
                return
    components.iframe(journal_service.JOURNAL_URL, height=1800, scrolling=True)
    components.html(_THEME_BRIDGE_JS, height=0)
