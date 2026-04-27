import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Price Radar - Confronto Listini", layout="wide")
DB_PATH = "database_rilevazioni.db"

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# --- NUOVA LOGICA DI SALVATAGGIO (Focus su Prezzi Rilevati) ---
def salva_rilevazione(ean, descrizione, fornitore_punto_vendita, prezzo):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 1. Gestione Prodotto ed EAN (La nostra Rosetta)
        cursor.execute("INSERT OR IGNORE INTO prodotti (descrizione) VALUES (?)", (descrizione.upper(),))
        cursor.execute("SELECT id_prodotto FROM prodotti WHERE descrizione = ?", (descrizione.upper(),))
        id_p = cursor.fetchone()[0]
        cursor.execute("INSERT OR IGNORE INTO barcode (ean, id_prodotto) VALUES (?, ?)", (ean, id_p))
        
        # 2. Registrazione Prezzo (Che sia acquisto o scaffale Tigre/Oasi)
        data_oggi = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("""INSERT INTO listini (id_prodotto, fornitore, costo_cessione, data) 
                          VALUES (?, ?, ?, ?)""", (id_p, fornitore_punto_vendita, prezzo, data_oggi))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

# --- INTERFACCIA ---
menu = ["📊 Dashboard Confronto", "📥 Importa Rilevazioni/Listini", "⚙️ Gestione Sistema"]
scelta = st.sidebar.radio("Navigazione", menu)

if scelta == "📊 Dashboard Confronto":
    st.title("🔎 Analisi Comparativa Prezzi")
    st.write("Qui puoi confrontare i prezzi rilevati tra diversi punti vendita o listini.")

    conn = get_connection()
    # Carichiamo tutti i dati per creare una tabella pivot dinamica
    query = """
    SELECT b.ean, p.descrizione, l.fornitore, l.costo_cessione as prezzo, l.data
    FROM listini l
    JOIN prodotti p ON l.id_prodotto = p.id_prodotto
    JOIN barcode b ON p.id_prodotto = b.id_prodotto
    """
    df_raw = pd.read_sql(query, conn)
    conn.close()

    if not df_raw.empty:
        # Creiamo la tabella di confronto: righe = Prodotti, colonne = Fornitori/Concorrenti
        df_pivot = df_raw.pivot_table(
            index=['ean', 'descrizione'], 
            columns='fornitore', 
            values='prezzo', 
            aggfunc='last'
        ).reset_index()

        # Evidenziamo il prezzo più basso (il positivo) tra le colonne dei fornitori
        cols_fornitori = df_pivot.columns[2:]
        st.dataframe(df_pivot.style.highlight_min(axis=1, subset=cols_fornitori, color='lightgreen'))

        # --- EXCEL DI USCITA ---
        if st.button("Genera File Excel di Confronto"):
            file_output = "confronto_competitors.xlsx"
            df_pivot.to_excel(file_output, index=False)
            with open(file_output, "rb") as f:
                st.download_button("📥 Scarica Excel", f, file_name=file_output)
    else:
        st.info("Carica dei dati per visualizzare il confronto.")

elif scelta == "📥 Importa Rilevazioni/Listini":
    st.title("📥 Caricamento Dati (Excel)")
    f_nome = st.text_input("Origine Dati (es. Tigre, Oasi, Brendolan)")
    f_up = st.file_uploader("Carica Excel", type=["xlsx", "xls"])

    if f_up and f_nome:
        df = pd.read_excel(f_up)
        c1, c2, c3 = st.columns(3)
        with c1: ean_col = st.selectbox("Colonna EAN", df.columns)
        with c2: desc_col = st.selectbox("Colonna Descrizione", df.columns)
        with c3: prz_col = st.selectbox("Colonna Prezzo", df.columns)

        if st.button("Importa Dati"):
            count = 0
            for _, row in df.iterrows():
                if salva_rilevazione(row[ean_col], row[desc_col], f_nome, float(row[prz_col])):
                    count += 1
            st.success(f"Importate {count} rilevazioni per {f_nome}")

elif scelta == "⚙️ Gestione Sistema":
    st.title("⚙️ Rosetta & Backup")
    # Qui carichi il famoso .db generato col PC per Brendolan
    up_db = st.file_uploader("Aggiorna Database (.db)", type=["db"])
    if up_db:
        with open(DB_PATH, "wb") as f:
            f.write(up_db.getbuffer())
        st.success("Database aggiornato!")
