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

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import database

load_dotenv()

# index.html fica na raiz do repositório (um nível acima desta pasta).
REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"

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
    return {"status": "ok"}


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
