import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
from tfa_scraper import scrape_tfa_tournament

# ---------- CONFIG ----------
SHEET_NAME = "TFA_Leaderboard_Data"  # title of your Google Sheet tab
GA_ID = st.secrets.get("GA_ID", "")  # optional, for Google Analytics
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")  # set in Streamlit Cloud

# ---------- (Optional) GA tracking ----------
if GA_ID:
    st.markdown(
        f"""
        <!-- Google tag (gtag.js) -->
        <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
        <script>
          window.dataLayer = window.dataLayer || [];
          function gtag(){{dataLayer.push(arguments);}}
          gtag('js', new Date());
          gtag('config', '{GA_ID}');
        </script>
        """,
        unsafe_allow_html=True,
    )

st.set_page_config(page_title="TFA Points Leaderboard", layout="wide")
st.title("🏆 TFA Points Leaderboard")
st.caption("Live totals of TFA State Qualification points. Admin can add tournaments below.")

# ---------- Google Sheets client ----------
def get_gs_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(creds)
    return gc

def ensure_sheet(gc):
    try:
        sh = gc.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        sh = gc.create(SHEET_NAME)
        # share with yourself if needed (view only): sh.share("youremail@domain.com", perm_type="user", role="reader")
        ws = sh.sheet1
        ws.update([["entry","school","qualifying_event","event","points","tournament"]])
        return sh, ws
    ws = sh.sheet1
    # ensure header
    headers = ws.row_values(1)
    needed = ["entry","school","qualifying_event","event","points","tournament"]
    if headers != needed:
        ws.clear()
        ws.update([needed])
    return sh, ws

def load_df(ws):
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

def append_rows(ws, df_new):
    if df_new.empty:
        return
    # Order columns
    cols = ["entry","school","qualifying_event","event","points","tournament"]
    df_new = df_new[cols]
    values = [df_new.columns.tolist()] + df_new.values.tolist()

    # skip header because already present
    values_no_header = values[1:]
    ws.append_rows(values_no_header, value_input_option="RAW")

# ---------- Read current leaderboard ----------
try:
    gc = get_gs_client()
    sh, ws = ensure_sheet(gc)
    data_df = load_df(ws)
except Exception as e:
    st.error(f"Google Sheets connection failed: {e}")
    data_df = pd.DataFrame(columns=["entry","school","qualifying_event","event","points","tournament"])

# Leaderboard view
if not data_df.empty:
    leaderboard_people = (
        data_df.groupby(["entry","school"])["points"]
        .sum()
        .reset_index()
        .sort_values("points", ascending=False)
        .rename(columns={"points":"total_points"})
    )
    st.subheader("Leaderboard (Competitors)")
    st.dataframe(leaderboard_people, use_container_width=True)

    leaderboard_schools = (
        data_df.groupby(["school"])["points"]
        .sum()
        .reset_index()
        .sort_values("points", ascending=False)
        .rename(columns={"points":"total_points"})
    )
    st.subheader("Leaderboard (Schools)")
    st.dataframe(leaderboard_schools, use_container_width=True)
else:
    st.info("No data yet. Add your first tournament below.")

st.divider()

# ---------- Admin: Add a tournament ----------
st.subheader("Admin: Add Tournament Results")
with st.expander("Open Admin Panel"):
    pw = st.text_input("Admin password", type="password")
    tourn_id = st.text_input("Enter Tournament ID (e.g., 36095)")
    run = st.button("Scrape & Append")

    if run:
        if not ADMIN_PASSWORD:
            st.error("ADMIN_PASSWORD is not set in Streamlit secrets.")
        elif pw != ADMIN_PASSWORD:
            st.error("Wrong password.")
        elif not tourn_id.strip():
            st.error("Please enter a tournament ID.")
        else:
            with st.spinner("Scraping tournament and updating sheet..."):
                # scrape
                scraped = scrape_tfa_tournament(tourn_id.strip())
                if not scraped:
                    st.warning("No TFA Qualification data found for this tournament.")
                else:
                    new_df = pd.DataFrame(scraped)[["entry","school","qualifying_event","event","points","tournament"]]
                    try:
                        append_rows(ws, new_df)
                        st.success(f"Appended {len(new_df)} rows from tournament {tourn_id}.")
                    except Exception as e:
                        st.error(f"Failed to append to sheet: {e}")

# ---------- Raw table view + download ----------
if not data_df.empty:
    st.subheader("Raw Data")
    st.dataframe(data_df, use_container_width=True)
    st.download_button(
        "📥 Download CSV",
        data=data_df.to_csv(index=False).encode("utf-8"),
        file_name="tfa_leaderboard_export.csv",
        mime="text/csv",
    )
