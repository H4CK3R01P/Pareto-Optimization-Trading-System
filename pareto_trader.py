import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from mpl_toolkits.mplot3d import Axes3D
from matplotlib import cm
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS & STRATEGY CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DAYS            = [-2, -1, 0]
DATA_DIR        = "ROUND1"
ASH_PRODUCT     = "ASH_COATED_OSMIUM"
PEPPER_PRODUCT  = "INTARIAN_PEPPER_ROOT"
ASH_FAIR_VALUE  = 10_000          # known fair value (mean-reverting asset)

# ── Optimal parameters found by Pareto sweep ──────────────────────────────
ASH_BAND        = 0.5   # tight mean-reversion band → max mean-rev frequency
PEPPER_STRATEGY = "trend_buyhold"   # ride the persistent uptrend
POSITION_SIZE   = 1     # 1 unit per signal


# ─────────────────────────────────────────────────────────────────────────────
#  DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

def load_price_data():
    """Load and clean price data from all ROUND1 CSVs."""
    dfs = []
    for day in DAYS:
        path = f"{DATA_DIR}/prices_round_1_day_{day}.csv"
        try:
            df = pd.read_csv(path, sep=";")
            dfs.append(df)
        except FileNotFoundError:
            raise FileNotFoundError(f"Missing: {path}")

    full_df = pd.concat(dfs, ignore_index=True)

    # Build per-product price series (clean zero / NaN mid-prices)
    prices_by_day = {}    # {day: {product: price_array}}
    prices_all    = {}    # {product: full_price_series}

    for day in DAYS:
        day_df = full_df[full_df["day"] == day]
        prices_by_day[day] = {}
        for product in day_df["product"].unique():
            p = day_df[day_df["product"] == product].sort_values("timestamp")
            series = p["mid_price"].values.astype(float)
            series[series == 0] = np.nan
            series = pd.Series(series).interpolate().ffill().bfill().values
            prices_by_day[day][product] = series

    for product in full_df["product"].unique():
        p = full_df[full_df["product"] == product].copy()
        series = p["mid_price"].values.astype(float)
        series[series == 0] = np.nan
        series = pd.Series(series).interpolate().ffill().bfill().values
        prices_all[product] = pd.Series(series)

    return prices_by_day, prices_all


# ─────────────────────────────────────────────────────────────────────────────
#  PRODUCT-SPECIFIC STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

def ash_mean_reversion(price_array, fair_value=ASH_FAIR_VALUE, band=ASH_BAND,
                       position_size=POSITION_SIZE):
    """
    Mean-reversion strategy for ASH_COATED_OSMIUM.
    Buy when price dips below (fair - band), sell when it rises above (fair + band).
    Flat otherwise.
    """
    p       = price_array
    pos     = 0
    pnl     = 0.0
    returns = []

    for i in range(1, len(p)):
        r = pos * (p[i] - p[i - 1])
        pnl += r
        returns.append(r)

        if p[i] < fair_value - band:
            pos = position_size          # buy the dip
        elif p[i] > fair_value + band:
            pos = -position_size         # sell the spike
        else:
            pos = 0                      # flat in neutral zone

    return pnl, np.array(returns)


def pepper_trend_buyhold(price_array, position_size=POSITION_SIZE):
    """
    INTARIAN_PEPPER_ROOT rides a strong persistent uptrend (~1000 pts/day).
    Simple buy-and-hold each day captures maximum trend profit.
    """
    p       = price_array
    pos     = position_size   # always long
    pnl     = 0.0
    returns = []

    for i in range(1, len(p)):
        r = pos * (p[i] - p[i - 1])
        pnl += r
        returns.append(r)

    return pnl, np.array(returns)


def pepper_ma_crossover(price_array, short_window=5, long_window=30,
                        position_size=POSITION_SIZE):
    """
    MA crossover for INTARIAN_PEPPER_ROOT — alternative to buy-hold.
    Goes long when short MA > long MA, flat otherwise.
    """
    p       = price_array
    sma_s   = pd.Series(p).rolling(short_window).mean().values
    sma_l   = pd.Series(p).rolling(long_window).mean().values
    pos, pnl = 0, 0.0
    returns = []

    for i in range(long_window, len(p)):
        r = pos * (p[i] - p[i - 1])
        pnl += r
        returns.append(r)
        pos = position_size if sma_s[i] > sma_l[i] else 0

    return pnl, np.array(returns)


# ─────────────────────────────────────────────────────────────────────────────
#  METRICS
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(returns_array):
    """Return (total_pnl, variance, max_drawdown, sharpe)."""
    arr      = np.array(returns_array)
    total    = arr.sum()
    var      = np.var(arr)
    cum      = np.cumsum(arr)
    peak     = np.maximum.accumulate(cum)
    drawdown = (cum - peak).min()
    sharpe   = arr.mean() / (arr.std() + 1e-10) * np.sqrt(len(arr))
    return total, var, drawdown, sharpe


# ─────────────────────────────────────────────────────────────────────────────
#  PARETO FRONT
# ─────────────────────────────────────────────────────────────────────────────

def is_pareto_efficient(costs):
    """
    Find Pareto-efficient points.
    costs: (N, objectives) — all objectives should be minimized.
    """
    n          = costs.shape[0]
    is_eff     = np.ones(n, dtype=bool)
    for i, c in enumerate(costs):
        if is_eff[i]:
            dominated = np.all(costs[is_eff] <= c, axis=1) & \
                        np.any(costs[is_eff] <  c, axis=1)
            is_eff[is_eff] &= ~dominated
            is_eff[i] = True
    return is_eff


def run_pareto_sweep(prices_by_day):
    """
    Grid search over ASH band and PEPPER MA windows.
    Returns results array and params list for Pareto analysis.
    """
    ash_bands      = np.arange(0.5, 12.5, 0.5)
    pepper_shorts  = [5, 10, 15, 20]
    pepper_longs   = [30, 50, 100]

    results, params = [], []

    for band in ash_bands:
        for ps in pepper_shorts:
            for pl in pepper_longs:
                if ps >= pl:
                    continue

                all_rets = []
                for day in DAYS:
                    day_prices = prices_by_day[day]

                    # ASH
                    if ASH_PRODUCT in day_prices:
                        _, r = ash_mean_reversion(day_prices[ASH_PRODUCT], band=band)
                        all_rets.extend(r)

                    # PEPPER
                    if PEPPER_PRODUCT in day_prices:
                        _, r = pepper_ma_crossover(day_prices[PEPPER_PRODUCT],
                                                   short_window=ps, long_window=pl)
                        all_rets.extend(r)

                total, var, dd, _ = compute_metrics(all_rets)
                results.append([total, var, dd])
                params.append({"ash_band": band, "pepper_short": ps, "pepper_long": pl})

    # Also include the optimal buy-hold variant
    for band in ash_bands:
        all_rets = []
        for day in DAYS:
            day_prices = prices_by_day[day]
            if ASH_PRODUCT in day_prices:
                _, r = ash_mean_reversion(day_prices[ASH_PRODUCT], band=band)
                all_rets.extend(r)
            if PEPPER_PRODUCT in day_prices:
                _, r = pepper_trend_buyhold(day_prices[PEPPER_PRODUCT])
                all_rets.extend(r)
        total, var, dd, _ = compute_metrics(all_rets)
        results.append([total, var, dd])
        params.append({"ash_band": band, "pepper_short": 0, "pepper_long": 0})

    return np.array(results), params


# ─────────────────────────────────────────────────────────────────────────────
#  VISUALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def plot_results(results, pareto_mask, params, prices_by_day, optimal_returns):
    """Full dashboard: Pareto 3D surface + PNL equity curves."""
    fig = plt.figure(figsize=(18, 10))
    fig.patch.set_facecolor("#0d0d1a")
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

    # ── 1. 3D Pareto Front ────────────────────────────────────────────────
    ax3d = fig.add_subplot(gs[:, 0], projection="3d")
    ax3d.set_facecolor("#0d0d1a")

    returns_arr   = results[:, 0]
    risks_arr     = results[:, 1]
    drawdown_arr  = results[:, 2]

    norm   = plt.Normalize(returns_arr.min(), returns_arr.max())
    colors = cm.plasma(norm(returns_arr))

    ax3d.scatter(returns_arr, risks_arr, drawdown_arr,
                 c=colors, s=15, alpha=0.4, label="All Strategies")
    ax3d.scatter(returns_arr[pareto_mask], risks_arr[pareto_mask], drawdown_arr[pareto_mask],
                 c="cyan", s=60, edgecolor="white", linewidth=0.5,
                 label="Pareto Front", zorder=5)

    # Mark global best
    best_idx = np.argmax(returns_arr)
    ax3d.scatter([returns_arr[best_idx]], [risks_arr[best_idx]], [drawdown_arr[best_idx]],
                 c="lime", s=200, marker="*", label="Optimal", zorder=6)

    ax3d.set_xlabel("PNL (Return)", color="white", labelpad=8)
    ax3d.set_ylabel("Risk (Variance)", color="white", labelpad=8)
    ax3d.set_zlabel("Max Drawdown", color="white", labelpad=8)
    ax3d.set_title("Pareto Front — Trading Strategies", color="white", fontsize=13, pad=12)
    ax3d.tick_params(colors="white")
    ax3d.xaxis.pane.fill = ax3d.yaxis.pane.fill = ax3d.zaxis.pane.fill = False
    ax3d.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=8)

    # ── 2. Per-day ASH equity curve ────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 1])
    ax1.set_facecolor("#0d0d1a")
    offset = 0
    colors_days = ["#00d4ff", "#7b2fff", "#ff6b6b"]
    for idx, day in enumerate(DAYS):
        if ASH_PRODUCT in prices_by_day[day]:
            _, r = ash_mean_reversion(prices_by_day[day][ASH_PRODUCT])
            cum  = np.cumsum(r)
            ax1.plot(np.arange(len(cum)) + offset, cum + (cum[0] if idx > 0 else 0),
                     color=colors_days[idx], linewidth=1.2, label=f"Day {day}")
            offset += len(cum)
    ax1.set_title(f"ASH Mean-Reversion Equity  (band={ASH_BAND})", color="white", fontsize=11)
    ax1.set_xlabel("Timestep", color="#aaa"); ax1.set_ylabel("Cumulative PNL", color="#aaa")
    ax1.tick_params(colors="#aaa"); ax1.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=8)
    ax1.spines[:].set_color("#333")

    # ── 3. Per-day PEPPER equity curve ────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 1])
    ax2.set_facecolor("#0d0d1a")
    offset = 0
    for idx, day in enumerate(DAYS):
        if PEPPER_PRODUCT in prices_by_day[day]:
            _, r = pepper_trend_buyhold(prices_by_day[day][PEPPER_PRODUCT])
            cum  = np.cumsum(r)
            ax2.plot(np.arange(len(cum)) + offset, cum,
                     color=colors_days[idx], linewidth=1.2, label=f"Day {day}")
            offset += len(cum)
    ax2.set_title("PEPPER Trend Buy-Hold Equity", color="white", fontsize=11)
    ax2.set_xlabel("Timestep", color="#aaa"); ax2.set_ylabel("Cumulative PNL", color="#aaa")
    ax2.tick_params(colors="#aaa"); ax2.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=8)
    ax2.spines[:].set_color("#333")

    fig.suptitle(
        f"Pareto Optimization Trading System  |  Max PNL: {returns_arr.max():,.2f}",
        color="white", fontsize=15, fontweight="bold", y=0.97
    )
    plt.savefig("pareto_results.png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print("Plot saved → pareto_results.png")
    plt.show()


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  PARETO OPTIMIZATION TRADING SYSTEM  —  ROUND 1")
    print("=" * 60)

    # ── Load data ──────────────────────────────────────────────────────────
    prices_by_day, prices_all = load_price_data()
    products = list(prices_all.keys())
    print(f"\nProducts loaded : {products}")
    print(f"Days loaded     : {DAYS}")

    # ── Run optimal strategy (maximized PNL) ───────────────────────────────
    print(f"\n{'─'*60}")
    print("  OPTIMAL STRATEGY (Max PNL Configuration)")
    print(f"{'─'*60}")
    print(f"  ASH_COATED_OSMIUM  : Mean-Reversion  |  band = {ASH_BAND}")
    print(f"  INTARIAN_PEPPER_ROOT: Trend Buy-Hold |  full position every day")

    total_pnl      = 0.0
    optimal_returns = []

    for day in DAYS:
        day_prices = prices_by_day[day]
        ash_pnl = pepper_pnl = 0.0

        if ASH_PRODUCT in day_prices:
            ash_pnl, r = ash_mean_reversion(day_prices[ASH_PRODUCT])
            optimal_returns.extend(r)

        if PEPPER_PRODUCT in day_prices:
            pepper_pnl, r = pepper_trend_buyhold(day_prices[PEPPER_PRODUCT])
            optimal_returns.extend(r)

        day_total = ash_pnl + pepper_pnl
        total_pnl += day_total
        print(f"\n  Day {day:+d}:")
        print(f"    ASH mean-rev  PNL : {ash_pnl:>10,.2f}")
        print(f"    PEPPER trend  PNL : {pepper_pnl:>10,.2f}")
        print(f"    Day Total     PNL : {day_total:>10,.2f}")

    total_ret, var, dd, sharpe = compute_metrics(optimal_returns)
    print(f"\n{'─'*60}")
    print(f"  TOTAL PNL          : {total_ret:>12,.2f}  ✓")
    print(f"  Variance (Risk)    : {var:>12.4f}")
    print(f"  Max Drawdown       : {dd:>12.2f}")
    print(f"  Sharpe Ratio (est) : {sharpe:>12.4f}")
    print(f"{'─'*60}")

    # ── Pareto sweep ───────────────────────────────────────────────────────
    print("\nRunning Pareto grid sweep across all parameter combinations …")
    results, params = run_pareto_sweep(prices_by_day)

    # objectives: minimize -PNL (maximize PNL), minimize variance, minimize |drawdown|
    costs        = np.column_stack([-results[:, 0], results[:, 1], -results[:, 2]])
    pareto_mask  = is_pareto_efficient(costs)

    print(f"\nPareto-optimal strategies found: {pareto_mask.sum()}")
    print(f"\n{'─'*60}")
    print("  TOP PARETO-OPTIMAL STRATEGIES (sorted by PNL desc)")
    print(f"{'─'*60}")
    pareto_results = [(results[i], params[i]) for i in range(len(results)) if pareto_mask[i]]
    pareto_results.sort(key=lambda x: x[0][0], reverse=True)

    for res, p in pareto_results[:15]:
        pep_label = (f"buyhold" if p['pepper_short'] == 0
                     else f"MA({p['pepper_short']}/{p['pepper_long']})")
        print(f"  PNL={res[0]:>10,.2f}  |  Var={res[1]:.4f}  |  DD={res[2]:>8.2f}"
              f"  |  ash_band={p['ash_band']:.1f}  pepper={pep_label}")

    print(f"\n{'═'*60}")
    print(f"  MAXIMUM ACHIEVABLE PNL : {results[:, 0].max():>12,.2f}")
    print(f"{'═'*60}")

    # ── Visualize ───────────────────────────────────────────────────────────
    plot_results(results, pareto_mask, params, prices_by_day, optimal_returns)


if __name__ == "__main__":
    main()
