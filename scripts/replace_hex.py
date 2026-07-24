"""Replace hardcoded hex/px in app.py with var() references."""
import sys

with open('web/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

count = 0

# ── 1. Sidebar toggle button CSS ──
OLD_TOGGLE = """<style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body {
        height: 100%; background: transparent;
        display: flex; align-items: center; justify-content: center;
      }
      .toggle-btn {
        background: #f8f9fa;
        border: 1px solid #d0d0d0;
        border-radius: 6px;
        cursor: pointer;
        font-size: 18px;
        width: 34px;
        height: 34px;
        color: #333;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.15s;
        padding: 0;
        line-height: 1;
        user-select: none;
        -webkit-user-select: none;
      }
      .toggle-btn:hover {
        background: #fff5f0;
        border-color: #e85d04;
        color: #e85d04;
      }
      .toggle-btn:active { transform: scale(0.93); }
    </style>"""

NEW_TOGGLE = """<style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body {
        height: 100%; background: transparent;
        display: flex; align-items: center; justify-content: center;
      }
      .toggle-btn {
        background: var(--toggle-bg);
        border: var(--hairline) solid var(--toggle-border);
        border-radius: var(--radius-sm);
        cursor: pointer;
        font-size: 18px;
        width: 34px;
        height: 34px;
        color: var(--toggle-icon);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.15s;
        padding: 0;
        line-height: 1;
        user-select: none;
        -webkit-user-select: none;
      }
      .toggle-btn:hover {
        background: var(--brand-soft);
        border-color: var(--brand);
        color: var(--brand);
      }
      .toggle-btn:active { transform: scale(0.93); }
    </style>"""

if OLD_TOGGLE in content:
    content = content.replace(OLD_TOGGLE, NEW_TOGGLE)
    count += 1
    print("[OK] Sidebar toggle button CSS")

# ── 2. Theme toggle button CSS ──
OLD_THEME = """<style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { height: 100%; background: transparent; display: flex; align-items: center; justify-content: center; }
      .theme-toggle { display: flex; gap: 2px; background: #e9ecef; border-radius: 8px; padding: 2px; }
      .theme-btn {
        width: 30px; height: 28px; border: none; border-radius: 6px;
        cursor: pointer; font-size: 14px;
        display: flex; align-items: center; justify-content: center;
        transition: all 0.12s ease; line-height: 1;
      }
      .theme-btn[data-theme="light"] { background: #fff; color: #333; }
      .theme-btn[data-theme="dark"]  { background: #111; color: #fff; }
      .theme-btn.active { box-shadow: 0 0 0 2px rgba(232,93,4,0.6); }
      .theme-btn:not(.active):hover { box-shadow: 0 0 0 2px rgba(232,93,4,0.25); }
    </style>"""

NEW_THEME = """<style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { height: 100%; background: transparent; display: flex; align-items: center; justify-content: center; }
      .theme-toggle { display: flex; gap: 2px; background: var(--theme-switch-bg); border-radius: var(--radius-md); padding: 2px; }
      .theme-btn {
        width: 30px; height: 28px; border: none; border-radius: var(--radius-sm);
        cursor: pointer; font-size: 14px;
        display: flex; align-items: center; justify-content: center;
        transition: all 0.12s ease; line-height: 1;
      }
      .theme-btn[data-theme="light"] { background: var(--theme-btn-light); color: #333; }
      .theme-btn[data-theme="dark"]  { background: var(--theme-btn-dark); color: #fff; }
      .theme-btn.active { box-shadow: 0 0 0 2px var(--brand); opacity: 0.6; }
      .theme-btn:not(.active):hover { box-shadow: 0 0 0 2px var(--brand); opacity: 0.25; }
    </style>"""

if OLD_THEME in content:
    content = content.replace(OLD_THEME, NEW_THEME)
    count += 1
    print("[OK] Theme toggle CSS")

# ── 3. _SIG dict ──
pairs = [
    ('"#22c55e", "#f0fdf4"', '"var(--buy)", "var(--buy-soft)"'),
    ('"#ef4444", "#fef2f2"', '"var(--sell)", "var(--sell-soft)"'),
    ('"#f59e0b", "#fffbeb"', '"var(--hold)", "var(--hold-soft)"'),
    ('"#444", "#f5f5f5"', '"var(--na)", "var(--na-soft)"'),
]
for old, new in pairs:
    if old in content:
        content = content.replace(old, new)
        count += 1
        print(f"[OK] _SIG: {old}")

# ── 4. Banner HTML ──
banner_pairs = [
    (
        '<span style="color: #ff5a1f;">Trading</span><span style="color: #1a1a1a;">Agents</span><span style="color: #1a1a1a;">-</span><span style="color: #ff5a1f;">Astock</span>',
        '<span style="color: var(--brand);">Trading</span><span style="color: var(--text);">Agents</span><span style="color: var(--text);">-</span><span style="color: var(--brand);">Astock</span>'
    ),
    (
        '<div style="color: #333; font-size: 0.82rem; margin-top: 0.2rem;">',
        '<div style="color: var(--muted); font-size: var(--font-md); margin-top: var(--space-xs);">'
    ),
    (
        'color: #ff5a1f; background: #fff5f0; display: inline-block; padding: 3px 12px; border-radius: 10px; border: 1px solid #ffccb0;',
        'color: var(--brand); background: var(--pill-bg); display: inline-block; padding: 3px 12px; border-radius: 10px; border: var(--hairline) solid var(--pill-border);'
    ),
]
for old, new in banner_pairs:
    if old in content:
        content = content.replace(old, new)
        count += 1
        print(f"[OK] Banner: {old[:50]}...")

# ── 5. Old var() renames ──
var_renames = [
    ('var(--text-primary)', 'var(--text)'),
    ('var(--text-secondary)', 'var(--muted)'),
    ('var(--text-tertiary)', 'var(--muted)'),
    ('var(--accent-hover)', 'var(--brand-hover)'),
    ('var(--accent-light)', 'var(--brand-soft)'),
    ('var(--card-bg)', 'var(--surface)'),
    ('var(--bg-primary)', 'var(--bg)'),
    ('var(--bg-secondary)', 'var(--bg)'),
    ('var(--border-color)', 'var(--line)'),
    ('var(--input-bg)', 'var(--surface)'),
    ('var(--input-border)', 'var(--line)'),
    ('var(--sidebar-bg)', 'var(--bg)'),
    ('var(--card-shadow)', 'var(--shadow-card)'),
]
# Do var(--accent) LAST to avoid breaking var(--accent-hover)
var_renames.append(('var(--accent)', 'var(--brand)'))

for old, new in var_renames:
    if old in content:
        content = content.replace(old, new)
        count += 1
        print(f"[OK] Var rename: {old} -> {new}")

# ── 6. Up/down color references ──
color_pairs = [
    ('clr = "#e03131" if', 'clr = "var(--up)" if'),
    ('clr = "#2f9e44"', 'clr = "var(--down)"'),
    ('"#e03131" if pct_val >= 0 else "#2f9e44"', '"var(--up)" if pct_val >= 0 else "var(--down)"'),
    ('"#e03131" if pct >= 0 else "#2f9e44"', '"var(--up)" if pct >= 0 else "var(--down)"'),
    ('"#e03131" if chg_all > 0 else "#2f9e44"', '"var(--up)" if chg_all > 0 else "var(--down)"'),
    ('"#e03131" if last["hgt_yi"] > 0 else "#2f9e44"', '"var(--up)" if last["hgt_yi"] > 0 else "var(--down)"'),
    ('"#e03131" if last["sgt_yi"] > 0 else "#2f9e44"', '"var(--up)" if last["sgt_yi"] > 0 else "var(--down)"'),
    (
        '"#e03131" if pe_fwd > 50 else ("#f08c00" if pe_fwd > 30 else "#2f9e44")',
        '"var(--up)" if pe_fwd > 50 else ("var(--warn)" if pe_fwd > 30 else "var(--down)")'
    ),
    (
        '"#2f9e44" if peg_val < 1 else ("#f08c00" if peg_val < 1.5 else "#e03131")',
        '"var(--down)" if peg_val < 1 else ("var(--warn)" if peg_val < 1.5 else "var(--up)")'
    ),
]
for old, new in color_pairs:
    if old in content:
        content = content.replace(old, new)
        count += 1
        print(f"[OK] Color: {old[:50]}...")

# Chg5 and chg (already handled by generic patterns above, but check)
more_colors = [
    ('"#e03131" if chg > 0 else "#2f9e44"', '"var(--up)" if chg > 0 else "var(--down)"'),
    ('"#e03131" if chg5 > 0 else "#2f9e44"', '"var(--up)" if chg5 > 0 else "var(--down)"'),
]
for old, new in more_colors:
    if old in content:
        content = content.replace(old, new)
        count += 1
        print(f"[OK] Color: {old[:50]}...")

with open('web/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f"\nTotal replacements: {count}")
print("Done. Run grep to verify remaining hex.")
