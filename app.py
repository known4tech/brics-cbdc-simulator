import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="BRICS CBDC Pricing Simulator",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# GLOBAL STYLE
# ─────────────────────────────────────────────
st.markdown("""
<style>
    /* Sidebar background */
    [data-testid="stSidebar"] { background-color: #0f172a; }
    [data-testid="stSidebar"] * { color: #e2e8f0 !important; }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 16px;
    }

    /* Section headers */
    .section-header {
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #94a3b8;
        margin-bottom: 4px;
    }

    /* Thesis callout box */
    .thesis-box {
        background: linear-gradient(135deg, #1e3a5f 0%, #0f2942 100%);
        border-left: 4px solid #3b82f6;
        border-radius: 8px;
        padding: 16px 20px;
        margin: 12px 0;
    }

    /* Savings highlight */
    .savings-hero {
        background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
        border: 1px solid #10b981;
        border-radius: 12px;
        padding: 20px 24px;
        text-align: center;
        margin: 16px 0;
    }
    .savings-hero h1 { color: #10b981 !important; font-size: 2.4rem; margin: 0; }
    .savings-hero p  { color: #6ee7b7; margin: 4px 0 0; font-size: 1rem; }

    hr { border-color: #334155; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# CACHED LIVE FOREX  (1-hour cache → no API crashes under traffic)
# Fallback = thesis baseline rates (Chapter 3, Table 2)
# ─────────────────────────────────────────────
THESIS_RATES = {
    "INR": 94.86,   # USD/INR  — March 2026 mid-market (Chapter 3.4, Assumption 4)
    "CNY":  7.20,
    "RUB": 90.00,
    "BRL":  5.00,
    "ZAR": 18.50,
}

@st.cache_data(ttl=3600)
def get_live_rates():
    tickers = {
        "INR": "INR=X",
        "CNY": "CNY=X",
        "RUB": "RUB=X",
        "BRL": "BRL=X",
        "ZAR": "ZAR=X",
    }
    rates = {}
    try:
        for currency, ticker in tickers.items():
            data = yf.download(ticker, period="1d", progress=False, auto_adjust=True)
            if not data.empty:
                rates[currency] = round(float(data["Close"].iloc[-1]), 2)
            else:
                rates[currency] = THESIS_RATES[currency]
        return rates, True          # True = live data fetched
    except Exception:
        return THESIS_RATES.copy(), False   # False = using fallback

live_rates, is_live = get_live_rates()

# ─────────────────────────────────────────────
# CORE CALCULATION FUNCTION
# All formulas mapped 1-to-1 with Chapter 4, Section 4.2
# ─────────────────────────────────────────────
def calculate(export_val_usd, usd_inr, swift_fx_spread_pct, working_cap_rate_pct):
    """
    Returns dict of all cost components for SWIFT and CBDC scenarios.
    Chapter 4.2.1  →  SWIFT breakdown
    Chapter 4.2.2  →  CBDC breakdown
    """
    export_val_inr = export_val_usd * usd_inr

    # ── SWIFT scenario ────────────────────────────────────────────────────
    # Step 1: Fixed bank charges (Chapter 4.2.1, Step 1 & 4)
    sending_bank_fee    = 1_000          # ₹1,000   (Table 2, Assumption 2)
    swift_message_fee   =   500          # ₹500     (Table 2, Assumption 2)
    receiving_bank_fee  =   750          # ₹750     (Table 2, Assumption 2)

    # Step 2: Correspondent banking fees (Chapter 4.2.1, Step 2)
    # 2 intermediary banks × USD 20 each = USD 40 (Table 2, Assumption 2)
    correspondent_fees  = 40 * usd_inr

    # Step 3: FX spread cost (Chapter 4.2.1, Step 3)
    swift_fx_cost       = export_val_inr * (swift_fx_spread_pct / 100)

    # Step 5: Hedging cost — 1.5% p.a. for 60-day forward cover (Table 2, Assumption 6)
    swift_hedging_cost  = export_val_inr * 0.015 * (60 / 365)

    # Step 6: Working capital interest — 8% p.a. for 3-day delay (Table 2, Assumption 5)
    swift_wc_cost       = export_val_inr * (working_cap_rate_pct / 100) * (3 / 365)

    total_swift_fixed   = sending_bank_fee + swift_message_fee + receiving_bank_fee
    total_swift_cost    = (total_swift_fixed + correspondent_fees +
                           swift_fx_cost + swift_hedging_cost + swift_wc_cost)
    net_swift           = export_val_inr - total_swift_cost
    swift_pct           = (total_swift_cost / export_val_inr) * 100

    # ── CBDC scenario ─────────────────────────────────────────────────────
    # Step 1: Platform fee 0.1% (Table 2, Assumption 3 — BIS mBridge data)
    cbdc_platform_fee   = export_val_inr * 0.001

    # Step 2: Reduced FX spread 0.5% (Table 2, Assumption 3)
    cbdc_fx_cost        = export_val_inr * 0.005

    # Steps 3 & 4: Real-time settlement → zero hedging & zero WC cost
    cbdc_hedging_cost   = 0.0
    cbdc_wc_cost        = 0.0

    total_cbdc_cost     = cbdc_platform_fee + cbdc_fx_cost
    net_cbdc            = export_val_inr - total_cbdc_cost
    cbdc_pct            = (total_cbdc_cost / export_val_inr) * 100

    # ── Summary ───────────────────────────────────────────────────────────
    savings             = total_swift_cost - total_cbdc_cost
    savings_pct         = (savings / export_val_inr) * 100
    cost_reduction_pct  = ((total_swift_cost - total_cbdc_cost) / total_swift_cost) * 100

    return {
        # Inputs
        "export_val_inr":        export_val_inr,
        "usd_inr":               usd_inr,
        # SWIFT components
        "sending_bank_fee":      sending_bank_fee,
        "swift_message_fee":     swift_message_fee,
        "receiving_bank_fee":    receiving_bank_fee,
        "correspondent_fees":    correspondent_fees,
        "swift_fx_cost":         swift_fx_cost,
        "swift_hedging_cost":    swift_hedging_cost,
        "swift_wc_cost":         swift_wc_cost,
        "total_swift_fixed":     total_swift_fixed,
        "total_swift_cost":      total_swift_cost,
        "net_swift":             net_swift,
        "swift_pct":             swift_pct,
        # CBDC components
        "cbdc_platform_fee":     cbdc_platform_fee,
        "cbdc_fx_cost":          cbdc_fx_cost,
        "cbdc_hedging_cost":     cbdc_hedging_cost,
        "cbdc_wc_cost":          cbdc_wc_cost,
        "total_cbdc_cost":       total_cbdc_cost,
        "net_cbdc":              net_cbdc,
        "cbdc_pct":              cbdc_pct,
        # Summary
        "savings":               savings,
        "savings_pct":           savings_pct,
        "cost_reduction_pct":    cost_reduction_pct,
    }


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
st.sidebar.image(
    "logo.png", width=130,
)
st.sidebar.title("BRICS CBDC Simulator")
st.sidebar.caption("PGDIM Research Project · SGGSCC, Delhi University")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate",
    [
        "💱 Financial Simulator",
        "🎯 Marketing Matrix",
        "📊 Sensitivity Analysis",
        "🎓 About the Research",
    ],
)

st.sidebar.markdown("---")
st.sidebar.markdown("**Live Forex Rates (1 USD =)**")
if is_live:
    st.sidebar.success("🟢 Live data · cached 1 hr")
else:
    st.sidebar.warning("🟡 Using thesis baseline rates")

for curr, rate in live_rates.items():
    flag = {"INR": "🇮🇳", "CNY": "🇨🇳", "RUB": "🇷🇺", "BRL": "🇧🇷", "ZAR": "🇿🇦"}[curr]
    st.sidebar.markdown(f"{flag} **{curr}:** ₹ {rate:,.2f}" if curr == "INR"
                        else f"{flag} **{curr}:** {rate:,.2f}")

st.sidebar.markdown("---")
st.sidebar.caption(
    "Thesis: *Strategic Impact of BRICS CBDC Linkage on Pricing "
    "Competitiveness of Indian Exporters*\n\n"
    "Yatin Kumar · Roll No. 257023 · Mentor: Dr. Kriti Chadha"
)


# ═══════════════════════════════════════════════════════════
# TAB 1 — FINANCIAL SIMULATOR
# ═══════════════════════════════════════════════════════════
if page == "💱 Financial Simulator":

    st.title("💱 BRICS CBDC vs. SWIFT — Live Cost Simulator")
    st.markdown(
        "Quantifying cross-border transaction frictions under the Dominant Currency Paradigm. "
        "All formulas are sourced directly from **Chapter 4, Tables 3–5** of the research thesis."
    )
    st.markdown("---")

    # ── INPUTS ────────────────────────────────────────────────────────────
    col_input, col_output = st.columns([1, 2], gap="large")

    with col_input:
        st.markdown('<p class="section-header">Model Parameters</p>', unsafe_allow_html=True)

        rate_mode = st.radio(
            "Exchange Rate Source",
            ["📌 Thesis Baseline (₹94.86)", "📡 Live Market Rate"],
            help="Thesis baseline = mid-market rate as of March 2026 (Chapter 3.4, Assumption 4)",
        )
        usd_inr = 94.86 if "Baseline" in rate_mode else live_rates["INR"]
        st.caption(f"Active rate: **₹{usd_inr:,.2f}** per USD")

        st.markdown(" ")
        export_val_usd = st.number_input(
            "Export Value (USD)",
            min_value=1_000,
            max_value=5_000_000,
            value=100_000,
            step=10_000,
            help="Thesis baseline = USD 100,000 (RBI SME average, Chapter 3.4 Assumption 1)",
        )

        swift_fx_spread = st.slider(
            "SWIFT Bank FX Spread (%)",
            min_value=1.0, max_value=5.0, value=3.0, step=0.1,
            help="Thesis baseline = 3.0% (World Bank 2023, Chapter 3.4 Assumption 2)",
        )

        working_cap_rate = st.slider(
            "Working Capital Interest Rate (% p.a.)",
            min_value=4.0, max_value=15.0, value=8.0, step=0.5,
            help="Thesis baseline = 8.0% for 3-day SWIFT delay (Jain 2026, Chapter 3.4 Assumption 5)",
        )

        st.markdown(" ")
        st.markdown('<p class="section-header">Fixed CBDC Parameters</p>', unsafe_allow_html=True)
        st.caption("🔒 CBDC platform fee: **0.1%** · CBDC FX spread: **0.5%** · Settlement: **real-time**")
        st.caption("*(BIS Project mBridge data — Chapter 3.4 Assumption 3)*")

    # ── CALCULATIONS ──────────────────────────────────────────────────────
    r = calculate(export_val_usd, usd_inr, swift_fx_spread, working_cap_rate)

    # Persist to session state for Tab 2
    st.session_state["r"]              = r
    st.session_state["export_val_usd"] = export_val_usd
    st.session_state["usd_inr"]        = usd_inr

    with col_output:

        # Savings hero banner
        st.markdown(
            f"""
            <div class="savings-hero">
                <h1>₹{r['savings']:,.0f}</h1>
                <p>Saved per USD {export_val_usd:,} transaction &nbsp;·&nbsp;
                   <strong>{r['savings_pct']:.2f}%</strong> of export value &nbsp;·&nbsp;
                   <strong>{r['cost_reduction_pct']:.0f}%</strong> cost reduction
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 3 headline metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("SWIFT Total Cost",    f"₹{r['total_swift_cost']:,.0f}", f"{r['swift_pct']:.2f}% of value")
        m2.metric("CBDC Total Cost",     f"₹{r['total_cbdc_cost']:,.0f}",  f"{r['cbdc_pct']:.2f}% of value")
        m3.metric("Net Savings",         f"₹{r['savings']:,.0f}",
                  f"{r['cost_reduction_pct']:.0f}% cheaper via CBDC", delta_color="normal")

        st.markdown(" ")

        # ── MAIN BAR CHART — total comparison ────────────────────────────
        df_bar = pd.DataFrame({
            "System":     ["Legacy SWIFT", "BRICS CBDC"],
            "Cost (INR)": [r["total_swift_cost"], r["total_cbdc_cost"]],
            "Net Received (INR)": [r["net_swift"], r["net_cbdc"]],
        })

        fig_bar = px.bar(
            df_bar, x="System", y="Cost (INR)", color="System",
            color_discrete_map={"Legacy SWIFT": "#ef4444", "BRICS CBDC": "#10b981"},
            text="Cost (INR)",
            hover_data={"Net Received (INR)": ":,.0f", "Cost (INR)": ":,.0f"},
            title="Total Transaction Cost Comparison (Chapter 4, Table 5)",
        )
        fig_bar.update_traces(
            texttemplate="₹%{text:,.0f}",
            textposition="outside",
            textfont_size=14,
        )
        fig_bar.update_layout(
            height=380,
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e8f0",
            title_font_size=13,
            yaxis=dict(showgrid=True, gridcolor="#334155"),
            xaxis=dict(showgrid=False),
            uniformtext_minsize=12, uniformtext_mode="hide",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # ── STACKED BREAKDOWN CHART ───────────────────────────────────────
        st.markdown("**Cost Breakdown by Component** *(hover for exact amounts)*")

        components = [
            ("Fixed Bank Fees",         r["total_swift_fixed"],    0),
            ("Correspondent Bank Fees", r["correspondent_fees"],   0),
            ("FX Spread",               r["swift_fx_cost"],        r["cbdc_fx_cost"]),
            ("Platform / Gateway Fee",  0,                         r["cbdc_platform_fee"]),
            ("Hedging Cost",            r["swift_hedging_cost"],   r["cbdc_hedging_cost"]),
            ("Working Capital Cost",    r["swift_wc_cost"],        r["cbdc_wc_cost"]),
        ]

        df_stack = pd.DataFrame(
            [(c[0], "Legacy SWIFT", c[1]) for c in components] +
            [(c[0], "BRICS CBDC",  c[2]) for c in components],
            columns=["Component", "System", "Amount (INR)"],
        )

        fig_stack = px.bar(
            df_stack, x="System", y="Amount (INR)", color="Component",
            barmode="stack",
            color_discrete_sequence=["#3b82f6","#8b5cf6","#f59e0b","#06b6d4","#ec4899","#14b8a6"],
            title="Stacked Cost Breakdown (Chapter 4, Tables 3 & 4)",
        )
        fig_stack.update_layout(
            height=350,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e8f0",
            title_font_size=13,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            yaxis=dict(showgrid=True, gridcolor="#334155"),
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_stack, use_container_width=True)

    # ── DETAILED LINE-ITEM TABLE ──────────────────────────────────────────
    with st.expander("📋 Full Line-Item Breakdown (replicates Chapter 4, Tables 3 & 4)"):
        df_detail = pd.DataFrame({
            "Cost Component": [
                "Export Value (mid-market)", "Sending Bank Fee", "SWIFT Message Fee",
                "Receiving Bank Fee", "Correspondent Bank Fees (2 × USD 20)",
                "FX Spread Cost", "CBDC Platform Fee (0.1%)",
                "Hedging Cost (1.5% p.a., 60 days)", "Working Capital Cost (3-day delay)",
                "─────────── TOTAL TRANSACTION COST ───────────",
                "Net INR Received by Exporter",
                "Cost as % of Export Value",
            ],
            "SWIFT (INR)": [
                f"₹{r['export_val_inr']:,.0f}",
                f"₹{r['sending_bank_fee']:,.0f}",
                f"₹{r['swift_message_fee']:,.0f}",
                f"₹{r['receiving_bank_fee']:,.0f}",
                f"₹{r['correspondent_fees']:,.0f}",
                f"₹{r['swift_fx_cost']:,.0f}",
                "₹0 (not applicable)",
                f"₹{r['swift_hedging_cost']:,.0f}",
                f"₹{r['swift_wc_cost']:,.0f}",
                f"₹{r['total_swift_cost']:,.0f}",
                f"₹{r['net_swift']:,.0f}",
                f"{r['swift_pct']:.2f}%",
            ],
            "BRICS CBDC (INR)": [
                f"₹{r['export_val_inr']:,.0f}",
                "₹0 (eliminated)",
                "₹0 (eliminated)",
                "₹0 (eliminated)",
                "₹0 (eliminated)",
                f"₹{r['cbdc_fx_cost']:,.0f}",
                f"₹{r['cbdc_platform_fee']:,.0f}",
                "₹0 (instant settlement)",
                "₹0 (real-time)",
                f"₹{r['total_cbdc_cost']:,.0f}",
                f"₹{r['net_cbdc']:,.0f}",
                f"{r['cbdc_pct']:.2f}%",
            ],
        })
        st.dataframe(df_detail, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# TAB 2 — MARKETING STRATEGY MATRIX
# ═══════════════════════════════════════════════════════════
elif page == "🎯 Marketing Matrix":

    st.title("🎯 Strategic Marketing Matrix")
    st.markdown(
        "Operationalizing the ₹2,63,336 CBDC cost advantage into competitive pricing strategy. "
        "Based on **Chapter 4, Section 4.4–4.6 and Table 7** of the thesis."
    )
    st.markdown("---")

    if "r" not in st.session_state:
        st.warning("⚠️ Please visit the **Financial Simulator** tab first to set your transaction baseline.")
        st.stop()

    r              = st.session_state["r"]
    export_val_usd = st.session_state["export_val_usd"]
    usd_inr        = st.session_state["usd_inr"]
    savings        = r["savings"]
    savings_pct    = r["savings_pct"]

    st.markdown(
        f"""
        <div class="thesis-box">
            <strong>Capital Liberated by BRICS CBDC:</strong>
            ₹{savings:,.0f} &nbsp;·&nbsp;
            <strong>Strategic Buffer Available:</strong> {savings_pct:.2f}% of export value &nbsp;·&nbsp;
            <strong>USD Equivalent:</strong> ${savings / usd_inr:,.0f}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(" ")
    st.markdown("### How will you deploy your margin advantage?")
    st.caption(
        "Slide to allocate savings between dropping your price (Penetration Pricing) "
        "or keeping it as pure profit (Margin Expansion). See Chapter 4.5, Table 7."
    )

    strategy_split = st.slider(
        "← Margin Expansion (Keep as Profit)  ────────────────  Penetration Pricing (Pass to Buyer) →",
        min_value=0, max_value=100, value=50, step=5,
        help="0% = keep all savings as profit · 100% = pass all savings as price reduction to buyer",
    )

    penetration_pct  = strategy_split / 100         # fraction passed to buyer
    margin_pct       = 1 - penetration_pct           # fraction kept as profit

    price_drop_inr   = savings * penetration_pct
    profit_kept_inr  = savings * margin_pct

    price_drop_usd   = price_drop_inr / usd_inr
    new_price_usd    = export_val_usd - price_drop_usd
    price_drop_pct   = (price_drop_usd / export_val_usd) * 100

    # Strategy label
    if strategy_split == 0:
        strategy_label = "🏦 Pure Margin Expansion"
        strategy_desc  = "All savings retained as profit. Fund R&D, compliance, or after-sales service."
        table_ref      = "Chapter 4.5.2"
    elif strategy_split == 100:
        strategy_label = "⚔️  Pure Penetration Pricing"
        strategy_desc  = "Entire savings passed as price reduction. Undercut Chinese/Turkish competitors."
        table_ref      = "Chapter 4.5.1"
    else:
        strategy_label = "⚖️  Hybrid Strategy"
        strategy_desc  = "Balanced approach — partial price cut to win share, partial profit to fund growth."
        table_ref      = "Chapter 4.4, Option 3 & Table 7"

    st.info(f"**{strategy_label}** — {strategy_desc} *({table_ref})*")

    st.markdown(" ")

    # 4 metric cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "New Landed Price (USD)",
        f"${new_price_usd:,.2f}",
        f"-${price_drop_usd:,.2f} vs SWIFT baseline",
        delta_color="inverse",
    )
    c2.metric(
        "Price Reduction",
        f"{price_drop_pct:.2f}%",
        "Competitiveness gained",
        delta_color="normal",
    )
    c3.metric(
        "Profit Retained (INR)",
        f"₹{profit_kept_inr:,.0f}",
        "Margin expansion",
        delta_color="normal",
    )
    c4.metric(
        "Passed to Buyer (INR)",
        f"₹{price_drop_inr:,.0f}",
        "Penetration pricing pool",
        delta_color="normal",
    )

    st.markdown(" ")
    col_donut, col_bar = st.columns(2, gap="large")

    # ── DONUT ─────────────────────────────────────────────────────────────
    with col_donut:
        fig_donut = go.Figure(data=[go.Pie(
            labels=["Passed to Buyer\n(Lower Price)", "Retained by Exporter\n(Higher Profit)"],
            values=[penetration_pct if penetration_pct > 0 else 0.001,
                    margin_pct      if margin_pct      > 0 else 0.001],
            hole=0.52,
            marker_colors=["#3b82f6", "#10b981"],
            textinfo="label+percent",
            textfont_size=13,
        )])
        fig_donut.update_layout(
            title="Savings Allocation Strategy (Chapter 4.4)",
            height=370,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e8f0",
            title_font_size=13,
            showlegend=False,
            annotations=[dict(
                text=f"₹{savings:,.0f}<br><span style='font-size:11px'>Total Pool</span>",
                x=0.5, y=0.5, font_size=16, showarrow=False,
            )],
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    # ── COMPETITOR PRICE LADDER ───────────────────────────────────────────
    with col_bar:
        st.markdown("**Competitive Positioning vs. Rivals**")
        st.caption("Chapter 4.5.1 — Indian exporter price after CBDC savings vs. competitors")

        # Illustrative competitor prices (held fixed — only Indian price moves)
        competitors = {
            "Chinese Supplier":   export_val_usd * 1.000,
            "Turkish Supplier":   export_val_usd * 1.012,
            "Indian (SWIFT)":     export_val_usd * 1.000,
            "Indian (CBDC)":      new_price_usd,
        }
        df_comp = pd.DataFrame(
            list(competitors.items()), columns=["Supplier", "Price (USD)"]
        )
        df_comp["Highlight"] = df_comp["Supplier"].apply(
            lambda x: "You" if "CBDC" in x else "Competitor"
        )

        fig_comp = px.bar(
            df_comp, x="Price (USD)", y="Supplier", orientation="h",
            color="Highlight",
            color_discrete_map={"You": "#10b981", "Competitor": "#64748b"},
            text="Price (USD)",
            title="Price Ladder vs. Global Competitors",
        )
        fig_comp.update_traces(
            texttemplate="$%{text:,.0f}", textposition="outside", textfont_size=12
        )
        fig_comp.update_layout(
            height=370,
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e8f0",
            title_font_size=13,
            xaxis=dict(showgrid=True, gridcolor="#334155",
                       range=[export_val_usd * 0.96, export_val_usd * 1.025]),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_comp, use_container_width=True)

    # ── STRATEGY COMPARISON TABLE (Table 7 replica) ───────────────────────
    with st.expander("📋 Full Strategy Matrix — replicates Chapter 4, Table 7"):
        df_matrix = pd.DataFrame({
            "Strategy": ["Penetration Pricing", "Margin Enhancement", "Hybrid Strategy"],
            "Use Case Example": [
                "Indian textiles into Russian market",
                "Active Pharmaceutical Ingredients to Brazil",
                "Engineering goods to China / South Africa",
            ],
            "Use of 2.78% Savings": [
                "Pass ~full 2.78% as price reduction",
                "Keep savings as profit margin",
                "Split savings between lower price and higher margin",
            ],
            "Expected Outcome": [
                "Undercut Chinese/Turkish rivals, rapidly gain market share",
                "Higher profitability; fund R&D and compliance investment",
                "Improved competitiveness and stronger financial sustainability",
            ],
        })
        st.dataframe(df_matrix, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# TAB 3 — SENSITIVITY ANALYSIS
# ═══════════════════════════════════════════════════════════
elif page == "📊 Sensitivity Analysis":

    st.title("📊 Sensitivity Analysis")
    st.markdown(
        "Testing how robust the ₹2,63,336 baseline saving is under different market conditions. "
        "Sourced directly from **Chapter 4, Section 4.9, Table 6**."
    )
    st.markdown("---")

    # ── STATIC THESIS TABLE 6 (exact figures) ────────────────────────────
    thesis_scenarios = [
        ("Base case (current model)",          3.0, 0.5, 1.5, 0.10, 2_63_336),
        ("SWIFT spread narrows (competitive)", 2.0, 0.5, 1.5, 0.10, 1_68_476),
        ("SWIFT spread widens (high friction)",4.0, 0.5, 1.5, 0.10, 3_58_196),
        ("Higher hedging (volatile pair)",     3.0, 0.5, 2.5, 0.10, 2_79_146),
        ("Higher CBDC platform fee",           3.0, 0.5, 1.5, 0.20, 2_53_850),
    ]

    df_sa = pd.DataFrame(
        thesis_scenarios,
        columns=["Scenario", "SWIFT FX Spread %", "CBDC FX Spread %",
                 "Hedging % p.a.", "CBDC Platform Fee %", "Savings (₹)"],
    )

    # ── HORIZONTAL BAR CHART ──────────────────────────────────────────────
    df_sa["colour"] = df_sa["Scenario"].apply(
        lambda s: "#3b82f6" if "Base case" in s else "#64748b"
    )
    df_sa["label"] = df_sa["Savings (₹)"].apply(lambda v: f"₹{v:,.0f}")

    fig_sa = go.Figure()
    for _, row in df_sa.iterrows():
        fig_sa.add_trace(go.Bar(
            x=[row["Savings (₹)"]],
            y=[row["Scenario"]],
            orientation="h",
            marker_color=row["colour"],
            text=row["label"],
            textposition="outside",
            textfont=dict(size=13),
            name=row["Scenario"],
            hovertemplate=(
                f"<b>{row['Scenario']}</b><br>"
                f"Savings: ₹{row['Savings (₹)']:,.0f}<br>"
                f"SWIFT FX Spread: {row['SWIFT FX Spread %']}%<br>"
                f"CBDC FX Spread: {row['CBDC FX Spread %']}%<br>"
                f"Hedging: {row['Hedging % p.a.']}% p.a.<br>"
                f"CBDC Platform Fee: {row['CBDC Platform Fee %']}%"
                "<extra></extra>"
            ),
        ))

    # Base case vertical reference line
    fig_sa.add_vline(
        x=2_63_336, line_dash="dash", line_color="#10b981",
        annotation_text="Base case ₹2,63,336",
        annotation_position="top right",
        annotation_font_color="#10b981",
    )

    fig_sa.update_layout(
        title="Sensitivity of Savings to Market Assumptions (Chapter 4, Table 6)",
        height=420,
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e8f0",
        title_font_size=14,
        xaxis=dict(
            title="Cost Savings per USD 100,000 Transaction (₹)",
            showgrid=True, gridcolor="#334155",
            range=[0, 4_20_000],
        ),
        yaxis=dict(showgrid=False, automargin=True),
        bargap=0.35,
    )
    st.plotly_chart(fig_sa, use_container_width=True)

    # ── KEY INSIGHTS ──────────────────────────────────────────────────────
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### Key Insight 1: FX Spread Dominates")
        st.markdown(
            "The **FX spread differential** is the most sensitive parameter. "
            "If SWIFT banks narrow spreads to 2% to compete with CBDC, savings fall by "
            f"**₹94,860** (−36%). But if spreads widen to 4% (common for smaller exporters "
            "with low negotiating power), savings rise to **₹3,58,196** (+36%). "
            "*Chapter 4.9 — Key Insight 1.*"
        )

        st.markdown("#### Key Insight 2: Hedging Volatility")
        st.markdown(
            "Higher hedging costs — such as the **INR/RUB pair**, which often exceeds "
            "2.5% p.a. — increase CBDC savings to ₹2,79,146. This makes the BRICS CBDC "
            "especially powerful for India–Russia trade specifically. "
            "*Chapter 4.9 — Key Insight 2.*"
        )

    with c2:
        st.markdown("#### Key Insight 3: CBDC Platform Fee is Stable")
        st.markdown(
            "Even **doubling** the CBDC platform fee from 0.1% to 0.2% reduces savings "
            "by only ₹9,486 — a fractional impact. The platform fee assumption is the "
            "least sensitive parameter in the model, confirming the core cost advantage "
            "is structurally robust. *Chapter 4.9 — Key Insight 3.*"
        )

        st.markdown("#### Conclusion: Floor of Advantage")
        st.markdown(
            "Across all five scenarios, the minimum saving is **₹1,68,476** (SWIFT spread "
            "at 2%). This represents the absolute floor of CBDC benefit — still a "
            f"**{1_68_476 / 2_63_336 * 100:.0f}%** retention of base case savings, "
            "confirming the advantage is durable even under optimistic SWIFT assumptions."
        )

    # ── INTERACTIVE CUSTOM SCENARIO ───────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔬 Custom Scenario Builder")
    st.caption(
        "Adjust parameters beyond the 5 thesis scenarios to test your own assumptions. "
        "Live calculation uses USD 100,000 at thesis baseline rate ₹94.86."
    )

    cs1, cs2, cs3, cs4 = st.columns(4)
    c_swift_fx   = cs1.slider("SWIFT FX Spread (%)",   1.0, 6.0, 3.0, 0.1)
    c_cbdc_fx    = cs2.slider("CBDC FX Spread (%)",    0.1, 2.0, 0.5, 0.1)
    c_hedging    = cs3.slider("Hedging Cost (% p.a.)", 0.5, 4.0, 1.5, 0.1)
    c_cbdc_fee   = cs4.slider("CBDC Platform Fee (%)", 0.05, 0.50, 0.10, 0.05)

    # Custom calculation (extends thesis formula — same structure)
    base_inr       = 100_000 * 94.86
    c_fixed        = 1_000 + 500 + 750 + (40 * 94.86)
    c_swift_total  = c_fixed + (base_inr * c_swift_fx / 100) + \
                     (base_inr * c_hedging / 100 * 60 / 365) + \
                     (base_inr * 0.08 * 3 / 365)
    c_cbdc_total   = (base_inr * c_cbdc_fee / 100) + (base_inr * c_cbdc_fx / 100)
    c_savings      = c_swift_total - c_cbdc_total
    c_reduction    = (c_savings / c_swift_total) * 100

    m1, m2, m3 = st.columns(3)
    m1.metric("Custom SWIFT Cost",  f"₹{c_swift_total:,.0f}")
    m2.metric("Custom CBDC Cost",   f"₹{c_cbdc_total:,.0f}")
    m3.metric("Custom Savings",     f"₹{c_savings:,.0f}", f"{c_reduction:.0f}% cost reduction")

    # ── FULL THESIS TABLE 6 ───────────────────────────────────────────────
    with st.expander("📋 Thesis Table 6 — Exact figures (Chapter 4.9)"):
        st.dataframe(
            df_sa.drop(columns=["colour", "label"]).rename(
                columns={"Savings (₹)": "Savings per USD 100,000 (₹)"}
            ),
            hide_index=True,
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════
# TAB 4 — ABOUT THE RESEARCH
# ═══════════════════════════════════════════════════════════
elif page == "🎓 About the Research":

    st.title("🎓 About the Research")
    st.markdown("---")

    col_logo, col_info = st.columns([1, 3], gap="large")
    with col_logo:
        st.image("logo.png", width=180)
    with col_info:
        st.markdown(
            """
            | Field | Detail |
            |---|---|
            | **Project Title** | Strategic Impact of BRICS CBDC Linkage on Pricing Competitiveness of Indian Exporters |
            | **Author** | Yatin Kumar |
            | **College Roll No.** | 257023 |
            | **University Roll No.** | 25078195034 |
            | **Program** | Post Graduate Diploma in International Marketing (PGDIM 2025–26) |
            | **Institution** | Sri Guru Gobind Singh College of Commerce, University of Delhi |
            | **Mentor** | Dr. Kriti Chadha (Assistant Professor, University of Delhi) |
            | **Submission** | Partial fulfillment of PGDIM requirements |
            """
        )

    st.markdown("---")
    st.markdown("### Executive Summary")
    st.markdown(
        """
        This research investigates the strategic marketing implications of the Reserve Bank of
        India's **January 2026 proposal** to link the Central Bank Digital Currencies (CBDCs)
        of BRICS nations.

        Currently, Indian exporters suffer reduced pricing competitiveness due to the
        **Dominant Currency Paradigm**, where US Dollar-denominated SWIFT settlements
        artificially inflate the landed cost of exports through correspondent banking fees,
        double foreign exchange spreads, and chronic settlement delays.

        Utilizing a quantitative comparative cost simulation grounded in secondary data from
        the RBI, BIS, and World Bank, this study models a standard **USD 100,000 export
        transaction** under traditional SWIFT infrastructure versus the proposed CBDC framework.

        The findings mathematically reveal that direct peer-to-peer CBDC settlement:
        - ✅ Reduces cross-border transaction costs by **82%** (from 3.38% → 0.60% of export value)
        - ✅ Generates savings of **₹2,63,336** per USD 100,000 transaction
        - ✅ Compresses settlement from **3 business days → real-time**
        - ✅ Eliminates hedging costs and working capital lock-in

        From an international marketing perspective, this **2.78 percentage point cost advantage**
        provides Indian exporters — particularly MSMEs in Delhi operating in textiles, garments,
        handicrafts, and engineering goods — with unprecedented pricing elasticity deployable
        as **Penetration Pricing** or **Margin Expansion**.
        """
    )

    st.markdown("---")
    st.markdown("### Primary Data Sources")
    sources = [
        ("Reserve Bank of India (RBI)", "Digital Rupee pilot reports, BRICS linkage proposal, January 2026"),
        ("Bank for International Settlements (BIS)", "Project mBridge data — $55B+ processed, 50% cost reduction benchmark"),
        ("World Bank", "3% FX spread benchmark for SWIFT commercial bank transactions (2023)"),
        ("SWIFT (SWIFT Annual Report)", "Correspondent banking fee schedules, 3-day settlement average"),
        ("UNCTAD", "Intra-BRICS merchandise trade: >USD 1.17 trillion (2026)"),
    ]
    for source, detail in sources:
        st.markdown(f"- **{source}** — {detail}")

    st.markdown("---")
    st.markdown("### App Architecture Notes")
    st.markdown(
        f"""
        - **Live forex data:** Yahoo Finance (`yfinance`) — cached for 1 hour to handle traffic spikes
        - **Fallback rates:** Thesis baseline activated if Yahoo Finance is unavailable
        - **Current data status:** {'🟢 Live market data active' if is_live else '🟡 Thesis baseline active'}
        - **Last cache refresh:** Every hour from app start
        - **Hosting:** Streamlit Community Cloud (free tier, HTTPS secured)
        - **Source code:** Push `app.py` + `requirements.txt` to GitHub → deploy at share.streamlit.io
        """
    )
