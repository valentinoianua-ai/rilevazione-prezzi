import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import os
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Price Manager", layout="wide")

DB_PATH = "database_rilevazioni.db"

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (id_prodotto INTEGER PRIMARY KEY AUTOINCREMENT, descrizione TEXT, peso TEXT, iva INTEGER DEFAULT 22)''')
    c.execute('''CREATE TABLE IF NOT EXISTS barcode 
                 (ean TEXT PRIMARY KEY, id_prodotto INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mappatura_fornitori 
                 (id_mappa INTEGER PRIMARY KEY AUTOINCREMENT, id_prodotto INTEGER, fornitore TEXT, codice_interno TEXT, UNIQUE(fornitore, codice_interno))''')
    c.execute('''CREATE TABLE IF NOT EXISTS listini 
                 (id_listino INTEGER PRIMARY KEY AUTOINCREMENT, id_prodotto INTEGER, fornitore TEXT, costo_cessione REAL, prezzo_suggerito REAL, data TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- INTERFACCIA ---
menu = ["Dashboard", "Importa Listino", "Analisi Prezzi", "Gestione Sistema"]
scelta = st.sidebar.radio("Navigazione", menu)

if scelta == "Importa Listino":
    st.title("📥 Caricamento Listini")
    f_nome = st.text_input("Fornitore (es. Apulia, Brendolan)")
    f_up = st.file_uploader("Trascina qui il file", type=["xlsx", "pdf"])

    if f_up and f_nome:
        if f_up.name.endswith(".pdf"):
            if st.button(f"Avvia Scansione Massiva ({f_nome})"):
                conn = get_connection()
                cursor = conn.cursor()
                progress_bar = st.progress(0)
                status_text = st.empty()
                count = 0
                
                with pdfplumber.open(f_up) as pdf:
                    total_pages = len(pdf.pages)
                    for i, page in enumerate(pdf.pages):
                        progress = (i + 1) / total_pages
                        progress_bar.progress(progress)
                        status_text.text(f"Elaborazione pagina {i+1} di {total_pages}...")
                        
                        testo = page.extract_text()
                        if not testo or "INDICE" in testo.upper():
                            continue 
                        
                        # Dividiamo il testo in righe per un'analisi chirurgica
                        righe = testo.split('\n')
                        for riga in righe:
                            try:
                                # CERCA EAN: sequenza di 13 cifre
                                ean_m = re.search(r'(\d{13})', riga)
                                # CERCA PREZZO: cerca un formato numero,virgola,due cifre (es. 12,50)
                                prezzo_m = re.search(r'(\d+,\d{2})', riga)
                                
                                if ean_m and prezzo_m:
                                    ean = ean_m.group(1)
                                    # Converte la virgola in punto per il database (es. 12,50 -> 12.50)
                                    costo = float(prezzo_m.group(1).replace(',', '.'))
                                    
                                    # 1. Inserimento prodotto generico se non esiste
                                    desc_placeholder = f"Prodotto {ean}"
                                    cursor.execute("INSERT OR IGNORE INTO prodotti (descrizione) VALUES (?)", (desc_placeholder,))
                                    cursor.execute("SELECT id_prodotto FROM prodotti WHERE descrizione = ?", (desc_placeholder,))
                                    res = cursor.fetchone()
                                    if res:
                                        id_p = res[0]
                                        # 2. Associazione Barcode
                                        cursor.execute("INSERT OR IGNORE INTO barcode (ean, id_prodotto) VALUES (?, ?)", (ean, id_p))
                                        # 3. Inserimento Listino
                                        data_oggi = datetime.now().strftime('%Y-%m-%d')
                                        cursor.execute("""INSERT INTO listini (id_prodotto, fornitore, costo_cessione, data) 
                                                          VALUES (?, ?, ?, ?)""", (id_p, f_nome, costo, data_oggi))
                                        count += 1
                            except Exception as e:
                                continue
                                
                conn.commit()
                conn.close()
                st.success(f"Completato! Caricati {count} record.")

elif scelta == "Gestione Sistema":
    st.title("⚙️ Amministrazione")
    st.write("Scarica il database locale per non perdere i dati:")
    
    if os.path.exists(DB_PATH):
        with open(DB_PATH, "rb") as f:
            st.download_button(
                label="📥 Scarica Database (.db)",
                data=f,
                file_name=f"backup_prezzi_{datetime.now().strftime('%Y%m%d')}.db",
                mime="application/x-sqlite3"
            )
    else:
        st.error("Nessun database trovato.")
