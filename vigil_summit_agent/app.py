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

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import database
import agent
import api_client

load_dotenv()

st.set_page_config(
    page_title="Vigil Summit · Painel do Agente",
    page_icon="🛡️",
    layout="wide",
)

# ----------------------------------------------------------------------
# Constantes de apresentação
# ----------------------------------------------------------------------
# Ordem dos estágios reaproveitada do agente (fonte única da verdade do funil).
STATUS_ORDER = agent.FUNNEL_STATUSES
STATUS_EMOJI = {
    agent.STATUS_INSCRITO: "📝",
    agent.STATUS_CONFIRMADO: "✅",
    agent.STATUS_PRESENTE: "🎟️",
    agent.STATUS_REUNIAO_AGENDADA: "🤝",
}
ORIGEM_OPCOES = [agent.ORIGEM_ORGANICA, agent.SEGMENTO_REMARKETING]
SETOR_OPCOES = [
    "Tecnologia", "Financeiro", "Varejo", "Saúde", "Indústria",
    "Educação", "Energia", "Telecomunicações", "Outro",
]

# Meta de comparecimento definida no case (usada como referência nos KPIs).
META_COMPARECIMENTO = 70

ACCENT = "#00ff9c"
CUSTOM_CSS = f"""
<style>
    .stApp {{ background-color: #0d0f12; }}
    section[data-testid="stSidebar"] {{ background-color: #14171c; }}
    h1, h2, h3 {{ letter-spacing: -0.5px; }}
    div[data-testid="stMetricValue"] {{ color: {ACCENT}; }}
    /* Abas com destaque no item ativo */
    button[data-baseweb="tab"] {{ font-size: 0.95rem; }}
    div[data-baseweb="tab-highlight"] {{ background-color: {ACCENT}; }}
</style>
"""

database.init_db()


# ----------------------------------------------------------------------
# Formatação de datas (padrão brasileiro: dd/mm/aaaa)
# ----------------------------------------------------------------------
def formatar_data(valor, com_hora: bool = False) -> str:
    """Converte uma data/datetime (ou string ISO) para dd/mm/aaaa [HH:MM]."""
    timestamp = pd.to_datetime(valor, errors="coerce")
    if pd.isna(timestamp):
        return "—"
    return timestamp.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


# ----------------------------------------------------------------------
# Autenticação (login por usuário + senha, sempre ativo).
# Um usuário "admin" inicial é criado com a senha configurada
# (st.secrets > APP_PASSWORD no .env > padrão), garantindo o primeiro acesso.
# ----------------------------------------------------------------------
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "vigil2026"


def _senha_inicial() -> str:
    try:
        if "APP_PASSWORD" in st.secrets:
            valor = str(st.secrets["APP_PASSWORD"]).strip()
            if valor:
                return valor
    except Exception:
        pass
    return os.getenv("APP_PASSWORD", "").strip() or DEFAULT_PASSWORD


database.ensure_default_user(DEFAULT_USERNAME, _senha_inicial())


def usuario_logado() -> str | None:
    return st.session_state.get("user")


def check_password() -> bool:
    if usuario_logado():
        return True

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
            usuario = st.text_input("Usuário", placeholder=DEFAULT_USERNAME)
            senha = st.text_input("Senha", type="password", placeholder="••••••••")
            entrar = st.form_submit_button("Entrar", width="stretch")
        if entrar:
            if database.verify_user(usuario.strip(), senha):
                st.session_state["user"] = usuario.strip()
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")
    return False


# ----------------------------------------------------------------------
# Acesso a dados
# ----------------------------------------------------------------------
def load_leads_df() -> pd.DataFrame:
    if api_client.modo_remoto():
        try:
            return api_client.fetch_leads_df()
        except RuntimeError as erro:
            st.error(str(erro))
            return pd.DataFrame()
    conn = database.get_connection()
    try:
        return pd.read_sql_query("SELECT * FROM leads ORDER BY id;", conn)
    finally:
        conn.close()


def load_logs_df(lead_id: int | None = None) -> pd.DataFrame:
    if api_client.modo_remoto():
        try:
            return api_client.fetch_logs_df(lead_id)
        except RuntimeError as erro:
            st.error(str(erro))
            return pd.DataFrame()
    conn = database.get_connection()
    try:
        if lead_id is None:
            return pd.read_sql_query(
                "SELECT * FROM interaction_logs ORDER BY id DESC;", conn
            )
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
# Componentes de UI
# ----------------------------------------------------------------------
def render_sidebar() -> None:
    """Contexto do evento, status do LLM e captação manual de leads (Fase 1)."""
    with st.sidebar:
        st.caption(f"👤 Conectado como **{usuario_logado()}**")
        if st.button("🚪 Sair", width="stretch"):
            st.session_state.pop("user", None)
            st.rerun()

        st.header("⚙️ Contexto do evento")
        dias = agent.dias_para_o_evento()
        st.metric("Data do Vigil Summit", formatar_data(agent.get_event_date()), border=True)
        st.metric(
            "Dias para o evento",
            dias if dias >= 0 else "Encerrado",
            delta=None if dias >= 0 else f"há {abs(dias)} dia(s)",
            border=True,
        )
        st.metric("Vagas totais", agent.EVENT_TOTAL_SEATS, border=True)

        if agent.llm_configurado():
            st.caption(f"LLM: **{agent.LLM_PROVIDER}** · `{agent.modelo_ativo()}` · ✅ configurado")
        else:
            st.caption(f"LLM: **{agent.LLM_PROVIDER}** · `{agent.modelo_ativo()}` · ⚠️ sem chave")

        st.header("➕ Captar lead (Fase 1)")
        with st.form("novo_lead", clear_on_submit=True):
            nome = st.text_input("Nome*")
            email = st.text_input("E-mail corporativo*")
            cargo = st.text_input("Cargo declarado")
            setor = st.selectbox("Setor", [""] + SETOR_OPCOES, format_func=lambda s: "Selecione..." if s == "" else s)
            empresa = st.text_input("Empresa")
            telefone = st.text_input("Telefone / WhatsApp")
            origem = st.selectbox("Origem", ORIGEM_OPCOES)
            enviar = st.form_submit_button("Inscrever lead", width="stretch")

        if not enviar:
            return
        if not nome or not email:
            st.error("Nome e e-mail são obrigatórios.")
            return
        if api_client.modo_remoto():
            try:
                resultado = api_client.registrar_inscricao({
                    "nome": nome.strip(),
                    "email": email.strip(),
                    "cargo": (cargo or "Não informado").strip(),
                    "setor": (setor or "Outro").strip(),
                    "empresa": (empresa or "Não informado").strip(),
                    "telefone": (telefone or "+5500000000000").strip(),
                })
                st.success(f"Lead #{resultado.get('lead_id')} inscrito na API!")
                st.rerun()
            except RuntimeError as erro:
                st.error(str(erro))
            return
        novo_id = database.insert_lead(
            nome=nome,
            email=email,
            telefone=telefone or None,
            cargo_declarado=cargo or None,
            setor=setor or None,
            empresa=empresa or None,
            origem=origem,
        )
        if novo_id is None:
            st.error("E-mail já cadastrado.")
        else:
            st.success(f"Lead #{novo_id} inscrito!")
            st.rerun()


def contar_por_status(leads_df: pd.DataFrame) -> dict:
    return {s: int((leads_df["status_funil"] == s).sum()) for s in STATUS_ORDER}


def render_visao_geral(leads_df: pd.DataFrame) -> None:
    """KPIs de negócio + funil de conversão com drop-off por estágio."""
    contagem = contar_por_status(leads_df)
    total = len(leads_df)
    confirmados = (
        contagem[agent.STATUS_CONFIRMADO]
        + contagem[agent.STATUS_PRESENTE]
        + contagem[agent.STATUS_REUNIAO_AGENDADA]
    )
    presentes = contagem[agent.STATUS_PRESENTE] + contagem[agent.STATUS_REUNIAO_AGENDADA]

    taxa_confirmacao = (confirmados / total * 100) if total else 0
    taxa_comparecimento = (presentes / confirmados * 100) if confirmados else 0
    taxa_reuniao = (contagem[agent.STATUS_REUNIAO_AGENDADA] / presentes * 100) if presentes else 0

    st.markdown("#### Indicadores-chave")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total de leads", total, border=True)
    k2.metric("Taxa de confirmação", f"{taxa_confirmacao:.0f}%", border=True)
    k3.metric(
        "Taxa de comparecimento",
        f"{taxa_comparecimento:.0f}%",
        delta=f"{taxa_comparecimento - META_COMPARECIMENTO:+.0f} p.p. vs meta",
        help=f"Meta do case: > {META_COMPARECIMENTO}%",
        border=True,
    )
    k4.metric("Conversão em reunião", f"{taxa_reuniao:.0f}%", border=True)

    st.markdown("#### Funil de conversão")
    st.caption("Alcance cumulativo: quantos leads chegaram *até* cada estágio.")
    grafico_col, tabela_col = st.columns([1.1, 1])

    # Como os status são mutuamente exclusivos (representam o estágio mais
    # avançado já atingido), o alcance de um estágio soma ele e os seguintes.
    alcance = {
        agent.STATUS_INSCRITO: total,
        agent.STATUS_CONFIRMADO: confirmados,
        agent.STATUS_PRESENTE: presentes,
        agent.STATUS_REUNIAO_AGENDADA: contagem[agent.STATUS_REUNIAO_AGENDADA],
    }

    funil_df = pd.DataFrame(
        {"Estágio": STATUS_ORDER, "Leads": [alcance[s] for s in STATUS_ORDER]}
    ).set_index("Estágio")
    grafico_col.bar_chart(funil_df, color=ACCENT, horizontal=True)

    funil_tabela = pd.DataFrame(
        {
            "Estágio": [f"{STATUS_EMOJI[s]} {s}" for s in STATUS_ORDER],
            "Alcançaram": [alcance[s] for s in STATUS_ORDER],
            "% do topo": [(alcance[s] / total * 100) if total else 0 for s in STATUS_ORDER],
        }
    )
    tabela_col.dataframe(
        funil_tabela,
        hide_index=True,
        width="stretch",
        column_config={
            "Alcançaram": st.column_config.NumberColumn("Alcançaram", width="small"),
            "% do topo": st.column_config.ProgressColumn(
                "% do topo", format="%.0f%%", min_value=0, max_value=100
            ),
        },
    )


def render_operacao(leads_df: pd.DataFrame) -> None:
    """Botões que disparam os pipelines do agente (Fases 2–4)."""
    remoto = api_client.modo_remoto()

    if remoto:
        st.caption(
            f"Modo nuvem: operações executadas na API `{api_client.base_url()}` "
            "(configure LLM no Render)."
        )
    elif not api_key_configurada():
        st.info(
            f"As ações de IA exigem a chave do provedor **{agent.LLM_PROVIDER}** no `.env`. "
            "Sem ela, o funil é exibido normalmente, mas a geração de texto fica indisponível."
        )

    acoes = [
        ("Fase 2 · Enriquecer", "Enriquecendo leads com o LLM...", "enrich",
         agent.run_enrichment_pipeline, "Enriquecimento concluído."),
        ("Fase 3 · Engajar + respostas", "Gerando confirmações e simulando respostas...", "engage",
         agent.run_engagement_with_simulated_responses, "Engajamento concluído."),
        ("Fase 4 · Follow-up", "Gerando follow-up pós-evento...", "post",
         lambda: agent.run_post_event_sequence(simular_sequencia_completa=True),
         "Follow-up concluído."),
        ("🎬 Demo ponta a ponta", "Rodando funil completo...", "demo",
         agent.run_full_funnel_demo, "Demo concluída."),
    ]

    desativadas = not remoto and not api_key_configurada()
    for coluna, (rotulo, spinner, acao_api, executar, sucesso) in zip(st.columns(len(acoes)), acoes):
        with coluna:
            if not st.button(rotulo, disabled=desativadas, width="stretch"):
                continue
            with st.spinner(spinner):
                try:
                    if remoto:
                        resultado = api_client.executar_agente(acao_api)
                        if resultado.get("log"):
                            st.code(resultado["log"], language=None)
                    else:
                        executar()
                    st.success(sucesso)
                except Exception as erro:
                    st.error(f"Falha: {erro}")
            st.rerun()


def _leads_para_exibicao(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara o DataFrame de leads para exibição (status com ícone, data tipada)."""
    view = df.copy()
    if "cargo_real" in view.columns or "cargo_declarado" in view.columns:
        def _cargo_exibido(row: pd.Series) -> str:
            for coluna in ("cargo_real", "cargo_declarado"):
                if coluna in row.index and pd.notna(row[coluna]) and str(row[coluna]).strip():
                    return str(row[coluna]).strip()
            return "—"

        view["cargo"] = view.apply(_cargo_exibido, axis=1)
    if "status_funil" in view.columns:
        view["status_funil"] = view["status_funil"].map(
            lambda s: f"{STATUS_EMOJI.get(s, '')} {s}".strip()
        )
    if "data_inscricao" in view.columns:
        view["data_inscricao"] = pd.to_datetime(view["data_inscricao"], errors="coerce")
    return view


LEADS_COLUMN_CONFIG = {
    "id": st.column_config.NumberColumn("ID", width="small"),
    "nome": st.column_config.TextColumn("Nome"),
    "email": st.column_config.TextColumn("E-mail"),
    "empresa": st.column_config.TextColumn("Empresa"),
    "cargo": st.column_config.TextColumn("Cargo"),
    "setor": st.column_config.TextColumn("Setor"),
    "tamanho_empresa": st.column_config.TextColumn("Porte"),
    "origem": st.column_config.TextColumn("Origem"),
    "status_funil": st.column_config.TextColumn("Status"),
    "data_inscricao": st.column_config.DatetimeColumn("Inscrição", format="DD/MM/YYYY"),
}
LEADS_VISIBLE_COLUMNS = [
    "id", "nome", "email", "empresa", "cargo",
    "setor", "tamanho_empresa", "origem", "status_funil", "data_inscricao",
]


def render_tabela_de_leads(leads_df: pd.DataFrame) -> None:
    filtro_status_col, filtro_origem_col, _ = st.columns([1, 1, 2])
    filtro_status = filtro_status_col.multiselect("Status", STATUS_ORDER, default=STATUS_ORDER)
    filtro_origem = filtro_origem_col.multiselect("Origem", ORIGEM_OPCOES, default=ORIGEM_OPCOES)

    df_view = leads_df.copy()
    if filtro_status:
        df_view = df_view[df_view["status_funil"].isin(filtro_status)]
    if filtro_origem and "origem" in df_view.columns:
        df_view = df_view[df_view["origem"].isin(filtro_origem)]

    df_view = _leads_para_exibicao(df_view)
    colunas = [c for c in LEADS_VISIBLE_COLUMNS if c in df_view.columns]
    st.caption(f"{len(df_view)} lead(s) exibido(s).")
    st.dataframe(
        df_view[colunas],
        width="stretch",
        hide_index=True,
        column_config=LEADS_COLUMN_CONFIG,
    )


def render_detalhe_do_lead(leads_df: pd.DataFrame) -> None:
    if leads_df.empty:
        st.info("Nenhum lead cadastrado ainda. Use a barra lateral para captar.")
        return

    opcoes = {
        f"#{row.id} · {row.nome} ({row.status_funil})": int(row.id)
        for row in leads_df.itertuples()
    }
    escolha = st.selectbox("Selecione um lead", list(opcoes.keys()))
    lead_id = opcoes[escolha]
    remoto = api_client.modo_remoto()
    if remoto:
        lead = leads_df.loc[leads_df["id"] == lead_id].iloc[0]
    else:
        lead = agent.get_lead_by_id(lead_id)

    perfil_col, acoes_col = st.columns([1, 1])
    with perfil_col:
        with st.container(border=True):
            st.markdown(f"**{STATUS_EMOJI.get(lead['status_funil'], '')} {lead['nome']}**")
            st.markdown(f"**E-mail:** {lead['email']}")
            st.markdown(f"**Empresa:** {lead['empresa'] or '—'}")
            st.markdown(f"**Cargo declarado:** {lead['cargo_declarado'] or '—'}")
            st.markdown(f"**Cargo (enriquecido):** {lead['cargo_real'] or '— (pendente Fase 2)'}")
            st.markdown(f"**Setor:** {lead['setor'] or '—'}")
            st.markdown(f"**Porte:** {lead['tamanho_empresa'] or '—'}")
            st.markdown(
                f"**Origem/Segmento:** {lead['origem']} → {agent._segmento_do_lead(lead)}"
            )
            st.markdown(f"**Inscrição:** {formatar_data(lead['data_inscricao'])}")
            st.markdown(f"**Sinais de interesse:** {lead['sinais_interesse'] or '—'}")
            try:
                perfil_li = (lead["linkedin_perfil"] or "").strip()
            except (KeyError, TypeError):
                perfil_li = ""
            if perfil_li:
                st.markdown(f"**LinkedIn:** {perfil_li}")

    with acoes_col:
        if remoto:
            with st.container(border=True):
                st.markdown("**Gerenciar estágio no funil**")
                indice = STATUS_ORDER.index(lead["status_funil"]) if lead["status_funil"] in STATUS_ORDER else 0
                novo_status = st.selectbox("Status", STATUS_ORDER, index=indice, key=f"status_{lead_id}")
                if st.button("Atualizar status", key=f"upd_{lead_id}", width="stretch"):
                    try:
                        api_client.atualizar_status(lead_id, novo_status)
                        st.success(f"Status atualizado para '{novo_status}'.")
                        st.rerun()
                    except RuntimeError as erro:
                        st.error(str(erro))

            with st.container(border=True):
                st.markdown("**Simular resposta do lead (WhatsApp)**")
                st.caption(f"Dica: a frase de compromisso é \"{agent.CONFIRMATION_PHRASE}\".")
                resposta = st.text_input("Resposta recebida", key=f"resp_{lead_id}")
                if st.button("Registrar resposta", key=f"send_{lead_id}", width="stretch"):
                    if resposta.strip():
                        try:
                            api_client.registrar_resposta(lead_id, resposta.strip())
                            st.success("Resposta registrada.")
                            st.rerun()
                        except RuntimeError as erro:
                            st.error(str(erro))
                    else:
                        st.error("Digite uma resposta.")
        else:
            with st.container(border=True):
                st.markdown("**Gerenciar estágio no funil**")
                indice = STATUS_ORDER.index(lead["status_funil"]) if lead["status_funil"] in STATUS_ORDER else 0
                novo_status = st.selectbox("Status", STATUS_ORDER, index=indice, key=f"status_{lead_id}")
                if st.button("Atualizar status", key=f"upd_{lead_id}", width="stretch"):
                    agent.update_lead_status(lead_id, novo_status)
                    st.success(f"Status atualizado para '{novo_status}'.")
                    st.rerun()

            with st.container(border=True):
                st.markdown("**Simular resposta do lead (WhatsApp)**")
                st.caption(f"Dica: a frase de compromisso é \"{agent.CONFIRMATION_PHRASE}\".")
                resposta = st.text_input("Resposta recebida", key=f"resp_{lead_id}")
                if st.button("Registrar resposta", key=f"send_{lead_id}", width="stretch"):
                    if resposta.strip():
                        agent.receive_lead_response(lead_id, resposta.strip())
                        st.success("Resposta registrada.")
                        st.rerun()
                    else:
                        st.error("Digite uma resposta.")

    st.markdown("**🧾 Histórico de interações**")
    logs_lead = load_logs_df(lead_id)
    if logs_lead.empty:
        st.info("Nenhuma interação registrada para este lead.")
        return
    for row in logs_lead.itertuples():
        titulo = (
            f"{formatar_data(row.data_envio, com_hora=True)} · "
            f"[{row.fase_funil}] {row.tipo_mensagem} · {row.canal}"
        )
        with st.expander(titulo):
            st.markdown("**Mensagem enviada:**")
            st.text(row.conteudo_enviado or "—")
            st.markdown("**Resposta do lead:**")
            st.text(row.resposta_lead or "— (sem resposta)")


LOGS_COLUMN_CONFIG = {
    "id": st.column_config.NumberColumn("ID", width="small"),
    "lead_id": st.column_config.NumberColumn("Lead", width="small"),
    "fase_funil": st.column_config.TextColumn("Fase"),
    "canal": st.column_config.TextColumn("Canal"),
    "tipo_mensagem": st.column_config.TextColumn("Tipo"),
    "conteudo_enviado": st.column_config.TextColumn("Mensagem", width="large"),
    "resposta_lead": st.column_config.TextColumn("Resposta"),
    "data_envio": st.column_config.DatetimeColumn("Enviado em", format="DD/MM/YYYY HH:mm"),
}


def render_log_geral() -> None:
    todos_logs = load_logs_df()
    if todos_logs.empty:
        st.info("Sem interações registradas ainda.")
        return
    if "data_envio" in todos_logs.columns:
        todos_logs["data_envio"] = pd.to_datetime(todos_logs["data_envio"], errors="coerce")
    st.dataframe(
        todos_logs,
        width="stretch",
        hide_index=True,
        column_config=LOGS_COLUMN_CONFIG,
    )


USERS_COLUMN_CONFIG = {
    "id": st.column_config.NumberColumn("ID", width="small"),
    "username": st.column_config.TextColumn("Usuário"),
    "created_at": st.column_config.DatetimeColumn("Criado em", format="DD/MM/YYYY HH:mm"),
}


def _criar_usuario(username: str, senha: str, confirmacao: str) -> None:
    """Valida e cria um novo usuário do painel."""
    if not username or not senha:
        st.error("Usuário e senha são obrigatórios.")
        return
    if len(senha) < database.MIN_PASSWORD_LENGTH:
        st.error(f"A senha deve ter ao menos {database.MIN_PASSWORD_LENGTH} caracteres.")
        return
    if senha != confirmacao:
        st.error("As senhas não conferem.")
        return
    if database.create_user(username, senha) is None:
        st.error(f"O usuário '{username}' já existe.")
        return
    st.success(f"Usuário '{username}' criado com sucesso!")
    st.rerun()


def render_usuarios() -> None:
    """Tela de gestão de usuários do painel (criar, listar e remover)."""
    st.caption("Quem pode acessar este painel. As senhas são armazenadas como hash (PBKDF2).")

    usuarios = database.list_users()
    df = pd.DataFrame(usuarios, columns=["id", "username", "created_at"])
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    st.dataframe(df, width="stretch", hide_index=True, column_config=USERS_COLUMN_CONFIG)

    criar_col, remover_col = st.columns(2)

    with criar_col:
        with st.container(border=True):
            st.markdown("**➕ Novo usuário**")
            with st.form("novo_usuario", clear_on_submit=True):
                username = st.text_input("Usuário")
                senha = st.text_input("Senha", type="password")
                confirmacao = st.text_input("Confirmar senha", type="password")
                criar = st.form_submit_button("Criar usuário", width="stretch")
            if criar:
                _criar_usuario(username.strip(), senha, confirmacao)

    with remover_col:
        with st.container(border=True):
            st.markdown("**🗑️ Remover usuário**")
            nomes = [u["username"] for u in usuarios]
            alvo = st.selectbox("Usuário a remover", nomes) if nomes else None
            # Travas de segurança: não remover a si mesmo nem o último acesso.
            indisponivel = alvo is None or alvo == usuario_logado() or len(nomes) <= 1
            if st.button("Remover", disabled=indisponivel, width="stretch"):
                database.delete_user(alvo)
                st.success(f"Usuário '{alvo}' removido.")
                st.rerun()
            if alvo == usuario_logado():
                st.caption("Você não pode remover o próprio usuário conectado.")
            elif len(nomes) <= 1:
                st.caption("Deve haver pelo menos um usuário com acesso.")


# ----------------------------------------------------------------------
# Página
# ----------------------------------------------------------------------
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

if not check_password():
    st.stop()

st.title("🛡️ Vigil Summit · Painel do Agente Autônomo")
st.caption("Funil de ponta a ponta: Captação → Enriquecimento → Engajamento → Follow-up")

if api_client.modo_remoto():
    st.caption(f"☁️ Modo nuvem · API: `{api_client.base_url()}`")

render_sidebar()
leads_df = load_leads_df()

tab_visao, tab_leads, tab_operacao, tab_logs, tab_usuarios = st.tabs(
    ["📊 Visão geral", "👥 Leads", "🤖 Operar o agente", "🧾 Interações", "👤 Usuários"]
)

with tab_visao:
    render_visao_geral(leads_df)

with tab_leads:
    render_tabela_de_leads(leads_df)
    st.markdown("#### 🔍 Detalhe do lead")
    render_detalhe_do_lead(leads_df)

with tab_operacao:
    render_operacao(leads_df)

with tab_logs:
    render_log_geral()

with tab_usuarios:
    render_usuarios()
