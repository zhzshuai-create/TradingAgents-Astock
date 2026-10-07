# -*- coding: utf-8 -*-
"""可点击卡片 → 隐藏原生按钮 的点击转发桥（srcdoc iframe 同源操作 parent）。

覆盖两类纯 HTML 卡片：首页快捷行情卡(.quick-card)与看板总览板块行(.sector-row)
——信息丰富但非交互元素，真正的 Streamlit 隐藏按钮按 data-code 精确匹配
按钮文本后 JS click（widget 按钮 JS click 一向可靠）。
"""

from __future__ import annotations

import streamlit.components.v1 as components


def wire_clickable_cards() -> None:
    """在当前渲染位置下发转发桥 iframe（幂等：data-wired 防重复挂监听）。"""
    components.html("""
<script>
(function(){
  var D = window.parent.document;
  function wire() {
    var cards = D.querySelectorAll('.quick-card:not([data-wired]), .sector-row:not([data-wired])');
    for (var i = 0; i < cards.length; i++) {
      var c = cards[i];
      c.setAttribute('data-wired', '1');
      c.addEventListener('click', function() {
        var code = this.getAttribute('data-code');
        if (!code) return;
        var btns = D.querySelectorAll('[data-testid="stMain"] button');
        for (var j = 0; j < btns.length; j++) {
          if (btns[j].textContent.trim() === code) { btns[j].click(); return; }
        }
      });
    }
  }
  wire();
  setTimeout(wire, 500);
  setTimeout(wire, 1500);
})();
</script>
""", height=0)
