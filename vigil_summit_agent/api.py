"""
api.py
------
API mínima de captação + servidor da landing page (Fase 1).

Serve o index.html e recebe inscrições via POST /api/inscricao,
gravando na mesma tabela `leads` usada pelo painel Streamlit.

Execução:
    py -m uvicorn api:app --reload --port 8080

Abra http://localhost:8080 — o formulário envia para /api/inscricao
e o lead aparece no painel (py -m streamlit run app.py).
"""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import database

load_dotenv()

# index.html fica na raiz do repositório (um nível acima desta pasta).
REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
if not INDEX_HTML.is_file():
    INDEX_HTML = Path(__file__).resolve().parent / "index.html"

API_KEY = os.getenv("VIGIL_API_KEY", "").strip()

app = FastAPI(title="Vigil Summit · Captação", version="1.0")

# CORS liberado para LP em outro domínio (ex.: GitHub Pages + API no Render).
origens = os.getenv("CORS_ORIGINS", "*").strip()
allow_origins = ["*"] if origens == "*" else [o.strip() for o in origens.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class InscricaoPayload(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=200)
    cargo: str = Field(min_length=2, max_length=200)
    setor: str = Field(min_length=2, max_length=100)
    empresa: str = Field(min_length=2, max_length=200)
    telefone: str = Field(min_length=8, max_length=50)


def _verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Exige X-API-Key quando VIGIL_API_KEY estiver configurada."""
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Chave de API inválida ou ausente.")


def _linha_para_dict(linha) -> dict[str, Any]:
    return {chave: linha[chave] for chave in linha.keys()}


@app.on_event("startup")
def startup() -> None:
    database.init_db()


@app.get("/")
def landing_page():
    """Serve a landing page de captação."""
    if not INDEX_HTML.is_file():
        raise HTTPException(status_code=404, detail="index.html não encontrado.")
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/health")
def health():
    return {"status": "ok", "service": "vigil-summit-api"}


@app.post("/api/inscricao")
def registrar_inscricao(payload: InscricaoPayload):
    """Grava um lead vindo da LP (origem LP_Organico, status Inscrito)."""
    lead_id = database.insert_lead(
        nome=payload.nome.strip(),
        email=payload.email.strip(),
        cargo_declarado=payload.cargo.strip(),
        setor=payload.setor.strip(),
        empresa=payload.empresa.strip(),
        telefone=payload.telefone.strip(),
        origem="LP_Organico",
    )
    if lead_id is None:
        raise HTTPException(status_code=409, detail="Este e-mail já está inscrito.")
    return {"ok": True, "lead_id": lead_id, "mensagem": "Inscrição recebida com sucesso."}


@app.get("/api/leads", dependencies=[Depends(_verificar_api_key)])
def listar_leads():
    """Lista leads para o painel Streamlit na nuvem (mesma origem da LP)."""
    conn = database.get_connection()
    try:
        linhas = conn.execute("SELECT * FROM leads ORDER BY id;").fetchall()
    finally:
        conn.close()
    return {"leads": [_linha_para_dict(linha) for linha in linhas]}


@app.get("/api/interactions", dependencies=[Depends(_verificar_api_key)])
def listar_interacoes(lead_id: int | None = Query(default=None)):
    """Lista interações registradas pelo agente."""
    conn = database.get_connection()
    try:
        if lead_id is None:
            linhas = conn.execute(
                "SELECT * FROM interaction_logs ORDER BY id DESC;"
            ).fetchall()
        else:
            linhas = conn.execute(
                "SELECT * FROM interaction_logs WHERE lead_id = ? ORDER BY id DESC;",
                (lead_id,),
            ).fetchall()
    finally:
        conn.close()
    return {"interactions": [_linha_para_dict(linha) for linha in linhas]}
