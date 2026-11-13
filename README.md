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
  project tax rate switch, exact vs. additive currency conversion.
- **Manual overrides** for unlevered beta, both corporate tax rates, the USD BBB spread and both 10-year
  yields. The foreign-currency BBB spread can be overridden; when the override is off, the app shows the
  auto-calculated spread.
- **Side-by-side results** (USD vs. foreign currency), an **assumptions** tab, an **all-industry comparison**
  (table + chart), **Excel/CSV downloads**, and a **verification** tab with built-in checks and a step-by-step
  worked example.

**Defaults on launch:** Software (System & Application), United States as target country, U.S. tax rate,
6.5% equity risk premium, 30% debt financing.

## Method

| Step | Formula |
|---|---|
| Debt-to-equity | D/E = w<sub>D</sub> / (1 − w<sub>D</sub>) |
| Levered beta (Hamada) | β<sub>L</sub> = β<sub>U</sub> [1 + (1 − t) D/E] |
| USD cost of equity | k<sub>E</sub><sup>$</sup> = y<sub>US</sub> + β<sub>L</sub> × ERP |
| USD cost of debt | k<sub>D</sub><sup>$</sup> = y<sub>US</sub> + s<sub>BBB</sub> |
| Conversion to foreign currency (exact) | 1 + k<sup>FC</sup> = (1 + k<sup>$</sup>)(1 + y<sub>F</sub>)/(1 + y<sub>US</sub>) |
| Conversion (additive option) | k<sup>FC</sup> = k<sup>$</sup> + (y<sub>F</sub> − y<sub>US</sub>) |
| Foreign cost of debt | k<sub>D</sub><sup>FC</sup> = y<sub>F</sub> + s<sup>FC</sup>; auto s<sup>FC</sup> = converted k<sub>D</sub><sup>$</sup> − y<sub>F</sub>, or a manual override |
| WACC (both currencies) | (1 − w<sub>D</sub>) k<sub>E</sub> + w<sub>D</sub> k<sub>D</sub> (1 − t) |

The same tax rate, debt share and ERP are used in both currencies.

> If the formulas given in class differ from these, edit `cost_of_capital()` in `app.py`; every table,
> chart, download and check uses that single function.

## Verification checks (built into the app)

1. Equal U.S. and foreign 10-year yields (spread override off) ⇒ identical USD and foreign results.
2. Zero debt ⇒ WACC equals cost of equity in both currencies.
3. Overriding the foreign-currency spread leaves all USD results unchanged.

The **Verification** tab also shows each calculation step with the actual numbers so you can reproduce one
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
