import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Price Intel Pro", layout="wide")

def get_connection():
    return sqlite3.connect("database_rilevazioni.db", check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (id_prodotto INTEGER PRIMARY KEY AUTOINCREMENT, 
                  descrizione TEXT, peso TEXT, iva INTEGER DEFAULT 22)''')
    c.execute('''CREATE TABLE IF NOT EXISTS barcode 
                 (ean TEXT PRIMARY KEY, id_prodotto INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mappatura_fornitori 
                 (id_mappa INTEGER PRIMARY KEY AUTOINCREMENT, 
                  id_prodotto INTEGER, fornitore TEXT, codice_interno TEXT,
                  UNIQUE(fornitore, codice_interno))''')
    c.execute('''CREATE TABLE IF NOT EXISTS listini 
                 (id_listino INTEGER PRIMARY KEY AUTOINCREMENT, 
                  id_prodotto INTEGER, fornitore TEXT, costo_cessione REAL, 
                  prezzo_suggerito REAL, data TEXT)''')
    conn.commit()
    conn.close()

init_db()

def clean_barcode(valore):
    if pd.isna(valore): return None
    ean_str = "".join(filter(str.isdigit, str(valore).split('.')[0]))
    return ean_str if 8 <= len(ean_str) <= 13 else None

def estrai_peso(testo):
    match = re.search(r'(\d+)\s?(GR|KG|ML|LT)', str(testo), re.IGNORECASE)
    return match.group(0) if match else ""

# --- INTERFACCIA ---
st.sidebar.title("💎 Granello di Sabbia")
menu = ["Dashboard", "Importa Listino (Excel/PDF)", "Confronto Prezzi"]
choice = st.sidebar.radio("Menu:", menu)

if choice == "Importa Listino (Excel/PDF)":
    st.title("📥 Importazione Dinamica Listini")
    
    fornitore = st.text_input("Nome Fornitore (es. Apulia, Brendolan, Maiorana)")
    file_caricato = st.file_uploader("Carica il file del listino", type=["xlsx", "pdf"])

    if file_caricato and fornitore:
        if file_caricato.name.endswith(".xlsx"):
            df = pd.read_excel(file_caricato)
            st.write("### Anteprima del file:")
            st.dataframe(df.head(3))
            
            st.info("Configura la corrispondenza delle colonne per questo file:")
            
            # Form di mappatura dinamica
            with st.form("mappatura_colonne"):
                col1, col2 = st.columns(2)
                cols = ["Nessuna"] + df.columns.tolist()
                
                with col1:
                    c_codice = st.selectbox("Colonna Codice Fornitore", cols)
                    c_desc = st.selectbox("Colonna Descrizione", cols)
                    c_ean = st.selectbox("Colonna Barcode (EAN)", cols)
                with col2:
                    c_costo = st.selectbox("Colonna Prezzo Cessione (Costo)", cols)
                    c_vendita = st.selectbox("Colonna Prezzo Consigliato", cols)
                    c_iva = st.selectbox("Colonna IVA (se presente)", cols)
                
                submit = st.form_submit_button("Avvia Importazione Intelligente")
            
            if submit:
                conn = get_connection()
                c = conn.cursor()
                p_count, m_count = 0, 0
                
                for _, row in df.iterrows():
                    ean_val = clean_barcode(row[c_ean]) if c_ean != "Nessuna" else None
                    if ean_val:
                        # 1. Controllo se esiste già il prodotto via EAN
                        c.execute("SELECT id_prodotto FROM barcode WHERE ean = ?", (ean_val,))
                        res = c.fetchone()
                        
                        if res:
                            id_p = res[0]
                        else:
                            # 2. Nuovo Prodotto
                            desc = str(row[c_desc]) if c_desc != "Nessuna" else "Senza Nome"
                            iva_val = int(row[c_iva]) if (c_iva != "Nessuna" and not pd.isna(row[c_iva])) else 22
                            c.execute("INSERT INTO prodotti (descrizione, peso, iva) VALUES (?,?,?)", 
                                      (desc, estrai_peso(desc), iva_val))
                            id_p = c.lastrowid
                            c.execute("INSERT INTO barcode (ean, id_prodotto) VALUES (?,?)", (ean_val, id_p))
                            p_count += 1
                        
                        # 3. Mappatura Codice Interno e Prezzi
                        cod_int = str(row[c_codice]) if c_codice != "Nessuna" else None
                        prezzo_c = float(row[c_costo]) if (c_costo != "Nessuna" and not pd.isna(row[c_costo])) else 0
                        prezzo_v = float(row[c_vendita]) if (c_vendita != "Nessuna" and not pd.isna(row[c_vendita])) else 0
                        
                        if cod_int:
                            c.execute("INSERT OR REPLACE INTO mappatura_fornitori (id_prodotto, fornitore, codice_interno) VALUES (?,?,?)",
                                      (id_p, fornitore, cod_int))
                        
                        c.execute("INSERT INTO listini (id_prodotto, fornitore, costo_cessione, prezzo_suggerito, data) VALUES (?,?,?,?,?)",
                                  (id_p, fornitore, prezzo_c, prezzo_v, str(datetime.now().date())))
                        m_count += 1
                
                conn.commit()
                conn.close()
                st.success(f"Fatto! Creati {p_count} nuovi prodotti e aggiornati {m_count} listini per {fornitore}.")

        elif file_caricato.name.endswith(".pdf"):
            st.warning("L'importazione PDF usa una logica di scansione automatica per layout tipo Brendolan.")
            if st.button("Avvia Scansione PDF"):
                # Qui si integra la logica pdfplumber specifica
                st.info("Funzione in fase di test...")
