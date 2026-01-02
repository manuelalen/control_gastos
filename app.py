import streamlit as st
from supabase import create_client
from datetime import date, datetime
import pandas as pd
import matplotlib.pyplot as plt

# ----------------------------
# CONFIG
# ----------------------------
st.set_page_config(page_title="Registro mensual", page_icon="💶", layout="wide")
st.title("💶 Registro mensual")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SCHEMA = "finance"
SOURCES = ["Gasto", "Nómina", "Otros Ingresos"]

# ----------------------------
# HELPERS
# ----------------------------
@st.cache_data(ttl=60)
def load_profiles():
    res = (
        supabase.schema(SCHEMA)
        .table("profiles")
        .select("user_id, full_name")
        .order("user_id")
        .execute()
    )
    return getattr(res, "data", None) or []

@st.cache_data(ttl=30)
def load_monthly_view():
    res = (
        supabase.schema(SCHEMA)
        .table("v_monthly_summary")  # vista
        .select("full_name,user_id,year,month,year_month,ingreso,gastos,ahorro")
        .order("year", desc=False)
        .order("month", desc=False)
        .execute()
    )
    rows = getattr(res, "data", None) or []
    return pd.DataFrame(rows)

@st.cache_data(ttl=30)
def load_income_entries():
    """
    Carga el detalle de inserts desde finance.income_entries.
    Intenta incluir created_at si existe; si no existe, hace fallback.
    """
    # Intento 1: con created_at
    res = (
        supabase.schema(SCHEMA)
        .table("income_entries")
        .select("id,created_at,user_id,year,month,source,amount")
        .order("created_at", desc=True)
        .execute()
    )

    # Si falla (p.ej. porque no existe created_at), fallback sin created_at
    if getattr(res, "error", None):
        res = (
            supabase.schema(SCHEMA)
            .table("income_entries")
            .select("id,user_id,year,month,source,amount")
            .order("year", desc=True)
            .order("month", desc=True)
            .execute()
        )

    rows = getattr(res, "data", None) or []
    return pd.DataFrame(rows)

def ym_to_date(ym: str) -> date:
    # ym = "YYYY-MM"
    return datetime.strptime(ym, "%Y-%m").date()

def date_to_ym(d: date) -> str:
    return d.strftime("%Y-%m")

def eur(x: float) -> str:
    # Formato español simple: 1.234,56 €
    s = f"{x:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"

# ----------------------------
# KPIs (ARRIBA DEL TODO, antes del formulario)
# ----------------------------
st.subheader("💰 Ahorro acumulado")

df_kpi = load_monthly_view()

if df_kpi.empty:
    st.metric("Total ahorro (todos)", eur(0.0))
    st.info("Aún no hay datos para calcular ahorros acumulados.")
else:
    df_kpi["ahorro"] = pd.to_numeric(df_kpi["ahorro"], errors="coerce").fillna(0)

    total_ahorro = float(df_kpi["ahorro"].sum())
    st.metric("Total ahorro (todos)", eur(total_ahorro))

    df_ahorro_user = (
        df_kpi.groupby(["full_name", "user_id"], as_index=False)["ahorro"]
        .sum()
        .sort_values("ahorro", ascending=False)
    )

    # Si hay pocos usuarios, muéstralos como tarjetas arriba
    if len(df_ahorro_user) <= 6:
        cols = st.columns(len(df_ahorro_user))
        for i, row in enumerate(df_ahorro_user.itertuples(index=False)):
            with cols[i]:
                st.metric(row.full_name, eur(float(row.ahorro)))

    # Tabla con el acumulado por usuario
    st.dataframe(
        df_ahorro_user[["full_name", "ahorro"]].rename(
            columns={"full_name": "Usuario", "ahorro": "Ahorro acumulado (€)"}
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ----------------------------
# FORMULARIO (ARRIBA)
# ----------------------------
profiles = load_profiles()
if not profiles:
    st.error("No hay usuarios en finance.profiles.")
    st.stop()

name_to_id = {p["full_name"]: p["user_id"] for p in profiles}
user_names = list(name_to_id.keys())

with st.form("insert_form", clear_on_submit=True):
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])

    with c1:
        selected_name_form = st.selectbox("Usuario", user_names, key="user_form")
    with c2:
        source = st.selectbox("Tipo", SOURCES, key="source_form")
    with c3:
        today = date.today()
        year = st.number_input(
            "Año",
            min_value=2000,
            max_value=2100,
            value=today.year,
            step=1,
            key="year_form",
        )
    with c4:
        month = st.number_input(
            "Mes",
            min_value=1,
            max_value=12,
            value=today.month,
            step=1,
            key="month_form",
        )

    amount = st.number_input(
        "Cantidad (€)",
        min_value=0.00,
        value=0.00,
        step=1.00,
        format="%.2f",
        key="amount_form",
    )
    submitted = st.form_submit_button("Insertar")

if submitted:
    if amount <= 0:
        st.error("La cantidad debe ser mayor que 0.")
    else:
        payload = {
            "user_id": name_to_id[selected_name_form],
            "year": int(year),
            "month": int(month),
            "source": source,
            "amount": float(amount),
        }
        try:
            res = (
                supabase.schema(SCHEMA)
                .table("income_entries")  # <-- aquí se insertan los datos
                .insert(payload)
                .execute()
            )
            if getattr(res, "error", None):
                st.error(f"Error insertando: {res.error}")
            else:
                st.success("Insertado correctamente ✅")
                st.cache_data.clear()
        except Exception as e:
            st.exception(e)

st.divider()

# ----------------------------
# DASHBOARD (DEBAJO)
# ----------------------------
st.subheader("📈 Evolución mensual")

df = load_monthly_view()

if df.empty:
    st.info("Aún no hay datos para construir la vista mensual.")
    st.stop()

df["ym_date"] = df["year_month"].apply(ym_to_date)

# Sidebar slicers (izquierda)
st.sidebar.header("Filtros")

user_filter = st.sidebar.selectbox("Usuario", sorted(df["full_name"].unique().tolist()))
metric_label = st.sidebar.selectbox("Qué quieres ver", ["Ingresos", "Gastos", "Ahorro"])

min_d = df["ym_date"].min()
max_d = df["ym_date"].max()

date_from = st.sidebar.date_input("Fecha origen", value=min_d, min_value=min_d, max_value=max_d)
date_to = st.sidebar.date_input("Fecha destino", value=max_d, min_value=min_d, max_value=max_d)

if date_from > date_to:
    date_from, date_to = date_to, date_from

metric_map = {
    "Ingresos": "ingreso",
    "Gastos": "gastos",
    "Ahorro": "ahorro",
}
metric_col = metric_map[metric_label]

df_f = df[
    (df["full_name"] == user_filter)
    & (df["ym_date"] >= date_from)
    & (df["ym_date"] <= date_to)
].copy()

df_f = df_f.sort_values(["year", "month"])

st.markdown(
    f"**Usuario:** {user_filter}  \n"
    f"**Métrica:** {metric_label}  \n"
    f"**Rango:** {date_to_ym(date_from)} → {date_to_ym(date_to)}"
)

if df_f.empty:
    st.warning("No hay datos en ese rango.")
else:
    fig = plt.figure()
    plt.plot(df_f["year_month"], df_f[metric_col])
    plt.xticks(rotation=45, ha="right")
    plt.xlabel("Mes")
    plt.ylabel(metric_label)
    plt.tight_layout()
    st.pyplot(fig)

st.subheader("📋 Tabla (vista mensual)")
cols_show = ["year_month", "ingreso", "gastos", "ahorro"]
df_table = df_f[cols_show].copy()
st.dataframe(df_table, use_container_width=True, hide_index=True)

# ----------------------------
# HISTÓRICO (DETALLE DE INSERTS)
# ----------------------------
st.divider()
st.subheader("🧾 Histórico de registros (detalle de inserts)")

df_entries = load_income_entries()

if df_entries.empty:
    st.info("Aún no hay inserts en finance.income_entries.")
else:
    # Enlazar user_id -> full_name
    df_profiles = pd.DataFrame(profiles)  # ya cargado arriba
    df_entries = df_entries.merge(df_profiles, on="user_id", how="left")

    # Normalizar numéricos
    for col in ["year", "month", "amount"]:
        if col in df_entries.columns:
            df_entries[col] = pd.to_numeric(df_entries[col], errors="coerce")

    # Construir YYYY-MM
    df_entries["year_month"] = df_entries.apply(
        lambda r: f"{int(r['year']):04d}-{int(r['month']):02d}"
        if pd.notna(r.get("year")) and pd.notna(r.get("month"))
        else None,
        axis=1,
    )

    # Filtros del histórico (en el panel principal)
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        hist_user = st.selectbox(
            "Usuario (histórico)",
            ["(Todos)"] + sorted(df_entries["full_name"].dropna().unique().tolist()),
            key="hist_user",
        )
    with c2:
        hist_tipo = st.selectbox(
            "Tipo (histórico)",
            ["(Todos)"] + sorted(df_entries["source"].dropna().unique().tolist()),
            key="hist_tipo",
        )
    with c3:
        # si existe created_at, se puede limitar por fecha
        if "created_at" in df_entries.columns:
            # parse si viene como string
            df_entries["created_at_dt"] = pd.to_datetime(df_entries["created_at"], errors="coerce")
            min_ins = df_entries["created_at_dt"].min()
            max_ins = df_entries["created_at_dt"].max()
            if pd.isna(min_ins) or pd.isna(max_ins):
                date_range = None
            else:
                date_range = st.date_input(
                    "Rango inserción (histórico)",
                    value=(min_ins.date(), max_ins.date()),
                    min_value=min_ins.date(),
                    max_value=max_ins.date(),
                    key="hist_date_range",
                )
        else:
            date_range = None
            st.caption("ℹ️ No hay columna created_at en income_entries, no se filtra por fecha de inserción.")

    df_hist = df_entries.copy()

    if hist_user != "(Todos)":
        df_hist = df_hist[df_hist["full_name"] == hist_user]
    if hist_tipo != "(Todos)":
        df_hist = df_hist[df_hist["source"] == hist_tipo]

    if "created_at_dt" in df_hist.columns and date_range is not None:
        d0, d1 = date_range
        if d0 > d1:
            d0, d1 = d1, d0
        df_hist = df_hist[
            (df_hist["created_at_dt"].dt.date >= d0) & (df_hist["created_at_dt"].dt.date <= d1)
        ]

    # Preparar columnas finales
    df_hist["Cantidad"] = df_hist["amount"].fillna(0).astype(float)
    df_hist["Cantidad (formato)"] = df_hist["Cantidad"].apply(lambda x: eur(float(x)))

    cols = []
    if "created_at" in df_hist.columns:
        cols.append("created_at")
    cols += ["id", "full_name", "user_id", "year_month", "source", "Cantidad", "Cantidad (formato)"]

    df_hist_out = (
        df_hist[cols]
        .rename(
            columns={
                "created_at": "Fecha inserción",
                "id": "ID registro",
                "full_name": "Usuario",
                "user_id": "User ID",
                "year_month": "Mes (YYYY-MM)",
                "source": "Tipo",
            }
        )
        .sort_values(
            by=["Fecha inserción"] if "Fecha inserción" in df_hist.columns else ["Mes (YYYY-MM)"],
            ascending=False,
        )
    )

    st.dataframe(df_hist_out, use_container_width=True, hide_index=True)
