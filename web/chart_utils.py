"""Chart generation for PDF research reports using matplotlib."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

logger = logging.getLogger(__name__)

# ── Light theme ────────────────────────────────────────────────────────────────

BG = "#ffffff"
GRID = "#e5e5e5"
TEXT = "#333333"
ORANGE = "#ff5a1f"
GREEN = "#16a34a"
RED = "#dc2626"
CYAN = "#0891b2"
MAGENTA = "#9333ea"
YELLOW = "#ca8a04"

plt.rcParams.update(
    {
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "axes.edgecolor": GRID,
        "axes.labelcolor": TEXT,
        "text.color": TEXT,
        "xtick.color": TEXT,
        "ytick.color": TEXT,
        "grid.color": GRID,
        "grid.alpha": 0.5,
        "legend.facecolor": BG,
        "legend.edgecolor": GRID,
        "legend.labelcolor": TEXT,
    }
)

# ── CJK font detection ────────────────────────────────────────────────────────

_CJK_CANDIDATES = [
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "Noto Sans CJK SC",
    "WenQuanYi Micro Hei",
    "PingFang SC",
    "STHeiti",
]


def _setup_cjk_font() -> str:
    """Return the name of an available CJK font, or DejaVu Sans as fallback."""
    try:
        from matplotlib.font_manager import fontManager
        available = {f.name for f in fontManager.ttflist}
        for name in _CJK_CANDIDATES:
            if name in available:
                return name
    except Exception:
        pass

    # Also try checking font files directly
    for name in _CJK_CANDIDATES:
        try:
            from matplotlib.font_manager import FontProperties
            fp = FontProperties(family=name)
            return name
        except Exception:
            continue

    return "DejaVu Sans"


_CJK_FONT = _setup_cjk_font()
plt.rcParams["font.sans-serif"] = [_CJK_FONT, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ── Data helpers ──────────────────────────────────────────────────────────────


def _get_ohlcv_dataframe(ticker: str, trade_date: str) -> pd.DataFrame:
    """Fetch OHLCV data for charting using the project's A-stock provider."""
    from tradingagents.dataflows.a_stock import _load_ohlcv_astock

    df = _load_ohlcv_astock(ticker, trade_date)
    if df is None or df.empty:
        raise ValueError(f"No OHLCV data for {ticker} on {trade_date}")

    df = df.sort_values("Date").reset_index(drop=True)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


# ── Chart generators ──────────────────────────────────────────────────────────


def generate_kline_chart(ticker: str, trade_date: str) -> bytes | None:
    """Generate a K-line (candlestick) chart with MA overlays and volume.

    Returns PNG bytes, or None on failure.
    """
    try:
        df = _get_ohlcv_dataframe(ticker, trade_date)
        if len(df) < 20:
            logger.warning("Not enough data points for K-line chart: %d", len(df))
            return None

        df = df.tail(120).reset_index(drop=True)  # Show last 120 trading days

        # Compute moving averages
        df["MA5"] = df["Close"].rolling(5).mean()
        df["MA10"] = df["Close"].rolling(10).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA60"] = df["Close"].rolling(60).mean()

        x = np.arange(len(df))

        # Create figure with 2 subplots (price + volume)
        fig = plt.figure(figsize=(12, 7), dpi=150)
        gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)

        # ── Top panel: K-line + MAs ──
        width = 0.6
        for i, row in df.iterrows():
            idx = x[i]
            is_green = row["Close"] >= row["Open"]
            body_color = GREEN if is_green else RED
            body_bottom = min(row["Open"], row["Close"])
            body_top = max(row["Open"], row["Close"])

            # Shadow (high-low line)
            ax1.plot(
                [idx, idx], [row["Low"], row["High"]],
                color=body_color, linewidth=0.8, zorder=2,
            )
            # Body (rectangle)
            body_h = body_top - body_bottom
            if body_h < 0.001:
                body_h = 0.001
            rect = Rectangle(
                (idx - width / 2, body_bottom), width, body_h,
                facecolor=body_color, edgecolor=body_color,
                linewidth=0.5, zorder=3,
            )
            ax1.add_patch(rect)

        # MA lines
        for col, color, label in [
            ("MA5", ORANGE, "MA5"),
            ("MA10", CYAN, "MA10"),
            ("MA20", MAGENTA, "MA20"),
            ("MA60", YELLOW, "MA60"),
        ]:
            valid = df[col].notna()
            ax1.plot(x[valid], df[col][valid], color=color, linewidth=1, label=label)

        ax1.legend(loc="upper left", fontsize=8, ncol=4, framealpha=0.6)
        ax1.set_ylabel("Price", fontsize=9)
        ax1.grid(True, linestyle="--", linewidth=0.3)
        ax1.set_title(f"{ticker}  K-line  |  {trade_date}", fontsize=12, fontweight="bold", color="#1a1a1a")

        # Date labels on top panel x-axis labels (hidden, shared with volume)
        plt.setp(ax1.get_xticklabels(), visible=False)

        # ── Bottom panel: Volume ──
        for i, row in df.iterrows():
            is_green = row["Close"] >= row["Open"]
            vol_color = GREEN if is_green else RED
            ax2.bar(
                x[i], row["Volume"],
                width=width, color=vol_color,
                alpha=0.6, zorder=2,
            )

        ax2.set_ylabel("Volume", fontsize=9)
        ax2.grid(True, linestyle="--", linewidth=0.3)
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v/1e6:.0f}M"))

        # Format x-axis dates
        date_labels = df["Date"].dt.strftime("%m-%d")
        step = max(1, len(df) // 10)
        tick_positions = x[::step]
        tick_labels = date_labels.iloc[::step]
        ax2.set_xticks(tick_positions)
        ax2.set_xticklabels(tick_labels, rotation=0, fontsize=7)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    except Exception:
        logger.warning("Failed to generate K-line chart for %s", ticker, exc_info=True)
        return None


def generate_macd_chart(ticker: str, trade_date: str) -> bytes | None:
    """Generate a MACD indicator chart. Returns PNG bytes, or None on failure."""
    try:
        df = _get_ohlcv_dataframe(ticker, trade_date)
        if len(df) < 35:
            return None

        df = df.tail(120)
        close = df["Close"].values

        # MACD calculation
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean()
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = 2 * (dif - dea)

        x = np.arange(len(close))

        fig, ax = plt.subplots(figsize=(12, 3), dpi=150)
        ax.set_facecolor(BG)

        # Histogram bars
        colors = [GREEN if v >= 0 else RED for v in hist]
        ax.bar(x, hist, color=colors, alpha=0.5, width=0.8, zorder=2)

        # DIF and DEA lines
        valid = ~np.isnan(dif)
        ax.plot(x[valid], dif[valid], color=ORANGE, linewidth=1.2, label="DIF")
        ax.plot(x[valid], dea[valid], color=CYAN, linewidth=1, label="DEA")

        # Zero line
        ax.axhline(y=0, color=GRID, linewidth=0.5, linestyle="--")

        ax.legend(loc="upper left", fontsize=8)
        ax.set_title(f"{ticker}  MACD", fontsize=11, fontweight="bold", color="#1a1a1a")
        ax.grid(True, linestyle="--", linewidth=0.3)

        date_labels = df["Date"].dt.strftime("%m-%d")
        step = max(1, len(df) // 10)
        ax.set_xticks(x[::step])
        ax.set_xticklabels(date_labels.iloc[::step], rotation=0, fontsize=7)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    except Exception:
        logger.warning("Failed to generate MACD chart for %s", ticker, exc_info=True)
        return None


def generate_rsi_chart(ticker: str, trade_date: str) -> bytes | None:
    """Generate an RSI(14) chart. Returns PNG bytes, or None on failure."""
    try:
        df = _get_ohlcv_dataframe(ticker, trade_date)
        if len(df) < 20:
            return None

        df = df.tail(120)
        close = df["Close"].values

        # RSI calculation
        deltas = np.diff(close, prepend=close[0])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = pd.Series(gains).ewm(span=14, adjust=False).mean()
        avg_loss = pd.Series(losses).ewm(span=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        x = np.arange(len(close))
        valid = ~np.isnan(rsi)

        fig, ax = plt.subplots(figsize=(12, 3), dpi=150)
        ax.set_facecolor(BG)

        ax.plot(x[valid], rsi[valid], color=ORANGE, linewidth=1.2, label="RSI(14)")

        # Overbought / Oversold lines
        ax.axhline(y=70, color=RED, linewidth=0.5, linestyle="--", alpha=0.6)
        ax.axhline(y=30, color=GREEN, linewidth=0.5, linestyle="--", alpha=0.6)
        ax.axhline(y=50, color=GRID, linewidth=0.3, linestyle="-")

        # Fill overbought/oversold zones
        ax.fill_between(x, 70, 100, color=RED, alpha=0.05)
        ax.fill_between(x, 0, 30, color=GREEN, alpha=0.05)

        ax.set_ylim(0, 100)
        ax.set_ylabel("RSI", fontsize=9)
        ax.legend(loc="upper left", fontsize=8)
        ax.set_title(f"{ticker}  RSI (14)", fontsize=11, fontweight="bold", color="#1a1a1a")
        ax.grid(True, linestyle="--", linewidth=0.3)

        date_labels = df["Date"].dt.strftime("%m-%d")
        step = max(1, len(df) // 10)
        ax.set_xticks(x[::step])
        ax.set_xticklabels(date_labels.iloc[::step], rotation=0, fontsize=7)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    except Exception:
        logger.warning("Failed to generate RSI chart for %s", ticker, exc_info=True)
        return None
