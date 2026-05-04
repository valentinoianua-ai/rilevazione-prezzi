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
        creds = service_account.Credentials.from_account_info(st.secrets["gcp_service_account"])
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

st.set_page_config(page_title="OmniPrice Hub", layout="wide")
pwd = st.sidebar.text_input("Password", type="password")

if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["🚀 Setup Anagrafica (EAN)", "🔗 Lega Fornitori", "📥 Import Listini", "📊 COMPARAZIONE"]
    scelta = st.sidebar.radio("Menu", menu)

    # --- FASE 1: ANAGRAFICA EAN ---
    if scelta == "🚀 Setup Anagrafica (EAN)":
        st.title("🚀 Fase 1: Anagrafica Centrale")
        files = st.file_uploader("Carica Excel Storici Maiorana/Altri", type="xlsx", accept_multiple_files=True)
        if files and st.button("Aggiorna Anagrafica"):
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
            st.success("Database EAN aggiornato!")

    # --- FASE 2: LEGA FORNITORI ---
    elif scelta == "🔗 Lega Fornitori":
        st.title("🔗 Fase 2: Mappatura Codici Interni")
        tab_ex, tab_db = st.tabs(["📄 Carica Excel", "💾 Recupero da .db"])
        with tab_ex:
            f_forn = st.text_input("Nome Fornitore (es. Brendolan, Sogegross, ecc.)")
            f_link = st.file_uploader("Carica Excel (Col A: Cod. Interno | Col B: EAN)", type="xlsx")
            if f_link and f_forn and st.button("Salva Mappatura"):
                df_l = pd.read_excel(f_link)
                c = conn.cursor()
                for _, row in df_l.iterrows():
                    cod, ean = str(row[0]).strip(), str(row[1]).split('.')[0].strip()
                    c.execute("INSERT OR IGNORE INTO mappatura (codice_interno, fornitore, ean) VALUES (?,?,?)", (cod, f_forn, ean))
                conn.commit()
                upload_db()
                st.success(f"Mappatura {f_forn} salvata!")
        with tab_db:
            f_db = st.file_uploader("Carica file .db", type="db")
            if f_db and st.button("Estrai da DB"):
                with open("/tmp/temp_mig.db", "wb") as f: f.write(f_db.getbuffer())
                old_c = sqlite3.connect("/tmp/temp_mig.db")
                try:
                    df_old = pd.read_sql("SELECT * FROM link", old_c)
                    old_c.close()
                    c = conn.cursor()
                    for _, row in df_old.iterrows():
                        c.execute("INSERT OR IGNORE INTO mappatura (codice_interno, fornitore, ean) VALUES (?,?,?)", (str(row['codice_interno']), "Brendolan", str(row['ean']).split('.')[0].strip()))
                    conn.commit()
                    upload_db()
                    st.success("Mappatura Brendolan recuperata dal DB!")
                except Exception as e: st.error(f"Errore: {e}")

    # --- FASE 3: IMPORT LISTINI (UNIVERSALE) ---
    elif scelta == "📥 Import Listini":
        st.title("📥 Fase 3: Caricamento Prezzi Fornitori")
        tipo = st.selectbox("Formato Listino", ["Excel (Altri Fornitori)", "PDF (Brendolan)"])
        nome_f = st.text_input("Nome Fornitore (deve corrispondere alla mappatura)", "Brendolan")
        
        f_list = st.file_uploader("Carica File Listino")
        
        if f_list:
            if tipo == "PDF (Brendolan)":
                if st.button("Elabora Listino PDF"):
                    c = conn.cursor()
                    with pdfplumber.open(f_list) as pdf:
                        for page in pdf.pages:
                            text = page.extract_text()
                            if text:
                                for line in text.split('\n'):
                                    m_cod = re.search(r'\s(\d{5,6})\s', line)
                                    m_prz = re.search(r'(\d+,\d{2})', line)
                                    if m_cod and m_prz:
                                        cod_int, prz = m_cod.group(1), float(m_prz.group(1).replace(',', '.'))
                                        res = c.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore=?", (cod_int, nome_f)).fetchall()
                                        for r in res:
                                            c.execute("INSERT OR REPLACE INTO listini (ean, fornitore, prezzo, data_aggiornamento) VALUES (?,?,?,?)", (r[0], nome_f, prz, datetime.now().strftime('%Y-%m-%d')))
                    conn.commit()
                    upload_db()
                    st.success(f"Listino {nome_f} (PDF) caricato!")
            
            else: # EXCEL PER ALTRI FORNITORI
                df_temp = pd.read_excel(f_list)
                st.write("Anteprima file:")
                st.dataframe(df_temp.head(3))
                cols = df_temp.columns.tolist()
                col_ean = st.selectbox("Seleziona colonna EAN", cols)
                col_prz = st.selectbox("Seleziona colonna PREZZO", cols)
                
                if st.button("Elabora Listino Excel"):
                    c = conn.cursor()
                    count = 0
                    for _, row in df_temp.iterrows():
                        ean = str(row[col_ean]).split('.')[0].strip()
                        try:
                            prz = float(str(row[col_prz]).replace(',', '.'))
                            c.execute("INSERT OR REPLACE INTO listini (ean, fornitore, prezzo, data_aggiornamento) VALUES (?,?,?,?)", (ean, nome_f, prz, datetime.now().strftime('%Y-%m-%d')))
                            count += 1
                        except: continue
                    conn.commit()
                    upload_db()
                    st.success(f"Listino {nome_f} (Excel) caricato: {count} prezzi aggiornati!")

    # --- FASE 4: COMPARAZIONE ---
    elif scelta == "📊 COMPARAZIONE":
        st.title("📊 Tabella Comparativa Listini")
        query = """
            SELECT p.ean as EAN, p.descrizione as Prodotto, l.fornitore as Fornitore, l.prezzo as Prezzo
            FROM prodotti p
            JOIN listini l ON p.ean = l.ean
        """
        df_f = pd.read_sql(query, conn)
        if not df_f.empty:
            pivot = df_f.pivot_table(index=['EAN', 'Prodotto'], columns='Fornitore', values='Prezzo')
            st.dataframe(pivot.style.highlight_min(axis=1, color='#C6EFCE'), use_container_width=True)
            
            # Export Excel
            towrite = io.BytesIO()
            pivot.to_excel(towrite, index=True, engine='openpyxl')
            st.download_button("📥 Scarica Comparazione in Excel", towrite.getvalue(), "comparazione_prezzi.xlsx")
        else:
            st.warning("Nessun dato di listino trovato. Carica i prezzi nella sezione Import.")
else:
    st.info("Inserisci password.")
