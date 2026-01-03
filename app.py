import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Dashboard Saham BEI", layout="wide")
st.title("📊 Monitoring Saham BEI")

# Ambil senarai saham dari fail yang diupload
uploaded_file = st.sidebar.file_uploader("Upload Kode Saham.xlsx", type=["xlsx", "csv"])

if uploaded_file:
    df_emiten = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
    list_saham = [str(k).strip() + ".JK" for k in df_emiten['Kode Saham'].tolist()]

    tipe_data = st.sidebar.radio("Pilih Tampilan:", ("Harga Penutupan", "Kenaikan (%)"))
    start_date = st.sidebar.date_input("Mula", date.today() - timedelta(days=30))
    end_date = st.sidebar.date_input("Tamat", date.today())

    if st.sidebar.button("Tarik Data"):
        data = yf.download(list_saham, start=start_date, end=end_date)['Close']
        df_tampil = (data.pct_change() * 100).round(2) if tipe_data == "Kenaikan (%)" else data
        st.dataframe(df_tampil.T)