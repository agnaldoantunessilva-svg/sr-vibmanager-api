from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
import shutil
import os
import uuid
import sqlite3
import re
from datetime import datetime, timedelta

app = FastAPI(title="SR VibManager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("fotos"):
    os.makedirs("fotos")

def iniciar_banco():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tags_importadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_sap TEXT UNIQUE,
            descricao TEXT,
            criticidade TEXT,
            diagnostico TEXT,
            recomendacao TEXT,
            status TEXT DEFAULT 'Aguardando PCM'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ordens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_sap TEXT,
            numero_sap TEXT,
            executante TEXT,
            semana TEXT,
            parada TEXT,
            apoio TEXT,
            status TEXT DEFAULT 'Pendente'
        )
    """)
    
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (matricula TEXT UNIQUE, senha TEXT, nome TEXT, perfil TEXT)")
    try:
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES ('1045', '1234', 'João Mecânico', 'mecanico')")
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES ('2000', '1234', 'Ricardo PCM', 'pcm')")
    except sqlite3.IntegrityError:
        pass 
    
    conexao.commit()
    conexao.close()

iniciar_banco()

@app.post("/login")
async def fazer_login(matricula: str = Form(...), senha: str = Form(...)):
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("SELECT nome, perfil FROM usuarios WHERE matricula = ? AND senha = ?", (matricula, senha))
    usuario = cursor.fetchone()
    conexao.close()
    if usuario: return {"sucesso": True, "nome": usuario[0], "perfil": usuario[1]}
    raise HTTPException(status_code=401, detail="Incorreto")

# ROTA DE IMPORTAÇÃO: Transforma o HTML em texto limpo e lê
@app.post("/importar_sigpred")
async def importar_sigpred(arquivo: UploadFile = File(...)):
    conteudo = await arquivo.read()
    texto = conteudo.decode('windows-1252', errors='ignore') 
    
    # MÁGICA AQUI: O BeautifulSoup remove todo o HTML e deixa só o texto puro!
    soup = BeautifulSoup(texto, 'html.parser')
    texto_limpo = soup.get_text(separator='\n')
    
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    importados = 0

    # Agora que o texto está limpo, dividimos ele pelos títulos dos relatórios
    blocos = re.split(r"RELATÓRIO OPERACIONAL DE INSPEÇÃO", texto_limpo, flags=re.IGNORECASE)
    
    for bloco in blocos:
        if not bloco.strip(): continue
        
        # Busca a Tag
        tag_match = re.search(r"Tag\s*SAP:\s*([^\n]+)", bloco, re.IGNORECASE)
        if not tag_match: continue
        tag = tag_match.group(1).strip()
        
        # Busca a Criticidade
        crit_match = re.search(r"Data:\s*\d{2}/\d{2}/\d{2}\s*\n*([A-Z0-9]{2})", bloco, re.IGNORECASE)
        criticidade = crit_match.group(1).strip() if crit_match else ""
        
        # Busca a Descrição
        desc_match = re.search(r"Descri[çc][ãa]o:\s*(.*?)\s*Resp\.", bloco, re.IGNORECASE | re.DOTALL)
        descricao = desc_match.group(1).strip() if desc_match else "Sem descrição"
        
        # Busca o Diagnóstico
        diag_match = re.search(r"DIAGN[ÓO]STICO:\s*(.*?)\s*RECOMENDA[ÇC][ÕO]ES:", bloco, re.IGNORECASE | re.DOTALL)
        diagnostico = diag_match.group(1).strip() if diag_match else "Sem diagnóstico"
        
        # Busca a Recomendação
        rec_match = re.search(r"RECOMENDA[ÇC][ÕO]ES:\s*(.*?)\s*FEED-BACK:", bloco, re.IGNORECASE | re.DOTALL)
        recomendacao = rec_match.group(1).strip() if rec_match else "Sem recomendação"

        if criticidade in ['A1', 'A2', 'A3']:
            try:
                cursor.execute("""
                    INSERT INTO tags_importadas (tag_sap, descricao, criticidade, diagnostico, recomendacao)
                    VALUES (?, ?, ?, ?, ?)
                """, (tag, descricao, criticidade, diagnostico, recomendacao))
                importados += 1
            except sqlite3.IntegrityError:
                pass 
                
    conexao.commit()
    conexao.close()
    return {"sucesso": True, "importados": importados}
