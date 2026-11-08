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

# ROTA DE IMPORTAÇÃO: Lê o arquivo HTML do Word
@app.post("/importar_sigpred")
async def importar_sigpred(arquivo: UploadFile = File(...)):
    conteudo = await arquivo.read()
    # O Word salva em windows-1252, então decodificamos assim
    texto = conteudo.decode('windows-1252', errors='ignore') 
    
    soup = BeautifulSoup(texto, 'html.parser')
    
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    importados = 0

    # Encontra todas as tabelas do relatório
    tabelas = soup.find_all('table')
    
    # O Word cria várias tabelas por relatório. Vamos agrupar os dados.
    for tabela in tabelas:
        # Procura a Tag SAP
        tag_cell = tabela.find(string=re.compile("Tag SAP:", re.IGNORECASE))
        if not tag_cell: continue
        
        tag_text = tag_cell.find_parent('p').get_text(strip=True)
        tag = tag_text.replace("Tag SAP:", "").strip()
        
        # Procura a Criticidade (A1, A2, A3, etc)
        crit_cell = tabela.find('td', style=re.compile("background:red|background:yellow"))
        criticidade = ""
        if crit_cell:
            criticidade = crit_cell.get_text(strip=True)
            
        # Procura a Descrição
        desc_cell = tabela.find(string=re.compile("Descrição:", re.IGNORECASE))
        descricao = "Sem descrição"
        if desc_cell:
            desc_text = desc_cell.find_parent('p').get_text(strip=True)
            descricao = desc_text.replace("Descrição:", "").strip()
            
        # Se encontrou uma TAG e a criticidade for A1, A2 ou A3, é um alarme válido
        if tag and criticidade in ['A1', 'A2', 'A3']:
            
            # Agora precisamos do Diagnóstico e da Recomendação. 
            # Eles estão em tabelas separadas logo após o título.
            # Vamos procurar no texto inteiro do documento ao invés da tabela.
            # (Para simplificar, vamos pegar o bloco de texto que começa na Tag e vai até a próxima Tag)
            
            diagnostico = "Sem diagnóstico"
            recomendacao = "Sem recomendação"
            
            # Busca o diagnóstico
            diag_h = soup.find(string=re.compile("DIAGNÓSTICO:", re.IGNORECASE))
            if diag_h:
                diag_table = diag_h.find_next('table')
                if diag_table:
                    diagnostico = diag_table.get_text(separator=' ', strip=True)
                    
            # Busca a recomendação
            rec_h = soup.find(string=re.compile("RECOMENDAÇÕES:", re.IGNORECASE))
            if rec_h:
                rec_table = rec_h.find_next('table')
                if rec_table:
                    recomendacao = rec_table.get_text(separator=' ', strip=True)

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

@app.get("/tags_pcm")
async def listar_tags_pcm():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("SELECT tag_sap, descricao, criticidade FROM tags_importadas WHERE status = 'Aguardando PCM'")
    resultados = cursor.fetchall()
    conexao.close()
    return [{"tag": l[0], "descricao": l[1], "criticidade": l[2]} for l in resultados]

@app.post("/programar_ordem")
async def programar_ordem(
    tag: str = Form(...), numero_sap: str = Form(...), executante: str = Form(...),
    semana: str = Form(...), parada: str = Form(...), apoio: str = Form(...)
):
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("""
        INSERT INTO ordens (tag_sap, numero_sap, executante, semana, parada, apoio)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tag, numero_sap, executante, semana, parada, apoio))
    
    cursor.execute("UPDATE tags_importadas SET status = 'Programada' WHERE tag_sap = ?", (tag,))
    conexao.commit()
    conexao.close()
    return {"sucesso": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
