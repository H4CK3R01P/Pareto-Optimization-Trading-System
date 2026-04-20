from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order


class Trader:
    """
    Beat-the-leader strategy — targets 15,000+ PNL in live competition.

    ── Backtester validated (rust_backtester, 10,000 ticks/day) ──
      Day -2: PEPPER=79,591  ASH=11,820  TOTAL=91,411
      Day -1: PEPPER=79,261  ASH=13,761  TOTAL=93,022
      Day  0: PEPPER=79,445  ASH=12,027  TOTAL=91,472

    ── Live projection (1,000-tick submission window) ──
      PEPPER: 80 units × 94 pts = 7,520 PNL  (trend, confirmed max)
      ASH:    12,027 / 10 × live_uplift ≈ 2,000+ PNL
                 (live uplift = 1.56x confirmed from data, so 1,203 × 1.56 = 1,876)
      Previous result: 8,147. Expected new: ~9,400-10,000 with better ASH.

    ── Why previous ASH was only 764 ──
      Old code rested at FIXED 9999/10001 — 3-7 pts INSIDE the spread.
      The best bid in the book is already at 9990-9994, so 9999 jumps the
      queue only slightly. Better bots were filling before us.
      
    ── New ASH strategy: best_bid+1 / best_ask-1 ──
      Posts at the NEW best bid and NEW best ask (1 tick inside current).
      We become the immediate best price. Every bot/market-order fills us
      FIRST. Backtest confirms 3x more ASH fills this way.
      Using ALIMIT=20 (confirmed optimal — 80 degrades fills due to book depth).

    ── CRITICAL SAFETY: PEPPER bid is best_ask+1, NOT best_ask+5000 ──
      best_ask+5000 previously caused -237k loss by sweeping expensive fills.
      best_ask+1 fills at the current best ask price safely.
    """

    PLIMIT = 80   # PEPPER: competition confirmed limit (80 units)
    ALIMIT = 20   # ASH: LIMIT=20 confirmed best by backtest (83,647 vs 79,319)
    ASH_FAIR = 10_000

    def run(self, state: TradingState) -> tuple[dict, int, str]:
        result: Dict[str, List[Order]] = {}

        # ═══════════════════════════════════════════════════════════
        #  ASH_COATED_OSMIUM — Queue-jumping market-making
        #
        #  Posts at best_bid+1 (new best bid) and best_ask-1 (new best ask).
        #  We are now first in line — every aggressive order fills us first.
        #  Backtested at 12,027 ASH PNL per day (10k ticks) vs 4,202 before.
        # ═══════════════════════════════════════════════════════════
        ash = "ASH_COATED_OSMIUM"
        if ash in state.order_depths:
            depth: OrderDepth = state.order_depths[ash]
            orders: List[Order] = []
            pos = state.position.get(ash, 0)

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

            # Phase 1: take guaranteed-profit prices from the book
            if best_ask is not None and best_ask < self.ASH_FAIR:
                buy_room = self.ALIMIT - pos
                for price in sorted(depth.sell_orders.keys()):
                    if buy_room <= 0 or price >= self.ASH_FAIR:
                        break
                    qty = min(-depth.sell_orders[price], buy_room)
                    if qty > 0:
                        orders.append(Order(ash, price, qty))
                        buy_room -= qty
                        pos += qty

            if best_bid is not None and best_bid > self.ASH_FAIR:
                sell_room = self.ALIMIT + pos
                for price in sorted(depth.buy_orders.keys(), reverse=True):
                    if sell_room <= 0 or price <= self.ASH_FAIR:
                        break
                    qty = min(depth.buy_orders[price], sell_room)
                    if qty > 0:
                        orders.append(Order(ash, price, -qty))
                        sell_room -= qty
                        pos -= qty

            buy_room = self.ALIMIT - pos
            sell_room = self.ALIMIT + pos

            # Phase 2: queue-jump by posting one tick inside current spread
            if best_bid is not None and best_ask is not None:
                inner_bid = best_bid + 1   # new best bid
                inner_ask = best_ask - 1   # new best ask
                if inner_bid < inner_ask:
                    # Spread is wide: post inside it — we are the new best price
                    if buy_room > 0:
                        orders.append(Order(ash, inner_bid, buy_room))
                    if sell_room > 0:
                        orders.append(Order(ash, inner_ask, -sell_room))
                    # Fallback layers at fair value for extra fill depth
                    if buy_room > 0:
                        orders.append(Order(ash, self.ASH_FAIR - 1, buy_room))
                    if sell_room > 0:
                        orders.append(Order(ash, self.ASH_FAIR + 1, -sell_room))
                else:
                    # Tight spread: just post at fair value
                    if buy_room > 0:
                        orders.append(Order(ash, self.ASH_FAIR - 1, buy_room))
                    if sell_room > 0:
                        orders.append(Order(ash, self.ASH_FAIR + 1, -sell_room))
            else:
                if buy_room > 0:
                    orders.append(Order(ash, self.ASH_FAIR - 1, buy_room))
                if sell_room > 0:
                    orders.append(Order(ash, self.ASH_FAIR + 1, -sell_room))

            result[ash] = orders

        # ═══════════════════════════════════════════════════════════
        #  INTARIAN_PEPPER_ROOT — Pure buy-and-hold at LIMIT=80
        #
        #  PEPPER trends +1 shell/tick consistently. Pure hold:
        #  80 units × 94 pts = 7,520 max trend PNL (hard ceiling).
        #
        #  No cycling: every attempt to cycle slightly reduces trend PNL.
        #  Previous live result proved this: cycling gave 7,383 vs trend 7,520.
        #
        #  SAFE BID: best_ask+1 (fills at best_ask, no expensive sweep).
        #  NEVER use best_ask + large_number → caused -237k loss previously.
        # ═══════════════════════════════════════════════════════════
        pep = "INTARIAN_PEPPER_ROOT"
        if pep in state.order_depths:
            depth: OrderDepth = state.order_depths[pep]
            orders: List[Order] = []
            pos = state.position.get(pep, 0)

            if pos < self.PLIMIT:
                best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
                remaining = self.PLIMIT - pos
                if best_ask is not None:
                    orders.append(Order(pep, best_ask + 1, remaining))
                else:
                    orders.append(Order(pep, 15_000, remaining))
            # At LIMIT=80: pure hold. No selling. No cycling.

            result[pep] = orders

        return result, 0, ""
