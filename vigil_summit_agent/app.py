"""
app.py
------
Painel de monitoramento e operação do Vigil Summit Agent (Pareto / Vigil.AI).

Interface visual em Streamlit que permite:
    - Visualizar o funil completo (Inscrito → Confirmado → Presente → Reunião Agendada)
    - Inspecionar o perfil enriquecido de cada lead e seu histórico de interações
    - Operar o agente: enriquecer (Fase 2), engajar (Fase 3), follow-up (Fase 4)
    - Simular respostas de leads e gerenciar o estágio no funil
    - Captar novos leads manualmente (Fase 1)

Execução:
    py -m streamlit run app.py
"""

import os
import sqlite3

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import database
import agent

load_dotenv()

# ----------------------------------------------------------------------
# Configuração da página
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="Vigil Summit · Painel do Agente",
    page_icon="🛡️",
    layout="wide",
)

STATUS_ORDER = ["Inscrito", "Confirmado", "Presente", "Reunião Agendada"]
STATUS_EMOJI = {
    "Inscrito": "📝",
    "Confirmado": "✅",
    "Presente": "🎟️",
    "Reunião Agendada": "🤝",
}

CUSTOM_CSS = """
<style>
    .stApp { background-color: #0d0f12; }
    section[data-testid="stSidebar"] { background-color: #14171c; }
    h1, h2, h3 { letter-spacing: -0.5px; }
    div[data-testid="stMetricValue"] { color: #00ff9c; }
    .vs-accent { color: #00ff9c; }
</style>
"""

# Garante o schema/seed ao abrir o painel.
database.init_db()


# ----------------------------------------------------------------------
# Proteção por senha (login sempre ativo): acesso publico protegido por senha
# ----------------------------------------------------------------------
# Senha padrao usada se nada for configurado. Em deploy, defina APP_PASSWORD
# em st.secrets (Streamlit Cloud) ou no .env.
DEFAULT_PASSWORD = "vigil2026"


def _senha_configurada() -> str:
    # Prioridade: st.secrets (deploy) > variavel de ambiente (.env) > padrao.
    try:
        if "APP_PASSWORD" in st.secrets:
            valor = str(st.secrets["APP_PASSWORD"]).strip()
            if valor:
                return valor
    except Exception:
        pass
    return os.getenv("APP_PASSWORD", "").strip() or DEFAULT_PASSWORD


def check_password() -> bool:
    if st.session_state.get("auth_ok"):
        return True

    senha_correta = _senha_configurada()

    _, meio, _ = st.columns([1, 1.4, 1])
    with meio:
        st.markdown(
            "<div style='text-align:center; padding-top:8vh'>"
            "<h1 style='margin-bottom:0'>🛡️ Vigil Summit</h1>"
            "<p style='color:#9aa1ad; margin-top:4px'>Painel do Agente Autônomo · acesso restrito</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.form("login"):
            senha = st.text_input("Senha de acesso", type="password", placeholder="••••••••")
            entrar = st.form_submit_button("Entrar", use_container_width=True)
        if entrar:
            if senha == senha_correta:
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Senha incorreta. Tente novamente.")
    return False


# ----------------------------------------------------------------------
# Acesso a dados
# ----------------------------------------------------------------------
def load_leads_df() -> pd.DataFrame:
    conn = database.get_connection()
    try:
        return pd.read_sql_query(
            "SELECT * FROM leads ORDER BY id;", conn
        )
    finally:
        conn.close()


def load_logs_df(lead_id: int | None = None) -> pd.DataFrame:
    conn = database.get_connection()
    try:
        if lead_id is None:
            query = "SELECT * FROM interaction_logs ORDER BY id DESC;"
            return pd.read_sql_query(query, conn)
        return pd.read_sql_query(
            "SELECT * FROM interaction_logs WHERE lead_id = ? ORDER BY id DESC;",
            conn,
            params=(lead_id,),
        )
    finally:
        conn.close()


def api_key_configurada() -> bool:
    return agent.llm_configurado()


# ----------------------------------------------------------------------
# Página
# ----------------------------------------------------------------------
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

if not check_password():
    st.stop()

st.title("🛡️ Vigil Summit · Painel do Agente Autônomo")
st.caption(
    "Funil de ponta a ponta: Captação → Enriquecimento → Engajamento → Follow-up"
)

leads_df = load_leads_df()

# --- Aviso sobre API key ---------------------------------------------
if not api_key_configurada():
    st.warning(
        f"⚠️ API key do provedor ativo (`{agent.LLM_PROVIDER}`) não configurada "
        "no `.env`. A visualização do funil funciona normalmente, mas as ações "
        "que geram texto com o LLM (enriquecer/engajar/follow-up) ficarão "
        "indisponíveis até você inserir um token válido."
    )

# ======================================================================
# SIDEBAR — contexto e captação (Fase 1)
# ======================================================================
with st.sidebar:
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state.pop("auth_ok", None)
        st.rerun()

    st.header("⚙️ Contexto do evento")
    st.metric("Data do Vigil Summit", agent.get_event_date().isoformat())
    dias = agent.dias_para_o_evento()
    st.metric("Dias para o evento", dias if dias >= 0 else f"{abs(dias)} (passou)")
    st.metric("Vagas totais", 120)
    st.caption(
        f"LLM: **{agent.LLM_PROVIDER}** · `{agent.modelo_ativo()}` · "
        + ("✅ configurado" if agent.llm_configurado() else "⚠️ sem chave")
    )

    st.divider()
    st.header("➕ Captar lead (Fase 1)")
    with st.form("novo_lead", clear_on_submit=True):
        nome = st.text_input("Nome*")
        email = st.text_input("E-mail corporativo*")
        cargo = st.text_input("Cargo declarado")
        empresa = st.text_input("Empresa")
        telefone = st.text_input("Telefone / WhatsApp")
        origem = st.selectbox("Origem", ["LP_Organico", "Remarketing"])
        enviar = st.form_submit_button("Inscrever lead")

    if enviar:
        if not nome or not email:
            st.error("Nome e e-mail são obrigatórios.")
        else:
            novo_id = database.insert_lead(
                nome=nome,
                email=email,
                telefone=telefone or None,
                cargo_declarado=cargo or None,
                empresa=empresa or None,
                origem=origem,
            )
            if novo_id is None:
                st.error("E-mail já cadastrado.")
            else:
                st.success(f"Lead #{novo_id} inscrito!")
                st.rerun()

# ======================================================================
# MÉTRICAS DO FUNIL
# ======================================================================
st.subheader("📊 Visão do funil")

contagem = {s: int((leads_df["status_funil"] == s).sum()) for s in STATUS_ORDER}
total_leads = len(leads_df)
confirmados = contagem["Confirmado"] + contagem["Presente"] + contagem["Reunião Agendada"]
presentes = contagem["Presente"] + contagem["Reunião Agendada"]

cols = st.columns(len(STATUS_ORDER))
for col, status in zip(cols, STATUS_ORDER):
    col.metric(f"{STATUS_EMOJI[status]} {status}", contagem[status])

# KPIs de negócio (taxas).
k1, k2, k3 = st.columns(3)
taxa_conf = (confirmados / total_leads * 100) if total_leads else 0
taxa_presenca = (presentes / confirmados * 100) if confirmados else 0
taxa_reuniao = (contagem["Reunião Agendada"] / presentes * 100) if presentes else 0
k1.metric("Taxa de confirmação", f"{taxa_conf:.0f}%")
k2.metric("Taxa de comparecimento", f"{taxa_presenca:.0f}%", help="Meta do case: > 70%")
k3.metric("Conversão em reunião", f"{taxa_reuniao:.0f}%")

# Gráfico simples do funil.
funil_df = pd.DataFrame(
    {"Estágio": STATUS_ORDER, "Leads": [contagem[s] for s in STATUS_ORDER]}
).set_index("Estágio")
st.bar_chart(funil_df, color="#00ff9c")

# ======================================================================
# AÇÕES EM LOTE (PIPELINES DO AGENTE)
# ======================================================================
st.subheader("🤖 Operar o agente")
acao_cols = st.columns(4)
acoes_desativadas = not api_key_configurada()

with acao_cols[0]:
    if st.button("Fase 2 · Enriquecer", disabled=acoes_desativadas, use_container_width=True):
        with st.spinner("Enriquecendo leads com o Claude..."):
            try:
                agent.run_enrichment_pipeline()
                st.success("Enriquecimento concluído.")
            except Exception as e:
                st.error(f"Falha: {e}")
        st.rerun()

with acao_cols[1]:
    if st.button("Fase 3 · Engajar + respostas", disabled=acoes_desativadas, use_container_width=True):
        with st.spinner("Gerando confirmações e simulando respostas..."):
            try:
                agent.run_engagement_with_simulated_responses()
                st.success("Engajamento concluído.")
            except Exception as e:
                st.error(f"Falha: {e}")
        st.rerun()

with acao_cols[2]:
    if st.button("Fase 4 · Follow-up", disabled=acoes_desativadas, use_container_width=True):
        with st.spinner("Gerando follow-up pós-evento..."):
            try:
                agent.run_post_event_sequence(simular_sequencia_completa=True)
                st.success("Follow-up concluído.")
            except Exception as e:
                st.error(f"Falha: {e}")
        st.rerun()

with acao_cols[3]:
    if st.button("🎬 Demo ponta a ponta", disabled=acoes_desativadas, use_container_width=True):
        with st.spinner("Rodando funil completo..."):
            try:
                agent.run_full_funnel_demo()
                st.success("Demo concluída.")
            except Exception as e:
                st.error(f"Falha: {e}")
        st.rerun()

# ======================================================================
# TABELA DE LEADS
# ======================================================================
st.subheader("👥 Leads")
filtro_cols = st.columns([1, 1, 2])
filtro_status = filtro_cols[0].multiselect("Status", STATUS_ORDER, default=STATUS_ORDER)
filtro_segmento = filtro_cols[1].multiselect(
    "Origem", ["LP_Organico", "Remarketing"], default=["LP_Organico", "Remarketing"]
)

df_view = leads_df.copy()
if filtro_status:
    df_view = df_view[df_view["status_funil"].isin(filtro_status)]
if filtro_segmento and "origem" in df_view.columns:
    df_view = df_view[df_view["origem"].isin(filtro_segmento)]

colunas_visiveis = [
    "id", "nome", "email", "empresa", "cargo_real",
    "setor", "tamanho_empresa", "origem", "status_funil",
]
colunas_visiveis = [c for c in colunas_visiveis if c in df_view.columns]
st.dataframe(df_view[colunas_visiveis], use_container_width=True, hide_index=True)

# ======================================================================
# DETALHE DO LEAD
# ======================================================================
st.subheader("🔍 Detalhe do lead")

if leads_df.empty:
    st.info("Nenhum lead cadastrado ainda. Use a barra lateral para captar.")
else:
    opcoes = {
        f"#{row.id} · {row.nome} ({row.status_funil})": int(row.id)
        for row in leads_df.itertuples()
    }
    escolha = st.selectbox("Selecione um lead", list(opcoes.keys()))
    lead_id = opcoes[escolha]
    lead = agent.get_lead_by_id(lead_id)

    det_cols = st.columns([1, 1])
    with det_cols[0]:
        st.markdown(f"**Nome:** {lead['nome']}")
        st.markdown(f"**E-mail:** {lead['email']}")
        st.markdown(f"**Empresa:** {lead['empresa'] or '—'}")
        st.markdown(f"**Cargo real:** {lead['cargo_real'] or '— (não enriquecido)'}")
        st.markdown(f"**Setor:** {lead['setor'] or '—'}")
        st.markdown(f"**Tamanho:** {lead['tamanho_empresa'] or '—'}")
        st.markdown(f"**Origem/Segmento:** {lead['origem']} → {agent._segmento_do_lead(lead)}")
        st.markdown(f"**Sinais de interesse:** {lead['sinais_interesse'] or '—'}")

    with det_cols[1]:
        st.markdown("**Gerenciar estágio no funil**")
        novo_status = st.selectbox(
            "Status",
            STATUS_ORDER,
            index=STATUS_ORDER.index(lead["status_funil"])
            if lead["status_funil"] in STATUS_ORDER else 0,
            key=f"status_{lead_id}",
        )
        if st.button("Atualizar status", key=f"upd_{lead_id}"):
            agent.update_lead_status(lead_id, novo_status)
            st.success(f"Status atualizado para '{novo_status}'.")
            st.rerun()

        st.markdown("**Simular resposta do lead (WhatsApp)**")
        st.caption(f"Dica: a frase de compromisso é \"{agent.CONFIRMATION_PHRASE}\".")
        resposta = st.text_input("Resposta recebida", key=f"resp_{lead_id}")
        if st.button("Registrar resposta", key=f"send_{lead_id}"):
            if resposta.strip():
                agent.receive_lead_response(lead_id, resposta.strip())
                st.success("Resposta registrada.")
                st.rerun()
            else:
                st.error("Digite uma resposta.")

    # Histórico de interações do lead.
    st.markdown("**🧾 Histórico de interações**")
    logs_lead = load_logs_df(lead_id)
    if logs_lead.empty:
        st.info("Nenhuma interação registrada para este lead.")
    else:
        for row in logs_lead.itertuples():
            with st.expander(
                f"[{row.fase_funil}] {row.tipo_mensagem} · {row.canal} · {row.data_envio}"
            ):
                st.markdown("**Mensagem enviada:**")
                st.text(row.conteudo_enviado or "—")
                st.markdown("**Resposta do lead:**")
                st.text(row.resposta_lead or "— (sem resposta)")

# ======================================================================
# LOG GERAL
# ======================================================================
with st.expander("📜 Ver todas as interações (log completo)"):
    todos_logs = load_logs_df()
    if todos_logs.empty:
        st.info("Sem interações registradas ainda.")
    else:
        st.dataframe(todos_logs, use_container_width=True, hide_index=True)
