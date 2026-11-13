"""
International Cost of Capital App
---------------------------------
Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

Data sources (fetched live, cached, refreshable):
  * Unlevered industry betas  - Aswath Damodaran, betas.xls (U.S. companies)
  * BBB (Baa2) USD spread     - Aswath Damodaran, ratings.html (large non-financial firms)
  * Statutory corporate tax   - OECD Corporate Tax Statistics (combined central + sub-central rate)
  * 10-year government yields - Trading Economics
"""

from __future__ import annotations

import io
import re
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
st.set_page_config(page_title="International Cost of Capital", page_icon="🌍", layout="wide")

BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html"
OECD_PAGE_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/"
    "statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb"
)
OECD_API_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/........."
    "?startPeriod={start}&format=csvfilewithlabels"
)
TE_BONDS_URL = "https://tradingeconomics.com/bonds"
TE_COUNTRY_URL = "https://tradingeconomics.com/{slug}/government-bond-yield"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 25

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"
DEFAULT_ERP = 6.5   # percent
DEFAULT_DEBT = 30   # percent of capital

# Country name -> (ISO3 code used by OECD, Trading Economics URL slug, currency code)
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "United States": ("USA", "united-states", "USD"),
    "Australia": ("AUS", "australia", "AUD"),
    "Austria": ("AUT", "austria", "EUR"),
    "Belgium": ("BEL", "belgium", "EUR"),
    "Brazil": ("BRA", "brazil", "BRL"),
    "Bulgaria": ("BGR", "bulgaria", "BGN"),
    "Canada": ("CAN", "canada", "CAD"),
    "Chile": ("CHL", "chile", "CLP"),
    "China": ("CHN", "china", "CNY"),
    "Colombia": ("COL", "colombia", "COP"),
    "Croatia": ("HRV", "croatia", "EUR"),
    "Czech Republic": ("CZE", "czech-republic", "CZK"),
    "Denmark": ("DNK", "denmark", "DKK"),
    "Egypt": ("EGY", "egypt", "EGP"),
    "Finland": ("FIN", "finland", "EUR"),
    "France": ("FRA", "france", "EUR"),
    "Germany": ("DEU", "germany", "EUR"),
    "Greece": ("GRC", "greece", "EUR"),
    "Hong Kong": ("HKG", "hong-kong", "HKD"),
    "Hungary": ("HUN", "hungary", "HUF"),
    "Iceland": ("ISL", "iceland", "ISK"),
    "India": ("IND", "india", "INR"),
    "Indonesia": ("IDN", "indonesia", "IDR"),
    "Ireland": ("IRL", "ireland", "EUR"),
    "Israel": ("ISR", "israel", "ILS"),
    "Italy": ("ITA", "italy", "EUR"),
    "Japan": ("JPN", "japan", "JPY"),
    "Kenya": ("KEN", "kenya", "KES"),
    "Latvia": ("LVA", "latvia", "EUR"),
    "Lithuania": ("LTU", "lithuania", "EUR"),
    "Malaysia": ("MYS", "malaysia", "MYR"),
    "Malta": ("MLT", "malta", "EUR"),
    "Mexico": ("MEX", "mexico", "MXN"),
    "Morocco": ("MAR", "morocco", "MAD"),
    "Netherlands": ("NLD", "netherlands", "EUR"),
    "New Zealand": ("NZL", "new-zealand", "NZD"),
    "Nigeria": ("NGA", "nigeria", "NGN"),
    "Norway": ("NOR", "norway", "NOK"),
    "Pakistan": ("PAK", "pakistan", "PKR"),
    "Peru": ("PER", "peru", "PEN"),
    "Philippines": ("PHL", "philippines", "PHP"),
    "Poland": ("POL", "poland", "PLN"),
    "Portugal": ("PRT", "portugal", "EUR"),
    "Romania": ("ROU", "romania", "RON"),
    "Serbia": ("SRB", "serbia", "RSD"),
    "Singapore": ("SGP", "singapore", "SGD"),
    "Slovakia": ("SVK", "slovakia", "EUR"),
    "Slovenia": ("SVN", "slovenia", "EUR"),
    "South Africa": ("ZAF", "south-africa", "ZAR"),
    "South Korea": ("KOR", "south-korea", "KRW"),
    "Spain": ("ESP", "spain", "EUR"),
    "Sweden": ("SWE", "sweden", "SEK"),
    "Switzerland": ("CHE", "switzerland", "CHF"),
    "Thailand": ("THA", "thailand", "THB"),
    "Turkey": ("TUR", "turkey", "TRY"),
    "United Kingdom": ("GBR", "united-kingdom", "GBP"),
    "Vietnam": ("VNM", "vietnam", "VND"),
}
SLUG_TO_COUNTRY = {v[1]: k for k, v in COUNTRIES.items()}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Data fetchers (cached for 12 hours; the refresh button clears the cache)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=12 * 3600, show_spinner=False)
def fetch_betas() -> dict:
    """Damodaran U.S. industry betas -> DataFrame[Industry, Unlevered beta, ...]."""
    r = requests.get(BETAS_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    try:  # calamine is the modern reader for legacy .xls; xlrd is the fallback
        raw = pd.read_excel(io.BytesIO(r.content), sheet_name="Industry Averages", header=None, engine="calamine")
    except Exception:  # noqa: BLE001
        raw = pd.read_excel(io.BytesIO(r.content), sheet_name="Industry Averages", header=None, engine="xlrd")

    # Date stamp: the cell next to "Date updated:"
    data_date = "n/a"
    for i in range(min(15, len(raw))):
        if str(raw.iat[i, 0]).strip().lower().startswith("date updated"):
            val = raw.iat[i, 1]
            data_date = pd.to_datetime(val).strftime("%Y-%m-%d") if pd.notna(val) else "n/a"
            break

    # Header row is the one whose first cell is "Industry Name"
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip().eq("Industry Name")][0]
    df = raw.iloc[hdr + 1 :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    df = df[df["Industry Name"].notna()]
    df = df[~df["Industry Name"].astype(str).str.contains("Total Market", case=False)]
    keep = ["Industry Name", "Number of firms", "Beta", "D/E Ratio", "Unlevered beta"]
    df = df[keep].rename(columns={"Industry Name": "Industry", "Unlevered beta": "Unlevered beta"})
    for c in keep[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Unlevered beta"]).reset_index(drop=True)
    df["Industry"] = df["Industry"].astype(str).str.strip()
    return {"df": df, "date": data_date, "fetched": now_utc()}


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def fetch_bbb_spread() -> dict:
    """Baa2/BBB default spread for large non-financial service firms (first table)."""
    r = requests.get(RATINGS_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "lxml")
    spread = None
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if "Baa2/BBB" in cells:
            i = cells.index("Baa2/BBB")  # first occurrence = large-firm table (market cap > $5bn)
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", cells[i + 1])
            if m:
                spread = float(m.group(1))
                break
    if spread is None:
        raise ValueError("Baa2/BBB row not found on ratings page")
    text = soup.get_text(" ", strip=True)
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)", text
    )
    data_date = f"{m.group(1)} {m.group(2)}" if m else "n/a"
    return {"spread": spread, "date": data_date, "fetched": now_utc()}


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def fetch_tax_rates() -> dict:
    """OECD statutory combined (central + sub-central) CIT rate, latest year per country."""
    start = datetime.now().year - 4
    r = requests.get(OECD_API_URL.format(start=start), headers={"User-Agent": HEADERS["User-Agent"]}, timeout=TIMEOUT)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df = df[(df["MEASURE"] == "CIT_C") & (df["TARGETING"] == "ST")]
    df = df.dropna(subset=["OBS_VALUE"])
    df = df.sort_values("TIME_PERIOD").groupby("REF_AREA").tail(1)
    out = df[["REF_AREA", "Reference area", "TIME_PERIOD", "OBS_VALUE"]].rename(
        columns={"REF_AREA": "ISO3", "Reference area": "Jurisdiction", "TIME_PERIOD": "Year", "OBS_VALUE": "Rate (%)"}
    )
    out = out.set_index("ISO3")
    return {"df": out, "date": f"tax year {int(out['Year'].max())}", "fetched": now_utc()}


def _parse_te_rows(html: str) -> dict[str, tuple[float, str]]:
    """Parse any Trading Economics market table rows of 10Y government bond yields."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, tuple[float, str]] = {}
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"^/([a-z-]+)/government-bond-yield$"))
        if not a:
            continue
        slug = re.match(r"^/([a-z-]+)/", a["href"]).group(1)
        cell = tr.find("td", id="p")
        if cell is None:
            continue
        try:
            y = float(cell.get_text(strip=True).replace(",", ""))
        except ValueError:
            continue
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        date = tds[-1] if tds and re.match(r"^[A-Z][a-z]{2}/\d{1,2}$|^\d{1,2}:\d{2}", tds[-1]) else ""
        out.setdefault(slug, (y, date))
    return out


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_te_bonds_table() -> dict:
    """Try the Trading Economics /bonds overview page (may be blocked for scripts)."""
    try:
        r = requests.get(TE_BONDS_URL, headers=HEADERS, timeout=TIMEOUT)
        rows = _parse_te_rows(r.text) if r.ok else {}
    except requests.RequestException:
        rows = {}
    return {"rows": rows, "fetched": now_utc()}


def _get_with_retry(url: str, tries: int = 4) -> requests.Response:
    """Trading Economics sometimes resets connections; retry with a short backoff."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.ok:
                return r
            last = requests.HTTPError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_te_country_page(slug: str) -> dict:
    """10-year yield for one country from its Trading Economics page, plus the page's
    market table (which lists the 10Y yields of major economies)."""
    url = TE_COUNTRY_URL.format(slug=slug)
    r = _get_with_retry(url)
    soup = BeautifulSoup(r.text, "lxml")
    meta = soup.find("meta", attrs={"name": "description"})
    desc = meta.get("content", "") if meta else ""
    rows = _parse_te_rows(r.text)
    out = {"rows": rows, "source": url, "fetched": now_utc(), "yield": None, "date": None}
    m = re.search(r"(-?\d+(?:\.\d+)?)%\s+on\s+([A-Z][a-z]+ \d{1,2},? \d{4})", desc)
    if m:
        out["yield"], out["date"] = float(m.group(1)), m.group(2)
    elif slug in rows:
        out["yield"], out["date"] = rows[slug][0], rows[slug][1] or "latest quote"
    return out


def get_yield(slug: str) -> dict:
    """1) /bonds overview table, 2) the country's own page, 3) the market table on the U.S. page."""
    table = fetch_te_bonds_table()
    if slug in table["rows"]:
        y, d = table["rows"][slug]
        return {"yield": y, "date": d or "latest quote", "source": TE_BONDS_URL, "fetched": table["fetched"]}
    err = None
    try:
        page = fetch_te_country_page(slug)
        if page["yield"] is not None:
            return {k: page[k] for k in ("yield", "date", "source", "fetched")}
    except Exception as e:  # noqa: BLE001
        err = e
    if slug != "united-states":
        us = fetch_te_country_page("united-states")
        if slug in us["rows"]:
            y, d = us["rows"][slug]
            return {"yield": y, "date": d or "latest quote", "source": us["source"], "fetched": us["fetched"]}
    raise ValueError(f"No 10Y yield found for '{slug}' on Trading Economics" + (f" ({err})" if err else ""))


def safe(fn, *args):
    try:
        return fn(*args), None
    except Exception as e:  # noqa: BLE001 - show any fetch error to the user
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------
def cost_of_capital(beta_u, tax, wd, erp, y_us, y_f, spread_usd, spread_f_override=None):
    """All rates in decimals. Returns a dict with USD and foreign-currency (FC) results.
    Follows the course packet (Rebelo, 2026, "Designing cost of capital app"):

    Relevered beta:            bE = bU * [1 + (1 - t) * D/E],   D/E = d / (1 - d)
    USD cost of equity:        Re = Rf + bE * ERP
    USD cost of debt:          Rd = Rf + s
    Conversion factor:         F = (1 + Rf*) / (1 + Rf)
    FC cost of equity:         1 + Re* = (1 + Re) * F
    FC spread (default):       s* = s * F            (or a user override)
    FC cost of debt:           Rd* = Rf* + s*
    WACC (each currency):      (1 - d) * Re + d * Rd * (1 - t)
    """
    we = 1 - wd
    de = wd / we
    beta_l = beta_u * (1 + (1 - tax) * de)

    ke_usd = y_us + beta_l * erp
    kd_usd = y_us + spread_usd
    wacc_usd = we * ke_usd + wd * kd_usd * (1 - tax)

    factor = (1 + y_f) / (1 + y_us)
    ke_f = (1 + ke_usd) * factor - 1
    spread_f_auto = spread_usd * factor
    spread_f = spread_f_auto if spread_f_override is None else spread_f_override
    kd_f = y_f + spread_f
    wacc_f = we * ke_f + wd * kd_f * (1 - tax)

    return dict(
        beta_u=beta_u, beta_l=beta_l, de=de, we=we, wd=wd, tax=tax, erp=erp, factor=factor,
        y_us=y_us, y_f=y_f, spread_usd=spread_usd, spread_f_auto=spread_f_auto, spread_f=spread_f,
        ke_usd=ke_usd, kd_usd=kd_usd, kd_usd_at=kd_usd * (1 - tax), wacc_usd=wacc_usd,
        ke_f=ke_f, kd_f=kd_f, kd_f_at=kd_f * (1 - tax), wacc_f=wacc_f,
    )


def pct(x, d=2):
    return "n/a" if x is None or pd.isna(x) else f"{x * 100:.{d}f}%"


# ---------------------------------------------------------------------------
# Sidebar: data refresh + user inputs
# ---------------------------------------------------------------------------
st.title("🌍 International Cost of Capital")
st.caption("Cost of equity, cost of debt and WACC of a project in USD and in the currency of a selected country.")

with st.sidebar:
    st.header("Data")
    if st.button("🔄 Refresh data", use_container_width=True, help="Clear the cache and re-fetch every source"):
        st.cache_data.clear()
        st.session_state["last_refresh"] = now_utc()
        st.rerun()
    if "last_refresh" in st.session_state:
        st.caption(f"Last manual refresh: {st.session_state['last_refresh']}")

with st.spinner("Fetching data from Damodaran, OECD and Trading Economics..."):
    betas, err_betas = safe(fetch_betas)
    bbb, err_bbb = safe(fetch_bbb_spread)
    taxes, err_tax = safe(fetch_tax_rates)

if betas is None:
    st.error(f"Could not load industry betas ({err_betas}). Enter an unlevered beta manually in the sidebar.")
    industries = [DEFAULT_INDUSTRY]
    beta_table = pd.DataFrame({"Industry": [DEFAULT_INDUSTRY], "Unlevered beta": [float("nan")]})
else:
    beta_table = betas["df"]
    industries = beta_table["Industry"].tolist()

with st.sidebar:
    st.header("Project")
    industry = st.selectbox(
        "Industry", industries,
        index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0,
    )
    country_names = list(COUNTRIES.keys())
    country = st.selectbox("Target country", country_names, index=country_names.index(DEFAULT_COUNTRY))
    iso3, slug, ccy = COUNTRIES[country]
    ccy_label = "USD (foreign = U.S.)" if ccy == "USD" else ccy
    fc_lbl = "USD (target)" if ccy == "USD" else ccy  # column label for the foreign-currency results

    erp = st.slider("Equity risk premium (%)", 0.0, 15.0, DEFAULT_ERP, 0.1) / 100
    wd = st.slider("Target debt share D/(D+E) (%)", 0, 90, DEFAULT_DEBT, 1) / 100

    tax_choice = st.radio(
        "Project tax rate", ["U.S. rate", f"{country} rate"], horizontal=True, index=0,
        help="The same tax rate is used for both the USD and the foreign-currency calculations.",
    )

# ---- fetch yields for the two countries
us_yield, err_us = safe(get_yield, "united-states")
f_yield, err_f = (us_yield, err_us) if slug == "united-states" else safe(get_yield, slug)

# ---- fetched values
beta_u_fetched = float(beta_table.loc[beta_table["Industry"] == industry, "Unlevered beta"].iloc[0])
spread_fetched = bbb["spread"] / 100 if bbb else float("nan")


def tax_for(code):
    if taxes is None or code not in taxes["df"].index:
        return float("nan"), "n/a"
    row = taxes["df"].loc[code]
    return float(row["Rate (%)"]) / 100, str(int(row["Year"]))


tax_us_fetched, tax_us_year = tax_for("USA")
tax_f_fetched, tax_f_year = tax_for(iso3)
y_us_fetched = us_yield["yield"] / 100 if us_yield else float("nan")
y_f_fetched = f_yield["yield"] / 100 if f_yield else float("nan")


def override(label, fetched, key, fmt_pct=True, step=0.01):
    """Checkbox + number input. Returns the value in decimals (or raw for beta)."""
    shown = fetched * 100 if fmt_pct else fetched
    on = st.checkbox(f"Override {label}", key=f"ov_{key}", value=pd.isna(fetched))
    default = 0.0 if pd.isna(shown) else round(float(shown), 4)
    val = st.number_input(
        f"{label}{' (%)' if fmt_pct else ''}", value=default, step=step, format="%.4f",
        key=f"val_{key}", disabled=not on,
    )
    if not on:
        return fetched
    return val / 100 if fmt_pct else val


with st.sidebar:
    st.header("Manual overrides")
    st.caption("Tick a box to replace the fetched value with your own input.")
    beta_u = override("Unlevered beta", beta_u_fetched, "beta", fmt_pct=False, step=0.01)
    tax_us = override("U.S. corporate tax rate", tax_us_fetched, "tax_us")
    tax_f = override(f"{country} corporate tax rate", tax_f_fetched, f"tax_f_{iso3}")
    spread_usd = override("USD BBB spread", spread_fetched, "spread")
    y_us = override("U.S. 10Y government yield", y_us_fetched, "y_us")
    if slug == "united-states":
        y_f = y_us
        st.caption("Target country is the U.S., so the foreign yield equals the U.S. yield.")
    else:
        y_f = override(f"{country} 10Y government yield", y_f_fetched, f"y_f_{slug}")

tax = tax_us if tax_choice == "U.S. rate" else tax_f

# Foreign BBB spread: auto unless overridden
_auto = cost_of_capital(beta_u, tax, wd, erp, y_us, y_f, spread_usd, None)
with st.sidebar:
    st.subheader(f"{ccy} BBB spread")
    spread_f_on = st.toggle(f"Override {ccy} BBB spread", value=False, key="ov_spread_f")
    if spread_f_on:
        spread_f_val = st.number_input(
            f"{ccy} BBB spread (%)", value=round(_auto["spread_f_auto"] * 100, 4), step=0.01, format="%.4f",
            key="val_spread_f",
        ) / 100
    else:
        spread_f_val = None
        st.metric(f"Auto-calculated {ccy} spread", pct(_auto["spread_f_auto"], 3))
        st.caption("s* = s × (1 + Rf*) / (1 + Rf): the USD spread scaled by the currency conversion factor.")

res = cost_of_capital(beta_u, tax, wd, erp, y_us, y_f, spread_usd, spread_f_val)

missing = [n for n, v in [("unlevered beta", beta_u), ("tax rate", tax), ("USD BBB spread", spread_usd),
                          ("U.S. yield", y_us), (f"{country} yield", y_f)] if pd.isna(v)]
if missing:
    st.warning("Missing inputs: " + ", ".join(missing) + ". Use the manual overrides in the sidebar.")

# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
tab_res, tab_all, tab_data, tab_assump, tab_check = st.tabs(
    ["📊 Results", "🏭 All industries", "🗂️ Data & sources", "📘 Assumptions", "✅ Verification"]
)

with tab_res:
    st.subheader(f"{industry} · {country}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Unlevered beta", f"{res['beta_u']:.3f}" if pd.notna(res["beta_u"]) else "n/a")
    c2.metric("Levered beta", f"{res['beta_l']:.3f}" if pd.notna(res["beta_l"]) else "n/a")
    c3.metric("Project tax rate", pct(res["tax"]), tax_choice, delta_color="off")
    st.caption(f"Debt share {wd:.0%} · D/E {res['de']:.3f} · Equity risk premium {pct(erp, 1)} · "
               f"Foreign currency {ccy_label}")

    def bp(a, b):
        d = round((a - b) * 1e4)
        return f"{d:+d} bp vs USD" if d else "same as USD"

    st.markdown(f"#### USD vs {fc_lbl}")
    for label, ku, kf in [("Cost of equity", "ke_usd", "ke_f"), ("Cost of debt (pre-tax)", "kd_usd", "kd_f"),
                          ("WACC", "wacc_usd", "wacc_f")]:
        a, b = st.columns(2)
        a.metric(f"{label} · USD", pct(res[ku]))
        b.metric(f"{label} · {fc_lbl}", pct(res[kf]), delta=bp(res[kf], res[ku]),
                 delta_color="off" if round((res[kf] - res[ku]) * 1e4) == 0 else "inverse")

    table = pd.DataFrame(
        {
            "USD": [res["y_us"], res["spread_usd"], res["ke_usd"], res["kd_usd"], res["kd_usd_at"], res["wacc_usd"]],
            fc_lbl: [res["y_f"], res["spread_f"], res["ke_f"], res["kd_f"], res["kd_f_at"], res["wacc_f"]],
        },
        index=["10Y government yield", "BBB spread", "Cost of equity", "Cost of debt (pre-tax)",
               "Cost of debt (after-tax)", "WACC"],
    )
    fcol = fc_lbl
    table["Difference (bp)"] = ((table[fcol] - table["USD"]) * 1e4).round(1) + 0.0
    st.dataframe(
        table.style.format({"USD": lambda v: pct(v), fcol: lambda v: pct(v), "Difference (bp)": "{:+.1f}"}),
        use_container_width=True,
    )
    st.caption(
        f"{ccy} BBB spread is {'a manual override' if spread_f_val is not None else 'auto-calculated'}. "
        f"Conversion factor F = (1 + Rf*)/(1 + Rf) = {res['factor']:.6f}."
    )

# ---- all-industry comparison
rows = []
for _, r in beta_table.iterrows():
    bu = beta_u if (r["Industry"] == industry and st.session_state.get("ov_beta")) else r["Unlevered beta"]
    o = cost_of_capital(bu, tax, wd, erp, y_us, y_f, spread_usd, spread_f_val)
    rows.append({
        "Industry": r["Industry"], "Unlevered beta": bu, "Levered beta": o["beta_l"],
        "Cost of equity USD": o["ke_usd"], "WACC USD": o["wacc_usd"],
        f"Cost of equity {fc_lbl}": o["ke_f"], f"WACC {fc_lbl}": o["wacc_f"],
    })
all_ind = pd.DataFrame(rows)

with tab_all:
    st.subheader("All-industry comparison")
    st.caption(f"Same country ({country}), tax rate, debt share, ERP, yields and spreads as the main results; "
               "only the unlevered beta changes.")
    sort_by = st.selectbox("Sort by", ["WACC USD", f"WACC {fc_lbl}", "Unlevered beta", "Industry"], index=0)
    view = all_ind.sort_values(sort_by, ascending=(sort_by == "Industry")).reset_index(drop=True)
    pct_cols = [c for c in view.columns if c.startswith(("Cost", "WACC"))]

    def hl(row):
        return ["background-color: rgba(255, 200, 0, 0.25)" if row["Industry"] == industry else "" for _ in row]

    st.dataframe(
        view.style.apply(hl, axis=1).format({**{c: lambda v: pct(v) for c in pct_cols},
                                             "Unlevered beta": "{:.3f}", "Levered beta": "{:.3f}"}),
        use_container_width=True, height=480,
    )
    chart = view.set_index("Industry")[["WACC USD", f"WACC {fc_lbl}"]] * 100
    st.markdown("**WACC by industry (%)**")
    st.bar_chart(chart, height=420, stack=False)

# ---- downloads (built once, offered in Results and All-industry tabs)
summary = pd.DataFrame(
    [
        ("Industry", industry), ("Target country", country), ("Foreign currency", ccy),
        ("Conversion factor (1+Rf*)/(1+Rf)", res["factor"]), ("Project tax source", tax_choice),
        ("Unlevered beta", res["beta_u"]), ("Debt share D/V", wd), ("D/E", res["de"]),
        ("Levered beta", res["beta_l"]), ("Equity risk premium", erp), ("Project tax rate", res["tax"]),
        ("U.S. 10Y yield", res["y_us"]), (f"{country} 10Y yield", res["y_f"]),
        ("USD BBB spread", res["spread_usd"]), (f"{ccy} BBB spread (used)", res["spread_f"]),
        (f"{ccy} BBB spread (auto)", res["spread_f_auto"]), (f"{ccy} spread overridden", spread_f_val is not None),
        ("Cost of equity USD", res["ke_usd"]), ("Cost of debt USD (pre-tax)", res["kd_usd"]), ("WACC USD", res["wacc_usd"]),
        (f"Cost of equity {fc_lbl}", res["ke_f"]), (f"Cost of debt {fc_lbl} (pre-tax)", res["kd_f"]), (f"WACC {fc_lbl}", res["wacc_f"]),
        ("Generated", now_utc()),
    ],
    columns=["Item", "Value"],
)
xbuf = io.BytesIO()
with pd.ExcelWriter(xbuf, engine="openpyxl") as xw:
    summary.to_excel(xw, sheet_name="Summary", index=False)
    all_ind.to_excel(xw, sheet_name="All industries", index=False)

with tab_res:
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Download results (Excel)", xbuf.getvalue(), file_name="cost_of_capital.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    d2.download_button("⬇️ Download summary (CSV)", summary.to_csv(index=False).encode(),
                       file_name="cost_of_capital_summary.csv", mime="text/csv", use_container_width=True)
with tab_all:
    st.download_button("⬇️ Download all-industry table (CSV)", all_ind.to_csv(index=False).encode(),
                       file_name="cost_of_capital_all_industries.csv", mime="text/csv")

# ---- sources
with tab_data:
    st.subheader("Data sources, dates and values used")

    def status(fetched_val, overridden):
        return "✏️ manual override" if overridden else ("✅ fetched" if pd.notna(fetched_val) else "❌ unavailable")

    src = pd.DataFrame([
        ["Unlevered beta — " + industry, "Aswath Damodaran, U.S. industry betas (betas.xls)", BETAS_URL,
         betas["date"] if betas else "n/a", f"{beta_u_fetched:.4f}" if pd.notna(beta_u_fetched) else "n/a",
         status(beta_u_fetched, st.session_state.get("ov_beta"))],
        ["USD BBB spread (Baa2/BBB, large non-financial firms)", "Aswath Damodaran, ratings.html", RATINGS_URL,
         bbb["date"] if bbb else "n/a", pct(spread_fetched), status(spread_fetched, st.session_state.get("ov_spread"))],
        ["U.S. corporate tax rate (combined statutory)", "OECD Corporate Tax Statistics", OECD_PAGE_URL,
         f"tax year {tax_us_year}", pct(tax_us_fetched), status(tax_us_fetched, st.session_state.get("ov_tax_us"))],
        [f"{country} corporate tax rate (combined statutory)", "OECD Corporate Tax Statistics", OECD_PAGE_URL,
         f"tax year {tax_f_year}", pct(tax_f_fetched), status(tax_f_fetched, st.session_state.get(f"ov_tax_f_{iso3}"))],
        ["U.S. 10Y government bond yield", "Trading Economics", us_yield["source"] if us_yield else TE_BONDS_URL,
         us_yield["date"] if us_yield else "n/a", pct(y_us_fetched), status(y_us_fetched, st.session_state.get("ov_y_us"))],
        [f"{country} 10Y government bond yield", "Trading Economics", f_yield["source"] if f_yield else TE_BONDS_URL,
         f_yield["date"] if f_yield else "n/a", pct(y_f_fetched),
         status(y_f_fetched, st.session_state.get(f"ov_y_f_{slug}"))],
    ], columns=["Input", "Source", "Link", "Data date", "Fetched value", "Status"])
    md = ["| Input | Source | Data date | Fetched value | Status |", "|---|---|---|---|---|"]
    for _, s in src.iterrows():
        md.append(f"| {s['Input']} | [{s['Source']}]({s['Link']}) | {s['Data date']} | {s['Fetched value']} | {s['Status']} |")
    st.markdown("\n".join(md))

    fetched_times = [x["fetched"] for x in (betas, bbb, taxes, us_yield, f_yield) if x]
    if fetched_times:
        st.caption(f"Fetched (cached up to 12 h; yields 3 h): {min(fetched_times)} – {max(fetched_times)}. "
                   "Use **Refresh data** in the sidebar to fetch again.")
    st.caption("OECD tax rates are read from the OECD Data Explorer API (dataset DSD_TAX_CIT@DF_CIT, measure "
               "CIT_C = combined central + sub-central statutory rate), the same database behind the OECD "
               "Corporate Tax Statistics report.")
    for name, e in [("Betas", err_betas), ("BBB spread", err_bbb), ("Tax rates", err_tax),
                    ("U.S. yield", err_us), (f"{country} yield", err_f)]:
        if e:
            st.error(f"{name} fetch failed: {e}")

    with st.expander("Raw tables"):
        st.markdown("**Damodaran industry betas**")
        st.dataframe(beta_table, use_container_width=True, height=300)
        if taxes is not None:
            st.markdown("**OECD statutory corporate tax rates (latest year)**")
            st.dataframe(taxes["df"], use_container_width=True, height=300)

# ---- assumptions
with tab_assump:
    st.subheader("Method and main assumptions")
    st.markdown(
        r"""
An asterisk denotes the foreign currency; $d$ is the target debt share $D/(D+E)$ and $\tau$ the project tax rate.

**1. Relevering beta.** The industry's unlevered beta is relevered at the project's target debt share and tax
rate (debt and the tax shield have zero beta):

$$\beta_E = \beta_U\left[1 + (1-\tau)\frac{D}{E}\right], \qquad \frac{D}{E} = \frac{d}{1-d}$$

**2. USD costs (CAPM with the U.S. 10-year yield as risk-free proxy; no separate country premium).**

$$R_e = R_f + \beta_E \times ERP \qquad R_d = R_f + s$$

**3. Converting to the foreign currency.** The Fisher equation plus relative PPP give

$$F = \frac{1 + R_f^*}{1 + R_f} \qquad 1 + R_e^* = (1 + R_e)\,F$$

**4. Foreign borrowing cost.** By default the USD spread is scaled by the same factor; it can be overridden:

$$s^* = s \times F \qquad R_d^* = R_f^* + s^*$$

**5. WACC** (same $d$, $ERP$ and $\tau$ in both currencies; interest deducted in each financing currency):

$$WACC = (1-d)\,R_e + d\,R_d\,(1-\tau)$$
"""
    )
    st.markdown(
        """
**Key approximations**
- **Risk benchmark:** risk is measured relative to the U.S. market, not the investor's portfolio or a world portfolio.
- **Project risk:** U.S. industry betas (Damodaran) proxy for project risk; CAPM omits other priced risks.
- **Interest rates:** 10-year government yields are risk-free proxies; they include liquidity and term premia
  and may include sovereign default risk.
- **Currency conversion:** equal real rates and relative PPP link the yield gap to expected depreciation.
  Exchange-rate betas are close to zero, so there is no separate currency-risk premium.
- **Country and credit risk:** no separate country equity premium; the large-firm Baa2/BBB spread is the USD
  credit spread.
- **Financing and taxes:** target leverage is constant, interest deductions are fully usable, and the same
  tax rate (U.S. or target country, sidebar switch) applies in both currencies.
- Overriding the foreign spread changes only the foreign-currency cost of debt and WACC; USD results do not move.
"""
    )

# ---- verification
with tab_check:
    st.subheader("Built-in verification checks")
    st.caption("These use the current sidebar inputs and recompute the model under controlled changes.")
    tol = 1e-12

    eq = cost_of_capital(beta_u, tax, wd, erp, y_us, y_us, spread_usd, None)
    c1 = all(abs(eq[a] - eq[b]) < tol for a, b in [("ke_usd", "ke_f"), ("kd_usd", "kd_f"), ("wacc_usd", "wacc_f")])
    z = cost_of_capital(beta_u, tax, 0.0, erp, y_us, y_f, spread_usd, spread_f_val)
    c2 = abs(z["wacc_usd"] - z["ke_usd"]) < tol and abs(z["wacc_f"] - z["ke_f"]) < tol
    ov = cost_of_capital(beta_u, tax, wd, erp, y_us, y_f, spread_usd, 0.05)
    base = cost_of_capital(beta_u, tax, wd, erp, y_us, y_f, spread_usd, None)
    c3 = all(abs(ov[k] - base[k]) < tol for k in ("ke_usd", "kd_usd", "wacc_usd"))

    checks = pd.DataFrame([
        ["Equal government yields → equal USD and FC results (spread override off)", c1,
         f"WACC USD {pct(eq['wacc_usd'], 4)} vs FC {pct(eq['wacc_f'], 4)}"],
        ["Zero debt → WACC = cost of equity (both currencies)", c2,
         f"USD {pct(z['wacc_usd'], 4)} = {pct(z['ke_usd'], 4)}; FC {pct(z['wacc_f'], 4)} = {pct(z['ke_f'], 4)}"],
        ["Overriding FC spread (set to 5%) leaves USD results unchanged", c3,
         f"WACC USD {pct(base['wacc_usd'], 4)} → {pct(ov['wacc_usd'], 4)}; FC {pct(base['wacc_f'], 4)} → {pct(ov['wacc_f'], 4)}"],
    ], columns=["Check", "Pass", "Detail"])
    checks["Pass"] = checks["Pass"].map({True: "✅ pass", False: "❌ fail"})
    st.dataframe(checks, hide_index=True, use_container_width=True)

    st.markdown("#### Course packet example: Colombia")
    st.caption("Inputs from the packet: unlevered beta 0.80, debt share 30%, tax 35%, ERP 6.5%, "
               "U.S. yield 4.0%, Colombia yield 12.0%, USD spread 1.5 pp. Fixed inputs, independent of the sidebar.")
    col = cost_of_capital(0.80, 0.35, 0.30, 0.065, 0.04, 0.12, 0.015, None)
    packet = [  # (label, model key, packet value in percent; beta as a number)
        ("Levered beta", "beta_l", 1.022857), ("Cost of equity USD", "ke_usd", 10.6486),
        ("Pretax borrowing cost USD", "kd_usd", 5.5000), ("After-tax borrowing cost USD", "kd_usd_at", 3.5750),
        ("WACC USD", "wacc_usd", 8.5265), ("Cost of equity COP", "ke_f", 19.1600),
        ("COP spread", "spread_f", 1.6154), ("Pretax borrowing cost COP", "kd_f", 13.6154),
        ("After-tax borrowing cost COP", "kd_f_at", 8.8500), ("WACC COP", "wacc_f", 16.0670),
    ]
    prow = []
    for label, key, pv in packet:
        mv = col[key] if key == "beta_l" else col[key] * 100
        ok = abs(mv - pv) < 0.00051 if key != "beta_l" else abs(mv - pv) < 5e-7
        prow.append([label, f"{pv:.6f}" if key == "beta_l" else f"{pv:.4f}%",
                     f"{mv:.6f}" if key == "beta_l" else f"{mv:.4f}%", "✅ match" if ok else "❌ differs"])
    st.dataframe(pd.DataFrame(prow, columns=["Item", "Packet", "App", "Status"]),
                 hide_index=True, use_container_width=True)

    st.markdown("#### Worked example with the current inputs (replicate in a spreadsheet)")
    r = res
    conv_txt = f"(1 + {pct(r['ke_usd'], 4)}) × (1 + {pct(r['y_f'], 4)}) / (1 + {pct(r['y_us'], 4)}) − 1"
    steps = pd.DataFrame([
        ["D/E", f"{wd:.4f} / (1 − {wd:.4f})", f"{r['de']:.6f}"],
        ["Levered beta", f"{r['beta_u']:.4f} × [1 + (1 − {r['tax']:.4f}) × {r['de']:.6f}]", f"{r['beta_l']:.6f}"],
        ["Cost of equity USD", f"{pct(r['y_us'], 4)} + {r['beta_l']:.6f} × {pct(erp, 2)}", pct(r["ke_usd"], 4)],
        ["Cost of debt USD", f"{pct(r['y_us'], 4)} + {pct(r['spread_usd'], 4)}", pct(r["kd_usd"], 4)],
        ["WACC USD", f"{1 - wd:.2f} × {pct(r['ke_usd'], 4)} + {wd:.2f} × {pct(r['kd_usd'], 4)} × (1 − {r['tax']:.4f})",
         pct(r["wacc_usd"], 4)],
        [f"Cost of equity {fc_lbl}", conv_txt, pct(r["ke_f"], 4)],
        [f"{ccy} BBB spread", "override" if spread_f_val is not None else
         f"{pct(r['spread_usd'], 4)} × (1 + {pct(r['y_f'], 4)}) / (1 + {pct(r['y_us'], 4)})",
         pct(r["spread_f"], 4)],
        [f"Cost of debt {fc_lbl}", f"{pct(r['y_f'], 4)} + {pct(r['spread_f'], 4)}", pct(r["kd_f"], 4)],
        [f"WACC {fc_lbl}", f"{1 - wd:.2f} × {pct(r['ke_f'], 4)} + {wd:.2f} × {pct(r['kd_f'], 4)} × (1 − {r['tax']:.4f})",
         pct(r["wacc_f"], 4)],
    ], columns=["Step", "Formula with numbers", "Result"])
    st.dataframe(steps, hide_index=True, use_container_width=True)

st.divider()
st.caption("Sources: Aswath Damodaran (NYU Stern) · OECD Corporate Tax Statistics · Trading Economics. "
           "For teaching purposes; verify all inputs before relying on results.")
