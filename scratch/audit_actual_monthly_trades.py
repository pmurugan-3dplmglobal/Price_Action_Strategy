import json

# Comprehensive list of all real executed broker trades over the last month (Sep 01 - Oct 01, 2026)
actual_trades = [
    {"date": "2026-09-01", "symbol": "ABCAPITAL", "contract": "ABCAPITAL26SEP410CE", "side": "CE", "entry": 7.10, "exit": 5.75, "qty": 3100, "pnl": -4185.00, "pnl_pct": -19.01, "cause": "Option Chart Illusion (Spot < 44 EMA) + OTM Drag"},
    {"date": "2026-09-01", "symbol": "ANGELONE", "contract": "ANGELONE26SEP285CE", "side": "CE", "entry": 10.90, "exit": 9.85, "qty": 2500, "pnl": -2625.00, "pnl_pct": -9.63, "cause": "Counter-trend buy in Daily Downtrend (Spot < 13/44 EMA)"},
    {"date": "2026-09-01", "symbol": "SOLARINDS", "contract": "SOLARINDS26SEP19750PE", "side": "PE", "entry": 365.35, "exit": 468.15, "qty": 50, "pnl": 5140.00, "pnl_pct": 28.14, "cause": "Clean Macro-Aligned Trend Win"},
    {"date": "2026-09-01", "symbol": "AXISBANK", "contract": "AXISBANK26SEP1300PE", "side": "PE", "entry": 39.00, "exit": 40.75, "qty": 625, "pnl": 1093.75, "pnl_pct": 4.49, "cause": "Favorable Live Tick Fill on Candle Close SL"},
    {"date": "2026-09-01", "symbol": "NIFTY", "contract": "NIFTY2690124050CE", "side": "CE", "entry": 31.35, "exit": 31.30, "qty": 65, "pnl": -3.25, "pnl_pct": -0.16, "cause": "Zero Risk Breakeven Scratch"},
    {"date": "2026-09-01", "symbol": "NIFTY", "contract": "NIFTY2690123950CE", "side": "CE", "entry": 176.10, "exit": 159.95, "qty": 65, "pnl": -1049.75, "pnl_pct": -9.17, "cause": "Weekly Expiry Chop at 24,150 Call Wall"},
    {"date": "2026-09-23", "symbol": "ASIANPAINT", "contract": "ASIANPAINT26OCT2460CE", "side": "CE", "entry": 21.15, "exit": 24.75, "qty": 250, "pnl": 1037.50, "pnl_pct": 19.62, "cause": "Clean Point D Breakout T1 Hit"},
    {"date": "2026-09-23", "symbol": "POWERGRID", "contract": "POWERGRID26OCT265CE", "side": "CE", "entry": 7.50, "exit": 7.70, "qty": 1900, "pnl": 380.00, "pnl_pct": 2.67, "cause": "Premature Manual 1-Click Scalp (Ran to 9.50 / +26%)"},
    {"date": "2026-09-23", "symbol": "NAUKRI", "contract": "NAUKRI26SEP1300PE", "side": "PE", "entry": 14.80, "exit": 8.35, "qty": 500, "pnl": -3217.50, "pnl_pct": -43.50, "cause": "Premature Option Tick SL (Exploded to 17.70 / +112%)"},
    {"date": "2026-09-23", "symbol": "MIDCPNIFTY", "contract": "MIDCPNIFTY26OCT14550CE", "side": "CE", "entry": 106.90, "exit": 88.80, "qty": 120, "pnl": -2172.00, "pnl_pct": -16.93, "cause": "09:18 AM Opening Whipsaw + Margin Rejection on Leg 2"},
    {"date": "2026-09-23", "symbol": "SENSEX", "contract": "SENSEX26OCT74700CE", "side": "CE", "entry": 237.25, "exit": 242.25, "qty": 20, "pnl": 100.00, "pnl_pct": 2.11, "cause": "Quick Micro-Scalp Profit Lock"},
    {"date": "2026-09-23", "symbol": "ULTRACEMCO", "contract": "ULTRACEMCO26OCT11000PE", "side": "PE", "entry": 193.45, "exit": 172.25, "qty": 50, "pnl": -1060.00, "pnl_pct": -10.96, "cause": "Structural Invalidation Saved Loss (Spot broke 11,100)"},
    {"date": "2026-09-23", "symbol": "TMPV", "contract": "TMPV26OCT300PE", "side": "PE", "entry": 9.00, "exit": 8.25, "qty": 1600, "pnl": -1200.00, "pnl_pct": -8.33, "cause": "Dynamic Slot Swap to fund R:R 4.06 setup"},
    {"date": "2026-09-28", "symbol": "BAJAJ-AUTO", "contract": "BAJAJ-AUTO26OCT11100PE", "side": "PE", "entry": 219.00, "exit": 248.30, "qty": 75, "pnl": 2197.50, "pnl_pct": 19.22, "cause": "Clean Candle Close Target Hit"},
    {"date": "2026-09-28", "symbol": "NIFTY", "contract": "NIFTY26SEP23000CE", "side": "CE", "entry": 70.00, "exit": 41.20, "qty": 65, "pnl": -2340.00, "pnl_pct": -41.14, "cause": "5-Minute Emergency Hard SL Opening Noise"},
    {"date": "2026-09-28", "symbol": "ASTRAL", "contract": "ASTRAL26OCT1400CE", "side": "CE", "entry": 42.80, "exit": 31.75, "qty": 425, "pnl": -4696.25, "pnl_pct": -25.82, "cause": "Multi-Day Weekend Theta Bleed in Stagnant Base"},
    {"date": "2026-09-28", "symbol": "GMRAIRPORT", "contract": "GMRAIRPORT26OCT99CE", "side": "CE", "entry": 3.20, "exit": 2.07, "qty": 7000, "pnl": -7881.75, "pnl_pct": -35.31, "cause": "Low-Priced OTM Drag + Theta Erosion"},
    {"date": "2026-10-01", "symbol": "ULTRACEMCO", "contract": "ULTRACEMCO26OCT10900PE", "side": "PE", "entry": 212.45, "exit": 345.15, "qty": 50, "pnl": 6635.00, "pnl_pct": 62.46, "cause": "Overnight Multi-Day Runner Clean Target Win"},
    {"date": "2026-10-01", "symbol": "360ONE", "contract": "360ONE26OCT1040CE", "side": "CE", "entry": 38.40, "exit": 26.80, "qty": 500, "pnl": -5800.00, "pnl_pct": -30.21, "cause": "Exited in panic dump @ 26.80; missed 21.00 re-entry, rallied to 33.75"},
    {"date": "2026-10-01", "symbol": "LICI", "contract": "LICI26OCT395CE", "side": "CE", "entry": 11.70, "exit": 8.65, "qty": 1400, "pnl": -4270.00, "pnl_pct": -26.07, "cause": "Structural Invalidation Saved Loss (Spot below VWAP, fell to 6.10)"},
    {"date": "2026-10-01", "symbol": "NIFTY", "contract": "NIFTY26O0622500CE", "side": "CE", "entry": 140.00, "exit": 100.00, "qty": 65, "pnl": -2600.00, "pnl_pct": -28.57, "cause": "220 pts OTM midday chop trap"},
    {"date": "2026-10-01", "symbol": "NIFTY", "contract": "NIFTY26O0622300CE", "side": "CE", "entry": 159.50, "exit": 220.80, "qty": 65, "pnl": 3984.50, "pnl_pct": 38.43, "cause": "ATM Precision Reversal Win (Open Runner)"}
]

wins = [t for t in actual_trades if t['pnl'] > 0]
losses = [t for t in actual_trades if t['pnl'] < 0]
breakevens = [t for t in actual_trades if t['pnl'] == 0]

tot_pnl = sum(t['pnl'] for t in actual_trades)
tot_wins = sum(t['pnl'] for t in wins)
tot_losses = sum(t['pnl'] for t in losses)

avg_win = tot_wins / len(wins) if wins else 0
avg_loss = tot_losses / len(losses) if losses else 0
avg_win_pct = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
avg_loss_pct = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0

win_rate = len(wins) / len(actual_trades) * 100

print("=== DEEP FORENSIC AUDIT OF ACTUAL BROKER TRADES (PAST MONTH) ===")
print(f"Total Trades Executed: {len(actual_trades)}")
print(f"Winning Trades: {len(wins)} ({win_rate:.1f}%)")
print(f"Losing Trades: {len(losses)} ({len(losses)/len(actual_trades)*100:.1f}%)")
print(f"Gross Profit from Wins: +Rs {tot_wins:,.2f}")
print(f"Gross Loss from Losses: -Rs {abs(tot_losses):,.2f}")
print(f"NET REALIZED BROKER P&L: Rs {tot_pnl:,.2f}")

print("\n--- THE MATHEMATICAL ROOT CAUSE (PAYOFF INVERSION) ---")
print(f"Average Win Amount: +Rs {avg_win:,.2f} (+{avg_win_pct:.1f}%)")
print(f"Average Loss Amount: -Rs {abs(avg_loss):,.2f} ({avg_loss_pct:.1f}%)")
print(f"Loss-to-Win Asymmetry Ratio: {abs(avg_loss) / avg_win:.2f}x")
print(f"Required Win Rate to Break Even: {(abs(avg_loss) / (avg_win + abs(avg_loss))) * 100:.1f}%")

with open('scratch/actual_trades_full_summary.json', 'w') as f:
    json.dump(actual_trades, f, indent=2)
