"""
api_client.py
-------------
Cliente HTTP para o painel Streamlit operar a API remota (Render).

Configure VIGIL_API_URL e VIGIL_API_KEY no .env ou Secrets do Streamlit Cloud.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import pandas as pd


def _ler_config(nome: str) -> str:
    valor = os.getenv(nome, "").strip()
    if valor:
        return valor
    try:
        import streamlit as st

        if nome in st.secrets:
            return str(st.secrets[nome]).strip()
    except Exception:
        pass
    return ""


def base_url() -> str | None:
    url = _ler_config("VIGIL_API_URL").rstrip("/")
    return url or None


def api_key() -> str:
    return _ler_config("VIGIL_API_KEY")


def modo_remoto() -> bool:
    return base_url() is not None


def _request(caminho: str, metodo: str = "GET", payload: dict | None = None) -> Any:
    url = f"{base_url()}{caminho}"
    dados = None
    headers = {"Accept": "application/json"}
    chave = api_key()
    if chave:
        headers["X-API-Key"] = chave
    if payload is not None:
        dados = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=dados, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        corpo = erro.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("detail", corpo)
        except json.JSONDecodeError:
            detalhe = corpo or str(erro)
        raise RuntimeError(str(detalhe)) from erro
    except urllib.error.URLError as erro:
        raise RuntimeError(
            "API indisponível. Render free tier pode levar ~1 min (cold start)."
        ) from erro


def fetch_leads_df() -> pd.DataFrame:
    dados = _request("/api/leads")
    leads = dados.get("leads", [])
    return pd.DataFrame(leads) if leads else pd.DataFrame()


def fetch_logs_df(lead_id: int | None = None) -> pd.DataFrame:
    caminho = "/api/interactions"
    if lead_id is not None:
        caminho = f"{caminho}?lead_id={lead_id}"
    dados = _request(caminho)
    logs = dados.get("interactions", [])
    return pd.DataFrame(logs) if logs else pd.DataFrame()


def registrar_inscricao(payload: dict) -> dict:
    return _request("/api/inscricao", metodo="POST", payload=payload)


def atualizar_status(lead_id: int, status_funil: str) -> dict:
    return _request(
        f"/api/leads/{lead_id}/status",
        metodo="PATCH",
        payload={"status_funil": status_funil},
    )


def registrar_resposta(lead_id: int, resposta: str) -> dict:
    return _request(
        f"/api/leads/{lead_id}/response",
        metodo="POST",
        payload={"resposta": resposta},
    )


def executar_agente(acao: str) -> dict:
    return _request(f"/api/agent/{acao}", metodo="POST", payload={})
