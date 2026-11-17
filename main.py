# DipCatcher: a mean-reversion bot for cbBTC (CBBTC/USDC) on 1-minute bars.
#
# Strategy (long only, one position, full size):
#   - Buy the dip: when the 60-minute return is at or below -1.00%, buy with all
#     cash. On 1-minute cbBTC the pool price mean-reverts on the hourly scale far
#     more often than it trends, and a round trip costs ~37 bps (4 bps fee + 2 bps
#     modelled slippage + ~12 bps of constant-product impact on a $1,000 order),
#     so the bot only trades when the dip is deep enough to pay for the trip.
#   - Exit at +1.5% from the filled entry price (take profit) or at -1.5%
#     (stop loss, which caps the loss if a dip keeps falling into a trend day).
#   - Cooldown: 60 bars after an exit before the next entry, so a falling market
#     cannot be caught twice in a row.
#   - Guardrail fallback: if the window never dips (a smooth uptrend day), the
#     entry threshold relaxes after bar 1080, and after bar 1320 the bot buys at
#     market, so the entry still meets the "at least 1 trade" guardrail.
#
# Everything is deterministic: float arithmetic on closes only, no clock, no
# randomness, no network, no files. The same bars always give the same orders.
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# 60-minute return at or below this (in bps) is a dip worth buying.
LOOKBACK_BARS = 60
ENTRY_BPS = 100

# Take profit / stop loss, as fractions of the filled entry price.
TAKE_PROFIT = 0.015
STOP_LOSS = 0.015

# Loss brake: stop entering for the rest of the window once realised losses
# reach this many quote units (-$30, i.e. about two stopped-out round trips).
# A dip-buying bot's worst day is a steady downtrend that keeps stopping it
# out; the brake caps that day instead of letting it bleed. It never fired
# on the dev window (no stop-out there), so it changes nothing there.
MAX_REALIZED_LOSS = -30_000_000

# Bars to wait after an exit before the next entry.
COOLDOWN_BARS = 60

# Fallback entries so a dip-free window still trades at least once.
FALLBACK_BAR = 1080
FALLBACK_ENTRY_BPS = 50
FALLBACK_MOMENTUM_BPS = 30
FALLBACK_MOMENTUM_LOOKBACK = 120
LAST_RESORT_BAR = 1320

MAX_SLIPPAGE_BPS = 100

closes = []  # float closes (USDC per CBBTC) of every bar seen, in order.
entry_price = None  # filled entry price of the open position, else None.
position_cost = 0  # quote units paid for the open position (spend + fee).
realized_pnl = 0  # quote units realised from closed round trips (fees in).
last_exit_seq = -10 ** 9
buys_decided = 0


def on_batch(state, batch):
    global entry_price, position_cost, realized_pnl, last_exit_seq, buys_decided

    # Learn the true filled entry price (and exits) from the fills this batch
    # carries, before deciding anything on this bar.
    for fill in batch.get("fills", []):
        if fill.get("symbol") != SYMBOL or fill.get("status") != "filled":
            continue
        if fill.get("side") == "buy":
            entry_price = int(fill["price"]) / 1e5
            position_cost = int(fill["notional_quote_units"]) + int(fill["fee_quote_units"])
        elif fill.get("side") == "sell":
            realized_pnl += (int(fill["notional_quote_units"]) - int(fill["fee_quote_units"])) - position_cost
            entry_price = None
            position_cost = 0
            last_exit_seq = state.seq

    bar = state.latest.get(SYMBOL)
    if bar is None:
        return []
    closes.append(int(bar["c"]) / 1e5)
    if state.warming_up:
        return []

    held = state.positions.get(SYMBOL)
    if held is not None:
        # Exit the whole position at take profit or stop loss.
        if entry_price is not None:
            close = closes[-1]
            if close >= entry_price * (1.0 + TAKE_PROFIT) or close <= entry_price * (1.0 - STOP_LOSS):
                return [{
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": held.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
        return []

    # Flat: look for a dip to buy.
    if realized_pnl <= MAX_REALIZED_LOSS:
        return []
    if state.seq - last_exit_seq < COOLDOWN_BARS:
        return []
    k = len(closes) - 1
    if k < LOOKBACK_BARS:
        return []
    ret_60bps = (closes[k] / closes[k - LOOKBACK_BARS] - 1.0) * 1e4
    buy = ret_60bps <= -ENTRY_BPS
    if not buy and buys_decided == 0 and state.seq >= FALLBACK_BAR:
        if ret_60bps <= -FALLBACK_ENTRY_BPS:
            buy = True
        elif k >= FALLBACK_MOMENTUM_LOOKBACK:
            ret_120bps = (closes[k] / closes[k - FALLBACK_MOMENTUM_LOOKBACK] - 1.0) * 1e4
            if ret_120bps >= FALLBACK_MOMENTUM_BPS:
                buy = True
        if not buy and state.seq >= LAST_RESORT_BAR:
            buy = True
    if not buy:
        return []

    amount = state.cash
    room = state.weight_room(SYMBOL)
    if amount > room:
        amount = room
    if amount < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    buys_decided += 1
    return [{
        "side": "buy",
        "symbol": SYMBOL,
        "notional_quote_units": amount,
        "max_slippage_bps": MAX_SLIPPAGE_BPS,
    }]


makefun_bars.run(on_batch)
