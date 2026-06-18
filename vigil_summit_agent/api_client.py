"""
api_client.py
-------------
Cliente HTTP opcional para ler leads da API de captação (Render) quando o
painel Streamlit roda na nuvem com banco separado do SQLite local.

Configure VIGIL_API_URL (e opcionalmente VIGIL_API_KEY) no .env ou nos
Secrets do Streamlit Cloud.
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
        with urllib.request.urlopen(req, timeout=90) as resp:
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
            "API de captação indisponível. Se usar Render free tier, "
            "aguarde ~1 minuto (cold start) e tente novamente."
        ) from erro


def fetch_leads_df() -> pd.DataFrame:
    dados = _request("/api/leads")
    leads = dados.get("leads", [])
    if not leads:
        return pd.DataFrame()
    return pd.DataFrame(leads)


def fetch_logs_df(lead_id: int | None = None) -> pd.DataFrame:
    caminho = "/api/interactions"
    if lead_id is not None:
        caminho = f"{caminho}?lead_id={lead_id}"
    dados = _request(caminho)
    logs = dados.get("interactions", [])
    if not logs:
        return pd.DataFrame()
    return pd.DataFrame(logs)


def registrar_inscricao(payload: dict) -> dict:
    return _request("/api/inscricao", metodo="POST", payload=payload)
