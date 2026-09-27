# TradingAgents-Astock

[English](README.en.md) | [简体中文](README.md)

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python" alt="Python >=3.10">
  <img src="https://img.shields.io/badge/version-0.2.19-green" alt="Version 0.2.18">
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange?logo=apache" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platform">
  <a href="https://github.com/zhzshuai-create/TradingAgents-Astock/actions/workflows/ci.yml"><img src="https://img.shields.io/badge/CI-passing-brightgreen?logo=github" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-171%20passed-brightgreen" alt="Tests">
</p>

A multi-agent AI research platform for China A-shares, with a real-time market dashboard built in. A deep customization of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (65K+ Stars).

> ⚠️ For research and learning only. Not investment advice.

---

## 📸 Screenshots

### Boot Splash

While cold-starting, a full-screen overlay plays a "7 analyst nodes lighting up → converging into the investment decision node" animation, covering the 3–5s blank wait. Light/dark theme aware; append `?noboot=1` to skip:

<p align="center">
  <img src="assets/boot-splash-light.png" width="49%" alt="Boot splash (light)"/>
  <img src="assets/boot-splash-dark.png" width="49%" alt="Boot splash (dark)"/>
</p>

### Responsive Top Bar

Below 1680px the index ticker wraps onto its own centered row; logo, mode switch and theme toggle never collide:

<p align="center">
  <img src="assets/topbar-responsive-fix.png" width="90%" alt="Responsive top bar: before/after at 1440px"/>
</p>

### AI Analysis Report

7 AI analysts (optional parallel execution) → bull/bear debate → risk team → final decision:

<p align="center">
  <img src="assets/screenshot-analysis.png" width="90%" alt="AI analysis report"/>
</p>

### Real-time Dashboard

Search by code or Chinese name · OHLC candlesticks (MA overlays + linked zoomable volume) · live quotes · sector attribution:

<p align="center">
  <img src="assets/dashboard-report.png" width="90%" alt="Real-time dashboard"/>
</p>

### Analysis Progress

12-stage pipeline with real-time progress; expandable analyst reports; pause/resume/stop:

<p align="center">
  <img src="assets/screenshot-progress.png" width="90%" alt="Analysis progress"/>
</p>

### Report Export

Signal card (Buy/Hold/Sell) + 7 analyst reports + debate + risk assessment, exported to PDF / Markdown:

<p align="center">
  <img src="assets/screenshot-pdf.png" width="90%" alt="Report export"/>
</p>

### Trade Journal (embedded)

Switch the top mode to **Trade Journal** to embed the standalone trade-journal review app via iframe (runs on port 8502, auto-started on demand). Equity curve click-through, holding-period / concentration / return-distribution diagnostics. Theme follows the platform's light/dark toggle automatically:

<p align="center">
  <img src="assets/trade-journal-dashboard.png" width="90%" alt="Trade journal"/>
</p>

---

## Features

| Feature | Description |
|---------|-------------|
| 🧠 **AI Analysis Report** | 7 AI analysts → bull/bear debate → 3-way risk team → final decision, fully automated Chinese research report |
| 📈 **Real-time Dashboard** | Stock search (code or Chinese name) · OHLC candlesticks with MA5/10/20 and linked zoomable volume · Tencent live quotes · northbound capital · concept-sector attribution |
| ⚡ **Parallel Analysts (opt-in)** | `TA_PARALLEL_ANALYSTS=1` fans out 7 analysts concurrently; wall time ≈ slowest analyst (measured −19% to −94%) |
| 💾 **Checkpoint Resume** | Crashed analyses resume from the last completed node |
| 🛡️ **Rate-limit Hardening** | Unified EastMoney throttling (token-bucket + jitter) with retries; TDX outage falls back to Sina HTTP k-line |
| ⏸️ **Controllable Runs** | Pause / resume / stop at any time, with stall detection |
| 📥 **Dual Export** | Markdown (zero-dependency) and PDF with CJK font adaptation |
| 📝 **History** | Every analysis saved; search by code/date; one-click revisit |
| 🌓 **Instant Theming** | Light/dark toggle, pure JS+CSS, persists in localStorage; embedded journal follows via postMessage |
| 📖 **Trade Journal** | Zero-intrusion iframe embed of the trade-journal review app |

---

## Performance & Experiments

All numbers below come from the 2026-09-13 benchmark (model: Xiaomi MiMo `mimo-v2.5` via OpenAI-compatible API; full 7-analyst pipeline). Reproduction scripts and raw data live in [experiments/](experiments/README.md).

### T1 · Parallel Analysts

| Ticker | Serial | Parallel | Reduction |
|--------|--------|----------|-----------|
| 000858 Wuliangye | 694.4s | 559.3s | **−19.5%** |
| 601318 Ping An | 684.3s | 508.2s | **−25.7%** |
| 300750 CATL | 8001.7s* | 466.7s | **−94.2%** |

\* The 8002s serial run for CATL hit provider-side latency variance (other serial runs ≈ 690s same-day). The 467s parallel run shows fan-out's natural immunity to single-point latency — the slowest analyst no longer drags the whole pipeline.

### T2 · Signal Direction Backtest

6 stocks analyzed on signal date 2026-08-13, validated against 2026-09-11 closes:

- Directional signals hit **2 / 2** (Overweight on 000001 and 601899, +4.36% / +0.16% over the window)
- The other 4 were Hold (neutral signals are excluded from hit-rate; the system skews conservative)
- ⚠️ Small sample (6 stocks / 1 month) — it only demonstrates that outputs are traceable and evaluable, not alpha.

### Startup Performance

Spinner "naked exposure" time (user sees a spinner but no content) reduced from **2.80s to 0.15s** (median of 3 runs; evidence in [docs/boot-splash/evidence/](docs/boot-splash/evidence/)): a themed overlay paints at 0.69s and main content lands at 2.13s.

---

## Project Structure

```
TradingAgents-Astock/
├── tradingagents/          # Core framework
│   ├── agents/             # 7 AI analysts + bull/bear debate
│   ├── dataflows/          # Data layer (all market/fundamental/news APIs)
│   │   └── a_stock/        # A-share data vendor (package)
│   └── graph/              # LangGraph orchestration (serial / parallel fan-out)
├── web/                    # Streamlit UI
│   ├── app.py              # Web entry + AI analysis mode
│   ├── components/         # Dashboard, boot splash, progress, journal embed
│   └── data_functions.py   # Cached data adapters over the core layer
├── cli/                    # Interactive CLI
├── experiments/            # Benchmark scripts + raw results (see experiments/README.md)
├── scripts/                # Utilities (incl. make_demo_gif.py)
├── tests/                  # 171 tests (offline unit + graph topology)
├── .github/workflows/      # CI (ubuntu/windows × py3.10/3.13)
└── CHANGELOG.md
```

---

## Quick Start

```bash
git clone https://github.com/zhzshuai-create/TradingAgents-Astock.git
cd TradingAgents-Astock
pip install -e .
```

Configure an LLM in `.env` (see `.env.example`), then:

```bash
streamlit run web/app.py     # Web UI (recommended), open http://localhost:8501
tradingagents                # Interactive CLI
```

Optional parallel analysts:

```bash
# PowerShell
$env:TA_PARALLEL_ANALYSTS = "1"; streamlit run web/app.py
# macOS / Linux
TA_PARALLEL_ANALYSTS=1 streamlit run web/app.py
```

No Docker required. Data sources are free and key-less (mootdx · Tencent · EastMoney · Sina · THS ·CLS · Baidu); only the LLM needs an API key.

---

## Acknowledgments

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — multi-agent trading framework
- [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) — A-share data layer seeds

## License

Apache 2.0 — see [LICENSE](LICENSE).
