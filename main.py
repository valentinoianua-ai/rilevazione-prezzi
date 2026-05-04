import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import io
import os
from datetime import datetime

# --- DATABASE LOCALE SEMPLICE ---
DB_PATH = "database_universale.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS prodotti (ean TEXT PRIMARY KEY, descrizione TEXT, data_inserimento TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS mappatura (codice_interno TEXT, fornitore TEXT, ean TEXT, UNIQUE(codice_interno, fornitore, ean))')
    c.execute('CREATE TABLE IF NOT EXISTS listini (ean TEXT, fornitore TEXT, prezzo REAL, data_aggiornamento TEXT, UNIQUE(ean, fornitore))')
    conn.commit()

init_db()

st.set_page_config(page_title="OmniPrice Hub", layout="wide")
st.sidebar.title("Login")
pwd = st.sidebar.text_input("Password", type="password")

if pwd == st.secrets.get("password", "V@l3nt!n0"):
    menu = ["🚀 Setup Anagrafica (EAN)", "🔗 Lega Fornitori", "📥 Import Listini", "📊 COMPARAZIONE"]
    scelta = st.sidebar.radio("Menu", menu)

    # --- FASE 1: ANAGRAFICA EAN ---
    if scelta == "🚀 Setup Anagrafica (EAN)":
        st.title("🚀 Fase 1: Anagrafica Centrale")
        files = st.file_uploader("Carica Excel Storici", type="xlsx", accept_multiple_files=True)
        if files and st.button("Aggiorna Anagrafica"):
            for f in files:
                df = pd.read_excel(f, header=None)
                for i, row in df.iterrows():
                    if i == 0: continue
                    desc = str(row[1]).strip()
                    for ean_raw in row[2:]:
                        if pd.notna(ean_raw):
                            ean = str(ean_raw).split('.')[0].strip()
                            if len(ean) > 7:
                                conn.execute("INSERT OR IGNORE INTO prodotti (ean, descrizione, data_inserimento) VALUES (?,?,?)", (ean, desc, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            st.success("Anagrafica aggiornata!")

    # --- FASE 2: LEGA FORNITORI ---
    elif scelta == "🔗 Lega Fornitori":
        st.title("🔗 Fase 2: Mappatura Codici")
        tab_ex, tab_db = st.tabs(["📄 Da Excel", "💾 Da file .db"])
        
        with tab_ex:
            f_forn = st.text_input("Nome Fornitore (es. Brendolan)")
            f_link = st.file_uploader("Carica Excel (A: Cod. Interno | B: EAN)", type="xlsx")
            if f_link and f_forn and st.button("Salva Mappatura"):
                df_l = pd.read_excel(f_link)
                for _, row in df_l.iterrows():
                    cod, ean = str(row[0]).strip(), str(row[1]).split('.')[0].strip()
                    conn.execute("INSERT OR IGNORE INTO mappatura (codice_interno, fornitore, ean) VALUES (?,?,?)", (cod, f_forn, ean))
                conn.commit()
                st.success(f"Mappatura {f_forn} salvata!")

        with tab_db:
            f_db = st.file_uploader("Carica file .db", type="db", key="db_mig")
            if f_db and st.button("Estrai e Collega"):
                with open("temp_mig.db", "wb") as f: f.write(f_db.getbuffer())
                try:
                    old_conn = sqlite3.connect("temp_mig.db")
                    # Trova automaticamente il nome della tabella nel file caricato
                    tab_name = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", old_conn).iloc[0,0]
                    df_old = pd.read_sql(f"SELECT * FROM {tab_name}", old_conn)
                    old_conn.close()
                    
                    # Trova le colonne per EAN e Codice Interno (cerca nomi simili)
                    col_ean = [c for c in df_old.columns if 'ean' in c.lower()][0]
                    col_cod = [c for c in df_old.columns if 'interno' in c.lower() or 'codice' in c.lower()][0]
                    
                    for _, row in df_old.iterrows():
                        ean = str(row[col_ean]).split('.')[0].strip()
                        cod = str(row[col_cod]).strip()
                        conn.execute("INSERT OR IGNORE INTO mappatura (codice_interno, fornitore, ean) VALUES (?,?,?)", (cod, "Brendolan", ean))
                    conn.commit()
                    st.success(f"Mappatura recuperata dalla tabella: {tab_name}")
                except Exception as e:
                    st.error(f"Errore durante l'estrazione: {e}")

    # --- FASE 3: IMPORT LISTINI ---
    elif scelta == "📥 Import Listini":
        st.title("📥 Fase 3: Caricamento Prezzi")
        tipo = st.selectbox("Formato", ["Excel (Generico)", "PDF (Brendolan)"])
        nome_f = st.text_input("Nome Fornitore", "Brendolan")
        f_list = st.file_uploader("Carica Listino")
        
        if f_list and st.button("Elabora e Salva Prezzi"):
            if tipo == "PDF (Brendolan)":
                with pdfplumber.open(f_list) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            for line in text.split('\n'):
                                m_cod = re.search(r'\s(\d{5,6})\s', line)
                                m_prz = re.search(r'(\d+,\d{2})', line)
                                if m_cod and m_prz:
                                    cod_int, prz = m_cod.group(1), float(m_prz.group(1).replace(',', '.'))
                                    res = conn.execute("SELECT ean FROM mappatura WHERE codice_interno=? AND fornitore=?", (cod_int, nome_f)).fetchall()
                                    for r in res:
                                        conn.execute("INSERT OR REPLACE INTO listini (ean, fornitore, prezzo, data_aggiornamento) VALUES (?,?,?,?)", (r[0], nome_f, prz, datetime.now().strftime('%Y-%m-%d')))
                conn.commit()
                st.success("Prezzi PDF caricati!")
            else:
                df_temp = pd.read_excel(f_list)
                st.info("Seleziona le colonne corrette dall'Excel caricato")
                c_ean = st.selectbox("Colonna EAN", df_temp.columns)
                c_prz = st.selectbox("Colonna PREZZO", df_temp.columns)
                for _, row in df_temp.iterrows():
                    try:
                        ean = str(row[c_ean]).split('.')[0].strip()
                        prz = float(str(row[c_prz]).replace(',', '.'))
                        conn.execute("INSERT OR REPLACE INTO listini (ean, fornitore, prezzo, data_aggiornamento) VALUES (?,?,?,?)", (ean, nome_f, prz, datetime.now().strftime('%Y-%m-%d')))
                    except: continue
                conn.commit()
                st.success("Prezzi Excel caricati!")

    # --- FASE 4: COMPARAZIONE ---
    elif scelta == "📊 COMPARAZIONE":
        st.title("📊 Tabella Comparativa")
        df_f = pd.read_sql("""
            SELECT p.ean as EAN, p.descrizione as PRODOTTO, l.fornitore as FORNITORE, l.prezzo as PREZZO 
            FROM prodotti p 
            INNER JOIN listini l ON p.ean = l.ean
        """, conn)
        if not df_f.empty:
            pivot = df_f.pivot_table(index=['EAN', 'PRODOTTO'], columns='FORNITORE', values='PREZZO')
            st.dataframe(pivot.style.highlight_min(axis=1, color='#C6EFCE'), use_container_width=True)
        else:
            st.warning("Nessun prezzo caricato. Vai in 'Import Listini'.")
