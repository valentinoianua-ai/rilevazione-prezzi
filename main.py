import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime

# --- CONFIGURAZIONE E SICUREZZA ---
st.set_page_config(page_title="Price Intel Manager", layout="wide", page_icon="📊")

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    st.title("🔐 Accesso Riservato")
    st.markdown("### Sistema di Monitoraggio Prezzi")
    password = st.text_input("Inserisci la password di sistema", type="password")
    if st.button("Accedi"):
        if password == st.secrets["password"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("⚠️ Password errata")
    return False

if not check_password():
    st.stop()

# --- GESTIONE DATABASE ---
DB_NAME = "database_rilevazioni.db"

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (id_prodotto INTEGER PRIMARY KEY AUTOINCREMENT, descrizione TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS barcode 
                 (ean TEXT PRIMARY KEY, id_prodotto INTEGER, 
                 FOREIGN KEY(id_prodotto) REFERENCES prodotti(id_prodotto))''')
    c.execute('''CREATE TABLE IF NOT EXISTS rilevazioni 
                 (id_rilevazione INTEGER PRIMARY KEY AUTOINCREMENT, 
                  id_prodotto INTEGER, prezzo REAL, data TEXT, pdv TEXT,
                  FOREIGN KEY(id_prodotto) REFERENCES prodotti(id_prodotto))''')
    conn.commit()
    conn.close()

init_db()

# --- LOGICA DI PULIZIA EAN ---
def clean_barcode(valore):
    if pd.isna(valore):
        return None
    # Converte da scientifico (8.01E+12) a stringa ed elimina decimali .0
    ean_str = str(valore).split('.')[0].strip()
    # Tiene solo i numeri
    ean_clean = "".join(filter(str.isdigit, ean_str))
    # Filtro lunghezza (8-13 cifre come concordato)
    if 8 <= len(ean_clean) <= 13:
        return ean_clean
    return None

# --- INTERFACCIA ---
st.sidebar.title("🗂️ Menu")
menu = ["Dashboard", "Rilevazione sul Campo", "Importa Master Data", "Esportazione Report"]
choice = st.sidebar.radio("Naviga:", menu)

# 1. DASHBOARD
if choice == "Dashboard":
    st.title("📊 Riepilogo Dati")
    conn = get_connection()
    c = conn.cursor()
    
    stats = {
        "Prodotti": pd.read_sql_query("SELECT COUNT(*) FROM prodotti", conn).iloc[0,0],
        "Barcode Mappati": pd.read_sql_query("SELECT COUNT(*) FROM barcode", conn).iloc[0,0],
        "Rilevazioni": pd.read_sql_query("SELECT COUNT(*) FROM rilevazioni", conn).iloc[0,0]
    }
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Prodotti", stats["Prodotti"])
    col2.metric("EAN Totali", stats["Barcode Mappati"])
    col3.metric("Rilevazioni", stats["Rilevazioni"])
    
    st.subheader("Ultime 10 Rilevazioni")
    query = """
        SELECT r.data, p.descrizione, r.prezzo, r.pdv 
        FROM rilevazioni r JOIN prodotti p ON r.id_prodotto = p.id_prodotto
        ORDER BY r.id_rilevazione DESC LIMIT 10
    """
    st.dataframe(pd.read_sql_query(query, conn), use_container_width=True)
    conn.close()

# 2. RILEVAZIONE SUL CAMPO
elif choice == "Rilevazione sul Campo":
    st.title("📸 Nuova Rilevazione")
    with st.form("form_ril"):
        pdv = st.text_input("Punto Vendita", "Coal Gesù Bambino, Napoli")
        ean = st.text_input("Scansiona o digita EAN")
        prezzo = st.number_input("Prezzo (€)", min_value=0.0, step=0.01, format="%.2f")
        data = st.date_input("Data", datetime.now())
        if st.form_submit_button("Salva Dato"):
            ean_c = clean_barcode(ean)
            if ean_c:
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT id_prodotto FROM barcode WHERE ean = ?", (ean_c,))
                res = c.fetchone()
                if res:
                    c.execute("INSERT INTO rilevazioni (id_prodotto, prezzo, data, pdv) VALUES (?,?,?,?)",
                              (res[0], prezzo, str(data), pdv))
                    conn.commit()
                    st.success(f"Registrato: {ean_c}")
                else:
                    st.error("EAN non trovato nel database!")
                conn.close()
            else:
                st.error("EAN non valido (deve essere tra 8 e 13 cifre)")

# 3. IMPORTA MASTER DATA
elif choice == "Importa Master Data":
    st.title("📥 Caricamento Excel")
    st.info("Il sistema leggerà la colonna 1 come Nome e le altre come Barcode (8-13 cifre).")
    up = st.file_upload("Carica file XLSX", type="xlsx")
    if up:
        df = pd.read_excel(up)
        if st.button("Avvia Importazione Incrementale"):
            conn = get_connection()
            c = conn.cursor()
            p_count, e_count = 0, 0
            for _, row in df.iterrows():
                desc = str(row.iloc[0]).strip()
                c.execute("SELECT id_prodotto FROM prodotti WHERE descrizione = ?", (desc,))
                res_p = c.fetchone()
                id_p = res_p[0] if res_p else None
                if not id_p:
                    c.execute("INSERT INTO prodotti (descrizione) VALUES (?)", (desc,))
                    id_p = c.lastrowid
                    p_count += 1
                
                for ean_val in row.iloc[1:]:
                    ean_c = clean_barcode(ean_val)
                    if ean_c:
                        c.execute("INSERT OR IGNORE INTO barcode (ean, id_prodotto) VALUES (?,?)", (ean_c, id_p))
                        if c.rowcount > 0: e_count += 1
            conn.commit()
            conn.close()
            st.success(f"Fatto! +{p_count} prodotti, +{e_count} barcode.")

# 4. ESPORTAZIONE REPORT
elif choice == "Esportazione Report":
    st.title("📄 Export Report Office")
    conn = get_connection()
    pdv_list = pd.read_sql_query("SELECT DISTINCT pdv FROM rilevazioni", conn)
    pdv_sel = st.selectbox("Scegli PDV", pdv_list['pdv'] if not pdv_list.empty else ["Nessun dato"])
    
    if st.button("Genera Excel"):
        query = f"""
            SELECT p.descrizione, r.prezzo, GROUP_CONCAT(b.ean, ' | ') as barcode_associati
            FROM rilevazioni r
            JOIN prodotti p ON r.id_prodotto = p.id_prodotto
            JOIN barcode b ON p.id_prodotto = b.id_prodotto
            WHERE r.pdv = '{pdv_sel}'
            GROUP BY p.id_prodotto
        """
        df_res = pd.read_sql_query(query, conn)
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            df_res.to_excel(writer, index=False, sheet_name='Rilevazione', startrow=2)
            ws = writer.sheets['Rilevazione']
            ws.write('A1', f"REPORT: {pdv_sel} - {datetime.now().strftime('%d/%m/%Y')}")
        
        st.download_button("Scarica File XLS", out.getvalue(), f"Report_{pdv_sel}.xlsx")
    conn.close()
