# PSX MCP — Investing Playbook & Data-Gap Critique

*Last updated: 2026-05-23. Compiled from the session experience using the MCP to research PSX Technology & Communication names (SYS, NETSOL, AIRLINK, TRG, PTC, OCTOPUS, etc.) plus widely-studied investing literature. Educational, not investment advice.*

---

## Part 1 — What the MCP can't do today (honest critique)

These are gaps observed while doing real research with the current 24 tools. Each one forced a workaround (external web search, manual computation, or a guess).

### Data coverage gaps

| Missing | Why it matters | Observed pain |
|---|---|---|
| **52-week high/low** | Standard reference for "where am I in the range" | `week52_high` / `week52_low` return `0` for every quote |
| **KSE-100 / KSE-30 / All-Share index values** | Sector and stock returns are meaningless without a benchmark | `get_market_summary` returned nulls even after refresh |
| **News bodies / announcement text** | Got 40 news IDs cached, but `get_news` returned `[]` — only titles or nothing | Couldn't read why SYS adjourned its board meeting |
| **Sector aggregates** | "Show me sector P/E, sector avg RSI, leaders/laggards within sector" | Had to manually probe ~10 symbols to identify tech names |
| **Dividend history** | Yield, payout, growth — core to any income/quality strategy | `div_yield` / `payout` always `null` |
| **Quality metrics** | ROE, ROA, ROIC, debt/equity, current ratio — fundamental quality filters | `roe` / `pb` always `null` |
| **Volume averages (20d, 50d)** | Today's volume only means something relative to baseline | `scan_volume_spikes` exists but raw avg isn't exposed |
| **Free float % / shares outstanding history** | Detect dilution, bonus issues | `free_float` partially populated, no history |
| **Corporate actions calendar** | Bonus shares, splits, rights, dividend ex-dates | No tool; SYS FY24 EPS looks "crashed" without action history |
| **Insider / director transactions** | Strongest short-term signal in EM markets | No tool |
| **Earnings calendar** | When does NETSOL report? Catalyst dates | No tool |
| **Macro feed** | USD/PKR, SBP policy rate, CPI, oil — drive 50%+ of PSX returns | No tool |
| **Analyst consensus / target prices** | Had to web-search to find SYS sell-side PT Rs 213 | No tool |

### Tool design issues

- **`search_symbol`** seemed to match only exact-symbol substrings (`SYS` worked, `TRG`/`NETSOL` returned `[]` despite being cached). Fix: also index name and sector.
- **`get_quote`** returns `stale=true` for known-active symbols (SYS, AVN) right after `refresh_market` — suggests refresh isn't covering all 486 rows uniformly, or the staleness check is wrong.
- **`compute_indicators`** requires explicit `indicators` list with no default — first call errored. Default to a sensible bundle (`["sma20","sma50","sma200","rsi14","atr14"]`).
- **`compare_symbols`** returned `null` for `change_pct` and `volume` even when `get_quote` had them — joining bug.
- **No screening tool** — can't ask "all symbols in TECHNOLOGY & COMMUNICATION with PE < 15 and RSI between 40 and 60." This is the single biggest workflow gap.

---

## Part 2 — Investing strategies that have held up in academic study

Frameworks ranked by evidence and applicability to PSX. Each lists the variables you'd need (and which the MCP exposes today).

### A. Value (Graham / Buffett / Fama-French HML)

**Core idea:** Buy cash flows cheaply; mean reversion is real. The value premium has been documented since Graham (1934) and quantified by Fama & French (1992).

**Signals:**
- **Earnings yield** = EPS / Price (inverse of P/E). High = cheap.
- **Book yield** = BV / Price. Fama-French HML factor.
- **FCF yield** = FCF / EV. Robust to accounting tricks.
- **EV / EBITDA**. Capital-structure-neutral.
- **Dividend yield** with payout coverage.

**Threshold rules of thumb (developed markets, adjust down for PSX):**
- Earnings yield > 10y bond yield + risk premium → attractive
- P/B < 1.5 with positive ROE → classic deep value
- Avoid "value traps": low P/E + falling EPS + rising debt

**PSX caveat:** PE of 1 on TRG was a one-time gain — always verify *trailing 5y* earnings power before trusting a low multiple.

**MCP exposes:** P/E, EPS. **Missing:** P/B, FCF, EV/EBITDA, multi-year EPS for trap detection (financials gives 4 yrs — usable!).

---

### B. Quality (Buffett / Joel Greenblatt / AQR QMJ)

**Core idea:** High-quality businesses compound; pay up moderately for them. Asness, Frazzini & Pedersen (2019) showed Quality-Minus-Junk earns positive returns globally.

**Signals:**
- **ROE / ROIC** ≥ 15% sustained
- **Gross margin** stable or expanding
- **Net debt / EBITDA** < 3
- **EPS variability** (std dev / mean) low
- **Accruals** low (cash earnings > reported earnings)

**Greenblatt's Magic Formula:**
1. Rank universe by **earnings yield** (cheap)
2. Rank universe by **ROIC** (quality)
3. Combined rank → top decile is the portfolio
4. Hold ~30 names, rebalance annually

This is **directly buildable on the MCP** once ROE/ROIC are added.

**MCP exposes:** Gross/Net margin from financials. **Missing:** ROE, ROIC, debt ratios.

---

### C. Momentum (Jegadeesh & Titman 1993; AQR UMD)

**Core idea:** Past winners outperform past losers over 3–12 months. One of the most replicated anomalies in finance.

**Signals:**
- **12-1 month return** (skip the most recent month to avoid 1-month reversal)
- **Risk-adjusted momentum**: 12-1 return / 12-month volatility
- **Relative strength**: stock return − sector return

**Trade rule (classic):** Long top-decile 12-1 momentum, hold 1–6 months, monthly rebalance.

**PSX caveat:** Liquidity matters — momentum on thin names produces fake signals. Filter for avg daily volume > a threshold (e.g., Rs 50M turnover).

**MCP exposes:** History (compute 12-1 manually). **Missing:** Built-in `rank_momentum` tool, turnover filter.

---

### D. Trend following (Faber's GTAA, Antonacci dual momentum)

**Core idea:** Trends persist; a simple SMA filter cuts ~half of equity drawdowns historically. Faber (2007) "Quantitative Approach to Tactical Asset Allocation."

**Signals:**
- **SMA10 monthly** (≈ SMA200 daily): if price < SMA200, exit equity; if >, hold
- **SMA20 / SMA50 / SMA200 stack**: bullish when 20 > 50 > 200
- **Donchian channel breakout**: new 20-day or 55-day high

This is the *simplest* strategy with real evidence. Excellent fit for PSX retail because it doesn't require deep fundamentals.

**MCP exposes:** `compute_indicators` with SMA20/50/200. ✅ Already supported.

**Missing:** ATR-based stops, Donchian, MACD, ADX (trend strength). Stack-detection helper would be nice.

---

### E. Mean reversion (DeBondt & Thaler 1985)

**Core idea:** 3–5 year losers beat 3–5 year winners. Long-horizon contrarian play.

**Signals:**
- 5-year return percentile rank (low = candidate)
- Combined with positive accounting catalyst (earnings turn, debt paydown)

**Short-horizon variant:** RSI < 30 + above-200-SMA = oversold pullback in uptrend.

**MCP exposes:** RSI14, sufficient history. **Missing:** Long-horizon return ranks.

---

### F. Low-volatility / "Betting against beta" (Frazzini & Pedersen 2014)

**Core idea:** Low-beta stocks earn higher risk-adjusted returns than CAPM predicts. Works because constrained investors lever up by buying high-beta — bidding them up and leaving low-beta cheap.

**Signals:**
- **Beta vs KSE-100** over 252 trading days
- **Idiosyncratic volatility** (residual after market beta)

Build a low-vol basket → competitive Sharpe with lower drawdowns.

**MCP exposes:** Nothing directly. **Missing:** Beta computation, vol stats.

---

### G. Piotroski F-Score (2000)

**Core idea:** A 9-point fundamental checklist that screens value stocks for improving health. Top deciles of "high F-score among low P/B" earned ~7.5% alpha in Piotroski's original study.

**The 9 points (1 if yes, 0 if no):**
1. Net income > 0
2. CFO > 0
3. ROA improving YoY
4. CFO > Net income (accrual quality)
5. Lower long-term debt YoY
6. Higher current ratio YoY
7. No new share issuance
8. Gross margin improving YoY
9. Asset turnover improving YoY

Score 8–9 → buy. Score 0–2 → avoid/short.

**Buildability:** Half-buildable today (sales, profit, gross margin, EPS for 4 yrs are in `get_financials`). Need balance-sheet items: total assets, current ratio, LT debt, shares outstanding. All scrapeable from PSX DPS.

---

### H. Sector rotation (relative strength)

**Core idea:** Different sectors lead different parts of the cycle. Rotate into the strongest relative-strength sectors.

**Signals:**
- Sector return − KSE-100 return (3m, 6m)
- Sector breadth: % of sector members above SMA200

**For PSX 2026 context:** AKD Research flagged Banks, E&P, Fertilizers, Cement, Tech as FY27 leaders. A relative-strength tool would let you confirm/reject this in real time.

**MCP missing:** Sector aggregates, breadth.

---

### I. Position sizing & risk

These are not "alpha" strategies but determine whether any of the above survives a bad year.

- **Kelly criterion (fractional):** position size = edge / odds. Use 1/4 or 1/2 Kelly in practice.
- **Fixed fractional:** risk 1–2% of portfolio per trade. Position size = (risk budget × portfolio) / (entry − stop).
- **ATR-based stop:** stop = entry − 2 × ATR(14). Built-in to most trend systems.
- **Volatility targeting:** scale exposure inversely to recent vol so portfolio vol is constant.
- **Max concentration:** no single name > 10%, no sector > 30%, for retail concentrated portfolios.

**MCP missing:** ATR, vol stats, portfolio simulation tools.

---

## Part 3 — How to combine these for a PSX retail workflow

A practical synthesis the MCP could *almost* support today:

### The "PSX 4-quadrant" weekly scan

For every symbol with adequate liquidity (e.g., 30d avg turnover > Rs 50M):

1. **Value quadrant:** P/E < sector median AND P/B < sector median (need P/B added)
2. **Quality quadrant:** Net margin > sector median AND positive EPS growth 2 of last 3 years
3. **Momentum quadrant:** 6m return > 0 AND price > SMA200 AND 20 > 50 SMA
4. **Trend quadrant:** RSI 40–70 AND price > SMA50

A name showing up in **3 of 4 quadrants** is a high-conviction candidate. Two quadrants = watchlist. One or zero = ignore.

This is the kind of multi-factor scoring that's well-supported by both academic research (Fama-French 5-factor + momentum, AQR's "Style Premia") and survives most regimes.

### Reapplied to today's basket

Reviewing the picks (NETSOL, AIRLINK, SYS) through this lens:

- **NETSOL** — Value ✅ (PE 5.74), Quality ⚠ (EPS −24% last yr), Momentum ✅ (20>50 SMA), Trend ✅ (RSI 52, near SMA200) → **3/4**
- **AIRLINK** — Value ⚠ (PE 15.7, sector midrange), Quality ⚠ (revenue −19.6%), Momentum ✅, Trend ⚠ (below SMA200) → **1.5/4**
- **SYS** — Value ✗ (PE 27.5), Quality ✅ (consistent margins, growing sales), Momentum ✅ (uptrending SMAs), Trend ✅ → **3/4**

By this scorecard SYS and NETSOL are stronger picks than AIRLINK — consistent with the analyst consensus on SYS (target Rs 213) and matches the cheaper-quality story on NETSOL.

---

## Part 4 — Free data sources to integrate (highest leverage first)

### Tier 1: PSX official endpoints (already partially used)

| Endpoint | What it gives | Effort |
|---|---|---|
| `dps.psx.com.pk/sector-summary` | Sector-level P/E, market cap, breadth | Low — HTML scrape |
| `dps.psx.com.pk/screener` | Pre-built filters (top dividend yield, top P/E, etc.) | Low |
| `dps.psx.com.pk/historical` | OHLCV (already used) | Done |
| `dps.psx.com.pk/announcements` | Corporate actions, board meetings (already used) | Done — but body text isn't being saved |
| `dps.psx.com.pk/indices` | KSE-100, KSE-30, KMI-30, All-Share | Low — fix the null index data |
| `dps.psx.com.pk/timeseries/eod/<INDEX>` | **JSON EOD series for an index** (confirmed via probe 2026-05-24: 200 OK, `application/json`, payload shape `{status, message, data:[[unix_ts, close, volume, ?metric], ...]}`) | Low — direct JSON, no scrape |
| `dps.psx.com.pk/timeseries/int/<INDEX>` | **JSON intraday series for an index** (confirmed via probe 2026-05-24: 200 OK, `application/json`, payload `{status, message, data:[[unix_ts, level, volume], ...]}`) | Low — direct JSON |
| `dps.psx.com.pk/dividends` | Dividend history per symbol | Low |
| `dps.psx.com.pk/board-meetings` | Earnings calendar | Low |

### Tier 2: Macro (free, official)

| Source | Data | URL |
|---|---|---|
| **SBP** | Policy rate, FX reserves, M2, monetary policy statements | `sbp.org.pk/ecodata/index2.asp` |
| **PBS** | CPI, WPI, industrial production, trade balance | `pbs.gov.pk` |
| **SBP** | USD/PKR daily reference rate | `sbp.org.pk/ecodata/rates/m2m/M2M-Current.asp` |
| **exchangerate.host** | Cross-checked FX, free API | `api.exchangerate.host` |
| **EIA** | Brent / WTI oil prices (Pakistan macro driver) | `eia.gov/dnav/pet/` |

### Tier 3: Third-party aggregators (free tiers)

| Source | What it adds | Caveat |
|---|---|---|
| **Sarmaaya.pk** | Analyst targets, broker research summaries | Scrape, rate-limited |
| **scstrade.com** | Fundamentals snapshot (PE, ROE, BV) — confirmed coverage of NETSOL/SYS | Scrape |
| **Mettis Global free** | News headlines | Limited |
| **Business Recorder** | News RSS feed | Free RSS available |
| **Dawn Business RSS** | News RSS feed | Free |
| **Investing.com Pakistan** | Analyst consensus, technical summaries | Scrape, ToS — keep gentle |
| **TradingView** | Webhook alerts (free tier) | Outbound only |

### Tier 4: Derived/computed (no new source needed)

Compute from history table the MCP already has:

- 52-week high/low (rolling max/min of 252 daily closes)
- 20-day avg volume (and "volume Z-score" today vs baseline)
- ATR(14), Bollinger bands, MACD, ADX
- Beta vs KSE-100 (once index series is fixed)
- 3m/6m/12m returns, drawdown from 52w high
- Vol-of-vol, realized vol
- Sector relative strength

---

## Part 5 — Proposed new MCP tools (priority-ranked)

### P0 — Fixes / extensions to existing tools

1. **Fix `get_market_summary`** to populate index values (refresh path is broken).
2. **Fix `search_symbol`** to fuzzy-match name and sector, not just symbol prefix.
3. **Save announcement bodies** in `refresh_announcements` so `get_announcements` returns useful text.
4. **Populate `week52_high/low`** by computing rolling max/min from history table.
5. **Add defaults to `compute_indicators`** — sensible bundle when none specified.

### P1 — Highest-value new tools

| Tool | Signature | Purpose |
|---|---|---|
| `screen_symbols` | `(filters: dict, sector?, min_turnover?)` | The single missing primitive. Multi-criteria screener. |
| `get_sector_summary` | `(sector: str)` | Sector PE, breadth (% above SMA200), top/bottom 5 by return |
| `get_macro` | `()` | SBP policy rate, USD/PKR, CPI YoY, Brent, KSE-100 1y/YTD |
| `get_corporate_actions` | `(symbol, since?)` | Bonus, split, rights, dividend ex-date history |
| `get_earnings_calendar` | `(window_days=30)` | Upcoming board meetings / results dates |
| `get_dividend_history` | `(symbol)` | Per-share, yield, payout ratio, growth |
| `get_analyst_consensus` | `(symbol)` | Mean/high/low target, # buy/hold/sell |

### P2 — Strategy primitives

| Tool | Signature | Purpose |
|---|---|---|
| `compute_quality_score` | `(symbol)` | Piotroski F-score variant (1–9) |
| `compute_value_score` | `(symbol)` | Combined EY + BY + FCFY rank within sector |
| `compute_momentum_score` | `(symbol)` | 12-1 risk-adjusted return, percentile |
| `compute_4quadrant_score` | `(symbol)` | The synthesis from Part 3 |
| `rank_symbols` | `(by: "value"\|"quality"\|"momentum"\|"composite", sector?)` | Cross-sectional ranking |
| `compute_beta` | `(symbol, window=252)` | Beta vs KSE-100 |
| `simulate_basket` | `(weights: dict, since)` | Backtest a basket against KSE-100 |

### P3 — News & sentiment

| Tool | Signature | Purpose |
|---|---|---|
| `get_news_feed` | `(query?, since?, sources?=["br","dawn","tribune"])` | Aggregated RSS from BR / Dawn / Tribune business desks |
| `summarize_news` | `(symbol, window_days=7)` | Headline-only summary; use the LLM, don't hardcode rules |
| `track_insider_trades` | `(symbol?)` | Director/sponsor transactions from PSX disclosures |

### P4 — Risk & alerts

| Tool | Signature | Purpose |
|---|---|---|
| `compute_position_size` | `(symbol, portfolio_value, risk_pct, stop_atr_mult)` | ATR-based sizing |
| `set_macro_alert` | `(metric: "policy_rate"\|"usdpkr"\|"kse100", rule)` | Move beyond per-symbol alerts |
| `compute_drawdown` | `(symbol)` | Current draw from 52w high, max DD trailing |

---

## Part 6 — Implementation roadmap

A pragmatic order that maximizes return on engineering hours:

**Week 1 — Fix the low-hanging data gaps**
- 52w high/low (derived from existing history)
- `get_market_summary` index population
- `compute_indicators` defaults
- Announcement bodies persisted

**Week 2 — Add the screener**
This unlocks 80% of the workflow value. Even a simple SQL-backed `screen_symbols` with PE/RSI/SMA filters changes the day-to-day from "guess 10 tickers" to "ask the question."

**Week 3 — Macro feed**
SBP scrape (policy rate + USD/PKR), one PBS scrape for CPI. Small footprint, huge analytical value — IT-exporter theses live or die on USD/PKR.

**Week 4 — Quality/value/momentum scoring**
Build on the financials already cached. F-score is the showcase win.

**Week 5+ — News aggregation**
Three RSS feeds (BR, Dawn, Tribune) + a per-symbol headline filter. Avoid sentiment modeling — use the LLM at query time.

---

## Part 7 — Things to consciously *not* do

Stay disciplined about scope:

- **No order placement / portfolio P&L tracking.** Already an explicit non-goal in the project spec; brokers do this better.
- **No paid feeds** (Mettis Premium, Bloomberg). Defeats the "free data" constraint.
- **No predictive ML models.** Free PSX history is too thin and biased. Stick to academically-validated rules.
- **No sentiment scoring on Pakistani news.** Tooling for Urdu/English mixed financial text is poor and the signal is weak. Let the LLM read headlines at query time.
- **No real-time tick data.** 15-min delay is fine for the swing/position horizons these strategies target.

---

## Appendix — Key references

**Academic foundations:**
- Graham, B. *The Intelligent Investor* (1949)
- Fama & French (1992) "The Cross-Section of Expected Stock Returns" — value factor
- Jegadeesh & Titman (1993) "Returns to Buying Winners and Selling Losers" — momentum
- Piotroski (2000) "Value Investing: The Use of Historical Financial Statement Information" — F-score
- Greenblatt, J. *The Little Book That Beats the Market* (2005) — Magic Formula
- DeBondt & Thaler (1985) "Does the Stock Market Overreact?" — long-horizon reversal
- Faber, M. (2007) "A Quantitative Approach to Tactical Asset Allocation"
- Frazzini & Pedersen (2014) "Betting Against Beta"
- Asness, Frazzini & Pedersen (2019) "Quality Minus Junk"

**PSX/Pakistan specific:**
- AKD Research, Topline Securities, Arif Habib, Optimus annual strategy reports — search for the December outlooks each year, all publish for free
- SBP Monetary Policy Statements (quarterly)
- PSX Annual Report (sector composition, free float methodology)
