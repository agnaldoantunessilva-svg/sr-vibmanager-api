from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
import uuid
import sqlite3

app = FastAPI(title="SR VibManager API")

# Configuração de CORS liberada para testes locais
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=False, # Tem que ser False quando usamos "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("fotos"):
    os.makedirs("fotos")

def iniciar_banco():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS execucoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT,
            observacao TEXT,
            foto_antes TEXT,
            foto_depois TEXT,
            data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conexao.commit()
    conexao.close()

iniciar_banco()

@app.post("/login")
async def fazer_login(matricula: str = Form(...), senha: str = Form(...)):
    return {"sucesso": True, "nome": "João Silva"}

@app.get("/ordens")
async def listar_ordens():
    return [
        {"id": 1, "tag": "BP03-INDU-R1-R1E-GR01-MTR11", "desc": "Soprador", "criticidade": "A2"},
        {"id": 2, "tag": "BP03-INDU-R1-R1M-GE01-MTR02", "desc": "Sul moinho 90%", "criticidade": "A2"}
    ]

@app.get("/historico")
async def listar_historico():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("SELECT tag, observacao, data_hora FROM execucoes ORDER BY id DESC")
    resultados = cursor.fetchall()
    conexao.close()
    
    historico = []
    for linha in resultados:
        historico.append({
            "tag": linha[0],
            "observacao": linha[1],
            "data_hora": linha[2]
        })
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

    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("""
        INSERT INTO execucoes (tag, observacao, foto_antes, foto_depois)
        VALUES (?, ?, ?, ?)
    """, (tag, observacao, id_foto_antes, id_foto_depois))
    conexao.commit()
    conexao.close()

    print(f"✅ Ordem Finalizada! TAG: {tag}")
    return {"sucesso": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)