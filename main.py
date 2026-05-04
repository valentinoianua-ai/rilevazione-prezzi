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
            st.error("Errore durante la sincronizzazione con Google Cloud.")

# Inizializzazione Database locale
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

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="OmniPrice Hub", layout="wide")

if not GCP_AVAILABLE:
    st.error("Librerie Google Cloud mancanti nel requirements.txt")

st.sidebar.title("🎮 OmniPrice Control")
pwd = st.sidebar.text_input("Password di accesso", type="password")

# Verifica Password
if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["📊 Report & Export", "🛒 Rilevazione Scaffale", "📥 Import Listini", "⚙️ Rosetta"]
    scelta = st.sidebar.radio("Naviga tra le funzioni", menu)

    # 1. REPORT & EXPORT
    if scelta == "📊 Report & Export":
        st.title("📊 Estrazione Dati e Comparazione")
        t1, t2 = st.tabs(["📄 Export Rilevato", "🆚 Comparazione Listini"])
        
        with t1:
            query_ril = """
                SELECT r.data_rilevazione as Data, r.ean as EAN, p.descrizione as Prodotto, 
                       r.punto_vendita as Negozio, r.prezzo_scaffale as Prezzo
                FROM rilevazioni r 
                LEFT JOIN prodotti p ON r.ean = p.ean
            """
            df_ril = pd.read_sql(query_ril, conn)
            if not df_ril.empty:
                st.dataframe(df_ril)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_ril.to_excel(writer, index=False)
                st.download_button("📥 Scarica Excel Rilevazioni", output.getvalue(), "rilevazioni_prezzi.xlsx")
            else:
                st.info("Nessuna rilevazione salvata.")

        with t2:
            query_comp = """
                SELECT p.descrizione as Prodotto, l.ean as EAN, l.fornitore as Fornitore, l.prezzo as Prezzo
                FROM listini l 
                JOIN prodotti p ON l.ean = p.ean
            """
            df_comp = pd.read_sql(query_comp, conn)
            if not df_comp.empty:
                pivot = df_comp.pivot_table(index=['EAN', 'Prodotto'], columns='Fornitore', values='Prezzo', aggfunc='last')
                st.dataframe(pivot.style.highlight_min(axis=1, color='#C6EFCE'))
                output_c = io.BytesIO()
                with pd.ExcelWriter(output_c, engine='openpyxl') as writer:
                    pivot.to_excel(writer)
                st.download_button("📥 Scarica Comparazione", output_c.getvalue(), "confronto_listini.xlsx")

    # 2. RILEVAZIONE SCAFFALE
    elif scelta == "🛒 Rilevazione Scaffale":
        st.title("🛒 Registra Prezzo Scaffale")
        with st.form("form_rilevazione"):
            e_ril = st.text_input("Inserisci EAN")
            p_ril = st.selectbox("Negozio", ["Tigre", "Oasi", "Concorrente", "Altro"])
            prz = st.number_input("Prezzo Scaffale (€)", format="%.2f", min_value=0.0)
            if st.form_submit_button("Salva Rilevazione"):
                if e_ril:
                    conn.execute("INSERT INTO rilevazioni (ean, punto_vendita, prezzo_scaffale, data_rilevazione) VALUES (?,?,?,?)",
                                 (e_ril, p_ril, prz, datetime.now().strftime('%d/%m/%Y %H:%M')))
                    conn.commit()
                    upload_db()
                    st.success(f"Rilevazione per {e_ril} salvata correttamente!")
                else:
                    st.error("Inserisci un codice EAN valido.")

    # 3. IMPORT LISTINI (DA PDF)
    elif scelta == "📥 Import Listini":
        st.title("📥 Caricamento Listini Fornitori")
        forn = st.text_input("Nome Fornitore (es. Brendolan)", "Brendolan")
        f_up = st.file_uploader("Carica Listino PDF o Excel", type=["pdf", "xlsx"])
        
        if f_up and st.button("Elabora Documento"):
            if f_up.name.endswith(".pdf"):
                with pdfplumber.open(f_up) as pdf:
                    progress = st.progress(0)
                    pages = pdf.pages
                    for i, page in enumerate(pages):
                        text = page.extract_text()
                        if text:
                            for line in text.split('\n'):
                                # Regex per catturare codice (5-6 cifre) e prezzo (0,00)
                                m_cod = re.search(r'\s(\d{5,6})\s', line)
                                m_prz = re.search(r'(\d+,\d{2})', line)
                                if m_cod and m_prz:
                                    cod_interno = m_cod.group(1)
                                    prezzo = float(m_prz.group(1).replace(',', '.'))
                                    # Trova EAN corrispondente nella Rosetta
                                    res = conn.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore=?", (cod_interno, forn)).fetchone()
                                    if res:
                                        conn.execute("INSERT INTO listini (ean, fornitore, prezzo, data_listino) VALUES (?,?,?,?)", 
                                                     (res[0], forn, prezzo, datetime.now().strftime('%Y-%m-%d')))
                        progress.progress((i + 1) / len(pages))
                conn.commit()
                upload_db()
                st.success("Listino PDF elaborato e salvato nel Cloud!")

    # 4. ROSETTA (GESTIONE MAPPATURE)
    elif scelta == "⚙️ Rosetta":
        st.title("⚙️ Configurazione Rosetta")
        t_m1, t_m2 = st.tabs(["💾 Importa Vecchio Database (.db)", "📋 Stato Rosetta"])
        
        with t_m1:
            st.subheader("Migrazione dati da versione precedente")
            f_old = st.file_uploader("Carica il file database precedente", type=["db"])
            if f_old and st.button("Avvia Importazione"):
                with open("/tmp/migrazione.db", "wb") as f:
                    f.write(f_old.getbuffer())
                try:
                    old_conn = sqlite3.connect("/tmp/migrazione.db")
                    old_df = pd.read_sql("SELECT * FROM mappatura", old_conn)
                    old_conn.close()
                    
                    c = conn.cursor()
                    for _, row in old_df.iterrows():
                        ean = str(row['ean']).split('.')[0].strip()
                        cod_int = str(row['codice_interno']).strip()
                        desc = row['descrizione'] if 'descrizione' in row else f"Prodotto {ean}"
                        # Inserimento in anagrafica e mappatura
                        c.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione) VALUES (?,?)", (ean, desc))
                        c.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?,?,?)", (ean, "Brendolan", cod_int))
                    
                    conn.commit()
                    upload_db()
                    st.success("Tutti i dati del vecchio DB sono stati migrati con successo!")
                except Exception as e:
                    st.error(f"Errore durante la lettura del vecchio DB: {e}")

        with t_m2:
            st.subheader("Anteprima collegamenti attivi")
            df_check = pd.read_sql("SELECT fornitore, codice_interno, ean FROM mappatura LIMIT 200", conn)
            st.dataframe(df_check)

else:
    st.info("Benvenuto. Inserisci la password nella barra laterale per accedere ai dati.")
