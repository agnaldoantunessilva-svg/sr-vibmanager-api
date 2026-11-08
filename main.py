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

@app.post("/importar_sigpred")
async def importar_sigpred(arquivo: UploadFile = File(...)):
    conteudo = await arquivo.read()
    texto = conteudo.decode('windows-1252', errors='ignore') 
    
    soup = BeautifulSoup(texto, 'html.parser')
    texto_limpo = soup.get_text(separator='\n')
    
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    importados = 0

    blocos = re.split(r"RELATÓRIO OPERACIONAL DE INSPEÇÃO", texto_limpo, flags=re.IGNORECASE)
    
    for bloco in blocos:
        if not bloco.strip(): continue
        
        tag_match = re.search(r"Tag\s*SAP:\s*([^\n]+)", bloco, re.IGNORECASE)
        if not tag_match: continue
        tag = tag_match.group(1).strip()
        
        crit_match = re.search(r"Data:\s*\d{2}/\d{2}/\d{2}\s*\n*([A-Z0-9]{2})", bloco, re.IGNORECASE)
        criticidade = crit_match.group(1).strip() if crit_match else ""
        
        desc_match = re.search(r"Descri[çc][ãa]o:\s*(.*?)\s*Resp\.", bloco, re.IGNORECASE | re.DOTALL)
        descricao = desc_match.group(1).strip() if desc_match else "Sem descrição"
        
        diag_match = re.search(r"DIAGN[ÓO]STICO:\s*(.*?)\s*RECOMENDA[ÇC][ÕO]ES:", bloco, re.IGNORECASE | re.DOTALL)
        diagnostico = diag_match.group(1).strip() if diag_match else "Sem diagnóstico"
        
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

# ROTA PARA O PCM: Lista as 9 TAGs importadas
@app.get("/tags_pcm")
async def listar_tags_pcm():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("SELECT tag_sap, descricao, criticidade FROM tags_importadas WHERE status = 'Aguardando PCM'")
    resultados = cursor.fetchall()
    conexao.close()
    return [{"tag": l[0], "descricao": l[1], "criticidade": l[2]} for l in resultados]

# ROTA PARA O PCM: Salvar a programação
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

# ROTA PARA O MECÂNICO: Lista as ordens que já foram programadas pelo PCM
@app.get("/minhas_ordens")
async def listar_minhas_ordens():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("""
        SELECT o.id, o.tag_sap, t.descricao, t.criticidade, o.numero_sap, t.diagnostico, t.recomendacao
        FROM ordens o
        JOIN tags_importadas t ON o.tag_sap = t.tag_sap
        WHERE o.status = 'Pendente'
    """)
    resultados = cursor.fetchall()
    conexao.close()
    
    ordens = []
    for linha in resultados:
        ordens.append({
            "id": linha[0], "tag": linha[1], "descricao": linha[2], 
            "criticidade": linha[3], "numero_sap": linha[4],
            "diagnostico": linha[5], "recomendacao": linha[6]
        })
    return ordens

# ROTA PARA O MECÂNICO: Registrar execução
@app.post("/executar")
async def registrar_execucao(
    tag: str = Form(...), observacao: str = Form(...), 
    foto_antes: UploadFile = File(...), foto_depois: UploadFile = File(...)
):
    id_foto_antes = str(uuid.uuid4()) + "_antes.jpg"
    id_foto_depois = str(uuid.uuid4()) + "_depois.jpg"

    with open(f"fotos/{id_foto_antes}", "wb") as buffer:
        shutil.copyfileobj(foto_antes.file, buffer)
    with open(f"fotos/{id_foto_depois}", "wb") as buffer:
        shutil.copyfileobj(foto_depois.file, buffer)

    fuso_brasilia = datetime.utcnow() - timedelta(hours=3)
    data_formatada = fuso_brasilia.strftime("%d/%m/%Y %H:%M:%S")

    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    
    cursor.execute("""
        INSERT INTO execucoes_v2 (tag, observacao, foto_antes, foto_depois, data_hora)
        VALUES (?, ?, ?, ?, ?)
    """, (tag, observacao, id_foto_antes, id_foto_depois, data_formatada))
    
    cursor.execute("UPDATE ordens SET status = 'Concluída' WHERE tag_sap = ?", (tag,))
    
    conexao.commit()
    conexao.close()
    return {"sucesso": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
