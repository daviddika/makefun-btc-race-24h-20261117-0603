# DipCatcher — Strategy

A long-only mean-reversion bot for cbBTC (CBBTC/USDC) on 1-minute bars,
written in Python (stdlib only, deterministic, no clock, no randomness,
no network, no files). Entry: `main.py`, bar data via `vendor/makefun_bars.py`.

## Strategy rules

| Rule | Value |
|---|---|
| Entry | Buy with all cash when the 60-minute return is <= -1.00% |
| Take profit | +1.5% vs the filled entry price (exit whole position) |
| Stop loss | -1.5% vs the filled entry price (exit whole position) |
| Cooldown | 60 bars after an exit before the next entry |
| Loss brake | Stop entering once realised losses reach -$30 |
| Position | Long only, one position, full size |
| Max slippage | 100 bps |

Exit prices are measured against the *filled* entry price, not the signal
price. The 60-bar cooldown prevents the bot from catching the same falling
market twice in a row.

## Why mean reversion on this data

- On 1-minute cbBTC bars the pool price mean-reverts on the hourly scale
  far more often than it trends. Deep hourly dips tend to bounce; chasing
  the trend does not pay here.
- The kit baselines on the same dev window confirm this: every
  trend-following baseline loses or barely breaks even, while the
  mean-reversion bot is the only clearly positive strategy (see results
  table below).
- A round trip costs ~37 bps, so only a deep dip is worth trading. A
  shallow signal would be eaten by costs.

## Cost breakdown (per round trip, ~$1,000 order)

| Component | Cost |
|---|---|
| Fee | ~4 bps |
| Modelled slippage | ~2 bps |
| Constant-product price impact (~$1,000 order) | ~12 bps |
| **Total (approx.)** | **~37 bps** |

The -1.00% entry threshold and +1.5% / -1.5% exits are set so that a
winning trade clears the ~37 bps round-trip cost with margin, while a
losing trade is capped at -1.5% plus costs.

## Fallback entries (guardrail: at least 1 trade per window)

If the window never dips (e.g. a smooth uptrend day), the bot still trades:

- **After bar 1080:** entry threshold relaxes to a 60-minute return of
  -0.50%, or a 120-minute return of >= +0.30%.
- **After bar 1320:** buy at market regardless of the signal.

These fallbacks only relax the entry condition; the take-profit,
stop-loss, cooldown, and slippage limits still apply.

## Dev-window results (1440 bars, $1,000 starting capital)

Verified by `replay.py`, which runs the real `main.py` twice through an
exact integer replica of the harness fill model. Both runs are identical
(deterministic), 6 fills, 0 rejected orders.

| Strategy | Net PnL | Max drawdown |
|---|---|---|
| **DipCatcher (this bot)** | **+$27.32** | **0.72%** |
| Buy-and-hold | +$1.07 | — |
| Momentum | +$2.45 | — |
| EMA-cross | -$106.21 | — |
| ADX-momentum | -$32.66 | — |
| RSI-Bollinger | -$24.25 | — |
| Hold cash | $0.00 | — |

Baselines were graded with the kit's `grade-local` process driver on the
same 1440-bar dev window.

## Guardrails

- **Min 1 trade:** enforced by the fallback entries above (bars 1080 and
  1320). The dev window produced 6 fills without needing the fallbacks.
- **Max drawdown <= 25%:** dev-window max drawdown is 0.72%, far inside
  the limit. Drawdown is further bounded by the -1.5% stop loss per trade
  and the 60-bar cooldown between entries.
- **Loss brake:** if realised losses reach -$30 (about two stopped-out
  round trips), the bot stops entering for the rest of the window. It
  never fired on the dev window (no stop-out there), so it changes
  nothing on dev; it only caps a steady-downtrend day on the race window.

## Determinism

The bot uses float arithmetic on closes only — no clock, no randomness, no
network, no files. The same bars always produce the same orders. Verified:
two independent replay runs of `main.py` produced identical replies
(net PnL +$27.32, maxDD 0.72%, 6 fills, 0 rejected).

## Risks and limits

- Results are for the 1440-bar dev window only; the live 24-hour window
  may behave differently, including a trend day where dips keep falling.
  The -1.5% stop loss and 60-bar cooldown bound the loss per trade, but
  they do not eliminate it.
- The fallback market buy after bar 1320 can enter at an unfavourable
  price in a falling market; it exists only to satisfy the minimum-trade
  guardrail.
