# LNG Trading Desk

A quant + trading platform for pricing physical LNG, building forward curves, valuing optionality (intrinsic + extrinsic), measuring risk, and generating trading ideas around global gas underlyings.

## Coverage

- **Hubs**: TTF, NBP, THE, Henry Hub, JKM, oil-indexed slope contracts (Brent).
- **Physical**: DES Japan/Korea/Taiwan/China/NWE, FOB US Gulf/Qatar/Australia.
- **Freight**: Spark25S Atlantic, Spark30S Pacific, basin spreads.
- **Optionality**: storage, swing, destination flex, cancellation rights, diversion.

## The team (subagents in `.claude/agents/`)

Invoke via the Agent tool with `subagent_type: <name>`. Each agent has a tight remit — see the file for "what they do not do" boundaries.

| Agent | Role | When to call |
|---|---|---|
| **finn** | Data Retrieval | "fetch X", "pull Y curve", concrete data download |
| **nora** | Data Sources Specialist | "where do I get X", "which source for Y" |
| **vance** | Python Architect | codebase structure, module boundaries, refactors |
| **eva** | Risk & VaR Specialist | methodology design, stress framework, limits |
| **kai** | VaR Runner | daily risk runs, EOD reports, limit checks |
| **marti** | LNG Quant | curves, physical pricing, intrinsic/extrinsic optionality |
| **johan** | LNG Analyst | fundamentals, supply/demand, idea generation |
| **alex** | Head of Desk | deal approval, capital allocation, escalations |
| **daniel** | Senior Trader | execution, deal structuring, hedge selection, market color |
| **lena** | LNG Infrastructure Analyst | facilities DB, capacity tracking, project schedule, disruptions, Excel report |

### Typical flows

- **New trade idea**: johan pitches → marti prices → daniel structures + finds liquidity → eva/kai check risk impact → alex approves.
- **Daily ops**: finn pulls curves → marti marks book → kai runs VaR → alex reviews flag list.
- **New product**: nora picks data source → finn integrates → vance scaffolds code → marti builds the model → eva extends risk → kai puts it into the daily run.

## Repo layout

```
src/lng_desk/
├── core/         # units, calendars, tz, half-month windows, market snapshots
├── data/         # source adapters (Platts, ICE, Spark, AGSI+, EIA, etc.)
├── curves/       # forward curve construction per hub + freight
├── pricing/
│   ├── physical/ # DES/FOB cargo PV
│   ├── intrinsic/# rolling intrinsic for storage / swing / destination flex
│   └── extrinsic/# LSM Monte Carlo, spread options
├── freight/      # voyage, boil-off, route choice
├── risk/         # VaR engines, ES, stress, scenarios, attribution
├── trades/       # trade records, position store
├── analytics/    # P&L attribution, MtM
└── ideas/        # systematic idea generation

data/raw/<source>/<date>/        # Finn writes here (raw, with .meta.json)
data/processed/                   # curves, snapshots
data/reference/lng_facilities/    # Lena's CSV DB (liquefaction, regas, disruptions)
data/reports/                     # generated reports (lng_facilities.xlsx, etc.)
reports/risk/YYYY-MM-DD.md        # Kai writes here
docs/risk/                        # Eva writes methodology here
deals/<deal_name>/                # per-deal folder (deal.csv + curves.csv)
notebooks/                        # exploratory analysis
tests/                            # pytest, including golden-file pricing tests
```

## Conventions

- All prices carry a currency and a unit (USD/MMBtu, EUR/MWh, USD/day). Never bare floats.
- All timestamps stored UTC, rendered local at boundaries.
- JKM uses half-month windows (H1/H2). Don't conflate with monthly.
- Every priced number traces to a `MarketSnapshot(id, ts, sources)`.
- Pricing functions are pure: `(trade, snapshot) → result`. No I/O inside.
- Adapters at the edges; the rest of the code talks to a normalized internal schema.

## Setup decisions

**Locked:**
- **JKM benchmark**: Platts JKM (S&P Global Commodity Insights). Half-month windows (H1/H2). Contract-grade reference for any DES Asia counterparty work.
- **Storage layer**: Parquet files only. No DB. Time series, snapshots, trade records all in Parquet under `data/`. Revisit if/when concurrent writes or audit requirements emerge.
- **Idea generation focus** (Johan): Atlantic basin (TTF, NBP, HH, US exports, NWE regas, Atlantic freight) and inter-basin arb (JKM-TTF spread, FOB US destination flex, basin freight imbalance). Pure Pacific work secondary for now.

**Still open:**
- [ ] Other data entitlements (Argus cross-check? Kpler vs Vortexa? Spark direct vs delayed?)
- [ ] Risk limits in absolute terms ($) and per-hub DV01
- [ ] P&L thresholds for escalation to Alex
- [ ] Counterparty list and exposure caps
