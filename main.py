import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import io
from datetime import datetime
from google.oauth2 import service_account
from google.cloud import storage

# --- CONFIGURAZIONE ---
BUCKET_NAME = "Archivio Anagrafe EAN"
DB_LOCAL_PATH = "/tmp/database_prezzi_v4.db"

# [Le funzioni get_gcs_client, download_db, upload_db rimangono identiche a prima]

def get_gcs_client():
    if "gcp_service_account" in st.secrets:
        creds = service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"])
        return storage.Client(credentials=creds, project=st.secrets["gcp_service_account"]["project_id"])
    return None

def download_db():
    client = get_gcs_client()
    if client:
        try:
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob("database_prezzi.db")
            blob.download_to_filename(DB_LOCAL_PATH)
        except: pass

def upload_db():
    client = get_gcs_client()
    if client:
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob("database_prezzi.db")
        blob.upload_from_filename(DB_LOCAL_PATH)

download_db()
conn = sqlite3.connect(DB_LOCAL_PATH, check_same_thread=False)

# --- AGGIUNTA FUNZIONI DI EXPORT EXCEL ---

def to_excel_rilevazioni(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Rilevazioni')
    return output.getvalue()

def to_excel_comparazione(df_pivot):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_pivot.to_excel(writer, sheet_name='Comparazione')
        workbook  = writer.book
        worksheet = writer.sheets['Comparazione']
        
        # Formato per evidenziare il prezzo minimo (il più conveniente)
        format_best = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
        
        # Applichiamo una formattazione condizionale sulle colonne dei fornitori
        num_rows = len(df_pivot)
        num_cols = len(df_pivot.columns)
        worksheet.conditional_format(1, 2, num_rows, num_cols + 1, 
                                     {'type': 'bottom', 'value': 1, 'format': format_best})
    return output.getvalue()

# --- INTERFACCIA ---
st.set_page_config(page_title="OmniPrice Hub v4", layout="wide")

# [Logica Password e Menu...]
pwd = st.sidebar.text_input("Password", type="password")
if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["📊 Report & Export", "🛒 Rilevazione", "📥 Import Listini", "⚙️ Rosetta"]
    scelta = st.sidebar.radio("Naviga", menu)

    if scelta == "📊 Report & Export":
        st.title("📊 Produzione Report Excel")
        
        tab1, tab2 = st.tabs(["📄 Export Rilevazioni", "🆚 Comparazione Listini"])
        
        with tab1:
            st.subheader("Scarica storico rilevazioni a scaffale")
            df_ril = pd.read_sql("""
                SELECT p.descrizione, r.ean, r.punto_vendita, r.prezzo_scaffale, r.data_rilevazione 
                FROM rilevazioni r JOIN prodotti p ON r.ean = p.ean
            """, conn)
            if not df_ril.empty:
                st.dataframe(df_ril)
                st.download_button("📥 Scarica Excel Rilevato", to_excel_rilevazioni(df_ril), "rilevazioni_prezzi.xlsx")
            else: st.info("Nessuna rilevazione presente.")

        with tab2:
            st.subheader("Confronto tra Listini Fornitori")
            # Prendiamo solo l'ultimo prezzo caricato per ogni fornitore/EAN
            df_comp = pd.read_sql("""
                SELECT p.descrizione, l.ean, l.fornitore, l.prezzo 
                FROM listini l JOIN prodotti p ON l.ean = p.ean
                WHERE l.id IN (SELECT MAX(id) FROM listini GROUP BY ean, fornitore)
            """, conn)
            
            if not df_comp.empty:
                pivot = df_comp.pivot(index=['ean', 'descrizione'], columns='fornitore', values='prezzo')
                st.write("Anteprima comparazione (il verde indica il prezzo più basso):")
                st.dataframe(pivot.style.highlight_min(axis=1, color='lightgreen'))
                
                st.download_button("📥 Scarica Excel Comparazione", to_excel_comparazione(pivot), "confronto_fornitori.xlsx")
            else: st.info("Carica almeno due listini per vedere la comparazione.")

    # [Le altre sezioni 🛒 Rilevazione, 📥 Import Listini, ⚙️ Rosetta rimangono come nel post precedente]
    # ... (copia le funzioni di inserimento e mappatura dal messaggio precedente)
