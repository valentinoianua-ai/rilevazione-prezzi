import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Price Manager", layout="wide")

def get_connection():
    return sqlite3.connect("database_rilevazioni.db", check_same_thread=False)

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

def estrai_peso(t):
    m = re.search(r'(\d+)\s?(GR|KG|ML|LT)', str(t), re.IGNORECASE)
    return m.group(0) if m else ""

# --- INTERFACCIA ---
menu = ["Dashboard", "Importa Listino", "Analisi Prezzi"]
scelta = st.sidebar.radio("Navigazione", menu)

if scelta == "Importa Listino":
    st.title("📥 Caricamento Listini")
    f_nome = st.text_input("Fornitore (es. Apulia, Brendolan)")
    f_up = st.file_uploader("Trascina qui il file (PDF o Excel)", type=["xlsx", "pdf"])

    if f_up and f_nome:
        if f_up.name.endswith(".pdf"):
            if st.button(f"Avvia Scansione Massiva ({f_nome})"):
                conn = get_connection()
                cursor = conn.cursor()
                
                # Barre di progresso per gestire le 1470 pagine
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                count = 0
                with pdfplumber.open(f_up) as pdf:
                    total_pages = len(pdf.pages)
                    for i, page in enumerate(pdf.pages):
                        # Aggiornamento UI ogni pagina
                        progress = (i + 1) / total_pages
                        progress_bar.progress(progress)
                        status_text.text(f"Elaborazione pagina {i+1} di {total_pages}...")
                        
                        testo = page.extract_text()
                        if not testo: continue
                        
                        # Pattern specifico per i blocchi Brendolan
                        blocchi = re.split(r'(\d{6})\n', testo) 
                        for j in range(1, len(blocchi), 2):
                            cod = blocchi[j]
                            corpo = blocchi[j+1]
                            ean_m = re.search(r'EAN\s(\d{13})', corpo)
                            cess_m = re.search(r'Cess\.\s(\d+,\d+)', corpo)
                            vend_m = re.search(r'Vend\.\s(\d+,\d+)', corpo)
                            desc = corpo.split('\n')[0].strip()
                            
                            if ean_m and cess_m:
                                ean = ean_m.group(1)
                                costo = float(cess_m.group(1).replace(',', '.'))
                                vendita = float(vend_m.group(1).replace(',', '.')) if vend_m else 0
                                
                                # Inserimento atomico per ogni prodotto trovato
                                cursor.execute("SELECT id_prodotto FROM barcode WHERE ean=?", (ean,))
                                res = cursor.fetchone()
                                id_p = res[0] if res else None
                                
                                if not id_p:
                                    cursor.execute("INSERT INTO prodotti (descrizione, peso) VALUES (?,?)", (desc, estrai_peso(desc)))
                                    id_p = cursor.lastrowid
                                    cursor.execute("INSERT INTO barcode (ean, id_prodotto) VALUES (?,?)", (ean, id_p))
                                
                                cursor.execute("INSERT OR REPLACE INTO mappatura_fornitori (id_prodotto, fornitore, codice_interno) VALUES (?,?,?)", (id_p, f_nome, cod))
                                cursor.execute("INSERT INTO listini (id_prodotto, fornitore, costo_cessione, prezzo_suggerito, data) VALUES (?,?,?,?,?)", (id_p, f_nome, costo, vendita, str(datetime.now().date())))
                                count += 1
                        
                        # Ogni 20 pagine facciamo il commit per non sovraccaricare la transazione
                        if i % 20 == 0:
                            conn.commit()
                            
                conn.commit()
                conn.close()
                st.success(f"Operazione completata! Elaborate {total_pages} pagine e caricati {count} record.")

        # ... (Logica Excel Apulia rimane invariata)
