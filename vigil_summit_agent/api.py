"""
api.py
------
API de captação + operação remota do agente (Render) + scheduler opcional.

Serve index.html, grava inscrições, expõe leads/interações e executa
pipelines do agent (Fases 2–4) para o painel Streamlit na nuvem.

Execução local:
    py -m uvicorn api:app --reload --port 8080
"""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import agent
import database

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
if not INDEX_HTML.is_file():
    INDEX_HTML = Path(__file__).resolve().parent / "index.html"

API_KEY = os.getenv("VIGIL_API_KEY", "").strip()
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "").strip().lower() in {
    "1", "true", "yes", "on",
}

app = FastAPI(title="Vigil Summit · API", version="1.1")

origens = os.getenv("CORS_ORIGINS", "*").strip()
allow_origins = ["*"] if origens == "*" else [o.strip() for o in origens.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

ACOES_AGENTE: dict[str, Callable[[], None]] = {
    "enrich": agent.run_enrichment_pipeline,
    "engage": agent.run_engagement_with_simulated_responses,
    "pre": lambda: agent.run_pre_event_sequence(simular_sequencia_completa=True),
    "post": lambda: agent.run_post_event_sequence(simular_sequencia_completa=True),
    "demo": agent.run_full_funnel_demo,
}


class InscricaoPayload(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=200)
    cargo: str = Field(min_length=2, max_length=200)
    setor: str = Field(min_length=2, max_length=100)
    empresa: str = Field(min_length=2, max_length=200)
    telefone: str = Field(min_length=8, max_length=50)


class StatusPayload(BaseModel):
    status_funil: str = Field(min_length=3, max_length=50)


class RespostaPayload(BaseModel):
    resposta: str = Field(min_length=1, max_length=2000)


def _verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Chave de API inválida ou ausente.")


def _linha_para_dict(linha) -> dict[str, Any]:
    return {chave: linha[chave] for chave in linha.keys()}


def _executar_com_log(funcao: Callable[[], None]) -> dict[str, Any]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        funcao()
    return {"ok": True, "log": buffer.getvalue()}


def _iniciar_scheduler() -> None:
    if not ENABLE_SCHEDULER:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("[scheduler] APScheduler não instalado; régua automática desativada.")
        return

    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")

    def job_pre_evento() -> None:
        print("[scheduler] Disparando régua pré-evento (etapa do dia)...")
        agent.run_pre_event_sequence(simular_sequencia_completa=False)

    def job_pos_evento() -> None:
        if agent.dias_para_o_evento() >= 0:
            return
        print("[scheduler] Disparando régua pós-evento...")
        agent.run_post_event_sequence(simular_sequencia_completa=False)

    scheduler.add_job(job_pre_evento, "cron", hour=9, minute=0, id="pre_evento")
    scheduler.add_job(job_pos_evento, "cron", hour=10, minute=0, id="pos_evento")
    scheduler.start()
    print("[scheduler] Régua automática ativa (09:00 pré · 10:00 pós).")


@app.on_event("startup")
def startup() -> None:
    database.init_db()
    database.seed_test_leads()
    _iniciar_scheduler()


@app.get("/")
def landing_page():
    if not INDEX_HTML.is_file():
        raise HTTPException(status_code=404, detail="index.html não encontrado.")
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "vigil-summit-api",
        "llm_provider": agent.LLM_PROVIDER,
        "llm_configurado": agent.llm_configurado(),
        "scheduler": ENABLE_SCHEDULER,
    }


@app.post("/api/inscricao")
def registrar_inscricao(payload: InscricaoPayload):
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
    conn = database.get_connection()
    try:
        linhas = conn.execute("SELECT * FROM leads ORDER BY id;").fetchall()
    finally:
        conn.close()
    return {"leads": [_linha_para_dict(linha) for linha in linhas]}


@app.get("/api/interactions", dependencies=[Depends(_verificar_api_key)])
def listar_interacoes(lead_id: int | None = Query(default=None)):
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


@app.patch("/api/leads/{lead_id}/status", dependencies=[Depends(_verificar_api_key)])
def atualizar_status(lead_id: int, payload: StatusPayload):
    lead = agent.get_lead_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead não encontrado.")
    if payload.status_funil not in agent.FUNNEL_STATUSES:
        raise HTTPException(status_code=400, detail="Status de funil inválido.")
    agent.update_lead_status(lead_id, payload.status_funil)
    return {"ok": True, "lead_id": lead_id, "status_funil": payload.status_funil}


@app.post("/api/leads/{lead_id}/response", dependencies=[Depends(_verificar_api_key)])
def registrar_resposta_lead(lead_id: int, payload: RespostaPayload):
    lead = agent.get_lead_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead não encontrado.")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        agent.receive_lead_response(lead_id, payload.resposta.strip())
    atual = agent.get_lead_by_id(lead_id)
    return {
        "ok": True,
        "lead_id": lead_id,
        "status_funil": atual["status_funil"] if atual else lead["status_funil"],
        "log": buffer.getvalue(),
    }


@app.post("/api/agent/{acao}", dependencies=[Depends(_verificar_api_key)])
def executar_agente(acao: str):
    if acao not in ACOES_AGENTE:
        raise HTTPException(
            status_code=404,
            detail=f"Ação inválida. Use: {', '.join(ACOES_AGENTE)}",
        )
    if not agent.llm_configurado():
        raise HTTPException(
            status_code=503,
            detail=(
                f"LLM não configurado na API. Defina {agent._nome_da_variavel_de_chave()} "
                f"e LLM_PROVIDER={agent.LLM_PROVIDER} no Render."
            ),
        )
    try:
        return _executar_com_log(ACOES_AGENTE[acao])
    except Exception as erro:
        raise HTTPException(status_code=500, detail=str(erro)) from erro
