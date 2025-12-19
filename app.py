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

def ym_to_date(ym: str) -> date:
    # ym = "YYYY-MM"
    return datetime.strptime(ym, "%Y-%m").date()

def date_to_ym(d: date) -> str:
    return d.strftime("%Y-%m")

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
        year = st.number_input("Año", min_value=2000, max_value=2100, value=today.year, step=1, key="year_form")
    with c4:
        month = st.number_input("Mes", min_value=1, max_value=12, value=today.month, step=1, key="month_form")

    amount = st.number_input("Cantidad (€)", min_value=0.00, value=0.00, step=1.00, format="%.2f", key="amount_form")
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
                .table("income_entries")
                .insert(payload)
                .execute()
            )
            if getattr(res, "error", None):
                st.error(f"Error insertando: {res.error}")
            else:
                st.success("Insertado correctamente ✅")
                # refrescar caches
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

# Convertir year_month a date para filtrar
df["ym_date"] = df["year_month"].apply(ym_to_date)

# Sidebar slicers (izquierda)
st.sidebar.header("Filtros")

user_filter = st.sidebar.selectbox("Usuario", sorted(df["full_name"].unique().tolist()))
metric_label = st.sidebar.selectbox("Qué quieres ver", ["Ingresos", "Gastos", "Ahorro"])

min_d = df["ym_date"].min()
max_d = df["ym_date"].max()

date_from = st.sidebar.date_input("Fecha origen", value=min_d, min_value=min_d, max_value=max_d)
date_to = st.sidebar.date_input("Fecha destino", value=max_d, min_value=min_d, max_value=max_d)

# Normalizar si el usuario pone al revés
if date_from > date_to:
    date_from, date_to = date_to, date_from

metric_map = {
    "Ingresos": "ingreso",
    "Gastos": "gastos",
    "Ahorro": "ahorro",
}
metric_col = metric_map[metric_label]

# Filtrar
df_f = df[
    (df["full_name"] == user_filter)
    & (df["ym_date"] >= date_from)
    & (df["ym_date"] <= date_to)
].copy()

df_f = df_f.sort_values(["year", "month"])

# --------- LINE CHART (matplotlib)
st.markdown(f"**Usuario:** {user_filter}  \n**Métrica:** {metric_label}  \n**Rango:** {date_to_ym(date_from)} → {date_to_ym(date_to)}")

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

# --------- TABLE (vista filtrada)
st.subheader("📋 Tabla (vista mensual)")
cols_show = ["year_month", "ingreso", "gastos", "ahorro"]
# Formateo simple
df_table = df_f[cols_show].copy()
st.dataframe(df_table, use_container_width=True)
