from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
import uuid
import sqlite3
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
    
    # Tabela de Execuções (Versão 2 - Fuso Brasília)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS execucoes_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT,
            observacao TEXT,
            foto_antes TEXT,
            foto_depois TEXT,
            data_hora TEXT
        )
    """)
    
    # Tabela de Usuários
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matricula TEXT UNIQUE,
            senha TEXT,
            nome TEXT,
            perfil TEXT
        )
    """)
    
    # Cria usuários de teste (senha padrão: 1234)
    try:
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES (?, ?, ?, ?)", ("1045", "1234", "João Mecânico", "mecanico"))
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES (?, ?, ?, ?)", ("2000", "1234", "Ricardo PCM", "pcm"))
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES (?, ?, ?, ?)", ("3000", "1234", "Eng. Barth", "engenharia"))
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES (?, ?, ?, ?)", ("4000", "1234", "Adriano Elétrica", "eletronica"))
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
    
    if usuario:
        return {"sucesso": True, "nome": usuario[0], "perfil": usuario[1]}
    else:
        raise HTTPException(status_code=401, detail="Matrícula ou senha incorretos")

@app.get("/historico")
async def listar_historico():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    # Puxa da tabela nova
    cursor.execute("SELECT tag, observacao, data_hora FROM execucoes_v2 ORDER BY id DESC")
    resultados = cursor.fetchall()
    conexao.close()
    
    historico = []
    for linha in resultados:
        historico.append({"tag": linha[0], "observacao": linha[1], "data_hora": linha[2]})
    return historico

@app.post("/executar")
async def registrar_execucao(
    tag: str = Form(...), 
    observacao: str = Form(...), 
    foto_antes: UploadFile = File(...), 
    foto_depois: UploadFile = File(...)
):
    id_foto_antes = str(uuid.uuid4()) + "_antes.jpg"
    id_foto_depois = str(uuid.uuid4()) + "_depois.jpg"

    with open(f"fotos/{id_foto_antes}", "wb") as buffer:
        shutil.copyfileobj(foto_antes.file, buffer)
    with open(f"fotos/{id_foto_depois}", "wb") as buffer:
        shutil.copyfileobj(foto_depois.file, buffer)

    # FORÇA O HORÁRIO DE BRASÍLIA (UTC-3)
    fuso_brasilia = datetime.utcnow() - timedelta(hours=3)
    data_formatada = fuso_brasilia.strftime("%d/%m/%Y %H:%M:%S")

    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("""
        INSERT INTO execucoes_v2 (tag, observacao, foto_antes, foto_depois, data_hora)
        VALUES (?, ?, ?, ?, ?)
    """, (tag, observacao, id_foto_antes, id_foto_depois, data_formatada))
    conexao.commit()
    conexao.close()

    return {"sucesso": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)