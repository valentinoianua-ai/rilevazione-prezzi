import streamlit as st
import pandas as pd
import sqlite3
import pdfplumber
import re
from datetime import datetime

# --- CONFIGURAZIONE CORE ---
st.set_page_config(page_title="Price Intel Manager", layout="wide")

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

# --- FUNZIONI TECNICHE ---
def pulisci_ean(v):
    if pd.isna(v): return None
    s = "".join(filter(str.isdigit, str(v).split('.')[0]))
    return s if 8 <= len(s) <= 13 else None

def estrai_peso(t):
    m = re.search(r'(\d+)\s?(GR|KG|ML|LT)', str(t), re.IGNORECASE)
    return m.group(0) if m else ""

def scan_brendolan(file_pdf, fornitore):
    dati = []
    with pdfplumber.open(file_pdf) as pdf:
        for page in pdf.pages:
            testo = page.extract_text()
            # Split basato sui codici prodotto a 6 cifre trovati nel PDF
            blocchi = re.split(r'(\d{6})\n', testo) 
            for i in range(1, len(blocchi), 2):
                cod = blocchi[i]
                corpo = blocchi[i+1]
                ean = re.search(r'EAN\s(\d{13})', corpo)
                cess = re.search(r'Cess\.\s(\d+,\d+)', corpo)
                vend = re.search(r'Vend\.\s(\d+,\d+)', corpo)
                desc = corpo.split('\n')[0].strip()
                if ean and cess:
                    dati.append({
                        'cod': cod, 'desc': desc, 'ean': ean.group(1),
                        'costo': float(cess.group(1).replace(',', '.')),
                        'vendita': float(vend.group(1).replace(',', '.')) if vend else 0
                    })
    return dati

# --- INTERFACCIA ---
menu = ["Dashboard", "Importa Listino", "Analisi Prezzi"]
scelta = st.sidebar.radio("Navigazione", menu)

if scelta == "Importa Listino":
    st.title("📥 Caricamento Listini")
    f_nome = st.text_input("Fornitore (es. Apulia, Brendolan)")
    f_up = st.file_uploader("Trascina qui il file", type=["xlsx", "pdf"])

    if f_up and f_nome:
        if f_up.name.endswith(".xlsx"):
            df = pd.read_excel(f_up)
            st.dataframe(df.head(3))
            with st.form("map"):
                c = df.columns.tolist()
                sel_cod = st.selectbox("Colonna Codice", c)
                sel_ean = st.selectbox("Colonna EAN", c)
                sel_des = st.selectbox("Colonna Descrizione", c)
                sel_pre = st.selectbox("Colonna Costo", c)
                if st.form_submit_button("Esegui Import"):
                    conn = get_connection(); cursor = conn.cursor()
                    for _, r in df.iterrows():
                        ean = pulisci_ean(r[sel_ean])
                        if ean:
                            cursor.execute("SELECT id_prodotto FROM barcode WHERE ean=?", (ean,))
                            res = cursor.fetchone()
                            id_p = res[0] if res else None
                            if not id_p:
                                cursor.execute("INSERT INTO prodotti (descrizione, peso) VALUES (?,?)", (str(r[sel_des]), estrai_peso(r[sel_des])))
                                id_p = cursor.lastrowid
                                cursor.execute("INSERT INTO barcode (ean, id_prodotto) VALUES (?,?)", (ean, id_p))
                            cursor.execute("INSERT OR REPLACE INTO mappatura_fornitori (id_prodotto, fornitore, codice_interno) VALUES (?,?,?)", (id_p, f_nome, str(r[sel_cod])))
                            cursor.execute("INSERT INTO listini (id_prodotto, fornitore, costo_cessione, data) VALUES (?,?,?,?)", (id_p, f_nome, float(r[sel_pre]), str(datetime.now().date())))
                    conn.commit(); conn.close(); st.success("Import completato")

        elif f_up.name.endswith(".pdf"):
            if st.button("Analizza PDF Brendolan"):
                risultati = scan_brendolan(f_up, f_nome)
                conn = get_connection(); cursor = conn.cursor()
                for d in risultati:
                    cursor.execute("SELECT id_prodotto FROM barcode WHERE ean=?", (d['ean'],))
                    res = cursor.fetchone()
                    id_p = res[0] if res else None
                    if not id_p:
                        cursor.execute("INSERT INTO prodotti (descrizione, peso) VALUES (?,?)", (d['desc'], estrai_peso(d['desc'])))
                        id_p = cursor.lastrowid
                        cursor.execute("INSERT INTO barcode (ean, id_prodotto) VALUES (?,?)", (d['ean'], id_p))
                    cursor.execute("INSERT OR REPLACE INTO mappatura_fornitori (id_prodotto, fornitore, codice_interno) VALUES (?,?,?)", (id_p, f_nome, d['cod']))
                    cursor.execute("INSERT INTO listini (id_prodotto, fornitore, costo_cessione, prezzo_suggerito, data) VALUES (?,?,?,?,?)", (id_p, f_nome, d['costo'], d['vendita'], str(datetime.now().date())))
                conn.commit(); conn.close(); st.success(f"Caricati {len(risultati)} prodotti")

elif scelta == "Analisi Prezzi":
    st.title("🔎 Ricerca")
    cerca = st.text_input("Inserisci EAN o Codice Interno")
    if cerca:
        conn = get_connection()
        df_res = pd.read_sql_query(f"SELECT p.descrizione, l.fornitore, l.costo_cessione FROM prodotti p JOIN barcode b ON p.id_prodotto=b.id_prodotto JOIN listini l ON p.id_prodotto=l.id_prodotto WHERE b.ean='{cerca}'", conn)
        st.table(df_res)
        conn.close()
