# International Cost of Capital App

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in USD and in the currency of
any selected country**, using live market and reference data.

## Features

- **Live data with sources and dates** (cached; a **🔄 Refresh data** button re-fetches everything):
  | Input | Source |
  |---|---|
  | U.S. industry unlevered betas | Aswath Damodaran, [betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) – "Unlevered beta" column |
  | USD BBB borrowing spread | Aswath Damodaran, [ratings.html](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html) – Baa2/BBB, large non-financial service firms |
  | Statutory corporate tax rates | OECD Corporate Tax Statistics (combined central + sub-central statutory rate, latest year), read from the OECD Data Explorer API, dataset `DSD_TAX_CIT@DF_CIT` |
  | 10-year government bond yields | [Trading Economics](https://tradingeconomics.com/bonds) – scraped (no API key) |
- **User controls:** industry, target country, equity risk premium, target debt share, U.S. vs. foreign
  and a U.S. vs. foreign project tax rate switch.
- **Manual overrides** for unlevered beta, both corporate tax rates, the USD BBB spread and both 10-year
  yields. The foreign-currency BBB spread can be overridden; when the override is off, the app shows the
  auto-calculated spread.
- **Side-by-side results** (USD vs. foreign currency), an **assumptions** tab, an **all-industry comparison**
  (table + chart), **Excel/CSV downloads**, and a **verification** tab with built-in checks and a step-by-step
  worked example.

**Defaults on launch:** Software (System & Application), United States as target country, U.S. tax rate,
6.5% equity risk premium, 30% debt financing.

## Method

The formulas follow the course packet (Rebelo, 2026, "Designing cost of capital app"). An asterisk denotes
the foreign currency; d is the target debt share D/(D + E) and τ the project tax rate.

| Step | Formula |
|---|---|
| Debt-to-equity | D/E = d / (1 − d) |
| Relevered beta | β<sub>E</sub> = β<sub>U</sub> [1 + (1 − τ) D/E] |
| USD cost of equity (CAPM) | R<sub>e</sub> = R<sub>f</sub> + β<sub>E</sub> × ERP |
| USD borrowing cost | R<sub>d</sub> = R<sub>f</sub> + s |
| Conversion factor | F = (1 + R<sub>f</sub>*) / (1 + R<sub>f</sub>) |
| Foreign cost of equity | 1 + R<sub>e</sub>* = (1 + R<sub>e</sub>) × F |
| Foreign spread (default, overridable) | s* = s × F |
| Foreign borrowing cost | R<sub>d</sub>* = R<sub>f</sub>* + s* |
| WACC (each currency) | (1 − d) R<sub>e</sub> + d R<sub>d</sub> (1 − τ) |

Government 10-year yields are the risk-free proxies. The same tax rate, debt share and ERP are used in both
currencies, and there is no separate country equity premium. All formulas live in `cost_of_capital()` in
`app.py`.

## Verification checks (built into the app)

1. Equal U.S. and foreign 10-year yields (spread override off) ⇒ identical USD and foreign results.
2. Zero debt ⇒ WACC equals cost of equity in both currencies.
3. Overriding the foreign-currency spread leaves all USD results unchanged.

The **Verification** tab also reproduces the course packet's Colombia example (WACC 8.5265% in USD and
16.0670% in COP) and shows each calculation step with the actual numbers so you can reproduce one
example independently in a spreadsheet or calculator.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Create a public GitHub repository and upload `app.py`, `requirements.txt` and `README.md`.
2. Go to [share.streamlit.io](https://share.streamlit.io), choose **Create app**, pick the repository, branch
   `main` and main file `app.py`, then **Deploy**.

## Notes and limitations

- Trading Economics occasionally blocks or resets automated requests. The app retries, falls back from the
  `/bonds` overview to the country's own page and to the market table on the U.S. page, and if everything
  fails it asks for a manual yield.
- Damodaran's betas are for U.S. companies; applying them abroad assumes the same business risk.
- For teaching purposes only; verify inputs before relying on the results.
