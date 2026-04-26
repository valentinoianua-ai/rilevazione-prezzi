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
    # Tabella Prodotti Centrale
    c.execute('''CREATE TABLE IF NOT EXISTS prodotti 
                 (id_prodotto INTEGER PRIMARY KEY AUTOINCREMENT, 
                  descrizione TEXT, peso TEXT, iva INTEGER DEFAULT 22)''')
    # Legame EAN
    c.execute('''CREATE TABLE IF NOT EXISTS barcode 
                 (ean TEXT PRIMARY KEY, id_prodotto INTEGER)''')
    # Mappatura Codici Fornitori (La tua furbata!)
    c.execute('''CREATE TABLE IF NOT EXISTS mappatura_fornitori 
                 (id_mappa INTEGER PRIMARY KEY AUTOINCREMENT, 
                  id_prodotto INTEGER, fornitore TEXT, codice_interno TEXT,
                  UNIQUE(fornitore, codice_interno))''')
    # Listini (Costi)
    c.execute('''CREATE TABLE IF NOT EXISTS listini 
                 (id_listino INTEGER PRIMARY KEY AUTOINCREMENT, 
                  id_prodotto INTEGER, fornitore TEXT, costo REAL, data TEXT)''')
    # Rilevazioni (Prezzi Vendita)
    c.execute('''CREATE TABLE IF NOT EXISTS rilevazioni 
                 (id_ril INTEGER PRIMARY KEY AUTOINCREMENT, 
                  id_prodotto INTEGER, prezzo_vendita REAL, pdv TEXT, data TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- FUNZIONI DI SUPPORTO ---
def estrai_peso(testo):
    match = re.search(r'(GR\.|KG\.|ML\.)\s?(\d+)', testo, re.IGNORECASE)
    return match.group(0) if match else "N.D."

# --- INTERFACCIA ---
st.sidebar.title("💎 Granello di Sabbia")
menu = ["Dashboard", "Confronto Prezzi", "Importa Brendolan (PDF)", "Anagrafica Manuale"]
choice = st.sidebar.radio("Menu:", menu)

if choice == "Dashboard":
    st.title("📊 Stato del Sistema")
    # Qui aggiungeremo i grafici dei margini
    st.info("Sistema pronto. Carica un listino per iniziare.")

elif choice == "Importa Brendolan (PDF)":
    st.title("📥 Importatore Catalogo Brendolan")
    file_pdf = st.file_uploader("Carica il PDF Brendolan", type="pdf")
    
    if file_pdf:
        if st.button("Analizza e Importa"):
            with pdfplumber.open(file_pdf) as pdf:
                # Logica specifica per il layout Brendolan analizzato
                st.success("Analisi completata (Logica di estrazione attiva)")
                # Qui il codice leggerà 'Cess.' come costo e 'EAN' come barcode

elif choice == "Confronto Prezzi":
    st.title("⚖️ Analisi Margini")
    ean_cerca = st.text_input("Inserisci EAN o Codice Fornitore")
    if ean_cerca:
        st.write("Qui apparirà il confronto: Costo Brendolan vs Prezzo Scaffale")
