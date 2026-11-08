from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
import shutil, os, uuid, sqlite3, re, email
from datetime import datetime, timedelta

app = FastAPI(title="SR VibManager API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

if not os.path.exists("fotos"): os.makedirs("fotos")

def iniciar_banco():
    conexao = sqlite3.connect("sr_vibmanager.db")
    cursor = conexao.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS tags_importadas (id INTEGER PRIMARY KEY AUTOINCREMENT, tag_sap TEXT UNIQUE, descricao TEXT, criticidade TEXT, diagnostico TEXT, recomendacao TEXT, data_inspecao TEXT, num_relatorio TEXT, status TEXT DEFAULT 'Aguardando PCM')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS ordens (id INTEGER PRIMARY KEY AUTOINCREMENT, tag_sap TEXT, numero_sap TEXT, executante TEXT, apoio TEXT, dia_semana TEXT, data_execucao TEXT, status TEXT DEFAULT 'Pendente')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS equipe (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE, funcao TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS execucoes_v2 (id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT, observacao TEXT, foto_antes TEXT, foto_depois TEXT, data_hora TEXT)""")
    cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (matricula TEXT UNIQUE, senha TEXT, nome TEXT, perfil TEXT)")
    try:
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES ('1045', '1234', 'Agnaldo', 'mecanico')")
        cursor.execute("INSERT INTO usuarios (matricula, senha, nome, perfil) VALUES ('2000', '1234', 'Ricardo PCM', 'pcm')")
        cursor.execute("INSERT INTO equipe (nome, funcao) VALUES ('Agnaldo', 'Mecânico')")
        cursor.execute("INSERT INTO equipe (nome, funcao) VALUES ('William', 'Mecânico')")
        cursor.execute("INSERT INTO equipe (nome, funcao) VALUES ('Aferitec', 'Terceiro')")
    except sqlite3.IntegrityError: pass 
    conexao.commit()
    conexao.close()

iniciar_banco()

@app.post("/login")
async def fazer_login(matricula: str = Form(...), senha: str = Form(...)):
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    cur.execute("SELECT nome, perfil FROM usuarios WHERE matricula = ? AND senha = ?", (matricula, senha))
    user = cur.fetchone(); conn.close()
    if user: return {"sucesso": True, "nome": user[0], "perfil": user[1]}
    raise HTTPException(status_code=401, detail="Incorreto")

@app.get("/equipe")
async def listar_equipe():
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    cur.execute("SELECT id, nome, funcao FROM equipe"); res = cur.fetchall(); conn.close()
    return [{"id": l[0], "nome": l[1], "funcao": l[2]} for l in res]

@app.post("/cadastrar_equipe")
async def cadastrar_equipe(nome: str = Form(...), funcao: str = Form(...)):
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO equipe (nome, funcao) VALUES (?, ?)", (nome, funcao)); conn.commit(); ret = {"sucesso": True}
    except sqlite3.IntegrityError: ret = {"sucesso": False, "erro": "Nome já cadastrado"}
    conn.close(); return ret

@app.post("/importar_sigpred")
async def importar_sigpred(arquivo: UploadFile = File(...)):
    conteudo = await arquivo.read()
    if arquivo.filename.endswith(('.mht', '.mhtml')):
        msg = email.message_from_bytes(conteudo)
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                texto_html = part.get_payload(decode=True).decode('windows-1252', errors='ignore'); break
    else: texto_html = conteudo.decode('windows-1252', errors='ignore')
    
    soup = BeautifulSoup(texto_html, 'html.parser'); texto_limpo = soup.get_text(separator='\n')
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor(); importados = 0
    for bloco in re.split(r"RELATÓRIO OPERACIONAL DE INSPEÇÃO", texto_limpo, flags=re.IGNORECASE):
        if not bloco.strip(): continue
        tag_match = re.search(r"Tag\s*SAP:\s*([^\n]+)", bloco, re.IGNORECASE)
        if not tag_match: continue
        tag = tag_match.group(1).strip()
        crit_match = re.search(r"Data:\s*(\d{2}/\d{2}/\d{2})\s*\n*([A-Z0-9]{2})", bloco, re.IGNORECASE)
        data_inspecao = crit_match.group(1).strip() if crit_match else ""
        criticidade = crit_match.group(2).strip() if crit_match else ""
        rel_match = re.search(r"Relatório:\s*([^\n]+)", bloco, re.IGNORECASE)
        num_relatorio = rel_match.group(1).strip() if rel_match else "-"
        desc_match = re.search(r"Descri[çc][ãa]o:\s*(.*?)\s*Resp\.", bloco, re.IGNORECASE | re.DOTALL)
        descricao = desc_match.group(1).strip() if desc_match else "Sem descrição"
        diag_match = re.search(r"DIAGN[ÓO]STICO:\s*(.*?)\s*RECOMENDA[ÇC][ÕO]ES:", bloco, re.IGNORECASE | re.DOTALL)
        diagnostico = diag_match.group(1).strip() if diag_match else "Sem diagnóstico"
        rec_match = re.search(r"RECOMENDA[ÇC][ÕO]ES:\s*(.*?)\s*FEED-BACK:", bloco, re.IGNORECASE | re.DOTALL)
        recomendacao = rec_match.group(1).strip() if rec_match else "Sem recomendação"
        if criticidade in ['A1', 'A2', 'A3']:
            try:
                cur.execute("""INSERT INTO tags_importadas (tag_sap, descricao, criticidade, diagnostico, recomendacao, data_inspecao, num_relatorio) VALUES (?, ?, ?, ?, ?, ?, ?)""", (tag, descricao, criticidade, diagnostico, recomendacao, data_inspecao, num_relatorio)); importados += 1
            except sqlite3.IntegrityError: pass 
    conn.commit(); conn.close(); return {"sucesso": True, "importados": importados}

@app.get("/tags_pcm")
async def listar_tags_pcm():
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    cur.execute("SELECT id, tag_sap, descricao, criticidade, data_inspecao, num_relatorio, diagnostico, recomendacao FROM tags_importadas WHERE status = 'Aguardando PCM'")
    res = cur.fetchall(); conn.close()
    return [{"id": l[0], "tag": l[1], "descricao": l[2], "criticidade": l[3], "data_inspecao": l[4], "num_relatorio": l[5], "diagnostico": l[6], "recomendacao": l[7]} for l in res]

@app.post("/programar_ordem")
async def programar_ordem(tag: str = Form(...), numero_sap: str = Form(...), executante: str = Form(...), apoio: str = Form(...), dia_semana: str = Form(...), data_execucao: str = Form(...)):
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    # Força a data para o formato YYYY-MM-DD caso venha com barras
    if '/' in data_execucao:
        p = data_execucao.split('/')
        if len(p) == 3: data_execucao = f"{p[2]}-{p[1]}-{p[0]}"
    
    cur.execute("""INSERT INTO ordens (tag_sap, numero_sap, executante, apoio, dia_semana, data_execucao) VALUES (?, ?, ?, ?, ?, ?)""", (tag, numero_sap, executante, apoio, dia_semana, data_execucao))
    cur.execute("UPDATE tags_importadas SET status = 'Programada' WHERE tag_sap = ?", (tag,))
    conn.commit(); conn.close(); return {"sucesso": True}

@app.get("/resumo_semana")
async def resumo_semana(executante: str):
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    cur.execute("SELECT dia_semana, COUNT(*) FROM ordens WHERE (executante = ? OR apoio = ?) AND status = 'Pendente' GROUP BY dia_semana", (executante, executante))
    res = cur.fetchall(); conn.close()
    dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    return [{"dia": d, "quantidade": next((r[1] for r in res if r[0] == d), 0)} for d in dias]

@app.get("/minhas_ordens")
async def listar_minhas_ordens(executante: str, dia: str):
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    cur.execute("""SELECT o.id, o.tag_sap, t.descricao, t.criticidade, o.numero_sap, t.diagnostico, t.recomendacao, t.data_inspecao, t.num_relatorio, o.executante, o.apoio, o.dia_semana, o.data_execucao FROM ordens o JOIN tags_importadas t ON o.tag_sap = t.tag_sap WHERE o.status = 'Pendente' AND (o.executante = ? OR o.apoio = ?) AND o.dia_semana = ?""", (executante, executante, dia))
    res = cur.fetchall(); conn.close()
    return [{"id": l[0], "tag": l[1], "descricao": l[2], "criticidade": l[3], "numero_sap": l[4], "diagnostico": l[5], "recomendacao": l[6], "data_inspecao": l[7], "num_relatorio": l[8], "executante": l[9], "apoio": l[10], "dia_semana": l[11], "data_execucao": l[12]} for l in res]

@app.post("/executar")
async def registrar_execucao(tag: str = Form(...), observacao: str = Form(...), foto_antes: UploadFile = File(...), foto_depois: UploadFile = File(...)):
    id_a = str(uuid.uuid4()) + "_antes.jpg"; id_d = str(uuid.uuid4()) + "_depois.jpg"
    with open(f"fotos/{id_a}", "wb") as b: shutil.copyfileobj(foto_antes.file, b)
    with open(f"fotos/{id_d}", "wb") as b: shutil.copyfileobj(foto_depois.file, b)
    data = (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S")
    conn = sqlite3.connect("sr_vibmanager.db"); cur = conn.cursor()
    cur.execute("INSERT INTO execucoes_v2 (tag, observacao, foto_antes, foto_depois, data_hora) VALUES (?, ?, ?, ?, ?)", (tag, observacao, id_a, id_d, data))
    cur.execute("UPDATE ordens SET status = 'Concluída' WHERE tag_sap = ?", (tag,))
    conn.commit(); conn.close(); return {"sucesso": True}

if __name__ == "__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=8000)