import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import io
import os
from datetime import datetime

# --- CONFIGURAZIONE STORAGE ---
DB_LOCAL_PATH = "/tmp/database_universale.db"
BUCKET_NAME = "Archivio Anagrafe EAN"

try:
    from google.oauth2 import service_account
    from google.cloud import storage
    GCP_AVAILABLE = True
except:
    GCP_AVAILABLE = False

def get_gcs_client():
    if GCP_AVAILABLE and "gcp_service_account" in st.secrets:
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
        try:
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob("database_prezzi.db")
            blob.upload_from_filename(DB_LOCAL_PATH)
        except: st.error("Errore backup Cloud")

if not os.path.exists(DB_LOCAL_PATH): download_db()
conn = sqlite3.connect(DB_LOCAL_PATH, check_same_thread=False)

def init_db():
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS prodotti (ean TEXT PRIMARY KEY, descrizione TEXT, data_inserimento TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS mappatura (codice_interno TEXT, fornitore TEXT, ean TEXT, UNIQUE(codice_interno, fornitore, ean))')
    c.execute('CREATE TABLE IF NOT EXISTS listini (ean TEXT, fornitore TEXT, prezzo REAL, data_aggiornamento TEXT, UNIQUE(ean, fornitore))')
    conn.commit()

init_db()

st.set_page_config(page_title="Comparatore Prezzi", layout="wide")
pwd = st.sidebar.text_input("Password", type="password")

if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["🚀 Setup Anagrafica (EAN)", "🔗 Lega Fornitori", "📥 Import Listini", "📊 COMPARAZIONE"]
    scelta = st.sidebar.radio("Menu", menu)

    # --- FASE 1: ANAGRAFICA ---
    if scelta == "🚀 Setup Anagrafica (EAN)":
        st.title("🚀 Fase 1: Anagrafica EAN")
        files = st.file_uploader("Carica Excel Storici", type="xlsx", accept_multiple_files=True)
        if files and st.button("Importa EAN"):
            c = conn.cursor()
            for f in files:
                df = pd.read_excel(f, header=None)
                for i, row in df.iterrows():
                    if i == 0: continue
                    desc = str(row[1]).strip()
                    for ean_raw in row[2:]:
                        if pd.notna(ean_raw):
                            ean = str(ean_raw).split('.')[0].strip()
                            if len(ean) > 7:
                                c.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione, data_inserimento) VALUES (?,?,?)", (ean, desc, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            upload_db()
            st.success("Anagrafica aggiornata!")

    # --- FASE 2: LEGA FORNITORI (CORRETTA) ---
    elif scelta == "🔗 Lega Fornitori":
        st.title("🔗 Fase 2: Lega Codici Brendolan a EAN")
        
        t1, t2 = st.tabs(["📄 Da Excel", "💾 Da vecchio file .db"])
        
        with t1:
            f_link = st.file_uploader("Carica Excel (Cod. Interno | EAN)", type="xlsx")
            if f_link and st.button("Collega da Excel"):
                df_l = pd.read_excel(f_link)
                c = conn.cursor()
                for _, row in df_l.iterrows():
                    cod, ean = str(row[0]).strip(), str(row[1]).split('.')[0].strip()
                    c.execute("INSERT OR IGNORE INTO mappatura (codice_interno, fornitore, ean) VALUES (?,?,?)", (cod, "Brendolan", ean))
                conn.commit()
                upload_db()
                st.success("Collegamenti Excel salvati!")

        with t2:
            st.info("Usa questa sezione per il file 'mappatu...endolan.db' che hai mostrato nello screenshot.")
            f_db = st.file_uploader("Carica file .db", type="db")
            if f_db and st.button("Estrai Mappatura da DB"):
                with open("/tmp/temp_mig.db", "wb") as f: f.write(f_db.getbuffer())
                old_c = sqlite3.connect("/tmp/temp_mig.db")
                try:
                    # Cerchiamo di leggere dalla tabella 'link' o 'mappatura'
                    df_old = pd.read_sql("SELECT * FROM link", old_c)
                    old_c.close()
                    c = conn.cursor()
                    for _, row in df_old.iterrows():
                        # Adattiamo i nomi colonne del vecchio DB
                        c_int = str(row['codice_interno']).strip()
                        c_ean = str(row['ean']).split('.')[0].strip()
                        c.execute("INSERT OR IGNORE INTO mappatura (codice_interno, fornitore, ean) VALUES (?,?,?)", (c_int, "Brendolan", c_ean))
                    conn.commit()
                    upload_db()
                    st.success("Mappatura Brendolan recuperata con successo dal file DB!")
                except Exception as e: st.error(f"Errore: {e}")

    # --- FASE 3: IMPORT LISTINI (PDF) ---
    elif scelta == "📥 Import Listini":
        st.title("📥 Fase 3: Caricamento Listino PDF")
        f_p = st.file_uploader("Carica PDF Brendolan", type="pdf")
        if f_p and st.button("Leggi PDF e assegna prezzi"):
            c = conn.cursor()
            with pdfplumber.open(f_p) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        for line in text.split('\n'):
                            m_cod = re.search(r'\s(\d{5,6})\s', line)
                            m_prz = re.search(r'(\d+,\d{2})', line)
                            if m_cod and m_prz:
                                cod_int = m_cod.group(1)
                                prz = float(m_prz.group(1).replace(',', '.'))
                                res = c.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore='Brendolan'", (cod_int,)).fetchall()
                                for r in res:
                                    c.execute("INSERT OR REPLACE INTO listini (ean, fornitore, prezzo, data_aggiornamento) VALUES (?,?,?,?)", (r[0], "Brendolan", prz, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            upload_db()
            st.success("Listino Brendolan caricato!")

    # --- FASE 4: COMPARAZIONE ---
    elif scelta == "📊 COMPARAZIONE":
        st.title("📊 Comparazione Finale")
        df_f = pd.read_sql("SELECT p.ean, p.descrizione, l.fornitore, l.prezzo FROM prodotti p LEFT JOIN listini l ON p.ean = l.ean", conn)
        if not df_f.empty:
            pivot = df_f.pivot_table(index=['ean', 'descrizione'], columns='fornitore', values='prezzo')
            st.dataframe(pivot, use_container_width=True)
