import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import io
import os
from datetime import datetime
from google.oauth2 import service_account
from google.cloud import storage

# --- CONFIGURAZIONE CLOUD STORAGE ---
BUCKET_NAME = "Archivio Anagrafe EAN"
DB_LOCAL_PATH = "/tmp/database_prezzi_vfinal.db"

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
        try:
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob("database_prezzi.db")
            blob.upload_from_filename(DB_LOCAL_PATH)
        except: st.error("Errore sincronizzazione Cloud")

# Inizializzazione
if not os.path.exists(DB_LOCAL_PATH): download_db()
conn = sqlite3.connect(DB_LOCAL_PATH, check_same_thread=False)

def init_db():
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS prodotti (ean TEXT PRIMARY KEY, descrizione TEXT, data_immissione TEXT, iva TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS mappatura (ean TEXT, fornitore TEXT, codice_interno TEXT, UNIQUE(ean, fornitore, codice_interno))')
    c.execute('CREATE TABLE IF NOT EXISTS listini (id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, fornitore TEXT, prezzo REAL, prezzo_consigliato REAL, data_listino TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS rilevazioni (id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, punto_vendita TEXT, prezzo_scaffale REAL, data_rilevazione TEXT)')
    conn.commit()

init_db()

def export_excel(df, sheet_name="Dati"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

# --- INTERFACCIA ---
st.set_page_config(page_title="OmniPrice Hub v5", layout="wide")
st.sidebar.title("🎮 OmniPrice Cloud")
pwd = st.sidebar.text_input("Password", type="password")

if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["📊 Report & Export", "🛒 Rilevazione Scaffale", "📥 Import Listini", "⚙️ Rosetta"]
    scelta = st.sidebar.radio("Naviga", menu)

    # 1. REPORT & EXPORT
    if scelta == "📊 Report & Export":
        st.title("📊 Estrazione Dati e Comparazione")
        
        t1, t2 = st.tabs(["📄 Export Rilevato", "🆚 Comparazione Listini"])
        
        with t1:
            st.subheader("Storico Rilevazioni Punti Vendita")
            df_ril = pd.read_sql("""
                SELECT r.data_rilevazione as Data, r.ean as EAN, p.descrizione as Prodotto, 
                       r.punto_vendita as Negozio, r.prezzo_scaffale as Prezzo_Rilevato
                FROM rilevazioni r JOIN prodotti p ON r.ean = p.ean
                ORDER BY r.data_rilevazione DESC
            """, conn)
            if not df_ril.empty:
                st.dataframe(df_ril)
                st.download_button("📥 Scarica Excel Rilevazioni", export_excel(df_ril, "Rilevato"), "rilevazioni.xlsx")
            else: st.info("Nessuna rilevazione salvata.")

        with t2:
            st.subheader("Confronto tra Listini Fornitori (Ultimo Prezzo)")
            df_comp = pd.read_sql("""
                SELECT p.descrizione as Prodotto, l.ean as EAN, l.fornitore as Fornitore, l.prezzo as Prezzo
                FROM listini l JOIN prodotti p ON l.ean = p.ean
                WHERE l.id IN (SELECT MAX(id) FROM listini GROUP BY ean, fornitore)
            """, conn)
            
            if not df_comp.empty:
                pivot = df_comp.pivot(index=['EAN', 'Prodotto'], columns='Fornitore', values='Prezzo')
                st.write("Comparazione Prezzi d'Acquisto tra Grossisti:")
                st.dataframe(pivot.style.highlight_min(axis=1, color='#C6EFCE'))
                st.download_button("📥 Scarica Excel Comparazione", export_excel(pivot.reset_index(), "Confronto"), "comparazione_listini.xlsx")
            else: st.info("Dati insufficienti per la comparazione.")

    # 2. RILEVAZIONE SCAFFALE
    elif scelta == "🛒 Rilevazione Scaffale":
        st.title("🛒 Nuova Rilevazione")
        with st.form("ril"):
            e_ril = st.text_input("EAN Prodotto")
            p_ril = st.selectbox("Punto Vendita Rilevato", ["Tigre", "Oasi", "Concorrente", "Altro"])
            prz = st.number_input("Prezzo Scaffale (€)", format="%.2f")
            if st.form_submit_button("Registra Rilevazione"):
                conn.execute("INSERT INTO rilevazioni (ean, punto_vendita, prezzo_scaffale, data_rilevazione) VALUES (?,?,?,?)",
                             (e_ril, p_ril, prz, datetime.now().strftime('%d/%m/%Y')))
                conn.commit()
                upload_db()
                st.success("Rilevazione salvata correttamente!")

    # 3. IMPORT LISTINI
    elif scelta == "📥 Import Listini":
        st.title("📥 Caricamento Listini Grossisti")
        forn = st.text_input("Fornitore Listino", "Brendolan")
        f_up = st.file_uploader("PDF o Excel", type=["pdf", "xlsx"])
        if f_up and st.button("Elabora Listino"):
            if f_up.name.endswith(".pdf"):
                with pdfplumber.open(f_up) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        for line in text.split('\n'):
                            m_cod = re.search(r'\s(\d{5,6})\s', line)
                            m_prz = re.search(r'(\d+,\d{2})', line)
                            if m_cod and m_prz:
                                cod = m_cod.group(1)
                                prz = float(m_prz.group(1).replace(',', '.'))
                                res = conn.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore=?", (cod, forn)).fetchone()
                                if res:
                                    conn.execute("INSERT INTO listini (ean, fornitore, prezzo, data_listino) VALUES (?,?,?,?)", 
                                                 (res[0], forn, prz, datetime.now().strftime('%Y-%m-%d')))
                conn.commit()
                upload_db()
                st.success("Listino caricato con successo!")

    # 4. ROSETTA
    elif scelta == "⚙️ Rosetta":
        st.title("⚙️ Gestione Rosetta")
        f_ros = st.file_uploader("Excel Rosetta (Col A: Cod. Interno, Col B: Desc, Col C+: EAN)", type="xlsx")
        if f_ros and st.button("Sincronizza"):
            df_r = pd.read_excel(f_ros, header=None)
            for i, row in df_r.iterrows():
                if i == 0: continue
                c_int, desc = str(row[0]), str(row[1])
                for ean in row.iloc[2:].dropna():
                    e_str = str(ean).split('.')[0].strip()
                    conn.execute("INSERT INTO prodotti (ean, descrizione, data_immissione) VALUES (?,?,?) ON CONFLICT(ean) DO UPDATE SET descrizione=excluded.descrizione", 
                                 (e_str, desc, datetime.now().strftime('%Y-%m-%d')))
                    conn.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?,?,?)", 
                                 (e_str, "Brendolan", c_int))
            conn.commit()
            upload_db()
            st.success("Configurazione Rosetta aggiornata!")
