"""
agent.py
--------
Lógica do agente de IA do "Case AI Engineer - Vigil Summit" (Pareto).

Fases implementadas:
    - Fase 2: Enriquecimento / qualificação de leads
    - Fase 3: Engajamento pré-evento (régua de confirmação anti no-show)
    - Fase 4: Follow-up pós-evento (régua comercial até a reunião agendada)

Decisões de produto deste protótipo:
    - ENVIO SIMULADO: o LLM gera o conteúdo da mensagem e nós a registramos
      na tabela `interaction_logs`. A arquitetura isola a geração do "envio",
      então plugar WhatsApp (ex.: Twilio/Meta) ou e-mail (SMTP) depois é trivial.
    - CANAL: combinação WhatsApp (lembretes curtos/alta abertura) + E-mail
      (conteúdo rico/credibilidade executiva).
    - DATA DO EVENTO: configurável via .env (VIGIL_EVENT_DATE=YYYY-MM-DD).

Uso via CLI:
    py -X utf8 agent.py enrich   # Fase 2 - enriquecimento
    py -X utf8 agent.py engage   # Fase 3 - confirmação (neurociência) + respostas
    py -X utf8 agent.py pre      # Fase 3 - régua pré-evento completa (4 toques)
    py -X utf8 agent.py post     # Fase 4 - régua pós-evento
    py -X utf8 agent.py demo     # fluxo completo de ponta a ponta (default)
"""

import os
import sys
import json
import sqlite3
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from anthropic import Anthropic

from database import get_connection, init_db

# Carrega variáveis do .env (chaves de API, provedor, data do evento).
load_dotenv()

# ======================================================================
# CONFIGURAÇÃO (dados configuráveis mantidos no topo)
# ======================================================================

# --- Provedor de LLM (selecionável via .env) --------------------------
# "anthropic" (padrão, preferência do case) ou "groq" (gratuito para testes).
# A lógica do agente é independente do provedor.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GROQ = "groq"

CLAUDE_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Valores placeholder do .env.example — tratados como "sem chave configurada".
PLACEHOLDER_TOKENS = frozenset({"seu_token_aqui", "sua_chave_groq_aqui"})

# Parâmetros de geração por tarefa (temperatura menor = mais determinístico).
ENRICHMENT_MAX_TOKENS = 1024
ENRICHMENT_TEMPERATURE = 0.4
MESSAGE_MAX_TOKENS = 700
MESSAGE_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.5

# --- Estágios do funil (fonte única da verdade) -----------------------
STATUS_INSCRITO = "Inscrito"
STATUS_CONFIRMADO = "Confirmado"
STATUS_PRESENTE = "Presente"
STATUS_REUNIAO_AGENDADA = "Reunião Agendada"
FUNNEL_STATUSES = [
    STATUS_INSCRITO,
    STATUS_CONFIRMADO,
    STATUS_PRESENTE,
    STATUS_REUNIAO_AGENDADA,
]

# --- Canais e fases ---------------------------------------------------
CANAL_WHATSAPP = "WhatsApp"
CANAL_EMAIL = "E-mail"
FASE_PRE_EVENTO = "Pre-Evento"
FASE_POS_EVENTO = "Pos-Evento"

# --- Segmentação de lead ----------------------------------------------
ORIGEM_ORGANICA = "LP_Organico"          # valor gravado na coluna `origem`
SEGMENTO_ORGANICO = "Organico_LP"        # rótulo retornado pela classificação
SEGMENTO_REMARKETING = "Remarketing"
ORGANIC_LEAD_DOMAIN = "pareto.io"        # fallback legado (registros sem origem)

# --- Evento -----------------------------------------------------------
DEFAULT_EVENT_DAYS_FROM_NOW = 14
EVENT_TOTAL_SEATS = 120

# Frase exata do gatilho de compromisso (neurociência: commitment & consistency).
CONFIRMATION_PHRASE = "Eu irei ao evento"

# Largura dos separadores impressos no terminal.
_SECTION_WIDTH = 64

# --- Contexto de negócio usado nos System Prompts ---------------------
VIGIL_CONTEXT = (
    "A Vigil.AI é uma empresa de cibersegurança que vende uma plataforma SaaS "
    "de monitoramento contínuo de postura de segurança cibernética para médias "
    "e grandes empresas (acima de 200 funcionários). A plataforma entrega "
    "dashboards em tempo real, alertas de vulnerabilidades, relatórios de "
    "conformidade (ISO 27001, LGPD, SOC 2) e recomendações automatizadas de "
    "remediação, com uma camada de IA que prioriza riscos e antecipa ameaças."
)

EVENT_CONTEXT = (
    "O evento é o 'Vigil Summit — Segurança para a Era da IA': um encontro "
    "corporativo presencial e exclusivo, com apenas 120 vagas, voltado a CISOs, "
    "CTOs, diretores de TI e gestores de risco. Há palestras, demos ao vivo da "
    "plataforma Vigil.AI e networking entre líderes de segurança."
)


# ======================================================================
# DATA DO EVENTO
# ======================================================================
def get_event_date() -> date:
    """Data do Vigil Summit: lê VIGIL_EVENT_DATE do .env ou usa o padrão."""
    configurada = os.getenv("VIGIL_EVENT_DATE", "").strip()
    if configurada:
        try:
            return datetime.strptime(configurada, "%Y-%m-%d").date()
        except ValueError:
            print(f"⚠️  VIGIL_EVENT_DATE inválida ('{configurada}'). Usando padrão.")
    return date.today() + timedelta(days=DEFAULT_EVENT_DAYS_FROM_NOW)


def dias_para_o_evento() -> int:
    """Quantos dias faltam para o evento (negativo se já ocorreu)."""
    return (get_event_date() - date.today()).days


# ======================================================================
# CAMADA DE LLM (multi-provedor: Anthropic | Groq)
# ======================================================================
def modelo_ativo() -> str:
    """Nome do modelo em uso, conforme o provedor configurado."""
    return GROQ_MODEL if LLM_PROVIDER == PROVIDER_GROQ else CLAUDE_MODEL


def _nome_da_variavel_de_chave() -> str:
    return "GROQ_API_KEY" if LLM_PROVIDER == PROVIDER_GROQ else "ANTHROPIC_API_KEY"


def _api_key_do_provedor() -> str:
    return os.getenv(_nome_da_variavel_de_chave(), "").strip()


def llm_configurado() -> bool:
    """True se a API key do provedor ativo estiver configurada no .env."""
    chave = _api_key_do_provedor()
    return bool(chave) and chave not in PLACEHOLDER_TOKENS


def _gerar_via_groq(system_prompt: str, user_prompt: str,
                    max_tokens: int, temperature: float, api_key: str) -> str:
    # Groq expõe um endpoint compatível com a API da OpenAI.
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    resposta = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (resposta.choices[0].message.content or "").strip()


def _gerar_via_anthropic(system_prompt: str, user_prompt: str,
                         max_tokens: int, temperature: float, api_key: str) -> str:
    client = Anthropic(api_key=api_key)
    mensagem = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return mensagem.content[0].text.strip()


def _chat(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """
    Envia uma conversa (system + user) ao provedor ativo e retorna o texto.

    Abstrai Anthropic e Groq, permitindo trocar de modelo apenas mudando
    LLM_PROVIDER no .env, sem tocar na lógica do agente.
    """
    chave = _api_key_do_provedor()
    if not chave or chave in PLACEHOLDER_TOKENS:
        raise RuntimeError(
            f"{_nome_da_variavel_de_chave()} ausente ou não configurada no .env "
            f"(provedor ativo: '{LLM_PROVIDER}'). Insira um token válido."
        )

    if LLM_PROVIDER == PROVIDER_GROQ:
        return _gerar_via_groq(system_prompt, user_prompt, max_tokens, temperature, chave)
    return _gerar_via_anthropic(system_prompt, user_prompt, max_tokens, temperature, chave)


# ======================================================================
# ACESSO A DADOS (helpers que encapsulam o ciclo de conexão)
# ======================================================================
def _fetch_all(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def _fetch_one(query: str, params: tuple = ()) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(query, params).fetchone()
    finally:
        conn.close()


def _execute(query: str, params: tuple = ()) -> None:
    conn = get_connection()
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def get_lead_by_id(lead_id: int) -> sqlite3.Row | None:
    """Retorna a linha completa de um lead pelo id."""
    return _fetch_one("SELECT * FROM leads WHERE id = ?;", (lead_id,))


def get_leads_by_status(status: str) -> list[sqlite3.Row]:
    """Retorna todos os leads em um determinado estágio do funil."""
    return _fetch_all("SELECT * FROM leads WHERE status_funil = ?;", (status,))


def update_lead_status(lead_id: int, novo_status: str) -> None:
    """Move o lead para outro estágio do funil (trigger atualiza updated_at)."""
    _execute(
        "UPDATE leads SET status_funil = ? WHERE id = ?;",
        (novo_status, lead_id),
    )


def get_unenriched_leads() -> list[sqlite3.Row]:
    """Busca leads cujo `cargo_real` ou `tamanho_empresa` esteja nulo/vazio."""
    return _fetch_all(
        """
        SELECT id, nome, cargo_declarado, empresa
        FROM leads
        WHERE cargo_real IS NULL OR TRIM(cargo_real) = ''
           OR tamanho_empresa IS NULL OR TRIM(tamanho_empresa) = '';
        """
    )


def get_enriched_inscritos() -> list[sqlite3.Row]:
    """Leads com status 'Inscrito' que já possuem dados de enriquecimento."""
    return _fetch_all(
        """
        SELECT * FROM leads
        WHERE status_funil = ?
          AND cargo_real IS NOT NULL AND TRIM(cargo_real) <> ''
          AND setor      IS NOT NULL AND TRIM(setor) <> '';
        """,
        (STATUS_INSCRITO,),
    )


def update_lead_enrichment(lead_id: int, enriquecimento: dict) -> None:
    """Atualiza a tabela `leads` com os dados enriquecidos pelo LLM."""
    linkedin = enriquecimento.get("linkedin_perfil") or None
    _execute(
        """
        UPDATE leads
        SET cargo_real = ?, setor = ?, tamanho_empresa = ?,
            sinais_interesse = ?, linkedin_perfil = COALESCE(?, linkedin_perfil)
        WHERE id = ?;
        """,
        (
            enriquecimento["cargo_real"],
            enriquecimento["setor"],
            enriquecimento["tamanho_empresa"],
            enriquecimento["sinais_interesse"],
            linkedin,
            lead_id,
        ),
    )


def log_interaction(
    lead_id: int,
    fase_funil: str,
    canal: str,
    tipo_mensagem: str,
    conteudo_enviado: str,
    resposta_lead: str | None = None,
) -> None:
    """Registra uma interação (mensagem enviada e eventual resposta)."""
    _execute(
        """
        INSERT INTO interaction_logs (
            lead_id, fase_funil, canal, tipo_mensagem, conteudo_enviado, resposta_lead
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (lead_id, fase_funil, canal, tipo_mensagem, conteudo_enviado, resposta_lead),
    )


def get_last_interaction(lead_id: int) -> sqlite3.Row | None:
    """Retorna a última interação registrada para um lead (ou None)."""
    return _fetch_one(
        "SELECT * FROM interaction_logs WHERE lead_id = ? ORDER BY id DESC LIMIT 1;",
        (lead_id,),
    )


# ======================================================================
# UTILITÁRIOS
# ======================================================================
def _print_titulo(texto: str) -> None:
    """Imprime um título de seção entre separadores."""
    linha = "=" * _SECTION_WIDTH
    print(linha)
    print(texto)
    print(linha)


def _extract_json(raw_text: str) -> dict:
    """Limpa cercas de código e isola/parseia o primeiro objeto JSON do texto."""
    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    if not cleaned.startswith("{"):
        inicio = cleaned.find("{")
        fim = cleaned.rfind("}")
        if inicio != -1 and fim != -1:
            cleaned = cleaned[inicio : fim + 1]

    return json.loads(cleaned)


def _parse_enrichment_json(raw_text: str) -> dict:
    """Valida o JSON de enriquecimento (Fase 2) com as chaves esperadas."""
    data = _extract_json(raw_text)
    chaves_obrigatorias = {"cargo_real", "setor", "tamanho_empresa", "sinais_interesse"}
    faltando = chaves_obrigatorias - data.keys()
    if faltando:
        raise ValueError(f"Resposta do LLM sem as chaves: {faltando}")
    resultado = {chave: data[chave] for chave in chaves_obrigatorias}
    if "linkedin_perfil" in data:
        resultado["linkedin_perfil"] = data["linkedin_perfil"]
    return resultado


# ======================================================================
# FASE 2 — ENRIQUECIMENTO
# ======================================================================
def enrich_lead_profile(nome: str, cargo_declarado: str, empresa: str) -> dict:
    """
    Deduz o perfil corporativo do lead via LLM a partir de (nome, cargo, empresa).

    Retorna um dict com: cargo_real, setor, tamanho_empresa, sinais_interesse.
    """
    system_prompt = (
        "Você é um agente de inteligência de mercado B2B especializado no "
        "mercado corporativo brasileiro.\n\n"
        f"CONTEXTO DA EMPRESA QUE VOCÊ APOIA:\n{VIGIL_CONTEXT}\n\n"
        "SUA TAREFA:\n"
        "A partir do nome, cargo declarado e empresa de um lead, deduza de "
        "forma REALISTA o perfil corporativo dele, considerando o mercado "
        "brasileiro atual e a proposta de valor da Vigil.AI. Deduza:\n"
        "- cargo_real: ajuste o cargo se o declarado for genérico. Ex.: se o "
        "lead declarou apenas 'TI', infira se ele provavelmente atua como "
        "'Gerente de Infraestrutura', 'CISO', 'Analista de Segurança', etc.\n"
        "- setor: o setor de atuação da empresa (Ex.: Tecnologia, Varejo, "
        "Financeiro, Saúde, Indústria, Educação).\n"
        "- tamanho_empresa: estimativa realista de porte/funcionários "
        "(Ex.: '+200 funcionários', '+500 funcionários', '+1000 funcionários').\n"
        "- sinais_interesse: prováveis dores de cibersegurança e conformidade "
        "dessa persona/empresa (Ex.: 'Preocupação com vazamento de dados de "
        "clientes no varejo e conformidade estrita com a LGPD').\n"
        "- linkedin_perfil: URL provável do perfil LinkedIn público deduzido "
        "a partir do nome e empresa (formato https://www.linkedin.com/in/...). "
        "Se não houver base razoável, use string vazia.\n\n"
        "REGRAS DE SAÍDA (OBRIGATÓRIAS):\n"
        "- Responda EXCLUSIVAMENTE com um objeto JSON válido, sem nenhum texto "
        "antes ou depois, sem markdown e sem cercas de código.\n"
        "- Use EXATAMENTE estas chaves: \"cargo_real\", \"setor\", "
        "\"tamanho_empresa\", \"sinais_interesse\", \"linkedin_perfil\".\n"
        "- Todos os valores devem ser strings em português."
    )

    user_prompt = (
        "Enriqueça o seguinte lead:\n"
        f"- Nome: {nome}\n"
        f"- Cargo declarado: {cargo_declarado or 'não informado'}\n"
        f"- Empresa: {empresa or 'não informada'}"
    )

    print(f"   🧠 Consultando o LLM ({modelo_ativo()}) sobre '{nome}' ({empresa})...")
    raw_text = _chat(system_prompt, user_prompt, ENRICHMENT_MAX_TOKENS, ENRICHMENT_TEMPERATURE)
    return _parse_enrichment_json(raw_text)


def run_enrichment_pipeline() -> None:
    """Orquestra o enriquecimento de todos os leads pendentes."""
    _print_titulo("🚀 FASE 2 — PIPELINE DE ENRIQUECIMENTO DE LEADS (Vigil.AI)")
    init_db()

    leads = get_unenriched_leads()
    if not leads:
        print("✅ Nenhum lead pendente de enriquecimento. Tudo em dia!")
        return

    total = len(leads)
    print(f"🔎 {total} lead(s) pendente(s) de enriquecimento encontrado(s).\n")

    sucessos = 0
    falhas = 0
    for indice, lead in enumerate(leads, start=1):
        print(f"[{indice}/{total}] 👤 Lead #{lead['id']} — {lead['nome']}")
        print(
            f"   ↳ Cargo declarado: {lead['cargo_declarado'] or '—'} | "
            f"Empresa: {lead['empresa'] or '—'}"
        )
        try:
            enriquecimento = enrich_lead_profile(
                nome=lead["nome"],
                cargo_declarado=lead["cargo_declarado"],
                empresa=lead["empresa"],
            )
            print("   📥 Dados deduzidos pelo LLM:")
            print(f"      • cargo_real .......: {enriquecimento['cargo_real']}")
            print(f"      • setor ............: {enriquecimento['setor']}")
            print(f"      • tamanho_empresa ..: {enriquecimento['tamanho_empresa']}")
            print(f"      • sinais_interesse .: {enriquecimento['sinais_interesse']}")
            if enriquecimento.get("linkedin_perfil"):
                print(f"      • linkedin_perfil ..: {enriquecimento['linkedin_perfil']}")
            update_lead_enrichment(lead["id"], enriquecimento)
            print("   💾 Banco atualizado com sucesso.\n")
            sucessos += 1
        except Exception as erro:
            print(f"   ❌ Falha ao enriquecer o lead #{lead['id']}: {erro}\n")
            falhas += 1

    _print_titulo(f"🏁 Enriquecimento concluído. Sucessos: {sucessos} | Falhas: {falhas}")


# ======================================================================
# GERAÇÃO DE MENSAGENS PERSONALIZADAS (compartilhada pelas Fases 3 e 4)
# ======================================================================
def _perfil_do_lead(lead: sqlite3.Row) -> str:
    """Monta o bloco de contexto do lead usado para personalizar a mensagem."""
    cargo = lead["cargo_real"] or lead["cargo_declarado"] or "Decisor"
    return (
        f"- Nome: {lead['nome']}\n"
        f"- Cargo: {cargo}\n"
        f"- Empresa: {lead['empresa'] or 'não informada'}\n"
        f"- Setor: {lead['setor'] or 'não informado'}\n"
        f"- Tamanho da empresa: {lead['tamanho_empresa'] or 'não informado'}\n"
        f"- Dores/sinais de interesse: {lead['sinais_interesse'] or 'não informado'}"
    )


def _segmento_do_lead(lead: sqlite3.Row) -> str:
    """
    Classifica o lead em SEGMENTO_ORGANICO (novo, vindo da landing page) ou
    SEGMENTO_REMARKETING (base de edições anteriores da Vigil.AI).

    Decisão de engenharia: a segmentação usa o campo EXPLÍCITO `origem`, que é
    o sinal correto (fonte do lead). O domínio do e-mail é apenas um fallback
    de compatibilidade para registros antigos sem `origem` definida.
    """
    try:
        origem = (lead["origem"] or "").strip()
    except (KeyError, IndexError):
        origem = ""

    if origem:
        return SEGMENTO_ORGANICO if origem == ORIGEM_ORGANICA else SEGMENTO_REMARKETING

    email = (lead["email"] or "").lower()
    if email.endswith("@" + ORGANIC_LEAD_DOMAIN):
        return SEGMENTO_ORGANICO
    return SEGMENTO_REMARKETING


def _instrucao_de_canal(canal: str) -> str:
    if canal == CANAL_WHATSAPP:
        return (
            "Canal: WhatsApp. Escreva uma mensagem CURTA (2 a 4 linhas), tom "
            "profissional e cordial, direta ao ponto, com no máximo 1 emoji "
            "discreto. Deixe \"assunto\" como string vazia."
        )
    return (
        "Canal: E-mail. Escreva um e-mail conciso e executivo (até ~120 "
        "palavras), com um \"assunto\" curto e atrativo e um \"corpo\" "
        "estruturado. Sem emojis em excesso."
    )


def _instrucao_de_segmento(segmento: str) -> str:
    if segmento == SEGMENTO_REMARKETING:
        return (
            "SEGMENTO: Remarketing. Este lead JÁ teve contato com a Vigil.AI em "
            "edições anteriores. Comece relembrando, de forma calorosa, esse "
            "relacionamento passado (ex.: 'que bom te ver de volta')."
        )
    return (
        "SEGMENTO: Orgânico (LP). Lead NOVO, captado pela landing page do "
        "Vigil Summit. Trate como primeiro contato, sem presumir histórico."
    )


def _instrucao_de_compromisso(step: dict) -> str:
    if not step.get("commitment_trigger"):
        return ""
    return (
        "\n\nGATILHO DE COMPROMISSO (OBRIGATÓRIO): direcione a mensagem a um "
        "decisor de segurança (CISO/CTO/Diretor de TI) e finalize induzindo-o "
        f"a responder com o texto EXATO \"{CONFIRMATION_PHRASE}\" para garantir "
        f"a vaga exclusiva (apenas {EVENT_TOTAL_SEATS} lugares). Deixe explícito "
        "que responder com essa frase confirma a presença."
    )


def _instrucao_se_nao_confirmou(lead: sqlite3.Row, step: dict) -> str:
    """Tom mais assertivo para quem ainda está 'Inscrito' (não confirmou)."""
    if lead["status_funil"] != STATUS_INSCRITO:
        return ""
    if step.get("tipo_mensagem") not in ("Pedido_Confirmacao", "Gatilho_Escassez"):
        return ""
    return (
        "\n\nATENÇÃO: este lead AINDA NÃO confirmou presença. "
        "Use tom mais assertivo e urgente, reforçando que precisa garantir a vaga agora."
    )


def _instrucao_sem_resposta_anterior(lead_id: int) -> str:
    """Reforço quando a última mensagem enviada não teve resposta do lead."""
    ultima = get_last_interaction(lead_id)
    if ultima is None:
        return ""
    resposta = ultima["resposta_lead"]
    if resposta is not None and str(resposta).strip():
        return ""
    return (
        "\n\nATENÇÃO: o lead NÃO respondeu à mensagem anterior. "
        "Relembre o valor do evento de forma mais direta e inclua um CTA claro "
        "(ex.: pedir confirmação ou resposta objetiva)."
    )


def generate_personalized_message(lead: sqlite3.Row, step: dict) -> dict:
    """
    Gera uma mensagem personalizada via LLM para uma etapa da régua.

    `step` deve conter: canal, tipo_mensagem, objetivo
    (e, opcionalmente, commitment_trigger).
    Retorna {"assunto": str, "mensagem": str} (assunto vazio no WhatsApp).
    """
    canal = step["canal"]

    system_prompt = (
        "Você é um agente de SDR/Marketing de eventos B2B da Vigil.AI, "
        "especialista em copywriting de alta conversão para executivos de "
        "segurança e TI no Brasil.\n\n"
        f"SOBRE A EMPRESA:\n{VIGIL_CONTEXT}\n\n"
        f"SOBRE O EVENTO:\n{EVENT_CONTEXT}\n\n"
        "DIRETRIZES:\n"
        "- Personalize SEMPRE usando o cargo, setor e principalmente as dores "
        "(sinais de interesse) do lead. Nada de mensagem genérica.\n"
        "- Trate o lead pelo primeiro nome.\n"
        "- Seja orientado a conversão: toda mensagem tem um CTA claro.\n"
        f"- {_instrucao_de_canal(canal)}\n\n"
        "REGRAS DE SAÍDA (OBRIGATÓRIAS):\n"
        "- Responda EXCLUSIVAMENTE com um objeto JSON válido, sem texto extra, "
        "sem markdown e sem cercas de código.\n"
        "- Use EXATAMENTE estas chaves: \"assunto\", \"mensagem\".\n"
        "- Os valores devem ser strings em português."
    )

    user_prompt = (
        f"PERFIL DO LEAD:\n{_perfil_do_lead(lead)}\n\n"
        f"{_instrucao_de_segmento(_segmento_do_lead(lead))}\n\n"
        f"OBJETIVO DESTA MENSAGEM:\n{step['objetivo']}{_instrucao_de_compromisso(step)}"
        f"{_instrucao_se_nao_confirmou(lead, step)}"
        f"{_instrucao_sem_resposta_anterior(lead['id'])}\n\n"
        "Gere a mensagem agora."
    )

    print(f"   ✍️  Gerando mensagem ({step['tipo_mensagem']} via {canal})...")
    raw_text = _chat(system_prompt, user_prompt, MESSAGE_MAX_TOKENS, MESSAGE_TEMPERATURE)
    data = _extract_json(raw_text)
    return {
        "assunto": data.get("assunto", "") or "",
        "mensagem": (data.get("mensagem", "") or "").strip(),
    }


def _conteudo_para_log(mensagem_gerada: dict) -> str:
    """Monta o texto final a ser persistido em conteudo_enviado."""
    assunto = mensagem_gerada.get("assunto", "").strip()
    mensagem = mensagem_gerada.get("mensagem", "").strip()
    if assunto:
        return f"Assunto: {assunto}\n\n{mensagem}"
    return mensagem


def _processar_step(lead: sqlite3.Row, step: dict, fase_funil: str) -> None:
    """Gera, exibe e registra uma etapa de régua para um lead."""
    mensagem_gerada = generate_personalized_message(lead, step)
    conteudo = _conteudo_para_log(mensagem_gerada)

    print(f"   📨 [{step['canal']}] {step['tipo_mensagem']}")
    if mensagem_gerada["assunto"]:
        print(f"      Assunto: {mensagem_gerada['assunto']}")
    for linha in mensagem_gerada["mensagem"].splitlines():
        print(f"      {linha}")

    log_interaction(
        lead_id=lead["id"],
        fase_funil=fase_funil,
        canal=step["canal"],
        tipo_mensagem=step["tipo_mensagem"],
        conteudo_enviado=conteudo,
    )
    print("   💾 Interação registrada em interaction_logs.\n")


# ======================================================================
# FASE 3 — ENGAJAMENTO PRÉ-EVENTO (RÉGUA DE CONFIRMAÇÃO)
# ======================================================================
# Regras de negócio para reduzir no-show (meta: presença > 70%):
#   D-14: boas-vindas + ancoragem de valor (e-mail rico)
#   D-7 : pedido ativo de confirmação + regra de acompanhante (WhatsApp)
#   D-3 : antecipação de conteúdo + gatilho de escassez por proximidade
#   D-1 : lembrete logístico (reduz no-show de última hora)
PRE_EVENT_STEPS = [
    {
        "dias_antes": 14,
        "canal": CANAL_EMAIL,
        "tipo_mensagem": "Boas_Vindas",
        "objetivo": (
            "Dar as boas-vindas confirmando a inscrição no Vigil Summit. "
            "Ancorar o valor de comparecer conectando explicitamente as dores "
            "do lead às palestras e demos. Pedir que ele salve a data na agenda."
        ),
    },
    {
        "dias_antes": 7,
        "canal": CANAL_WHATSAPP,
        "tipo_mensagem": "Pedido_Confirmacao",
        "commitment_trigger": True,
        "objetivo": (
            "Pedir a CONFIRMAÇÃO ATIVA de presença. Aplicar a regra de "
            "acompanhante: convidar o lead a trazer um par da própria empresa "
            "(ex.: o CTO ou um diretor de risco), reforçando exclusividade."
        ),
    },
    {
        "dias_antes": 3,
        "canal": CANAL_WHATSAPP,
        "tipo_mensagem": "Gatilho_Escassez",
        "objetivo": (
            "Criar antecipação revelando 1 atração de destaque (palestra/demo) "
            "alinhada às dores do lead e aplicar GATILHO DE ESCASSEZ pela "
            "proximidade da data (poucas vagas, lista de espera). Caso ele ainda "
            "não tenha confirmado, reforçar que precisa garantir a vaga agora."
        ),
    },
    {
        "dias_antes": 1,
        "canal": CANAL_WHATSAPP,
        "tipo_mensagem": "Lembrete_Logistico",
        "objetivo": (
            "Lembrete logístico de véspera: horário, local e o que esperar do "
            "dia. Tom acolhedor, gerar empolgação para reduzir no-show de última "
            "hora. Encerrar com um 'te vejo amanhã'."
        ),
    },
]

# Passo único de confirmação (copy de neurociência) usado por run_pre_event_engagement().
CONFIRMATION_STEP = {
    "canal": CANAL_WHATSAPP,
    "tipo_mensagem": "Confirmacao_Neurociencia",
    "commitment_trigger": True,
    "objetivo": (
        "Mensagem de confirmação de presença para um decisor de segurança. "
        "Conectar UMA dor concreta do lead ao que ele verá no Vigil Summit "
        "(palestra/demo) e reforçar a exclusividade do evento."
    ),
}


def _step_mais_proximo_da_data(steps: list[dict]) -> dict:
    """Escolhe a etapa cujo 'dias_antes' está mais próximo de hoje."""
    restantes = abs(dias_para_o_evento())
    return min(steps, key=lambda step: abs(step["dias_antes"] - restantes))


def run_pre_event_sequence(
    lead_id: int | None = None,
    simular_sequencia_completa: bool = False,
) -> None:
    """
    Fase 3: conduz a régua de confirmação pré-evento.

    - simular_sequencia_completa=True dispara todas as etapas (ideal para demo).
    - Caso contrário, dispara apenas a etapa adequada à proximidade da data.
    """
    _print_titulo("📣 FASE 3 — RÉGUA DE ENGAJAMENTO PRÉ-EVENTO")
    print(f"   Evento em {get_event_date().isoformat()} "
          f"({dias_para_o_evento()} dia(s) restante(s))\n")
    init_db()

    if lead_id is not None:
        alvo = get_lead_by_id(lead_id)
        leads = [alvo] if alvo else []
    else:
        # Pré-evento atinge quem ainda não compareceu (Inscrito/Confirmado).
        leads = get_leads_by_status(STATUS_INSCRITO) + get_leads_by_status(STATUS_CONFIRMADO)

    if not leads:
        print("ℹ️  Nenhum lead elegível para a régua pré-evento.")
        return

    steps = PRE_EVENT_STEPS if simular_sequencia_completa else [_step_mais_proximo_da_data(PRE_EVENT_STEPS)]
    for lead in leads:
        print(f"👤 Lead #{lead['id']} — {lead['nome']} ({lead['empresa']}) "
              f"| status: {lead['status_funil']}")
        for step in steps:
            try:
                _processar_step(lead, step, FASE_PRE_EVENTO)
            except Exception as erro:
                print(f"   ❌ Falha na etapa {step['tipo_mensagem']}: {erro}\n")


def run_pre_event_engagement() -> None:
    """
    Fase 3 (confirmação): para cada lead 'Inscrito' já enriquecido, gera um
    copy de WhatsApp personalizado com gatilho de compromisso e o registra.
    """
    _print_titulo("🧲 FASE 3 — ENGAJAMENTO DE CONFIRMAÇÃO (Neurociência)")
    init_db()

    leads = get_enriched_inscritos()
    if not leads:
        print("ℹ️  Nenhum lead 'Inscrito' enriquecido para engajar.")
        return

    print(f"🔎 {len(leads)} lead(s) elegível(is) para confirmação.\n")
    for lead in leads:
        print(f"👤 Lead #{lead['id']} — {lead['nome']} ({lead['empresa']}) "
              f"| segmento: {_segmento_do_lead(lead)}")
        try:
            _processar_step(lead, CONFIRMATION_STEP, FASE_PRE_EVENTO)
        except Exception as erro:
            print(f"   ❌ Falha ao gerar a confirmação: {erro}\n")


def _registrar_resposta(lead_id: int, resposta: str) -> None:
    """Anexa a resposta à última interação do lead, ou cria um registro avulso."""
    ultima = get_last_interaction(lead_id)
    if ultima is not None:
        _execute(
            "UPDATE interaction_logs SET resposta_lead = ? WHERE id = ?;",
            (resposta, ultima["id"]),
        )
    else:
        log_interaction(
            lead_id=lead_id,
            fase_funil=FASE_PRE_EVENTO,
            canal=CANAL_WHATSAPP,
            tipo_mensagem="Resposta_Avulsa",
            conteudo_enviado="",
            resposta_lead=resposta,
        )


def _confirma_presenca(resposta: str) -> bool:
    """Confirma presença por frase exata ou classificação de intenção via LLM."""
    if resposta.strip().lower() == CONFIRMATION_PHRASE.lower():
        return True
    if not llm_configurado():
        return False
    try:
        system_prompt = (
            "Você classifica respostas de leads sobre confirmação de presença em evento. "
            "Responda APENAS JSON: {\"confirma\": true} se a mensagem indica que a pessoa "
            "vai comparecer; {\"confirma\": false} caso contrário."
        )
        user_prompt = f"Mensagem do lead: \"{resposta.strip()}\""
        raw = _chat(system_prompt, user_prompt, 64, 0.0)
        data = _extract_json(raw)
        return bool(data.get("confirma"))
    except Exception:
        return False


def receive_lead_response(lead_id: int, resposta: str) -> None:
    """
    Registra a resposta de um lead (simulada) e, se for a frase de compromisso,
    promove o lead de 'Inscrito' para 'Confirmado'.
    """
    lead = get_lead_by_id(lead_id)
    if lead is None:
        print(f"⚠️  Lead #{lead_id} não encontrado.")
        return

    _registrar_resposta(lead_id, resposta)
    print(f"📩 Lead #{lead_id} ({lead['nome']}) respondeu: \"{resposta}\"")

    if _confirma_presenca(resposta):
        update_lead_status(lead_id, STATUS_CONFIRMADO)
        print("   ✅ Gatilho de compromisso acionado! "
              f"Status: '{STATUS_INSCRITO}' → '{STATUS_CONFIRMADO}'.\n")
    else:
        print("   ↪️  Resposta não confirma presença. Status mantido como "
              f"'{lead['status_funil']}'.\n")


def run_engagement_with_simulated_responses() -> None:
    """
    Fase 3 ponta a ponta: dispara a confirmação e simula as respostas no
    WhatsApp (a maioria confirma; 1 não, para exercitar o no-show).
    """
    run_pre_event_engagement()

    # Captura ANTES de qualquer mudança de status (todos ainda 'Inscrito').
    inscritos = get_enriched_inscritos()
    if not inscritos:
        return

    print("🤖 Simulando respostas dos leads no WhatsApp...\n")
    for indice, lead in enumerate(inscritos):
        primeiro_lead_nao_confirma = indice == 0 and len(inscritos) > 1
        resposta = "Preciso verificar minha agenda" if primeiro_lead_nao_confirma else CONFIRMATION_PHRASE
        receive_lead_response(lead["id"], resposta)


# ======================================================================
# FASE 4 — PÓS-EVENTO (RÉGUA DE FOLLOW-UP COMERCIAL)
# ======================================================================
# Objetivo: converter presença em reunião comercial agendada.
#   D+1: agradecimento + recap personalizado do que viu (e-mail)
#   D+3: proposta concreta de reunião com horários (WhatsApp)
#   D+7: última chamada / oferta de valor para quem não respondeu (e-mail)
POST_EVENT_STEPS = [
    {
        "dias_depois": 1,
        "canal": CANAL_EMAIL,
        "tipo_mensagem": "Agradecimento_Recap",
        "objetivo": (
            "Agradecer a presença no Vigil Summit e fazer um recap personalizado "
            "conectando a demo da plataforma às dores específicas do lead. "
            "Encerrar com um CTA suave: sugerir uma conversa de 30 minutos."
        ),
    },
    {
        "dias_depois": 3,
        "canal": CANAL_WHATSAPP,
        "tipo_mensagem": "Convite_Reuniao",
        "objetivo": (
            "Propor de forma concreta uma reunião de demonstração 1:1, "
            "oferecendo 2 opções de horário. Reforçar o ROI ligado às dores do "
            "lead (ex.: reduzir risco de vazamento, acelerar conformidade LGPD)."
        ),
    },
    {
        "dias_depois": 7,
        "canal": CANAL_EMAIL,
        "tipo_mensagem": "Ultima_Chamada",
        "objetivo": (
            "Última chamada para quem não respondeu: oferecer um material de "
            "valor (ex.: relatório de postura/benchmark do setor dele) como "
            "incentivo e fazer um CTA final e educado para agendar a reunião."
        ),
    },
]

# Régua separada para quem confirmou mas NÃO compareceu (no-show).
NO_SHOW_STEP = {
    "dias_depois": 1,
    "canal": CANAL_EMAIL,
    "tipo_mensagem": "Reengajamento_NoShow",
    "objetivo": (
        "O lead confirmou mas não compareceu ao evento. Demonstrar empatia "
        "('sentimos sua falta'), oferecer a gravação das palestras e uma demo "
        "1:1 em data alternativa, conectando ao interesse dele em segurança."
    ),
}


def _processar_steps_do_lead(lead: sqlite3.Row, steps: list[dict], rotulo: str) -> None:
    """Executa uma lista de etapas pós-evento para um lead, com tratamento de erro."""
    print(f"👤 [{rotulo}] Lead #{lead['id']} — {lead['nome']} ({lead['empresa']})")
    for step in steps:
        try:
            _processar_step(lead, step, FASE_POS_EVENTO)
        except Exception as erro:
            print(f"   ❌ Falha na etapa {step['tipo_mensagem']}: {erro}\n")


def run_post_event_sequence(
    lead_id: int | None = None,
    simular_sequencia_completa: bool = False,
) -> None:
    """
    Fase 4: conduz a régua de follow-up pós-evento.

    - Leads 'Presente' entram na régua comercial (agendar reunião).
    - Leads 'Confirmado' (não compareceram) entram na régua de no-show.
    """
    _print_titulo("📈 FASE 4 — RÉGUA DE FOLLOW-UP PÓS-EVENTO")
    init_db()

    if lead_id is not None:
        alvo = get_lead_by_id(lead_id)
        presentes = [alvo] if alvo and alvo["status_funil"] == STATUS_PRESENTE else []
        no_shows = [alvo] if alvo and alvo["status_funil"] == STATUS_CONFIRMADO else []
    else:
        presentes = get_leads_by_status(STATUS_PRESENTE)
        no_shows = get_leads_by_status(STATUS_CONFIRMADO)

    if not presentes and not no_shows:
        print("ℹ️  Nenhum lead elegível para a régua pós-evento.")
        return

    steps_comerciais = POST_EVENT_STEPS if simular_sequencia_completa else POST_EVENT_STEPS[:1]
    for lead in presentes:
        _processar_steps_do_lead(lead, steps_comerciais, "PRESENTE")
    for lead in no_shows:
        _processar_steps_do_lead(lead, [NO_SHOW_STEP], "NO-SHOW")


# ======================================================================
# ORQUESTRADOR DE DEMONSTRAÇÃO PONTA A PONTA
# ======================================================================
def _simular_dia_do_evento() -> None:
    """Entre os confirmados, marca presença e mantém 1 como no-show."""
    print("🎬 Simulando o dia do evento (presenças x no-show)...\n")
    confirmados = get_leads_by_status(STATUS_CONFIRMADO)
    for indice, lead in enumerate(confirmados):
        manter_como_no_show = indice == 0 and len(confirmados) > 1
        if manter_como_no_show:
            print(f"   🚪 Lead #{lead['id']} ({lead['nome']}) confirmou mas "
                  f"NÃO compareceu (no-show).")
        else:
            update_lead_status(lead["id"], STATUS_PRESENTE)
            print(f"   ✅ Lead #{lead['id']} ({lead['nome']}) compareceu.")
    print()


def run_full_funnel_demo() -> None:
    """
    Demonstra o funil completo numa única execução (Fases 2 → 3 → 4),
    simulando as transições de status entre as etapas.
    """
    print("\n" + "#" * _SECTION_WIDTH)
    print("# DEMONSTRAÇÃO PONTA A PONTA — VIGIL SUMMIT AGENT")
    print("#" * _SECTION_WIDTH + "\n")

    init_db()
    run_enrichment_pipeline()
    run_engagement_with_simulated_responses()
    _simular_dia_do_evento()
    run_post_event_sequence(simular_sequencia_completa=True)

    print("\n" + "#" * _SECTION_WIDTH)
    print("# DEMONSTRAÇÃO CONCLUÍDA — verifique a tabela interaction_logs")
    print("#" * _SECTION_WIDTH)


# ======================================================================
# CLI
# ======================================================================
COMANDOS = {
    "enrich": run_enrichment_pipeline,
    "engage": run_engagement_with_simulated_responses,
    "pre": lambda: run_pre_event_sequence(simular_sequencia_completa=True),
    "post": lambda: run_post_event_sequence(simular_sequencia_completa=True),
    "demo": run_full_funnel_demo,
}


def main() -> None:
    comando = sys.argv[1] if len(sys.argv) > 1 else "demo"
    acao = COMANDOS.get(comando)
    if acao is None:
        print(f"Comando desconhecido: '{comando}'.")
        print(f"Use: {' | '.join(COMANDOS)}")
        sys.exit(1)
    acao()


if __name__ == "__main__":
    main()
