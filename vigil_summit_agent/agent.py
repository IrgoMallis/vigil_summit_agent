"""
agent.py
--------
Lógica do Agente Claude para o "Case AI Engineer - Vigil Summit" (Pareto).

Fases implementadas:
    - Fase 2: Enriquecimento / qualificação de leads
    - Fase 3: Engajamento pré-evento (régua de confirmação anti no-show)
    - Fase 4: Follow-up pós-evento (régua comercial até a reunião agendada)

Decisões de produto deste protótipo:
    - ENVIO SIMULADO: o Claude gera o conteúdo da mensagem e nós a registramos
      na tabela `interaction_logs`. A arquitetura isola a geração do "envio",
      então plugar WhatsApp (ex.: Twilio/Meta) ou e-mail (SMTP) depois é trivial.
    - CANAL: combinação WhatsApp (lembretes curtos/alta abertura) + E-mail
      (conteúdo rico/credibilidade executiva).
    - DATA DO EVENTO: configurável via .env (VIGIL_EVENT_DATE=YYYY-MM-DD);
      por padrão, 14 dias a partir de hoje.

Uso via CLI:
    py -X utf8 agent.py enrich   # Fase 2 - enriquecimento
    py -X utf8 agent.py engage   # Fase 3 - confirmação (neurociência) + respostas simuladas
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

# ----------------------------------------------------------------------
# Provedor de LLM (configurável via .env)
# ----------------------------------------------------------------------
# LLM_PROVIDER = "anthropic" (padrão, preferência do case) ou "groq" (gratuito).
# O case dá preferência ao ecossistema Anthropic; o Groq fica disponível para
# desenvolvimento/teste sem custo. A lógica do agente independe do provedor.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()

# Modelos (sobrescritíveis via .env).
CLAUDE_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Contexto de negócio da Vigil.AI usado em todos os System Prompts.
VIGIL_CONTEXT = (
    "A Vigil.AI é uma empresa de cibersegurança que vende uma plataforma SaaS "
    "de monitoramento contínuo de postura de segurança cibernética para médias "
    "e grandes empresas (acima de 200 funcionários). A plataforma entrega "
    "dashboards em tempo real, alertas de vulnerabilidades, relatórios de "
    "conformidade (ISO 27001, LGPD, SOC 2) e recomendações automatizadas de "
    "remediação, com uma camada de IA que prioriza riscos e antecipa ameaças."
)

# Descrição do evento usada nas réguas de comunicação.
EVENT_CONTEXT = (
    "O evento é o 'Vigil Summit — Segurança para a Era da IA': um encontro "
    "corporativo presencial e exclusivo, com apenas 120 vagas, voltado a CISOs, "
    "CTOs, diretores de TI e gestores de risco. Há palestras, demos ao vivo da "
    "plataforma Vigil.AI e networking entre líderes de segurança."
)

# Frase exata do gatilho de compromisso (neurociência: commitment & consistency).
CONFIRMATION_PHRASE = "Eu irei ao evento"

# Domínio tratado como lead NOVO orgânico (captado pela landing page).
# Os demais domínios são tratados como base de Remarketing (edições anteriores).
ORGANIC_LEAD_DOMAIN = "pareto.io"


# ----------------------------------------------------------------------
# Configuração de data do evento
# ----------------------------------------------------------------------
def get_event_date() -> date:
    """Data do Vigil Summit: lê VIGIL_EVENT_DATE do .env ou usa hoje + 14 dias."""
    raw = os.getenv("VIGIL_EVENT_DATE", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print(f"⚠️  VIGIL_EVENT_DATE inválida ('{raw}'). Usando fallback.")
    return date.today() + timedelta(days=14)


def dias_para_o_evento() -> int:
    """Quantos dias faltam para o evento (negativo se já ocorreu)."""
    return (get_event_date() - date.today()).days


# ----------------------------------------------------------------------
# Camada de LLM (multi-provedor: Anthropic | Groq)
# ----------------------------------------------------------------------
def modelo_ativo() -> str:
    """Nome do modelo em uso, conforme o provedor configurado."""
    return GROQ_MODEL if LLM_PROVIDER == "groq" else CLAUDE_MODEL


def _api_key_do_provedor() -> str:
    var = "GROQ_API_KEY" if LLM_PROVIDER == "groq" else "ANTHROPIC_API_KEY"
    return os.getenv(var, "").strip()


def llm_configurado() -> bool:
    """True se a API key do provedor ativo estiver configurada no .env."""
    chave = _api_key_do_provedor()
    return bool(chave) and chave != "seu_token_aqui"


def _chat(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1024,
    temperature: float = 0.5,
) -> str:
    """
    Envia uma conversa (system + user) ao provedor ativo e retorna o texto.

    Abstrai Anthropic (SDK nativo) e Groq (endpoint compatível com OpenAI),
    permitindo trocar de modelo apenas mudando LLM_PROVIDER no .env.
    """
    chave = _api_key_do_provedor()
    if not chave or chave == "seu_token_aqui":
        var = "GROQ_API_KEY" if LLM_PROVIDER == "groq" else "ANTHROPIC_API_KEY"
        raise RuntimeError(
            f"{var} ausente ou não configurada no .env. "
            f"Provedor ativo: '{LLM_PROVIDER}'. Edite o .env e insira um token válido."
        )

    if LLM_PROVIDER == "groq":
        # Groq é compatível com a API da OpenAI.
        from openai import OpenAI

        client = OpenAI(api_key=chave, base_url=GROQ_BASE_URL)
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

    # Provedor padrão: Anthropic (Claude).
    client = Anthropic(api_key=chave)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


# ----------------------------------------------------------------------
# Helpers de banco de dados
# ----------------------------------------------------------------------
def get_lead_by_id(lead_id: int) -> sqlite3.Row | None:
    """Retorna a linha completa de um lead pelo id."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads WHERE id = ?;", (lead_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def get_leads_by_status(status: str) -> list[sqlite3.Row]:
    """Retorna todos os leads em um determinado estágio do funil."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads WHERE status_funil = ?;", (status,))
        return cursor.fetchall()
    finally:
        conn.close()


def update_lead_status(lead_id: int, novo_status: str) -> None:
    """Move o lead para outro estágio do funil (trigger atualiza updated_at)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE leads SET status_funil = ? WHERE id = ?;",
            (novo_status, lead_id),
        )
        conn.commit()
    finally:
        conn.close()


def log_interaction(
    lead_id: int,
    fase_funil: str,
    canal: str,
    tipo_mensagem: str,
    conteudo_enviado: str,
    resposta_lead: str | None = None,
) -> None:
    """Registra uma interação na tabela `interaction_logs`."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO interaction_logs (
                lead_id, fase_funil, canal, tipo_mensagem,
                conteudo_enviado, resposta_lead
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (lead_id, fase_funil, canal, tipo_mensagem, conteudo_enviado, resposta_lead),
        )
        conn.commit()
    finally:
        conn.close()


def get_last_interaction(lead_id: int) -> sqlite3.Row | None:
    """Retorna a última interação registrada para um lead (ou None)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM interaction_logs
            WHERE lead_id = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (lead_id,),
        )
        return cursor.fetchone()
    finally:
        conn.close()


# ----------------------------------------------------------------------
# Parsing de JSON do Claude
# ----------------------------------------------------------------------
def _extract_json(raw_text: str) -> dict:
    """Limpa cercas de código e isola/parseia o primeiro objeto JSON do texto."""
    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]

    return json.loads(cleaned)


def _parse_claude_json(raw_text: str) -> dict:
    """Valida o JSON de enriquecimento (Fase 2) com as 4 chaves esperadas."""
    data = _extract_json(raw_text)
    expected_keys = {"cargo_real", "setor", "tamanho_empresa", "sinais_interesse"}
    missing = expected_keys - data.keys()
    if missing:
        raise ValueError(f"Resposta do Claude sem as chaves: {missing}")
    return {key: data[key] for key in expected_keys}


# ======================================================================
# FASE 2 — ENRIQUECIMENTO
# ======================================================================
def get_unenriched_leads() -> list[sqlite3.Row]:
    """Busca leads cujo `cargo_real` ou `tamanho_empresa` esteja nulo/vazio."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, nome, cargo_declarado, empresa
            FROM leads
            WHERE cargo_real IS NULL OR TRIM(cargo_real) = ''
               OR tamanho_empresa IS NULL OR TRIM(tamanho_empresa) = '';
            """
        )
        return cursor.fetchall()
    finally:
        conn.close()


def enrich_lead_with_claude(nome: str, cargo_declarado: str, empresa: str) -> dict:
    """
    Envia (nome, cargo_declarado, empresa) para o Claude e retorna um dict
    com as chaves: cargo_real, setor, tamanho_empresa, sinais_interesse.
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
        "clientes no varejo e conformidade estrita com a LGPD').\n\n"
        "REGRAS DE SAÍDA (OBRIGATÓRIAS):\n"
        "- Responda EXCLUSIVAMENTE com um objeto JSON válido, sem nenhum texto "
        "antes ou depois, sem markdown e sem cercas de código.\n"
        "- Use EXATAMENTE estas chaves: \"cargo_real\", \"setor\", "
        "\"tamanho_empresa\", \"sinais_interesse\".\n"
        "- Todos os valores devem ser strings em português."
    )

    user_prompt = (
        "Enriqueça o seguinte lead:\n"
        f"- Nome: {nome}\n"
        f"- Cargo declarado: {cargo_declarado or 'não informado'}\n"
        f"- Empresa: {empresa or 'não informada'}"
    )

    print(f"   🧠 Consultando o LLM ({modelo_ativo()}) sobre '{nome}' ({empresa})...")

    raw_text = _chat(system_prompt, user_prompt, max_tokens=1024, temperature=0.4)
    return _parse_claude_json(raw_text)


def update_lead_enrichment(lead_id: int, data_json: dict) -> None:
    """Atualiza a tabela `leads` com os dados enriquecidos pelo Claude."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE leads
            SET cargo_real = ?,
                setor = ?,
                tamanho_empresa = ?,
                sinais_interesse = ?
            WHERE id = ?;
            """,
            (
                data_json["cargo_real"],
                data_json["setor"],
                data_json["tamanho_empresa"],
                data_json["sinais_interesse"],
                lead_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def run_enrichment_pipeline() -> None:
    """Orquestra o enriquecimento de todos os leads pendentes."""
    print("=" * 64)
    print("🚀 FASE 2 — PIPELINE DE ENRIQUECIMENTO DE LEADS (Vigil.AI)")
    print("=" * 64)

    init_db()

    leads = get_unenriched_leads()
    total = len(leads)

    if total == 0:
        print("✅ Nenhum lead pendente de enriquecimento. Tudo em dia!")
        return

    print(f"🔎 {total} lead(s) pendente(s) de enriquecimento encontrado(s).\n")

    sucessos, falhas = 0, 0
    for indice, lead in enumerate(leads, start=1):
        print(f"[{indice}/{total}] 👤 Lead #{lead['id']} — {lead['nome']}")
        print(
            f"   ↳ Cargo declarado: {lead['cargo_declarado'] or '—'} | "
            f"Empresa: {lead['empresa'] or '—'}"
        )

        try:
            enriched = enrich_lead_with_claude(
                nome=lead["nome"],
                cargo_declarado=lead["cargo_declarado"],
                empresa=lead["empresa"],
            )

            print("   📥 Dados deduzidos pelo Claude:")
            print(f"      • cargo_real .......: {enriched['cargo_real']}")
            print(f"      • setor ............: {enriched['setor']}")
            print(f"      • tamanho_empresa ..: {enriched['tamanho_empresa']}")
            print(f"      • sinais_interesse .: {enriched['sinais_interesse']}")

            update_lead_enrichment(lead["id"], enriched)
            print("   💾 Banco atualizado com sucesso.\n")
            sucessos += 1

        except Exception as erro:
            print(f"   ❌ Falha ao enriquecer o lead #{lead['id']}: {erro}\n")
            falhas += 1

    print("=" * 64)
    print(f"🏁 Enriquecimento concluído. Sucessos: {sucessos} | Falhas: {falhas}")
    print("=" * 64)


# ======================================================================
# GERADOR DE MENSAGENS PERSONALIZADAS (compartilhado pelas Fases 3 e 4)
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
    Classifica o lead em 'Organico_LP' (novo, vindo da landing page) ou
    'Remarketing' (base de edições anteriores da Vigil.AI).

    Decisão de engenharia: a segmentação usa o campo EXPLÍCITO `origem`, que é
    o sinal correto (fonte do lead). O domínio do e-mail é apenas um fallback
    de compatibilidade para registros antigos sem `origem` definida.
    """
    try:
        origem = (lead["origem"] or "").strip()
    except (KeyError, IndexError):
        origem = ""

    if origem:
        return "Organico_LP" if origem == "LP_Organico" else "Remarketing"

    # Fallback legado (registros sem origem): heurística por domínio.
    email = (lead["email"] or "").lower()
    return "Organico_LP" if email.endswith("@" + ORGANIC_LEAD_DOMAIN) else "Remarketing"


def generate_personalized_message(lead: sqlite3.Row, step: dict) -> dict:
    """
    Gera uma mensagem personalizada via Claude para uma etapa da régua.

    `step` deve conter: canal, tipo_mensagem, objetivo.
    Retorna dict {"assunto": str, "mensagem": str} (assunto vazio no WhatsApp).
    """
    canal = step["canal"]

    if canal == "WhatsApp":
        regras_canal = (
            "Canal: WhatsApp. Escreva uma mensagem CURTA (2 a 4 linhas), tom "
            "profissional e cordial, direta ao ponto, com no máximo 1 emoji "
            "discreto. Deixe \"assunto\" como string vazia."
        )
    else:
        regras_canal = (
            "Canal: E-mail. Escreva um e-mail conciso e executivo (até ~120 "
            "palavras), com um \"assunto\" curto e atrativo e um \"corpo\" "
            "estruturado. Sem emojis em excesso."
        )

    # Segmentação: muda o enquadramento do primeiro contato.
    segmento = _segmento_do_lead(lead)
    if segmento == "Remarketing":
        contexto_segmento = (
            "SEGMENTO: Remarketing. Este lead JÁ teve contato com a Vigil.AI em "
            "edições anteriores. Comece relembrando, de forma calorosa, esse "
            "relacionamento passado (ex.: 'que bom te ver de volta')."
        )
    else:
        contexto_segmento = (
            "SEGMENTO: Orgânico (LP). Lead NOVO, captado pela landing page do "
            "Vigil Summit. Trate como primeiro contato, sem presumir histórico."
        )

    # Gatilho de compromisso (neurociência): CTA com frase exata.
    instrucao_compromisso = ""
    if step.get("commitment_trigger"):
        instrucao_compromisso = (
            "\n\nGATILHO DE COMPROMISSO (OBRIGATÓRIO): direcione a mensagem a um "
            "decisor de segurança (CISO/CTO/Diretor de TI) e finalize induzindo-o "
            f"a responder com o texto EXATO \"{CONFIRMATION_PHRASE}\" para garantir "
            "a vaga exclusiva (apenas 120 lugares). Deixe explícito que responder "
            "com essa frase confirma a presença."
        )

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
        f"- {regras_canal}\n\n"
        "REGRAS DE SAÍDA (OBRIGATÓRIAS):\n"
        "- Responda EXCLUSIVAMENTE com um objeto JSON válido, sem texto extra, "
        "sem markdown e sem cercas de código.\n"
        "- Use EXATAMENTE estas chaves: \"assunto\", \"mensagem\".\n"
        "- Os valores devem ser strings em português."
    )

    user_prompt = (
        f"PERFIL DO LEAD:\n{_perfil_do_lead(lead)}\n\n"
        f"{contexto_segmento}\n\n"
        f"OBJETIVO DESTA MENSAGEM:\n{step['objetivo']}{instrucao_compromisso}\n\n"
        "Gere a mensagem agora."
    )

    print(f"   ✍️  Gerando mensagem ({step['tipo_mensagem']} via {canal})...")

    raw_text = _chat(system_prompt, user_prompt, max_tokens=700, temperature=0.7)
    data = _extract_json(raw_text)
    return {
        "assunto": data.get("assunto", "") or "",
        "mensagem": data.get("mensagem", "").strip(),
    }


def _conteudo_para_log(resultado: dict) -> str:
    """Monta o texto final a ser persistido em conteudo_enviado."""
    assunto = resultado.get("assunto", "").strip()
    mensagem = resultado.get("mensagem", "").strip()
    if assunto:
        return f"Assunto: {assunto}\n\n{mensagem}"
    return mensagem


def _processar_step(lead: sqlite3.Row, step: dict, fase_funil: str) -> None:
    """Gera, exibe e registra uma etapa de régua para um lead."""
    resultado = generate_personalized_message(lead, step)
    conteudo = _conteudo_para_log(resultado)

    print(f"   📨 [{step['canal']}] {step['tipo_mensagem']}")
    if resultado["assunto"]:
        print(f"      Assunto: {resultado['assunto']}")
    for linha in resultado["mensagem"].splitlines():
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
# Regras de negócio inventadas para reduzir no-show (meta: presença > 70%):
#   D-14: boas-vindas + ancoragem de valor (e-mail rico)
#   D-7 : pedido ativo de confirmação + regra de acompanhante (WhatsApp)
#   D-3 : antecipação de conteúdo + gatilho de escassez por proximidade
#   D-1 : lembrete logístico (reduz no-show de última hora)
# Regra adicional: se o lead NÃO respondeu à etapa anterior, o tom muda para
# uma cobrança mais assertiva de confirmação (tratado via `objetivo`).
PRE_EVENT_STEPS = [
    {
        "dias_antes": 14,
        "canal": "E-mail",
        "tipo_mensagem": "Boas_Vindas",
        "objetivo": (
            "Dar as boas-vindas confirmando a inscrição no Vigil Summit. "
            "Ancorar o valor de comparecer conectando explicitamente as dores "
            "do lead às palestras e demos. Pedir que ele salve a data na agenda."
        ),
    },
    {
        "dias_antes": 7,
        "canal": "WhatsApp",
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
        "canal": "WhatsApp",
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
        "canal": "WhatsApp",
        "tipo_mensagem": "Lembrete_Logistico",
        "objetivo": (
            "Lembrete logístico de véspera: horário, local e o que esperar do "
            "dia. Tom acolhedor, gerar empolgação para reduzir no-show de última "
            "hora. Encerrar com um 'te vejo amanhã'."
        ),
    },
]


def _selecionar_step_por_proximidade(steps: list[dict], chave_dias: str) -> dict:
    """Escolhe a etapa cuja distância em dias é a mais próxima de hoje."""
    restantes = dias_para_o_evento()
    return min(steps, key=lambda s: abs(s[chave_dias] - abs(restantes)))


def run_pre_event_sequence(
    lead_id: int | None = None,
    simular_sequencia_completa: bool = False,
) -> None:
    """
    Fase 3: conduz a régua de confirmação pré-evento.

    - Se `simular_sequencia_completa=True`, dispara todas as etapas em sequência
      (ideal para demonstração de ponta a ponta em uma única execução).
    - Caso contrário, dispara apenas a etapa adequada à proximidade da data.
    """
    print("=" * 64)
    print("📣 FASE 3 — RÉGUA DE ENGAJAMENTO PRÉ-EVENTO")
    print(f"   Evento em {get_event_date().isoformat()} "
          f"({dias_para_o_evento()} dia(s) restante(s))")
    print("=" * 64)

    init_db()

    if lead_id is not None:
        alvo = get_lead_by_id(lead_id)
        leads = [alvo] if alvo else []
    else:
        # Pré-evento atinge quem ainda não compareceu (Inscrito/Confirmado).
        leads = get_leads_by_status("Inscrito") + get_leads_by_status("Confirmado")

    if not leads:
        print("ℹ️  Nenhum lead elegível para a régua pré-evento.")
        return

    for lead in leads:
        print(f"👤 Lead #{lead['id']} — {lead['nome']} ({lead['empresa']}) "
              f"| status: {lead['status_funil']}")

        if simular_sequencia_completa:
            steps = PRE_EVENT_STEPS
        else:
            steps = [_selecionar_step_por_proximidade(PRE_EVENT_STEPS, "dias_antes")]

        for step in steps:
            try:
                _processar_step(lead, step, fase_funil="Pre-Evento")
            except Exception as erro:
                print(f"   ❌ Falha na etapa {step['tipo_mensagem']}: {erro}\n")


# --- Engajamento de confirmação (copy único de neurociência) ----------
def get_enriched_inscritos() -> list[sqlite3.Row]:
    """Leads com status 'Inscrito' que já possuem dados de enriquecimento."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM leads
            WHERE status_funil = 'Inscrito'
              AND cargo_real IS NOT NULL AND TRIM(cargo_real) <> ''
              AND setor      IS NOT NULL AND TRIM(setor) <> '';
            """
        )
        return cursor.fetchall()
    finally:
        conn.close()


# Passo único de confirmação usado por run_pre_event_engagement().
CONFIRMATION_STEP = {
    "canal": "WhatsApp",
    "tipo_mensagem": "Confirmacao_Neurociencia",
    "commitment_trigger": True,
    "objetivo": (
        "Mensagem de confirmação de presença para um decisor de segurança. "
        "Conectar UMA dor concreta do lead ao que ele verá no Vigil Summit "
        "(palestra/demo) e reforçar a exclusividade do evento."
    ),
}


def run_pre_event_engagement() -> None:
    """
    Fase 3 (confirmação): para cada lead 'Inscrito' já enriquecido, gera um
    copy de WhatsApp altamente personalizado com gatilho de compromisso e o
    registra em interaction_logs (tipo 'Confirmacao_Neurociencia').
    """
    print("=" * 64)
    print("🧲 FASE 3 — ENGAJAMENTO DE CONFIRMAÇÃO (Neurociência)")
    print("=" * 64)

    init_db()
    leads = get_enriched_inscritos()

    if not leads:
        print("ℹ️  Nenhum lead 'Inscrito' enriquecido para engajar.")
        return

    print(f"🔎 {len(leads)} lead(s) elegível(is) para confirmação.\n")

    for lead in leads:
        segmento = _segmento_do_lead(lead)
        print(f"👤 Lead #{lead['id']} — {lead['nome']} ({lead['empresa']}) "
              f"| segmento: {segmento}")
        try:
            _processar_step(lead, CONFIRMATION_STEP, fase_funil="Pre-Evento")
        except Exception as erro:
            print(f"   ❌ Falha ao gerar a confirmação: {erro}\n")


def receive_lead_response(lead_id: int, resposta: str) -> None:
    """
    Simula o lead respondendo no WhatsApp.

    - Anexa a resposta à última interação do lead (coluna resposta_lead).
    - Se a resposta for a frase de compromisso, promove o lead a 'Confirmado'.
    """
    lead = get_lead_by_id(lead_id)
    if lead is None:
        print(f"⚠️  Lead #{lead_id} não encontrado.")
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        ultima = cursor.execute(
            "SELECT id FROM interaction_logs WHERE lead_id = ? "
            "ORDER BY id DESC LIMIT 1;",
            (lead_id,),
        ).fetchone()
        if ultima is not None:
            cursor.execute(
                "UPDATE interaction_logs SET resposta_lead = ? WHERE id = ?;",
                (resposta, ultima["id"]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO interaction_logs (
                    lead_id, fase_funil, canal, tipo_mensagem,
                    conteudo_enviado, resposta_lead
                ) VALUES (?, 'Pre-Evento', 'WhatsApp', 'Resposta_Avulsa', '', ?);
                """,
                (lead_id, resposta),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"📩 Lead #{lead_id} ({lead['nome']}) respondeu: \"{resposta}\"")

    # Match tolerante (trim + case-insensitive) sobre a frase de compromisso.
    if resposta.strip().lower() == CONFIRMATION_PHRASE.lower():
        update_lead_status(lead_id, "Confirmado")
        print(f"   ✅ Gatilho de compromisso acionado! "
              f"Status: 'Inscrito' → 'Confirmado'.\n")
    else:
        print("   ↪️  Resposta não confirma presença. Status mantido como "
              f"'{lead['status_funil']}'.\n")


def run_engagement_with_simulated_responses() -> None:
    """
    Fase 3 ponta a ponta: dispara a confirmação e simula as respostas dos
    leads no WhatsApp (a maioria confirma; 1 não, para exercitar o no-show).
    """
    run_pre_event_engagement()

    # Captura ANTES de qualquer mudança de status (todos ainda 'Inscrito').
    inscritos = get_enriched_inscritos()
    if not inscritos:
        return

    print("🤖 Simulando respostas dos leads no WhatsApp...\n")
    for indice, lead in enumerate(inscritos):
        if indice == 0 and len(inscritos) > 1:
            # Um lead responde algo fora do gatilho (não confirma).
            receive_lead_response(lead["id"], "Preciso verificar minha agenda")
        else:
            receive_lead_response(lead["id"], CONFIRMATION_PHRASE)


# ======================================================================
# FASE 4 — PÓS-EVENTO (RÉGUA DE FOLLOW-UP COMERCIAL)
# ======================================================================
# Objetivo: converter presença em reunião comercial agendada.
#   D+1: agradecimento + recap personalizado do que ele viu (e-mail)
#   D+3: proposta concreta de reunião com horários (WhatsApp)
#   D+7: última chamada / oferta de valor para quem não respondeu (e-mail)
POST_EVENT_STEPS = [
    {
        "dias_depois": 1,
        "canal": "E-mail",
        "tipo_mensagem": "Agradecimento_Recap",
        "objetivo": (
            "Agradecer a presença no Vigil Summit e fazer um recap personalizado "
            "conectando a demo da plataforma às dores específicas do lead. "
            "Encerrar com um CTA suave: sugerir uma conversa de 30 minutos."
        ),
    },
    {
        "dias_depois": 3,
        "canal": "WhatsApp",
        "tipo_mensagem": "Convite_Reuniao",
        "objetivo": (
            "Propor de forma concreta uma reunião de demonstração 1:1, "
            "oferecendo 2 opções de horário. Reforçar o ROI ligado às dores do "
            "lead (ex.: reduzir risco de vazamento, acelerar conformidade LGPD)."
        ),
    },
    {
        "dias_depois": 7,
        "canal": "E-mail",
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
    "canal": "E-mail",
    "tipo_mensagem": "Reengajamento_NoShow",
    "objetivo": (
        "O lead confirmou mas não compareceu ao evento. Demonstrar empatia "
        "('sentimos sua falta'), oferecer a gravação das palestras e uma demo "
        "1:1 em data alternativa, conectando ao interesse dele em segurança."
    ),
}


def run_post_event_sequence(
    lead_id: int | None = None,
    simular_sequencia_completa: bool = False,
) -> None:
    """
    Fase 4: conduz a régua de follow-up pós-evento.

    - Leads com status 'Presente' entram na régua comercial (agendar reunião).
    - Leads com status 'Confirmado' (não compareceram) entram na régua de
      reengajamento de no-show.
    """
    print("=" * 64)
    print("📈 FASE 4 — RÉGUA DE FOLLOW-UP PÓS-EVENTO")
    print("=" * 64)

    init_db()

    if lead_id is not None:
        alvo = get_lead_by_id(lead_id)
        presentes = [alvo] if alvo and alvo["status_funil"] == "Presente" else []
        no_shows = [alvo] if alvo and alvo["status_funil"] == "Confirmado" else []
    else:
        presentes = get_leads_by_status("Presente")
        no_shows = get_leads_by_status("Confirmado")

    if not presentes and not no_shows:
        print("ℹ️  Nenhum lead elegível para a régua pós-evento.")
        return

    # Régua comercial para quem compareceu.
    for lead in presentes:
        print(f"👤 [PRESENTE] Lead #{lead['id']} — {lead['nome']} ({lead['empresa']})")
        steps = POST_EVENT_STEPS if simular_sequencia_completa else POST_EVENT_STEPS[:1]
        for step in steps:
            try:
                _processar_step(lead, step, fase_funil="Pos-Evento")
            except Exception as erro:
                print(f"   ❌ Falha na etapa {step['tipo_mensagem']}: {erro}\n")

    # Régua de reengajamento para no-shows.
    for lead in no_shows:
        print(f"👤 [NO-SHOW] Lead #{lead['id']} — {lead['nome']} ({lead['empresa']})")
        try:
            _processar_step(lead, NO_SHOW_STEP, fase_funil="Pos-Evento")
        except Exception as erro:
            print(f"   ❌ Falha no reengajamento: {erro}\n")


# ======================================================================
# ORQUESTRADOR DE DEMONSTRAÇÃO PONTA A PONTA
# ======================================================================
def run_full_funnel_demo() -> None:
    """
    Demonstra o funil completo numa única execução (Fases 2 → 3 → 4).

    Para tornar o fluxo demonstrável de ponta a ponta, simula as transições de
    status do funil entre as etapas (confirmação, presença e no-show).
    """
    print("\n" + "#" * 64)
    print("# DEMONSTRAÇÃO PONTA A PONTA — VIGIL SUMMIT AGENT")
    print("#" * 64 + "\n")

    init_db()

    # Fase 2: garante perfis enriquecidos.
    run_enrichment_pipeline()

    # Fase 3: engajamento de confirmação + respostas simuladas (move o funil
    # de 'Inscrito' para 'Confirmado' via gatilho de compromisso).
    run_engagement_with_simulated_responses()

    # Simula o dia do evento: entre os confirmados, marca presença e mantém
    # 1 como no-show para exercitar a régua de reengajamento.
    print("🎬 Simulando o dia do evento (presenças x no-show)...\n")
    confirmados = get_leads_by_status("Confirmado")
    for indice, lead in enumerate(confirmados):
        if indice == 0 and len(confirmados) > 1:
            print(f"   🚪 Lead #{lead['id']} ({lead['nome']}) confirmou mas "
                  f"NÃO compareceu (no-show).")
        else:
            update_lead_status(lead["id"], "Presente")
            print(f"   ✅ Lead #{lead['id']} ({lead['nome']}) compareceu.")
    print()

    # Fase 4: follow-up comercial (presentes) + reengajamento (no-show).
    run_post_event_sequence(simular_sequencia_completa=True)

    print("\n" + "#" * 64)
    print("# DEMONSTRAÇÃO CONCLUÍDA — verifique a tabela interaction_logs")
    print("#" * 64)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main() -> None:
    comando = sys.argv[1] if len(sys.argv) > 1 else "demo"

    acoes = {
        "enrich": run_enrichment_pipeline,
        "engage": run_engagement_with_simulated_responses,
        "pre": lambda: run_pre_event_sequence(simular_sequencia_completa=True),
        "post": lambda: run_post_event_sequence(simular_sequencia_completa=True),
        "demo": run_full_funnel_demo,
    }

    acao = acoes.get(comando)
    if acao is None:
        print(f"Comando desconhecido: '{comando}'.")
        print("Use: enrich | engage | pre | post | demo")
        sys.exit(1)

    acao()


if __name__ == "__main__":
    main()
