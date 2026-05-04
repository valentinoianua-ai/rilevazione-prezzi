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

st.set_page_config(page_title="OmniPrice Hub", layout="wide")

st.sidebar.title("🎮 OmniPrice Control")
pwd = st.sidebar.text_input("Password di accesso", type="password")

if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["📊 Report & Export", "🛒 Rilevazione Scaffale", "📥 Import Listini", "⚙️ Rosetta"]
    scelta = st.sidebar.radio("Naviga tra le funzioni", menu)

    if scelta == "📊 Report & Export":
        st.title("📊 Estrazione Dati e Comparazione")
        t1, t2 = st.tabs(["📄 Export Rilevato", "🆚 Comparazione Listini"])
        with t1:
            df_ril = pd.read_sql("SELECT r.data_rilevazione as Data, r.ean as EAN, p.descrizione as Prodotto, r.punto_vendita as Negozio, r.prezzo_scaffale as Prezzo FROM rilevazioni r LEFT JOIN prodotti p ON r.ean = p.ean", conn)
            if not df_ril.empty:
                st.dataframe(df_ril)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_ril.to_excel(writer, index=False)
                st.download_button("📥 Scarica Excel Rilevazioni", output.getvalue(), "rilevazioni_prezzi.xlsx")

        with t2:
            df_comp = pd.read_sql("SELECT p.descrizione as Prodotto, l.ean as EAN, l.fornitore as Fornitore, l.prezzo as Prezzo FROM listini l JOIN prodotti p ON l.ean = p.ean", conn)
            if not df_comp.empty:
                pivot = df_comp.pivot_table(index=['EAN', 'Prodotto'], columns='Fornitore', values='Prezzo', aggfunc='last')
                st.dataframe(pivot.style.highlight_min(axis=1, color='#C6EFCE'))

    elif scelta == "🛒 Rilevazione Scaffale":
        st.title("🛒 Registra Prezzo Scaffale")
        with st.form("form_rilevazione"):
            e_ril = st.text_input("Inserisci EAN")
            p_ril = st.selectbox("Negozio", ["Tigre", "Oasi", "Concorrente", "Altro"])
            prz = st.number_input("Prezzo Scaffale (€)", format="%.2f", min_value=0.0)
            if st.form_submit_button("Salva Rilevazione"):
                conn.execute("INSERT INTO rilevazioni (ean, punto_vendita, prezzo_scaffale, data_rilevazione) VALUES (?,?,?,?)", (e_ril, p_ril, prz, datetime.now().strftime('%d/%m/%Y %H:%M')))
                conn.commit()
                upload_db()
                st.success("Salvato!")

    elif scelta == "📥 Import Listini":
        st.title("📥 Caricamento Listini Fornitori")
        forn = st.text_input("Nome Fornitore", "Brendolan")
        f_up = st.file_uploader("Carica Listino PDF", type=["pdf"])
        if f_up and st.button("Elabora Documento"):
            with pdfplumber.open(f_up) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        for line in text.split('\n'):
                            m_cod = re.search(r'\s(\d{5,6})\s', line)
                            m_prz = re.search(r'(\d+,\d{2})', line)
                            if m_cod and m_prz:
                                cod_interno = m_cod.group(1)
                                prezzo = float(m_prz.group(1).replace(',', '.'))
                                res = conn.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore=?", (cod_interno, forn)).fetchone()
                                if res:
                                    conn.execute("INSERT INTO listini (ean, fornitore, prezzo, data_listino) VALUES (?,?,?,?)", (res[0], forn, prezzo, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            upload_db()
            st.success("Listino elaborato!")

  elif scelta == "⚙️ Rosetta":
        st.title("⚙️ Configurazione Rosetta")
        t_m1, t_m2, t_m3 = st.tabs(["💾 Importa Vecchio DB", "📄 Importa Excel (EAN Orizzontali)", "📋 Stato Rosetta"])
        
        with t_m1:
            st.subheader("Migrazione dati da .db")
            f_old = st.file_uploader("Carica il file .db", type=["db"], key="db_mig")
            if f_old and st.button("Avvia Migrazione DB"):
                with open("/tmp/migrazione.db", "wb") as f:
                    f.write(f_old.getbuffer())
                try:
                    old_conn = sqlite3.connect("/tmp/migrazione.db")
                    cursor = old_conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    tables = [t[0] for t in cursor.fetchall()]
                    if tables:
                        table_name = tables[0]
                        old_df = pd.read_sql(f"SELECT * FROM {table_name}", old_conn)
                        old_conn.close()
                        c = conn.cursor()
                        col_ean = [c for c in old_df.columns if 'ean' in c.lower()][0]
                        col_int = [c for c in old_df.columns if 'interno' in c.lower() or 'codice' in c.lower()][0]
                        for _, row in old_df.iterrows():
                            ean = str(row[col_ean]).split('.')[0].strip()
                            cod_int = str(row[col_int]).strip()
                            c.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione) VALUES (?,?)", (ean, f"Migrato {ean}"))
                            c.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?,?,?)", (ean, "Brendolan", cod_int))
                        conn.commit()
                        upload_db()
                        st.success(f"Migrazione completata da '{table_name}'!")
                except Exception as e:
                    st.error(f"Errore: {e}")

        with t_m2:
            st.subheader("Caricamento da Excel (Maiorana)")
            st.write("L'Excel deve avere: Col A (Cod. Interno), Col B (Descrizione), Col C in poi (EAN)")
            f_xl = st.file_uploader("Carica Excel Rosetta", type=["xlsx"], key="xl_ros")
            
            if f_xl and st.button("Elabora Excel"):
                try:
                    # Leggiamo l'excel saltando l'intestazione se necessario
                    df_xl = pd.read_excel(f_xl, header=None)
                    c = conn.cursor()
                    count_ean = 0
                    
                    for i, row in df_xl.iterrows():
                        if i == 0: continue # Salta intestazione
                        
                        cod_maiorana = str(row[0]).strip()
                        descrizione = str(row[1]).strip()
                        
                        # Leggiamo tutte le colonne dalla 2 in poi (gli EAN)
                        for ean_val in row[2:]:
                            if pd.notna(ean_val) and str(ean_val).strip() != "":
                                # Puliamo l'EAN (rimuove .0 se letto come numero)
                                ean_clean = str(ean_val).split('.')[0].strip()
                                
                                # Inseriamo in prodotti
                                c.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione, data_immissione) VALUES (?,?,?)", 
                                         (ean_clean, descrizione, datetime.now().strftime('%Y-%m-%d')))
                                
                                # Colleghiamo l'EAN al codice interno (usiamo Brendolan come fornitore predefinito)
                                c.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?,?,?)", 
                                         (ean_clean, "Brendolan", cod_maiorana))
                                count_ean += 1
                    
                    conn.commit()
                    upload_db()
                    st.success(f"Excel elaborato! Inseriti {count_ean} collegamenti EAN.")
                except Exception as e:
                    st.error(f"Errore durante l'elaborazione: {e}")

        with t_m3:
            st.subheader("Verifica Dati")
            df_check = pd.read_sql("""
                SELECT m.codice_interno as 'Cod. Maiorana', p.descrizione, m.ean 
                FROM mappatura m 
                JOIN prodotti p ON m.ean = p.ean 
                LIMIT 500
            """, conn)
            st.dataframe(df_check, use_container_width=True)
