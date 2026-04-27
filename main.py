import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import os
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Price Manager Pro", layout="wide")

# Il nome del DB deve essere lo stesso che hai generato sul PC se vuoi che i dati coincidano
DB_PATH = "database_rilevazioni.db"

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Tabella Prodotti
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (id_prodotto INTEGER PRIMARY KEY AUTOINCREMENT, descrizione TEXT, peso TEXT, iva INTEGER DEFAULT 22)''')
    # Tabella Barcode (EAN)
    c.execute('''CREATE TABLE IF NOT EXISTS barcode 
                 (ean TEXT PRIMARY KEY, id_prodotto INTEGER)''')
    # Tabella Mappatura (Il ponte tra codice interno fornitore ed EAN)
    c.execute('''CREATE TABLE IF NOT EXISTS mappatura_fornitori 
                 (id_mappa INTEGER PRIMARY KEY AUTOINCREMENT, id_prodotto INTEGER, fornitore TEXT, codice_interno TEXT, UNIQUE(fornitore, codice_interno))''')
    # Tabella Listini (I prezzi storici)
    c.execute('''CREATE TABLE IF NOT EXISTS listini 
                 (id_listino INTEGER PRIMARY KEY AUTOINCREMENT, id_prodotto INTEGER, fornitore TEXT, costo_cessione REAL, prezzo_suggerito REAL, data TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- FUNZIONI DI SUPPORTO ---
def salva_dato_completo(ean, codice_interno, fornitore, costo, descrizione=""):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 1. Inserisci prodotto
        cursor.execute("INSERT OR IGNORE INTO prodotti (descrizione) VALUES (?)", (descrizione or f"Prodotto {ean}",))
        cursor.execute("SELECT id_prodotto FROM prodotti WHERE descrizione = ?", (descrizione or f"Prodotto {ean}",))
        id_p = cursor.fetchone()[0]

        # 2. Inserisci Barcode
        cursor.execute("INSERT OR IGNORE INTO barcode (ean, id_prodotto) VALUES (?, ?)", (ean, id_p))

        # 3. Inserisci Mappatura Fornitore
        if codice_interno:
            cursor.execute("INSERT OR IGNORE INTO mappatura_fornitori (id_prodotto, fornitore, codice_interno) VALUES (?, ?, ?)", 
                           (id_p, fornitore, str(codice_interno)))

        # 4. Inserisci Listino
        data_oggi = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("INSERT INTO listini (id_prodotto, fornitore, costo_cessione, data) VALUES (?, ?, ?, ?)", 
                       (id_p, fornitore, costo, data_oggi))
        
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

# --- INTERFACCIA ---
menu = ["Dashboard", "Importa Listino", "Gestione Sistema"]
scelta = st.sidebar.radio("Navigazione", menu)

if scelta == "Importa Listino":
    st.title("📥 Caricamento Listini (PDF o Excel)")
    f_nome = st.text_input("Fornitore (es. Brendolan, Apulia)")
    f_up = st.file_uploader("Carica il file (Excel o PDF)", type=["xlsx", "xls", "pdf"])

    if f_up and f_nome:
        # --- CASO EXCEL ---
        if f_up.name.endswith(('.xlsx', '.xls')):
            st.info("Rilevato file Excel. Cerco colonne Codice, EAN e Prezzo...")
            df = pd.read_excel(f_up)
            st.dataframe(df.head())
            
            col_codice = st.selectbox("Seleziona colonna Codice Interno", df.columns)
            col_ean = st.selectbox("Seleziona colonna EAN (se esiste, altrimenti seleziona Codice)", df.columns)
            col_prezzo = st.selectbox("Seleziona colonna Prezzo/Costo", df.columns)

            if st.button("Elabora Excel"):
                successi = 0
                for _, row in df.iterrows():
                    res = salva_dato_completo(
                        ean=str(row[col_ean]), 
                        codice_interno=str(row[col_codice]), 
                        fornitore=f_nome, 
                        costo=float(str(row[col_prezzo]).replace(',', '.'))
                    )
                    if res: successi += 1
                st.success(f"Excel elaborato! Inseriti {successi} prodotti.")

        # --- CASO PDF ---
        elif f_up.name.endswith(".pdf"):
            if st.button(f"Avvia Scansione PDF ({f_nome})"):
                count = 0
                with pdfplumber.open(f_up) as pdf:
                    for page in pdf.pages:
                        testo = page.extract_text()
                        if not testo: continue
                        
                        for riga in testo.split('\n'):
                            ean_m = re.search(r'(\d{13})', riga)
                            prezzo_m = re.search(r'(\d+,\d{2})', riga)
                            # Cerchiamo anche un codice interno opzionale a 6 cifre
                            cod_int_m = re.search(r'\b(\d{6})\b', riga)
                            
                            if ean_m and prezzo_m:
                                ean = ean_m.group(1)
                                costo = float(prezzo_m.group(1).replace(',', '.'))
                                cod_int = cod_int_m.group(1) if cod_int_m else None
                                
                                if salva_dato_completo(ean, cod_int, f_nome, costo):
                                    count += 1
                st.success(f"PDF elaborato! Caricati {count} record.")

elif scelta == "Gestione Sistema":
    st.title("⚙️ Amministrazione")
    
    # Upload del DB generato offline
    st.subheader("Aggiorna Memoria di Sistema")
    db_file = st.file_uploader("Carica il file mappatura_brendolan.db generato sul PC", type=["db"])
    if db_file:
        with open(DB_PATH, "wb") as f:
            f.write(db_file.getbuffer())
        st.success("Database di mappatura aggiornato con successo!")

    st.divider()
    
    if os.path.exists(DB_PATH):
        with open(DB_PATH, "rb") as f:
            st.download_button("📥 Scarica Database Attuale", f, file_name="database_prezzi.db")
