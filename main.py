import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
import io
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Granello di Sabbia Pro", layout="wide", page_icon="💎")

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

# --- LOGICA DI ESTRAZIONE ---
def clean_barcode(valore):
    if pd.isna(valore): return None
    ean_str = "".join(filter(str.isdigit, str(valore).split('.')[0]))
    return ean_str if 8 <= len(ean_str) <= 13 else None

def estrai_peso(testo):
    match = re.search(r'(\d+)\s?(GR|KG|ML|LT)', str(testo), re.IGNORECASE)
    return match.group(0) if match else ""

def analizza_pdf_brendolan(file_pdf, fornitore):
    prodotti_estratti = []
    with pdfplumber.open(file_pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            # Pattern specifico Brendolan: Codice (6 cifre), Descrizione, EAN, Prezzi
            # Cerchiamo blocchi che contengono 'EAN' e 'Cess.'
            items = re.split(r'(\d{6})\n', text) # Split sul codice fornitore a 6 cifre
            for i in range(1, len(items), 2):
                cod_int = items[i]
                corpo = items[i+1]
                
                ean_m = re.search(r'EAN\s(\d{13})', corpo)
                cess_m = re.search(r'Cess\.\s(\d+,\d+)', corpo)
                vend_m = re.search(r'Vend\.\s(\d+,\d+)', corpo)
                desc_m = corpo.split('\n')[0].strip()
                
                if ean_m and cess_m:
                    prodotti_estratti.append({
                        'codice': cod_int,
                        'descrizione': desc_m,
                        'ean': ean_m.group(1),
                        'costo': float(cess_m.group(1).replace(',', '.')),
                        'vendita': float(vend_m.group(1).replace(',', '.')) if vend_m else 0,
                        'peso': estrai_peso(corpo)
                    })
    return prodotti_estratti

# --- INTERFACCIA ---
st.sidebar.title("💎 Granello di Sabbia")
menu = ["Dashboard", "Importa Listino (Excel/PDF)", "Confronto Prezzi"]
choice = st.sidebar.radio("Menu:", menu)

if choice == "Importa Listino (Excel/PDF)":
    st.title("📥 Importazione Dinamica Listini")
    nome_fornitore = st.text_input("Nome Fornitore (es. Apulia, Brendolan)")
    file_up = st.file_uploader("Carica Listino", type=["xlsx", "pdf"])

    if file_up and nome_fornitore:
        if file_up.name.endswith(".xlsx"):
            df = pd.read_excel(file_up)
            st.write("### Mappatura Colonne Excel")
            with st.form("map_form"):
                cols = ["Nessuna"] + df.columns.tolist()
                c_cod = st.selectbox("Colonna Codice Fornitore", cols)
                c_des = st.selectbox("Colonna Descrizione", cols)
                c_ean = st.selectbox("Colonna EAN", cols)
                c_cos = st.selectbox("Colonna Costo Cessione", cols)
                c_ven = st.selectbox("Colonna Prezzo Vendita", cols)
                c_iva = st.selectbox("Colonna IVA", cols)
                btn = st.form_submit_button("Importa Excel")
            
            if btn:
                conn = get_connection(); c = conn.cursor()
                for _, row in df.iterrows():
                    ean = clean_barcode(row[c_ean]) if c_ean != "Nessuna" else None
                    if ean:
                        c.execute("SELECT id_prodotto FROM barcode WHERE ean = ?", (ean,))
                        r = c.fetchone()
                        id_p = r[0] if r else None
                        if not id_p:
                            desc = str(row[c_des]) if c_des != "Nessuna" else "Prodotto Ignoto"
                            iva = int(row[c_iva]) if c_iva != "Nessuna" and not pd.isna(row[c_iva]) else 22
                            c.execute("INSERT INTO prodotti (descrizione, peso, iva) VALUES (?,?,?)", (desc, estrai_peso(desc), iva))
                            id_p = c.lastrowid
                            c.execute("INSERT INTO barcode (ean, id_prodotto) VALUES (?,?)", (ean, id_p))
                        
                        costo = float(row[c_cos]) if c_cos != "Nessuna" and not pd.isna(row[c_cos]) else 0
                        prezzo_v = float(row[c_ven]) if c_ven != "Nessuna" and not pd.isna(row[c_ven]) else 0
                        cod_i = str(row[c_cod]) if c_cod != "Nessuna" else None
                        
                        if cod_i: c.execute("INSERT OR REPLACE INTO mappatura_fornitori (id_prodotto, fornitore, codice_interno) VALUES (?,?,?)", (id_p, nome_fornitore, cod_i))
                        c.execute("INSERT INTO listini (id_prodotto, fornitore, costo_cessione, prezzo_suggerito, data) VALUES (?,?,?,?,?)", (id_p, nome_fornitore, costo, prezzo_v, str(datetime.now().date())))
                conn.commit(); conn.close(); st.success("Excel Importato!")

        elif file_up.name.endswith(".pdf"):
            if st.button("Avvia Scansione PDF Brendolan"):
                dati = analizza_pdf_brendolan(file_up, nome_fornitore)
                conn = get_connection(); c = conn.cursor()
                for d in dati:
                    c.execute("SELECT id_prodotto FROM barcode WHERE ean = ?", (d['ean'],))
                    r = c.fetchone()
                    id_p = r[0] if r else None
                    if not id_p:
                        c.execute("INSERT INTO prodotti (descrizione, peso) VALUES (?,?)", (d['descrizione'], d['peso']))
                        id_p = c.lastrowid
                        c.execute("INSERT INTO barcode (ean, id_prodotto) VALUES (?,?)", (d['ean'], id_p))
                    c.execute("INSERT OR REPLACE INTO mappatura_fornitori (id_prodotto, fornitore, codice_interno) VALUES (?,?,?)", (id_p, nome_fornitore, d['codice']))
                    c.execute("INSERT INTO listini (id_prodotto, fornitore, costo_cessione, prezzo_suggerito, data) VALUES (?,?,?,?,?)", (id_p, nome_fornitore, d['costo'], d['vendita'], str(datetime.now().date())))
                conn.commit(); conn.close(); st.success(f"PDF Elaborato: {len(dati)} prodotti gestiti.")

elif choice == "Confronto Prezzi":
    st.title("⚖️ Analisi Incrociata")
    cerca = st.text_input("Cerca per EAN o Codice Fornitore")
    if cerca:
        conn = get_connection()
        query = f"""
            SELECT p.descrizione, p.peso, l.fornitore, l.costo_cessione, l.prezzo_suggerito, m.codice_interno
            FROM prodotti p
            JOIN barcode b ON p.id_prodotto = b.id_prodotto
            LEFT JOIN listini l ON p.id_prodotto = l.id_prodotto
            LEFT JOIN mappatura_fornitori m ON p.id_prodotto = m.id_prodotto AND l.fornitore = m.fornitore
            WHERE b.ean = '{cerca}' OR m.codice_interno = '{cerca}'
        """
        res_df = pd.read_sql_query(query, conn)
        st.dataframe(res_df)
        conn.close()
