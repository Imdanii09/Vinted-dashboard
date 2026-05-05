import json
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db import (
    delete_search,
    get_all_searches,
    get_items_for_run,
    get_runs_for_search,
    init_db,
    save_run,
    save_search,
)
from i18n import (
    CATEGORY_LABELS,
    CONDITION_LABELS,
    DELAY_LABELS,
    DOMAIN_LABELS,
    ORDER_LABELS,
    STRINGS,
)
from scraper import (
    CATEGORIES,
    CONDITIONS,
    DELAY_MODES,
    DOMAINS,
    ORDER_OPTIONS,
    fetch_items,
)

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Vinted Dashboard",
    page_icon="👗",
    layout="wide",
    initial_sidebar_state="expanded",
)

VINTED_TEAL = "#09B1BA"

st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css');
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif !important;
    }

    .block-container {
        max-width: 1200px !important;
        margin: 0 auto !important;
        padding-top: 4.5rem !important;
        padding-bottom: 2rem !important;
    }

    header[data-testid="stHeader"] {
        z-index: 0 !important;
    }

    .tw-card {
        background-color: white;
        border-radius: 0.75rem;
        padding: 1rem 1.25rem;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s, box-shadow 0.2s;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .tw-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        border-color: #09B1BA;
    }

    @media (prefers-color-scheme: dark) {
        .tw-card {
            background-color: #1e293b;
            border-color: #334155;
        }
        .tw-label { color: #94a3b8 !important; }
        .tw-value { color: #f8fafc !important; }
    }
</style>
""", unsafe_allow_html=True)

init_db()

for key, default in [
    ("selected_search_id", None),
    ("selected_run_id", None),
    ("toast_msg", None),
    ("lang", "es"),
]:
    if key not in st.session_state:
        st.session_state[key] = default

lang = st.session_state["lang"]
T = STRINGS[lang]

# ── Lookup helpers for translated selectbox options ────────────────────────────

_domain_keys   = list(DOMAINS.keys())
_domain_labels = [DOMAIN_LABELS[lang][k] for k in _domain_keys]

_cond_keys   = list(CONDITIONS.keys())
_cond_labels = [CONDITION_LABELS[lang][k] for k in _cond_keys]

_cat_keys   = list(CATEGORIES.keys())
_cat_labels = [CATEGORY_LABELS[lang][k] for k in _cat_keys]

_order_keys   = list(ORDER_OPTIONS.keys())
_order_labels = [ORDER_LABELS[lang][k] for k in _order_keys]

_delay_keys   = list(DELAY_MODES.keys())
_delay_labels = [DELAY_LABELS[lang][k] for k in _delay_keys]


def _s(n: int) -> str:
    """Return 's' for plural, '' for singular."""
    return "s" if n != 1 else ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_params(filters: dict) -> dict:
    params = {}
    if filters.get("search_text"):
        params["search_text"] = filters["search_text"]
    if filters.get("price_from"):
        params["price_from"] = filters["price_from"]
    if filters.get("price_to"):
        params["price_to"] = filters["price_to"]
    if filters.get("catalog_ids"):
        params["catalog_ids"] = filters["catalog_ids"]
    if filters.get("status_ids"):
        ids = [s.strip() for s in str(filters["status_ids"]).split(",") if s.strip()]
        params["status_ids[]"] = ids
    if filters.get("order"):
        params["order"] = filters["order"]
    return params


def run_search(
    domain_url: str,
    params: dict,
    max_items: int,
    delay_min: float = 2.0,
    delay_max: float = 4.0,
    label: str = "",
) -> list[dict]:
    progress_bar = st.progress(0.0, text=f"{label}…")
    counter = st.empty()

    def on_progress(count: int):
        pct = min(count / max_items, 1.0)
        progress_bar.progress(pct, text=f"{label}… {count} / {max_items}")
        counter.caption(f"{count} / {max_items}")

    try:
        items = fetch_items(
            domain_url=domain_url,
            params=params,
            max_items=max_items,
            delay_min=delay_min,
            delay_max=delay_max,
            progress_callback=on_progress,
        )
    except ConnectionError as e:
        progress_bar.empty()
        counter.empty()
        st.error(str(e))
        return []
    except Exception as e:
        progress_bar.empty()
        counter.empty()
        st.error(T["err_unexpected"].format(e=e))
        return []

    progress_bar.empty()
    counter.empty()
    return items


@st.cache_data
def load_history(search_id: int, run_ids: tuple) -> pd.DataFrame:
    rows = []
    for run in get_runs_for_search(search_id):
        items_raw = get_items_for_run(run["id"])
        prices = [i["price"] for i in items_raw if i.get("price") is not None]
        rows.append({
            "run_id":      run["id"],
            "date":        run["run_at"][:16].replace("T", " "),
            "total":       run["item_count"],
            "mean_price":  round(sum(prices) / len(prices), 2) if prices else None,
            "min_price":   min(prices) if prices else None,
            "max_price":   max(prices) if prices else None,
            "median_price":sorted(prices)[len(prices) // 2] if prices else None,
        })
    return pd.DataFrame(rows).sort_values("date")


def ts_to_dt(val):
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc).replace(tzinfo=None)
        return pd.to_datetime(val, utc=True).replace(tzinfo=None)
    except Exception:
        return None


def price_metrics(df: pd.DataFrame):
    d = df.dropna(subset=["price"])
    if d.empty:
        return None
    return {
        "mean":   d["price"].mean(),
        "min":    d["price"].min(),
        "max":    d["price"].max(),
        "median": d["price"].median(),
        "std":    d["price"].std(),
    }


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    # Language toggle
    _title_col, _lang_col = st.columns([3, 1])
    _title_col.markdown(T["app_title"])
    with _lang_col:
        _lang_choice = st.radio(
            "lang", ["ES", "EN"],
            index=0 if lang == "es" else 1,
            horizontal=True,
            label_visibility="collapsed",
            key="lang_radio",
        )
        _new_lang = "es" if _lang_choice == "ES" else "en"
        if _new_lang != lang:
            st.session_state["lang"] = _new_lang
            st.rerun()

    st.markdown("---")

    with st.expander(T["new_search_expander"], expanded=True):
        s_name   = st.text_input(T["search_name_label"], placeholder=T["search_name_ph"])
        s_domain = st.selectbox(T["country_label"], _domain_labels)
        s_text   = st.text_input(T["search_text_label"], placeholder=T["search_text_ph"])

        col_pf, col_pt = st.columns(2)
        s_price_from = col_pf.number_input(T["price_min_label"], min_value=0, value=0, step=1)
        s_price_to   = col_pt.number_input(T["price_max_label"], min_value=0, value=0, step=1,
                                            help=T["price_max_help"])

        s_cat_label = st.selectbox(T["category_label"], _cat_labels)
        s_cat_key   = _cat_keys[_cat_labels.index(s_cat_label)]
        catalog_id  = CATEGORIES[s_cat_key]
        if catalog_id == "_custom":
            custom_val = st.text_input(
                T["custom_id_label"],
                placeholder=T["custom_id_ph"],
                help=T["custom_id_help"],
            )
            catalog_id = "".join(c for c in custom_val if c.isdigit()) if custom_val else None

        s_cond_labels  = st.multiselect(T["condition_label"], _cond_labels)
        s_cond_keys    = [_cond_keys[_cond_labels.index(lbl)] for lbl in s_cond_labels]

        s_order_label  = st.selectbox(T["order_label"], _order_labels)
        s_order_key    = _order_keys[_order_labels.index(s_order_label)]

        s_max = st.slider(T["max_items_label"], 50, 5000, 500, step=50)

        s_delay_label = st.selectbox(T["scan_mode_label"], _delay_labels, index=1)
        s_delay_key   = _delay_keys[_delay_labels.index(s_delay_label)]
        d_min, d_max  = DELAY_MODES[s_delay_key]

        if st.button(T["search_btn"], width="stretch"):
            if not s_name.strip():
                st.error(T["err_no_name"])
            elif not s_text.strip() and not catalog_id:
                st.error(T["err_no_query"])
            else:
                filters = {
                    "search_text": s_text.strip() or None,
                    "price_from":  s_price_from if s_price_from > 0 else None,
                    "price_to":    s_price_to if s_price_to > 0 else None,
                    "catalog_ids": catalog_id if catalog_id and catalog_id != "_custom" else None,
                    "status_ids":  ",".join(CONDITIONS[k] for k in s_cond_keys) if s_cond_keys else None,
                    "order":       ORDER_OPTIONS[s_order_key],
                    "delay_min":   d_min,
                    "delay_max":   d_max,
                }
                domain_url = DOMAINS[_domain_keys[_domain_labels.index(s_domain)]]
                items = run_search(domain_url, build_params(filters), s_max, d_min, d_max,
                                   T["progress_fetching"])
                if items:
                    search_id = save_search(s_name.strip(), filters, domain_url, s_max)
                    run_id    = save_run(search_id, items)
                    st.session_state.selected_search_id = search_id
                    st.session_state.selected_run_id    = run_id
                    st.session_state.toast_msg = T["toast_saved"].format(n=len(items))
                    st.rerun()
                else:
                    st.warning(T["warn_no_items"])

    st.markdown("---")
    st.markdown(T["saved_searches_header"])

    searches = get_all_searches()
    if not searches:
        st.caption(T["no_saved_searches"])
    else:
        for s in searches:
            cols = st.columns([5, 1])
            label = f"{'▶ ' if s['id'] == st.session_state.selected_search_id else ''}{s['name']}"
            if cols[0].button(label, key=f"sel_{s['id']}", width="stretch"):
                runs = get_runs_for_search(s["id"])
                st.session_state.selected_search_id = s["id"]
                st.session_state.selected_run_id    = runs[0]["id"] if runs else None
                st.rerun()
            if cols[1].button("🗑", key=f"del_{s['id']}", help=T["delete_search_help"]):
                delete_search(s["id"])
                if st.session_state.selected_search_id == s["id"]:
                    st.session_state.selected_search_id = None
                    st.session_state.selected_run_id    = None
                st.rerun()
            count = s.get("run_count", 0)
            last  = s.get("last_run", "")[:16].replace("T", " ") if s.get("last_run") else "—"
            st.caption(T["run_count_caption"].format(count=count, s=_s(count), last=last))


# ── Main area ─────────────────────────────────────────────────────────────────

if st.session_state.toast_msg:
    st.toast(st.session_state.toast_msg)
    st.session_state.toast_msg = None

if st.session_state.selected_search_id is None:
    st.markdown(T["welcome_title"])
    st.markdown(T["welcome_body"])
    st.info(T["welcome_tip"])
    st.stop()

# ── Selected search ───────────────────────────────────────────────────────────

selected_id = st.session_state.selected_search_id
searches    = get_all_searches()
search      = next((s for s in searches if s["id"] == selected_id), None)

if search is None:
    st.session_state.selected_search_id = None
    st.rerun()

filters    = json.loads(search["filters"])
domain_url = search["domain"]
max_items  = search.get("max_items", 500)
runs       = get_runs_for_search(selected_id)

# ── Header ────────────────────────────────────────────────────────────────────

header_col, btn_col = st.columns([4, 1])
with header_col:
    st.markdown(f"<h1 class='text-3xl font-bold mb-1'>📊 {search['name']}</h1>",
                unsafe_allow_html=True)
    tags = []
    if filters.get("search_text"):
        tags.append(f"🔎 {filters['search_text']}")
    if filters.get("price_from") or filters.get("price_to"):
        pf = filters.get("price_from") or 0
        pt = filters.get("price_to") or "∞"
        tags.append(f"💶 {pf}–{pt} €")
    if filters.get("status_ids"):
        id_to_key   = {v: k for k, v in CONDITIONS.items()}
        cond_labels = [
            CONDITION_LABELS[lang].get(id_to_key.get(x.strip(), ""), x.strip())
            for x in str(filters["status_ids"]).split(",") if x.strip()
        ]
        tags.append("⭐ " + ", ".join(cond_labels))
    if filters.get("catalog_ids"):
        id_to_key = {v: k for k, v in CATEGORIES.items() if v and v != "_custom"}
        cat_key   = id_to_key.get(filters["catalog_ids"], "")
        cat_label = CATEGORY_LABELS[lang].get(cat_key, filters["catalog_ids"])
        tags.append("📁 " + cat_label)

    if tags:
        tag_html = "".join([
            f"<span class='bg-blue-50 text-blue-700 border border-blue-200 px-3 py-1 rounded-full text-sm font-medium'>{t}</span>"
            for t in tags
        ])
        st.markdown(f"<div class='flex flex-wrap gap-2 mt-2 mb-4'>{tag_html}</div>",
                    unsafe_allow_html=True)
    else:
        st.caption(T["no_extra_filters"])

with btn_col:
    if st.button(T["update_btn"], width="stretch", help=T["update_btn_help"]):
        params = build_params(filters)
        d_min  = filters.get("delay_min", 2.0)
        d_max  = filters.get("delay_max", 4.0)
        items  = run_search(domain_url, params, max_items, d_min, d_max, T["progress_updating"])
        if items:
            run_id = save_run(selected_id, items)
            st.session_state.selected_run_id = run_id
            st.session_state.toast_msg = T["toast_updated"].format(n=len(items))
            st.rerun()
        else:
            st.warning(T["warn_no_items_update"])

if not runs:
    st.warning(T["no_data_warning"])
    st.stop()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_dash, tab_hist = st.tabs([T["tab_dashboard"], T["tab_history"]])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 – Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

with tab_dash:
    run_options = {
        r["id"]: f"{r['run_at'][:16].replace('T', ' ')}  ({r['item_count']})"
        for r in runs
    }
    sel_run_id = st.selectbox(
        T["run_selector_label"],
        options=list(run_options.keys()),
        format_func=lambda x: run_options[x],
        index=0,
    )
    st.session_state.selected_run_id = sel_run_id

    raw_items = get_items_for_run(sel_run_id)
    if not raw_items:
        st.warning(T["no_items_warning"])
        df = pd.DataFrame(columns=["price", "published_at", "condition", "brand", "size",
                                    "title", "currency", "url"])
    else:
        df = pd.DataFrame(raw_items)
    df["price"]        = pd.to_numeric(df["price"], errors="coerce")
    df["published_dt"] = df["published_at"].apply(ts_to_dt)

    # ── KPIs ──────────────────────────────────────────────────────────────────
    m = price_metrics(df)

    total_val = f"{len(df):,}"
    p_mean    = f"{m['mean']:.2f} €"   if m else "—"
    p_min     = f"{m['min']:.2f} €"    if m else "—"
    p_max     = f"{m['max']:.2f} €"    if m else "—"
    p_median  = f"{m['median']:.2f} €" if m else "—"

    cards_html = f"""
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-8 mt-4">
        <div class="tw-card">
            <div class="tw-label text-sm font-medium text-gray-500">{T["kpi_total"]}</div>
            <div class="tw-value text-2xl font-bold text-gray-900 mt-1">{total_val}</div>
        </div>
        <div class="tw-card">
            <div class="tw-label text-sm font-medium text-gray-500">{T["kpi_mean"]}</div>
            <div class="tw-value text-2xl font-bold text-gray-900 mt-1">{p_mean}</div>
        </div>
        <div class="tw-card">
            <div class="tw-label text-sm font-medium text-gray-500">{T["kpi_min"]}</div>
            <div class="tw-value text-2xl font-bold text-gray-900 mt-1">{p_min}</div>
        </div>
        <div class="tw-card">
            <div class="tw-label text-sm font-medium text-gray-500">{T["kpi_max"]}</div>
            <div class="tw-value text-2xl font-bold text-gray-900 mt-1">{p_max}</div>
        </div>
        <div class="tw-card">
            <div class="tw-label text-sm font-medium text-gray-500">{T["kpi_median"]}</div>
            <div class="tw-value text-2xl font-bold text-gray-900 mt-1">{p_median}</div>
        </div>
    </div>
    """
    st.markdown(cards_html, unsafe_allow_html=True)
    st.markdown("<hr class='my-6 border-gray-200 dark:border-gray-700'>", unsafe_allow_html=True)

    # ── Row 1: Timeline + Price distribution ──────────────────────────────────
    c1, c2 = st.columns(2)

    with c1:
        st.subheader(T["chart_timeline_title"])
        df_time = df.dropna(subset=["published_dt"]).copy()
        if not df_time.empty:
            df_time["date"] = df_time["published_dt"].dt.date

            # Separate items whose date matches the scan date (likely fallback timestamps)
            current_run = next((r for r in runs if r["id"] == sel_run_id), None)
            run_date    = pd.to_datetime(current_run["run_at"]).date() if current_run else datetime.now().date()
            df_spike    = df_time[df_time["date"] >= run_date]
            df_time     = df_time[df_time["date"] < run_date]

            if not df_time.empty:
                max_date = df_time["date"].max()
                min_date = max_date - pd.Timedelta(days=365)
                df_time  = df_time[df_time["date"] >= min_date]

                # Group by week when the date range exceeds 30 days
                date_range = (df_time["date"].max() - df_time["date"].min()).days
                if date_range > 30:
                    df_time["period"] = (
                        pd.to_datetime(df_time["date"]).dt.to_period("W").dt.start_time.dt.date
                    )
                    timeline = df_time.groupby("period").size().reset_index(name="count")
                    timeline.rename(columns={"period": "date"}, inplace=True)
                    x_label  = T["chart_timeline_xlabel_week"]
                else:
                    timeline = df_time.groupby("date").size().reset_index(name="count")
                    x_label  = T["chart_timeline_xlabel_day"]

                fig = px.area(
                    timeline, x="date", y="count",
                    labels={"date": x_label, "count": T["chart_timeline_ylabel"]},
                    color_discrete_sequence=[VINTED_TEAL],
                )
                fig.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False),
                    yaxis=dict(gridcolor="rgba(200,200,200,0.2)"),
                    margin=dict(l=20, r=20, t=20, b=20), hovermode="x unified",
                    font=dict(family="Inter, sans-serif"),
                )
                fig.update_traces(line_shape="spline",
                                  fillcolor="rgba(9, 177, 186, 0.2)", line=dict(width=3))
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption(T["timeline_no_older"])

            if not df_spike.empty:
                n = len(df_spike)
                st.caption(T["timeline_spike_caption"].format(n=n, s=_s(n)))
        else:
            st.caption(T["timeline_no_dates"])

    with c2:
        st.subheader(T["chart_price_title"])
        df_price = df.dropna(subset=["price"])
        if not df_price.empty:
            # Clip outliers at the 99th percentile
            p99     = df_price["price"].quantile(0.99)
            n_excl  = int((df_price["price"] > p99).sum())
            df_plot = df_price[df_price["price"] <= p99]

            fig = px.histogram(
                df_plot, x="price", nbins=40,
                labels={"price": T["chart_price_xlabel"]},
                color_discrete_sequence=[VINTED_TEAL],
            )
            fig.update_yaxes(title_text=T["chart_price_ylabel"])
            if m:
                fig.add_vline(x=m["mean"], line_dash="dash", line_color="#FF9F43",
                              annotation_text=T["chart_price_mean_label"].format(v=f"{m['mean']:.0f}"),
                              annotation_position="top right", annotation_font_size=11)
                fig.add_vline(x=m["median"], line_dash="dot", line_color="#28C76F",
                              annotation_text=T["chart_price_median_label"].format(v=f"{m['median']:.0f}"),
                              annotation_position="top left", annotation_font_size=11)
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(gridcolor="rgba(200,200,200,0.2)"), xaxis=dict(showgrid=False),
                margin=dict(l=20, r=20, t=45, b=20), hovermode="x unified",
                font=dict(family="Inter, sans-serif"),
            )
            fig.update_traces(marker_line_width=1, marker_line_color="white", opacity=0.85)
            st.plotly_chart(fig, width="stretch")
            if n_excl > 0:
                st.caption(T["chart_price_excl_caption"].format(
                    n=n_excl, s=_s(n_excl), p=f"{p99:.0f}"
                ))
        else:
            st.caption(T["chart_price_no_data"])

    # ── Row 2: Condition + Brands ──────────────────────────────────────────────
    c3, c4 = st.columns(2)

    with c3:
        st.subheader(T["chart_condition_title"])
        cond_series = df["condition"].dropna()
        if not cond_series.empty:
            cond_counts = cond_series.value_counts().reset_index()
            cond_counts.columns = ["condition", "count"]
            fig = px.pie(
                cond_counts, names="condition", values="count",
                color_discrete_sequence=["#09B1BA", "#4A6CF7", "#7367F0",
                                         "#EA5455", "#FF9F43", "#28C76F"],
                hole=0.6,
            )
            fig.update_traces(textposition="outside", textinfo="percent+label",
                              marker=dict(line=dict(color="white", width=2)))
            fig.update_layout(
                showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=40, r=40, t=10, b=10), font=dict(family="Inter, sans-serif"),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption(T["chart_condition_no_data"])

    with c4:
        st.subheader(T["chart_brands_title"])
        brand_series = df["brand"].dropna()
        if not brand_series.empty:
            brand_counts = brand_series.value_counts().head(10).reset_index()
            brand_counts.columns = ["brand", "count"]
            fig = px.bar(
                brand_counts, x="count", y="brand", orientation="h",
                labels={"count": T["chart_brands_xlabel"], "brand": T["chart_brands_ylabel"]},
                text="count",
                color_discrete_sequence=[VINTED_TEAL],
            )
            fig.update_layout(
                yaxis={"categoryorder": "total ascending", "showgrid": False},
                xaxis={"visible": False, "showgrid": False},
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=20, b=20), font=dict(family="Inter, sans-serif"),
            )
            fig.update_traces(opacity=0.9, textposition="outside",
                              marker_line_width=0, cliponaxis=False)
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption(T["chart_brands_no_data"])

    # ── Items table ───────────────────────────────────────────────────────────
    with st.expander(T["table_expander"], expanded=False):
        fc1, fc2, fc3 = st.columns(3)

        brands_avail = sorted(df["brand"].dropna().unique().tolist())
        sizes_avail  = sorted(df["size"].dropna().unique().tolist(), key=lambda x: (len(x), x))
        conds_avail  = sorted(df["condition"].dropna().unique().tolist())

        sel_brands = fc1.multiselect(T["table_brand_filter"],     brands_avail, key="tbl_brand")
        sel_sizes  = fc2.multiselect(T["table_size_filter"],      sizes_avail,  key="tbl_size")
        sel_conds  = fc3.multiselect(T["table_condition_filter"], conds_avail,  key="tbl_cond")

        df_tbl = df.copy()
        if sel_brands: df_tbl = df_tbl[df_tbl["brand"].isin(sel_brands)]
        if sel_sizes:  df_tbl = df_tbl[df_tbl["size"].isin(sel_sizes)]
        if sel_conds:  df_tbl = df_tbl[df_tbl["condition"].isin(sel_conds)]

        st.caption(T["table_count_caption"].format(shown=len(df_tbl), total=len(df)))

        display_cols = [c for c in ["title", "price", "currency", "brand", "size",
                                     "condition", "published_dt", "url"] if c in df_tbl.columns]
        col_rename = {
            "title":        T["col_title"],
            "price":        T["col_price"],
            "currency":     T["col_currency"],
            "brand":        T["col_brand"],
            "size":         T["col_size"],
            "condition":    T["col_condition"],
            "published_dt": T["col_published"],
            "url":          T["col_url"],
        }
        st.dataframe(
            df_tbl[display_cols].rename(columns=col_rename),
            width="stretch",
            column_config={
                T["col_url"]:       st.column_config.LinkColumn(T["col_url"]),
                T["col_published"]: st.column_config.DatetimeColumn(
                    T["col_published"], format="DD/MM/YYYY HH:mm"
                ),
            },
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 – History
# ═══════════════════════════════════════════════════════════════════════════════

with tab_hist:
    if len(runs) < 2:
        st.info(T["hist_need_more_runs"])
        if runs:
            r = runs[0]
            st.markdown(T["hist_first_run"].format(
                date=r["run_at"][:16].replace("T", " "),
                count=r["item_count"],
            ))
    else:
        with st.spinner("Loading history…"):
            hist_df = load_history(selected_id, tuple(r["id"] for r in runs))

        h1, h2 = st.columns(2)

        with h1:
            st.subheader(T["hist_chart_count_title"])
            fig = px.line(
                hist_df, x="date", y="total", markers=True,
                labels={"date": T["hist_col_date"], "total": T["hist_col_total"]},
                color_discrete_sequence=[VINTED_TEAL],
            )
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(gridcolor="rgba(200,200,200,0.2)"), xaxis=dict(showgrid=False),
                margin=dict(l=20, r=20, t=20, b=20), hovermode="x unified",
                font=dict(family="Inter, sans-serif"),
            )
            fig.update_traces(line=dict(width=3), marker=dict(size=8, line=dict(width=2, color="white")))
            st.plotly_chart(fig, width="stretch")

        with h2:
            st.subheader(T["hist_chart_price_title"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist_df["date"], y=hist_df["mean_price"],
                mode="lines+markers", name=T["hist_mean_label"],
                line=dict(color=VINTED_TEAL, width=3), marker=dict(size=8),
            ))
            fig.add_trace(go.Scatter(
                x=hist_df["date"], y=hist_df["min_price"],
                mode="lines+markers", name=T["hist_min_label"],
                line=dict(color="#28C76F", dash="dash", width=2), marker=dict(size=6),
            ))
            fig.add_trace(go.Scatter(
                x=hist_df["date"], y=hist_df["max_price"],
                mode="lines+markers", name=T["hist_max_label"],
                line=dict(color="#EA5455", dash="dash", width=2), marker=dict(size=6),
            ))
            fig.add_trace(go.Scatter(
                x=hist_df["date"], y=hist_df["median_price"],
                mode="lines+markers", name=T["hist_median_label"],
                line=dict(color="#FF9F43", dash="dot", width=2), marker=dict(size=6),
            ))
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(gridcolor="rgba(200,200,200,0.2)", title=T["hist_price_ylabel"]),
                xaxis=dict(showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
                margin=dict(l=20, r=20, t=20, b=20), hovermode="x unified",
                font=dict(family="Inter, sans-serif"),
            )
            st.plotly_chart(fig, width="stretch")

        st.markdown("---")
        st.subheader(T["hist_table_title"])

        col_map = {
            "date":         T["hist_col_date"],
            "total":        T["hist_col_total"],
            "mean_price":   T["hist_col_mean"],
            "min_price":    T["hist_col_min"],
            "max_price":    T["hist_col_max"],
            "median_price": T["hist_col_median"],
        }
        hist_display = (
            hist_df.drop(columns=["run_id"])
                   .rename(columns=col_map)
                   .set_index(T["hist_col_date"])
        )
        st.dataframe(hist_display, width="stretch")
