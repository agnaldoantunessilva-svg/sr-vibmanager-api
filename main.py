from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    
    # Tabela de TAGs Importadas
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
    
    # Tabela de Ordens
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
    
    # Usuários
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

# ROTA DE IMPORTAÇÃO: Agora lê o arquivo TXT do Sigpred
@app.post("/importar_sigpred")
async def importar_sigpred(arquivo: UploadFile = File(...)):
    conteudo = await arquivo.read()
    texto = conteudo.decode('utf-8', errors='ignore') # Lida com acentos corrompidos
    
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    importados = 0

    # Divide o texto grande em blocos, cada bloco é um relatório
    blocos = texto.split("RELATÓRIO OPERACIONAL DE INSPEÇĂO")
    
    for bloco in blocos:
        if not bloco.strip(): continue
        
        # 1. Extrai a TAG
        tag_match = re.search(r"Tag\s*SAP:\s*([^\s]+)", bloco)
        if not tag_match: continue
        tag = tag_match.group(1).strip()
        
        # 2. Extrai a Criticidade (Pega o primeiro A1, A2, A3 que aparecer após a data)
        crit_match = re.search(r"Data:\s*\d{2}/\d{2}/\d{2}\s*(A1|A2|A3|A4|N|P|M)", bloco)
        if not crit_match: continue
        criticidade = crit_match.group(1).strip()
        
        # 3. Extrai a Descrição
        desc_match = re.search(r"Descriçăo:\s*(.*?)\s*Resp\.:", bloco, re.DOTALL)
        descricao = desc_match.group(1).strip() if desc_match else "Sem descrição"
        
        # 4. Extrai o Diagnóstico
        diag_match = re.search(r"DIAGNÓSTICO:\s*(.*?)\s*RECOMENDAÇŐES:", bloco, re.DOTALL)
        diagnostico = diag_match.group(1).strip() if diag_match else "Sem diagnóstico"
        
        # 5. Extrai a Recomendação
        rec_match = re.search(r"RECOMENDAÇŐES:\s*(.*?)\s*FEED-BACK:", bloco, re.DOTALL)
        recomendacao = rec_match.group(1).strip() if rec_match else "Sem recomendação"

        # Se for um alarme válido (A1, A2 ou A3), salva no banco
        if criticidade in ['A1', 'A2', 'A3']:
            try:
                # Limpa o texto (remove quebras de linha excessivas)
                diagnostico = " ".join(diagnostico.split())
                recomendacao = " ".join(recomendacao.split())
                
                cursor.execute("""
                    INSERT INTO tags_importadas (tag_sap, descricao, criticidade, diagnostico, recomendacao)
                    VALUES (?, ?, ?, ?, ?)
                """, (tag, descricao, criticidade, diagnostico, recomendacao))
                importados += 1
            except sqlite3.IntegrityError:
                pass # Se a TAG já existe, pula
                
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
