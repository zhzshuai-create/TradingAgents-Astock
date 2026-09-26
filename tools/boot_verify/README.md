# boot_verify — 启动遮罩验收门禁

Playwright 端到端门禁，覆盖 `web/components/boot_splash.py` 的全部承诺。
依赖：`pip install playwright && playwright install chromium`（本机已装）。

## 运行

```bash
cd <任意目录>          # 截图/JSON 证据落到当前目录, 不污染仓库
python <repo>/tools/boot_verify/verify_boot_mask.py       # 覆盖/淡入/淡出/可点 8 项
python <repo>/tools/boot_verify/verify_boot_anim.py       # 节点点亮时间线 4 项
python <repo>/tools/boot_verify/verify_boot_gating.py     # 门控 7 场景
python <repo>/tools/boot_verify/verify_boot_fallback.py   # 崩溃兜底变异测试
python <repo>/tools/boot_verify/round2_timeline.py        # 冷启动浏览器内时间线
python <repo>/tools/boot_verify/round2_launcher_verify.py # launcher 并行自举 + 日志探活
python <repo>/tools/boot_verify/verify_journal_autostart.py # 日志页懒加载冷进自动拉起
```

默认对**本仓库**起服务（端口 8503/8504）。要对别的树跑：`ASTOCK_REPO=C:\path\to\tree`；
日志目录非同级时：`ASTOCK_JOURNAL=C:\path\to\trade-journal`。

## 各门禁证明什么

| 脚本 | 证明 |
|---|---|
| verify_boot_mask | 遮罩铺满视口、无祖先劫持 fixed、淡入后 opacity=1、亮/暗满屏为遮罩底色（像素采样）、淡出后 display:none 且主界面可点 |
| verify_boot_anim | 0.3s 遮罩在/节点未亮、0.9s 前两位点亮、1.7s 七节点全亮未汇聚、2.7s 已汇聚且决策节点出现 |
| verify_boot_gating | 首载播 / F5 不重播 / 切模式不重播 / reload 不重播 / 新标签页重播 / ?noboot=1 跳过 / prefers-reduced-motion 跳过 |
| verify_boot_fallback | 遮罩后抛异常时, FALLBACK_MS 后遮罩自行放行（变异测试） |
| round2_timeline | mask/play/ready/done/gone/script_end 六点时间线（进程冷重启 ×3） |
| round2_launcher_verify | 双服务并行自举耗时 + 首帧切日志模式 iframe 直挂 + 遮罩时间线无回归 |
| verify_journal_autostart | 8502 冷态进日志页: spinner 内自动拉起子进程, iframe 出且日志应用真渲染(截图); 预检要求 8502/8503 空闲 |

## 已知环境怪象（写新门禁前必读）

本机 loopback 上 `urlopen` 单次探测不可信：出现过无监听端口返回假 200，
也出现过 ::1 连接被丢弃直到超时。就绪判定用 `health_stable`（双探 + 忽略 dt<0.5s）。
详见 DEV_LOG「轮 2 优化」节。

## 资产管线

`process_logo.py <源图路径>`：去水印 → 背景转 alpha（AA 边 un-mix）→ bbox 裁切 →
方形 pad → 写 `assets/logo-dragon.png`(512) / `logo-dragon-192.png` / `app_icon.ico`(7 尺寸)。
