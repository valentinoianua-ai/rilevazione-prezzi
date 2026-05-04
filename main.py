import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import io
import os
from datetime import datetime

# --- CONFIGURAZIONE GOOGLE CLOUD STORAGE ---
try:
    from google.oauth2 import service_account
    from google.cloud import storage
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

BUCKET_NAME = "Archivio Anagrafe EAN"
DB_LOCAL_PATH = "/tmp/database_prezzi_vfinal.db"

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
        except:
            pass

def upload_db():
    client = get_gcs_client()
    if client:
        try:
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob("database_prezzi.db")
            blob.upload_from_filename(DB_LOCAL_PATH)
        except:
            st.error("Errore sincronizzazione Cloud")

# Inizializzazione
if not os.path.exists(DB_LOCAL_PATH):
    download_db()

conn = sqlite3.connect(DB_LOCAL_PATH, check_same_thread=False)

def init_db():
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS prodotti (ean TEXT PRIMARY KEY, descrizione TEXT, data_immissione TEXT, iva TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS mappatura (ean TEXT, fornitore TEXT, codice_interno TEXT, UNIQUE(ean, fornitore, codice_interno))')
    c.execute('CREATE TABLE IF NOT EXISTS listini (id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, fornitore TEXT, prezzo REAL, prezzo_consigliato REAL, data_listino TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS rilevazioni (id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, punto_vendita TEXT, prezzo_scaffale REAL, data_rilevazione TEXT)')
    conn.commit()

init_db()

# --- INTERFACCIA ---
st.set_page_config(page_title="OmniPrice Hub", layout="wide")
st.sidebar.title("🎮 OmniPrice Control")
pwd = st.sidebar.text_input("Password", type="password")

if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["📊 Report", "🛒 Rilevazione", "📥 Import Listini", "⚙️ Rosetta"]
    scelta = st.sidebar.radio("Naviga", menu)

    if scelta == "📊 Report":
        st.title("📊 Report e Comparazione")
        t1, t2 = st.tabs(["📄 Export Rilevato", "🆚 Comparazione Listini"])
        with t1:
            df = pd.read_sql("SELECT r.data_rilevazione, r.ean, p.descrizione, r.punto_vendita, r.prezzo_scaffale FROM rilevazioni r LEFT JOIN prodotti p ON r.ean = p.ean", conn)
            st.dataframe(df, use_container_width=True)
        with t2:
            df_c = pd.read_sql("SELECT p.descrizione, l.ean, l.fornitore, l.prezzo FROM listini l JOIN prodotti p ON l.ean = p.ean", conn)
            if not df_c.empty:
                pivot = df_c.pivot_table(index=['ean', 'descrizione'], columns='fornitore', values='prezzo', aggfunc='last')
                st.dataframe(pivot.style.highlight_min(axis=1, color='#C6EFCE'), use_container_width=True)

    elif scelta == "🛒 Rilevazione":
        st.title("🛒 Nuova Rilevazione")
        with st.form("ril"):
            e = st.text_input("EAN")
            pv = st.selectbox("Negozio", ["Tigre", "Oasi", "Altro"])
            prz = st.number_input("Prezzo", format="%.2f")
            if st.form_submit_button("Salva"):
                conn.execute("INSERT INTO rilevazioni (ean, punto_vendita, prezzo_scaffale, data_rilevazione) VALUES (?,?,?,?)", (e, pv, prz, datetime.now().strftime('%d/%m/%Y')))
                conn.commit()
                upload_db()
                st.success("Rilevato!")

    elif scelta == "📥 Import Listini":
        st.title("📥 Import Listino PDF")
        forn = st.text_input("Fornitore", "Brendolan")
        f = st.file_uploader("Carica PDF", type="pdf")
        if f and st.button("Elabora"):
            with pdfplumber.open(f) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        for line in text.split('\n'):
                            m_cod = re.search(r'\s(\d{5,6})\s', line)
                            m_prz = re.search(r'(\d+,\d{2})', line)
                            if m_cod and m_prz:
                                cod = m_cod.group(1)
                                prz = float(m_prz.group(1).replace(',', '.'))
                                res = conn.execute("SELECT ean FROM mappatura WHERE codice_interno=?", (cod,)).fetchone()
                                if res:
                                    conn.execute("INSERT INTO listini (ean, fornitore, prezzo, data_listino) VALUES (?,?,?,?)", (res[0], forn, prz, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            upload_db()
            st.success("Listino caricato!")

    elif scelta == "⚙️ Rosetta":
        st.title("⚙️ Configurazione Rosetta")
        tab1, tab2, tab3 = st.tabs(["💾 Vecchio DB", "📄 Excel Maiorana", "📋 Stato"])
        
        with tab1:
            f_db = st.file_uploader("Carica .db", type="db")
            if f_db and st.button("Migra DB"):
                with open("/tmp/old.db", "wb") as f_tmp: 
                    f_tmp.write(f_db.getbuffer())
                try:
                    old_conn = sqlite3.connect("/tmp/old.db")
                    tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", old_conn)
                    t_name = tables.iloc[0,0]
                    old_df = pd.read_sql(f"SELECT * FROM {t_name}", old_conn)
                    c_ean = [c for c in old_df.columns if 'ean' in c.lower()][0]
                    c_int = [c for c in old_df.columns if 'interno' in c.lower() or 'codice' in c.lower()][0]
                    for _, r in old_df.iterrows():
                        ean = str(r[c_ean]).split('.')[0].strip()
                        cod = str(r[c_int]).strip()
                        conn.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione) VALUES (?,?)", (ean, f"Migrato {ean}"))
                        conn.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?,?,?)", (ean, "Brendolan", cod))
                    conn.commit()
                    upload_db()
                    st.success("DB Migrato!")
                except Exception as e: 
                    st.error(f"Errore: {e}")

        with tab2:
            st.write("L'Excel deve avere: Colonna A (Codice), Colonna B (Descrizione), Colonne C... (EAN)")
            f_xl = st.file_uploader("Carica Excel Rosetta", type="xlsx")
            if f_xl and st.button("Elabora Excel"):
                df_xl = pd.read_excel(f_xl, header=None)
                c_ros = conn.cursor()
                for i, row in df_xl.iterrows():
                    if i == 0: continue
                    cod, desc = str(row[0]).strip(), str(row[1]).strip()
                    for ean_val in row[2:]:
                        if pd.notna(ean_val) and str(ean_val).strip() != "":
                            ean = str(ean_val).split('.')[0].strip()
                            c_ros.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione) VALUES (?,?)", (ean, desc))
                            c_ros.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?,?,?)", (ean, "Brendolan", cod))
                conn.commit()
                upload_db()
                st.success("Excel Maiorana caricato con successo!")

        with tab3:
            df_st = pd.read_sql("SELECT m.codice_interno as 'Cod. Interno', p.descrizione, m.ean FROM mappatura m JOIN prodotti p ON m.ean = p.ean LIMIT 500", conn)
            st.dataframe(df_st, use_container_width=True)
else:
    st.info("Inserisci la password nella barra laterale.")
