import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import os
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="OmniPrice Hub v3.0", layout="wide", page_icon="🎯")
DB_PATH = "master_price_archive.db"

# --- FUNZIONI DATABASE ---
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Anagrafica: EAN è la chiave primaria
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (ean TEXT PRIMARY KEY, descrizione TEXT, iva REAL DEFAULT 22)''')
    # Rosetta: Associa Codice Interno Fornitore -> EAN
    c.execute('''CREATE TABLE IF NOT EXISTS mappatura 
                 (ean TEXT, fornitore TEXT, codice_interno TEXT, UNIQUE(ean, fornitore, codice_interno))''')
    # Rilevazioni: Storico prezzi
    c.execute('''CREATE TABLE IF NOT EXISTS rilevazioni 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, fornitore_punto TEXT, 
                  prezzo_ingrosso REAL, prezzo_consigliato REAL, prezzo_scaffale REAL, 
                  data TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- MOTORE INCREMENTALE ---
def salva_dato_incrementale(ean, descrizione, fornitore, data, p_ing=None, p_cons=None, p_scaf=None, cod_int=None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Pulizia EAN (rimuove .0 e spazi)
        ean_clean = str(ean).split('.')[0].strip()
        if not ean_clean or ean_clean == 'nan' or len(ean_clean) < 8: return False
        
        desc = descrizione.upper().strip() if descrizione and str(descrizione) != 'nan' else f"PRODOTTO {ean_clean}"
        
        # 1. Update Anagrafica
        cursor.execute("""
            INSERT INTO prodotti (ean, descrizione) VALUES (?, ?)
            ON CONFLICT(ean) DO UPDATE SET 
            descrizione = CASE WHEN descrizione LIKE 'PRODOTTO %' OR descrizione = '' THEN excluded.descrizione ELSE descrizione END
        """, (ean_clean, desc))

        # 2. Update Rosetta (Mappatura)
        if cod_int:
            cod_clean = str(cod_int).split('.')[0].strip()
            cursor.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?, ?, ?)", 
                           (ean_clean, fornitore, cod_clean))

        # 3. Registra Prezzo
        cursor.execute("""
            INSERT INTO rilevazioni (ean, fornitore_punto, prezzo_ingrosso, prezzo_consigliato, prezzo_scaffale, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ean_clean, fornitore, p_ing, p_cons, p_scaf, data))
        
        conn.commit()
        return True
    except Exception as e:
        return False
    finally:
        conn.close()

# --- SIDEBAR INFO ---
st.sidebar.title("🎮 OmniPrice Hub")
if os.path.exists(DB_PATH):
    size = os.path.getsize(DB_PATH) / (1024 * 1024)
    st.sidebar.success(f"Database Online: {size:.2f} MB")
else:
    st.sidebar.error("Database mancante!")

menu = ["📊 Dashboard Analisi", "📥 Importazione Listini", "🗂️ Gestione Archivio & Rosetta"]
scelta = st.sidebar.radio("Navigazione", menu)

# --- 1. DASHBOARD ANALISI ---
if scelta == "📊 Dashboard Analisi":
    st.title("📊 Analisi Comparativa")
    conn = get_connection()
    query = """
        SELECT p.descrizione, r.ean, r.fornitore_punto, r.prezzo_ingrosso, r.prezzo_scaffale, r.data
        FROM rilevazioni r
        JOIN prodotti p ON r.ean = p.ean
    """
    df = pd.read_sql(query, conn)
    conn.close()

    if not df.empty:
        col_filtro = st.text_input("🔍 Cerca prodotto o EAN...")
        if col_filtro:
            df = df[df['descrizione'].str.contains(col_filtro.upper()) | df['ean'].contains(col_filtro)]

        tab1, tab2 = st.tabs(["🛒 Prezzi Scaffale", "📦 Costi Ingrosso"])
        with tab1:
            piv_s = df.pivot_table(index=['ean', 'descrizione'], columns='fornitore_punto', values='prezzo_scaffale', aggfunc='last')
            st.dataframe(piv_s.style.highlight_min(axis=1, color='#b7e4c7'))
        with tab2:
            piv_i = df.pivot_table(index=['ean', 'descrizione'], columns='fornitore_punto', values='prezzo_ingrosso', aggfunc='last')
            st.dataframe(piv_i.style.highlight_min(axis=1, color='#a2d2ff'))
    else:
        st.info("Carica dei dati per vedere il confronto.")

# --- 2. IMPORTAZIONE (FOCUS BRENDOLAN PDF) ---
elif scelta == "📥 Importazione Listini":
    st.title("📥 Caricamento Nuovi Listini")
    f_nome = st.text_input("Fornitore (es. Brendolan, Tigre, Oasi)")
    f_up = st.file_uploader("Carica file", type=["xlsx", "xls", "pdf"])
    
    if f_up and f_nome:
        data_oggi = datetime.now().strftime('%Y-%m-%d')
        
        if f_up.name.endswith(".pdf"):
            st.warning("⚠️ Scansione PDF: I prezzi verranno associati tramite Codice Interno (Rosetta).")
            if st.button("🚀 Avvia Scansione Brendolan"):
                count = 0
                with pdfplumber.open(f_up) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if not text: continue
                        for line in text.split('\n'):
                            # Regex per: Codice(inizio riga) ... Prezzo(0,00)
                            m_cod = re.search(r'^(\d{4,7})\s', line)
                            m_prz = re.search(r'(\d+,\d{2})', line)
                            if m_cod and m_prz:
                                cod = m_cod.group(1)
                                prz = float(m_prz.group(1).replace(',', '.'))
                                
                                # Cerca EAN nel DB
                                conn = get_connection()
                                res = conn.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore=?", (cod, f_nome)).fetchone()
                                conn.close()
                                
                                if res:
                                    if salva_dato_incrementale(res[0], None, f_nome, data_oggi, p_ing=prz, cod_int=cod):
                                        count += 1
                st.success(f"Aggiornamento completato! {count} prodotti trovati e aggiornati.")
        else:
            # Importazione Excel Standard
            df_ex = pd.read_excel(f_up)
            cols = st.multiselect("Seleziona colonne: EAN, Descrizione, Prezzo", df_ex.columns)
            # ... logica salvataggio Excel ...

# --- 3. ARCHIVIO & SYNC ---
elif scelta == "🗂️ Gestione Archivio & Rosetta":
    st.title("⚙️ Sincronizzazione Dati")
    
    st.subheader("1️⃣ Importa Archivio Orizzontale (Maiorana/Tutti EAN)")
    f_maestro = st.file_uploader("Excel Archivio (A:Cod, B:Desc, C+:EAN)", type=["xlsx"])
    if f_maestro and st.button("Sincronizza Maestro"):
        df_m = pd.read_excel(f_maestro, header=None)
        c_ean = 0
        for i, row in df_m.iterrows():
            if i == 0: continue
            cod, desc = str(row[0]), str(row[1])
            ean_list = row.iloc[2:].dropna()
            for e in ean_list:
                if salva_dato_incrementale(e, desc, "ARCHIVIO", datetime.now().strftime('%Y-%m-%d'), cod_int=cod):
                    c_ean += 1
        st.success(f"Mappatura completata: {c_ean} EAN salvati.")

    st.divider()
    st.subheader("2️⃣ Backup Cloud (DB Permanente)")
    with open(DB_PATH, "rb") as f:
        st.download_button("📥 Scarica DB per Google Cloud", f, file_name="master_price_archive.db")
    
    up_db = st.file_uploader("📤 Ripristina DB dal Cloud", type=["db"])
    if up_db:
        with open(DB_PATH, "wb") as f:
            f.write(up_db.getbuffer())
        st.rerun()
