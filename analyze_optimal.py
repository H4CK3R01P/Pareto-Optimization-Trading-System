"""
Analyze the actual market data to determine the REAL PNL achievable
with proper execution (not magic mid-price fills).
"""
import pandas as pd
import numpy as np

DAYS = [-2, -1, 0]
DATA_DIR = "ROUND1"
LIMIT = 20

def load_day(day):
    path = f"{DATA_DIR}/prices_round_1_day_{day}.csv"
    df = pd.read_csv(path, sep=";")
    return df

def simulate_ash_realistic(df, fair=10000):
    """
    Simulate ASH with REALISTIC execution:
    - Buy by lifting the ask when mid < fair (take the best ask)
    - Sell by hitting the bid when mid > fair (take the best bid)
    - Track position with LIMIT=20
    """
    ash = df[df["product"] == "ASH_COATED_OSMIUM"].sort_values("timestamp").reset_index(drop=True)
    
    pos = 0
    cash = 0.0
    trades = 0
    
    for _, row in ash.iterrows():
        mid = row["mid_price"]
        best_bid = row["bid_price_1"] if pd.notna(row["bid_price_1"]) else None
        best_ask = row["ask_price_1"] if pd.notna(row["ask_price_1"]) else None
        bid_vol = int(row["bid_volume_1"]) if pd.notna(row["bid_volume_1"]) else 0
        ask_vol = int(row["ask_volume_1"]) if pd.notna(row["ask_volume_1"]) else 0
        
        # Mean reversion signal
        if mid < fair and best_ask and pos < LIMIT:
            # BUY: take the ask
            qty = min(ask_vol, LIMIT - pos)
            if qty > 0:
                cash -= best_ask * qty
                pos += qty
                trades += 1
        elif mid > fair and best_bid and pos > -LIMIT:
            # SELL: hit the bid  
            qty = min(bid_vol, LIMIT + pos)
            if qty > 0:
                cash += best_bid * qty
                pos -= qty
                trades += 1
    
    # Mark-to-market final position
    final_mid = ash.iloc[-1]["mid_price"]
    mtm = cash + pos * final_mid
    
    print(f"  ASH realistic: trades={trades}, final_pos={pos}, cash={cash:.0f}, mtm_pnl={mtm:.2f}")
    return mtm

def simulate_ash_take_both_sides(df, fair=10000):
    """
    Take BOTH sides but ONLY when profitable relative to fair value:
    - Buy asks that are BELOW fair value
    - Sell bids that are ABOVE fair value
    """
    ash = df[df["product"] == "ASH_COATED_OSMIUM"].sort_values("timestamp").reset_index(drop=True)
    
    pos = 0
    cash = 0.0
    trades = 0
    
    for _, row in ash.iterrows():
        # Check all 3 ask levels - buy anything below fair
        for lvl in [1, 2, 3]:
            ask_p = row.get(f"ask_price_{lvl}")
            ask_v = row.get(f"ask_volume_{lvl}")
            if pd.notna(ask_p) and pd.notna(ask_v) and ask_p < fair and pos < LIMIT:
                qty = min(int(ask_v), LIMIT - pos)
                if qty > 0:
                    cash -= ask_p * qty
                    pos += qty
                    trades += 1
        
        # Check all 3 bid levels - sell anything above fair
        for lvl in [1, 2, 3]:
            bid_p = row.get(f"bid_price_{lvl}")
            bid_v = row.get(f"bid_volume_{lvl}")
            if pd.notna(bid_p) and pd.notna(bid_v) and bid_p > fair and pos > -LIMIT:
                qty = min(int(bid_v), LIMIT + pos)
                if qty > 0:
                    cash += bid_p * qty
                    pos -= qty
                    trades += 1
    
    final_mid = ash.iloc[-1]["mid_price"]
    mtm = cash + pos * final_mid
    print(f"  ASH take-profitable: trades={trades}, final_pos={pos}, cash={cash:.0f}, mtm_pnl={mtm:.2f}")
    return mtm

def simulate_ash_aggressive_mm(df, fair=10000):
    """
    Position-skewed aggressive market making:
    - When pos <= 0: buy at best ask (any price)
    - When pos > 0: sell at best bid (any price)  
    - Always max out position to cycle faster
    """
    ash = df[df["product"] == "ASH_COATED_OSMIUM"].sort_values("timestamp").reset_index(drop=True)
    
    pos = 0
    cash = 0.0
    trades = 0
    
    for _, row in ash.iterrows():
        best_bid = row["bid_price_1"] if pd.notna(row["bid_price_1"]) else None
        best_ask = row["ask_price_1"] if pd.notna(row["ask_price_1"]) else None
        bid_vol = int(row["bid_volume_1"]) if pd.notna(row["bid_volume_1"]) else 0
        ask_vol = int(row["ask_volume_1"]) if pd.notna(row["ask_volume_1"]) else 0
        
        if pos <= 0 and best_ask:
            # BUY to go long
            qty = min(ask_vol, LIMIT - pos)
            if qty > 0:
                cash -= best_ask * qty
                pos += qty
                trades += 1
        elif pos > 0 and best_bid:
            # SELL to go flat/short
            qty = min(bid_vol, LIMIT + pos)
            if qty > 0:
                cash += best_bid * qty
                pos -= qty
                trades += 1
    
    final_mid = ash.iloc[-1]["mid_price"]
    mtm = cash + pos * final_mid
    print(f"  ASH aggressive-mm: trades={trades}, final_pos={pos}, cash={cash:.0f}, mtm_pnl={mtm:.2f}")
    return mtm

def simulate_pepper(df):
    """PEPPER: buy max at first tick, hold forever."""
    pep = df[df["product"] == "INTARIAN_PEPPER_ROOT"].sort_values("timestamp").reset_index(drop=True)
    
    pos = 0
    cash = 0.0
    
    for _, row in pep.iterrows():
        if pos >= LIMIT:
            continue
        # Buy at best ask
        for lvl in [1, 2, 3]:
            ask_p = row.get(f"ask_price_{lvl}")
            ask_v = row.get(f"ask_volume_{lvl}")
            if pd.notna(ask_p) and pd.notna(ask_v) and pos < LIMIT:
                qty = min(int(ask_v), LIMIT - pos)
                if qty > 0:
                    cash -= ask_p * qty
                    pos += qty
    
    final_mid = pep.iloc[-1]["mid_price"]
    mtm = cash + pos * final_mid
    print(f"  PEPPER buy-hold: final_pos={pos}, entry_cost={-cash:.0f}, final_val={pos*final_mid:.0f}, mtm_pnl={mtm:.2f}")
    return mtm


def simulate_ash_only_below_fair(df, fair=10000):
    """
    ONLY buy asks below fair, ONLY sell bids above fair.
    This is the only strategy guaranteed to be profitable per-trade.
    Walk all 3 levels of the book.
    """
    ash = df[df["product"] == "ASH_COATED_OSMIUM"].sort_values("timestamp").reset_index(drop=True)
    
    pos = 0
    cash = 0.0
    buy_trades = 0
    sell_trades = 0
    
    for _, row in ash.iterrows():
        # BUY: take asks that are BELOW fair value
        for lvl in [1, 2, 3]:
            ask_p = row.get(f"ask_price_{lvl}")
            ask_v = row.get(f"ask_volume_{lvl}")
            if pd.notna(ask_p) and pd.notna(ask_v) and ask_p < fair and pos < LIMIT:
                qty = min(int(ask_v), LIMIT - pos)
                if qty > 0:
                    cash -= ask_p * qty
                    pos += qty
                    buy_trades += 1
        
        # SELL: hit bids that are ABOVE fair value
        for lvl in [1, 2, 3]:
            bid_p = row.get(f"bid_price_{lvl}")
            bid_v = row.get(f"bid_volume_{lvl}")
            if pd.notna(bid_p) and pd.notna(bid_v) and bid_p > fair and pos > -LIMIT:
                qty = min(int(bid_v), LIMIT + pos)
                if qty > 0:
                    cash += bid_p * qty
                    pos -= qty
                    sell_trades += 1
    
    final_mid = ash.iloc[-1]["mid_price"]
    mtm = cash + pos * final_mid
    print(f"  ASH below/above-fair: buys={buy_trades}, sells={sell_trades}, final_pos={pos}, mtm_pnl={mtm:.2f}")
    return mtm


print("=" * 60)
print("  REALISTIC EXECUTION SIMULATOR")
print("=" * 60)

total_by_strategy = {}

for day in DAYS:
    print(f"\n--- Day {day} ---")
    df = load_day(day)
    
    print("\n Strategy 1: Mean-reversion (buy ask when mid<fair, sell bid when mid>fair)")
    ash1 = simulate_ash_realistic(df)
    pep = simulate_pepper(df)
    total_by_strategy.setdefault("mean_rev", 0)
    total_by_strategy["mean_rev"] += ash1 + pep
    
    print("\n Strategy 2: Only take profitable sides (buy asks < fair, sell bids > fair)")  
    ash2 = simulate_ash_only_below_fair(df)
    total_by_strategy.setdefault("profitable_only", 0)
    total_by_strategy["profitable_only"] += ash2 + pep
    
    print("\n Strategy 3: Aggressive MM (alternate buy/sell to cycle)")
    ash3 = simulate_ash_aggressive_mm(df)
    total_by_strategy.setdefault("aggressive_mm", 0)
    total_by_strategy["aggressive_mm"] += ash3 + pep
    
    print(f"\n  Day {day} totals: MeanRev={ash1+pep:.0f}, ProfitOnly={ash2+pep:.0f}, AggMM={ash3+pep:.0f}")

print(f"\n{'='*60}")
print("  TOTAL PNL ACROSS ALL DAYS")
print(f"{'='*60}")
for name, pnl in sorted(total_by_strategy.items(), key=lambda x: -x[1]):
    print(f"  {name:20s}: {pnl:>10,.2f}")
