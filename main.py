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

# --- CREAZIONE TABELLE (NON CANCELLANO I DATI) ---
def init_db():
    c = conn.cursor()
    # Tabella Prodotti: l'EAN è la chiave unica
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (ean TEXT PRIMARY KEY, descrizione TEXT, data_inserimento TEXT)''')
    # Tabella Mappatura: lega codici interni (Brendolan, ecc) agli EAN
    c.execute('''CREATE TABLE IF NOT EXISTS mappatura 
                 (codice_interno TEXT, fornitore TEXT, ean TEXT, UNIQUE(codice_interno, fornitore, ean))''')
    # Tabella Listini: accumula i prezzi nel tempo
    c.execute('''CREATE TABLE IF NOT EXISTS listini 
                 (ean TEXT, fornitore TEXT, prezzo REAL, data_aggiornamento TEXT, UNIQUE(ean, fornitore))''')
    conn.commit()

init_db()

# --- INTERFACCIA ---
st.set_page_config(page_title="Comparatore Prezzi Universale", layout="wide")
st.sidebar.title("Controllo Accesso")
pwd = st.sidebar.text_input("Password", type="password")

if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["🚀 Setup Anagrafica (EAN)", "🔗 Lega Fornitori", "📥 Import Listini", "📊 COMPARAZIONE"]
    scelta = st.sidebar.radio("Menu", menu)

    # --- FASE 1: IMPALCATURA EAN ---
    if scelta == "🚀 Setup Anagrafica (EAN)":
        st.title("🚀 Fase 1: Costruzione Anagrafica Incrementale")
        st.write("Carica qui i file storici (Maiorana/Altri). Il sistema aggiungerà nuovi EAN senza cancellare i vecchi.")
        files = st.file_uploader("Carica Excel Storici", type="xlsx", accept_multiple_files=True)
        
        if files and st.button("Avvia Importazione Incrementale"):
            c = conn.cursor()
            nuovi = 0
            per_file = ""
            for f in files:
                df = pd.read_excel(f, header=None)
                count_f = 0
                for i, row in df.iterrows():
                    if i == 0: continue
                    desc = str(row[1]).strip()
                    # Prendi tutti gli EAN dalla colonna C in poi
                    for ean_raw in row[2:]:
                        if pd.notna(ean_raw):
                            ean = str(ean_raw).split('.')[0].strip()
                            if len(ean) > 7: # Evita codici spazzatura
                                c.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione, data_inserimento) VALUES (?,?,?)",
                                         (ean, desc, datetime.now().strftime('%Y-%m-%d')))
                                if c.rowcount > 0: count_f += 1
                nuovi += count_f
                per_file += f"- {f.name}: {count_f} nuovi EAN\n"
            conn.commit()
            upload_db()
            st.success(f"Importazione completata!\n{per_file}")

    # --- FASE 2: LEGA FORNITORI ---
    elif scelta == "🔗 Lega Fornitori":
        st.title("🔗 Fase 2: Lega Codici Interni a EAN")
        forn = st.selectbox("Seleziona Fornitore", ["Brendolan", "Altro"])
        f_link = st.file_uploader("Carica Excel Rosetta (Cod. Interno | EAN)", type="xlsx")
        if f_link and st.button("Crea Collegamenti"):
            df_l = pd.read_excel(f_link)
            c = conn.cursor()
            for _, row in df_l.iterrows():
                cod = str(row[0]).strip()
                ean = str(row[1]).split('.')[0].strip()
                c.execute("INSERT OR IGNORE INTO mappatura (codice_interno, fornitore, ean) VALUES (?,?,?)", (cod, forn, ean))
            conn.commit()
            upload_db()
            st.success("Collegamenti creati!")

    # --- FASE 3: IMPORT LISTINI ---
    elif scelta == "📥 Import Listini":
        st.title("📥 Fase 3: Caricamento Prezzi")
        f_type = st.radio("Tipo file", ["PDF (Brendolan)", "Excel (Altri)"])
        forn_p = st.text_input("Nome Fornitore", "Brendolan")
        f_p = st.file_uploader("Carica Listino")
        
        if f_p and st.button("Aggiorna Prezzi"):
            c = conn.cursor()
            if f_type == "PDF (Brendolan)":
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
                                    # Cerca EAN corrispondente al codice Brendolan
                                    res = c.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore=?", (cod_int, forn_p)).fetchall()
                                    for r in res:
                                        c.execute("INSERT OR REPLACE INTO listini (ean, fornitore, prezzo, data_aggiornamento) VALUES (?,?,?,?)",
                                                 (r[0], forn_p, prz, datetime.now().strftime('%Y-%m-%d')))
            else: # Excel
                df_p = pd.read_excel(f_p)
                # Assumiamo Col A = EAN, Col B = Prezzo
                for _, row in df_p.iterrows():
                    ean = str(row[0]).split('.')[0].strip()
                    prz = float(row[1])
                    c.execute("INSERT OR REPLACE INTO listini (ean, fornitore, prezzo, data_aggiornamento) VALUES (?,?,?,?)",
                             (ean, forn_p, prz, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            upload_db()
            st.success("Prezzi aggiornati!")

    # --- FASE 4: COMPARAZIONE ---
    elif scelta == "📊 COMPARAZIONE":
        st.title("📊 Comparazione Listini")
        query = """
            SELECT p.ean as EAN, p.descrizione as Prodotto, l.fornitore as Fornitore, l.prezzo as Prezzo
            FROM prodotti p
            LEFT JOIN listini l ON p.ean = l.ean
        """
        df_final = pd.read_sql(query, conn)
        if not df_final.empty:
            pivot = df_final.pivot_table(index=['EAN', 'Prodotto'], columns='Fornitore', values='Prezzo')
            st.dataframe(pivot.style.highlight_min(axis=1, color='#C6EFCE'), use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                pivot.to_excel(writer)
            st.download_button("📥 Scarica Comparazione Finale", output.getvalue(), "comparazione_prezzi.xlsx")
else:
    st.info("Inserisci password per operare.")
