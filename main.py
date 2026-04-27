import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import os
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="OmniPrice Hub v2", layout="wide")
DB_PATH = "master_price_archive.db"

# --- FUNZIONI DATABASE ---
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    # 1. Anagrafica Centrale (EAN unico per prodotto)
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (ean TEXT PRIMARY KEY, descrizione TEXT, iva REAL DEFAULT 22)''')
    # 2. Mappatura (Traduzione codici interni dei fornitori)
    c.execute('''CREATE TABLE IF NOT EXISTS mappatura 
                 (ean TEXT, fornitore TEXT, codice_interno TEXT, UNIQUE(ean, fornitore, codice_interno))''')
    # 3. Storico Rilevazioni (Costi, Prezzi Vendita, Concorrenza)
    c.execute('''CREATE TABLE IF NOT EXISTS rilevazioni 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, fornitore_punto TEXT, 
                  prezzo_ingrosso REAL, prezzo_consigliato REAL, prezzo_scaffale REAL, 
                  data TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- MOTORE INCREMENTALE (Il cuore del sistema) ---
def salva_dato_incrementale(ean, descrizione, fornitore, data, p_ing=None, p_cons=None, p_scaf=None, cod_int=None, iva=22):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        ean = str(ean).strip()
        desc = descrizione.upper().strip() if descrizione else f"PRODOTTO {ean}"
        
        # Inserimento/Aggiornamento Anagrafica: non sovrascrive descrizioni reali con "PRODOTTO X"
        cursor.execute("""
            INSERT INTO prodotti (ean, descrizione, iva) VALUES (?, ?, ?)
            ON CONFLICT(ean) DO UPDATE SET 
            descrizione = CASE WHEN descrizione LIKE 'PRODOTTO %' OR descrizione = '' THEN excluded.descrizione ELSE descrizione END,
            iva = COALESCE(excluded.iva, iva)
        """, (ean, desc, iva))

        # Aggiornamento Mappatura Codici Interni
        if cod_int:
            cursor.execute("INSERT OR IGNORE INTO mappatura (ean, fornitore, codice_interno) VALUES (?, ?, ?)", 
                           (ean, fornitore, str(cod_int)))

        # Registrazione della rilevazione specifica
        cursor.execute("""
            INSERT INTO rilevazioni (ean, fornitore_punto, prezzo_ingrosso, prezzo_consigliato, prezzo_scaffale, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ean, fornitore, p_ing, p_cons, p_scaf, data))
        
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Errore nel salvataggio EAN {ean}: {e}")
        return False
    finally:
        conn.close()

# --- INTERFACCIA ---
st.sidebar.title("🎮 OmniPrice Hub")
menu = ["📊 Dashboard Analisi", "📥 Importazione Dati", "🗂️ Gestione Archivio & Rosetta"]
scelta = st.sidebar.radio("Navigazione", menu)

# --- 1. DASHBOARD ANALISI ---
if scelta == "📊 Dashboard Analisi":
    st.title("📊 Dashboard Comparativa")
    
    conn = get_connection()
    query = """
    SELECT p.descrizione, r.ean, r.fornitore_punto, r.prezzo_ingrosso, r.prezzo_scaffale, r.data
    FROM rilevazioni r
    JOIN prodotti p ON r.ean = p.ean
    """
    df_raw = pd.read_sql(query, conn)
    conn.close()

    if not df_raw.empty:
        st.write("Confronto dinamico dei prezzi rilevati:")
        tab1, tab2 = st.tabs(["🛒 Confronto Scaffale (Tigre/Oasi/Mio)", "📦 Confronto Acquisti (Ingrosso)"])
        
        with tab1:
            p_scaffale = df_raw.pivot_table(index=['ean', 'descrizione'], columns='fornitore_punto', values='prezzo_scaffale', aggfunc='last')
            st.dataframe(p_scaffale.style.highlight_min(axis=1, color='lightgreen'))
            
        with tab2:
            p_ingrosso = df_raw.pivot_table(index=['ean', 'descrizione'], columns='fornitore_punto', values='prezzo_ingrosso', aggfunc='last')
            st.dataframe(p_ingrosso.style.highlight_min(axis=1, color='lightblue'))

        if st.button("🚀 Esporta Report Excel Completo"):
            file_rep = "Report_Prezzi_OmniPrice.xlsx"
            with pd.ExcelWriter(file_rep) as writer:
                p_scaffale.to_excel(writer, sheet_name="Scaffale")
                p_ingrosso.to_excel(writer, sheet_name="Ingrosso")
            st.download_button("Scarica Excel", data=open(file_rep, "rb"), file_name=file_rep)
    else:
        st.info("Nessun dato presente. Carica listini o rilevazioni per iniziare.")

# --- 2. IMPORTAZIONE DATI (Excel e PDF) ---
elif scelta == "📥 Importazione Dati":
    st.title("📥 Caricamento Flussi")
    f_nome = st.text_input("Origine Dati (es. Tigre, Brendolan, Mio Negozio)")
    f_up = st.file_uploader("Carica file Excel o PDF", type=["xlsx", "xls", "pdf"])
    
    if f_up and f_nome:
        # GESTIONE EXCEL
        if f_up.name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(f_up)
            st.write("Mappa le colonne del file Excel:")
            c1, c2, c3, c4 = st.columns(4)
            with c1: ean_col = st.selectbox("Colonna EAN", df.columns)
            with c2: desc_col = st.selectbox("Colonna Descrizione", df.columns)
            with c3: ing_col = st.selectbox("Costo Ingrosso", ["Assente"] + list(df.columns))
            with c4: scaf_col = st.selectbox("Prezzo Scaffale", ["Assente"] + list(df.columns))
            
            if st.button("Importa Excel nel Database"):
                data_oggi = datetime.now().strftime('%Y-%m-%d')
                count = 0
                for _, row in df.iterrows():
                    p_ing = float(row[ing_col]) if ing_col != "Assente" else None
                    p_scaf = float(row[scaf_col]) if scaf_col != "Assente" else None
                    if salva_dato_incrementale(row[ean_col], row[desc_col], f_nome, data_oggi, p_ing=p_ing, p_scaf=p_scaf):
                        count += 1
                st.success(f"Importazione completata: {count} prodotti caricati!")

        # GESTIONE PDF (Ripristinata)
        elif f_up.name.endswith(".pdf"):
            st.warning("La scansione PDF cerca EAN e Prezzi (formato 0,00).")
            if st.button("Avvia Scansione PDF"):
                count = 0
                data_oggi = datetime.now().strftime('%Y-%m-%d')
                with pdfplumber.open(f_up) as pdf:
                    for page in pdf.pages:
                        testo = page.extract_text()
                        if not testo: continue
                        for riga in testo.split('\n'):
                            ean_m = re.search(r'(\d{13})', riga)
                            prezzo_m = re.search(r'(\d+,\d{2})', riga)
                            if ean_m and prezzo_m:
                                ean = ean_m.group(1)
                                prezzo = float(prezzo_m.group(1).replace(',', '.'))
                                if salva_dato_incrementale(ean, None, f_nome, data_oggi, p_scaf=prezzo):
                                    count += 1
                st.success(f"Scansione PDF conclusa: {count} record estratti!")

# --- 3. GESTIONE ARCHIVIO & ROSETTA ---
elif scelta == "🗂️ Gestione Archivio & Rosetta":
    st.title("⚙️ Centro Gestione Dati Storici")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📚 Archivio Corposo (Anagrafica)")
        st.write("Carica il tuo Excel maestro (Codice Interno, Descrizione, EAN multipli).")
        f_arch = st.file_uploader("Upload Excel Archivio", type=["xlsx"])
        if f_arch:
            df_a = pd.read_excel(f_arch)
            c1, c2, c3 = st.columns(3)
            col_ean = c1.selectbox("Colonna EAN", df_a.columns)
            col_desc = c2.selectbox("Colonna Descrizione", df_a.columns)
            col_cod = c3.selectbox("Colonna Codice Interno", df_a.columns)
            
            if st.button("Sincronizza Archivio Maestro"):
                data_oggi = datetime.now().strftime('%Y-%m-%d')
                for _, row in df_a.iterrows():
                    salva_dato_incrementale(row[col_ean], row[col_desc], "ARCHIVIO", data_oggi, cod_int=row[col_cod])
                st.success("Archivio sincronizzato con successo!")

    with col2:
        st.subheader("🌩️ Rosetta & Cloud Sync")
        st.write("Usa queste funzioni per non perdere i dati su Google Cloud.")
        
        up_db = st.file_uploader("Ripristina Database (.db)", type=["db"])
        if up_db:
            with open(DB_PATH, "wb") as f:
                f.write(up_db.getbuffer())
            st.success("Database ripristinato correttamente!")
        
        st.divider()
        if os.path.exists(DB_PATH):
            with open(DB_PATH, "rb") as f:
                st.download_button("📥 Scarica Backup Database Attuale", f, file_name="master_price_archive.db")
