"""
leads_simulacao.py
------------------
Base de 22 leads sintéticos para demonstração do funil Vigil Summit.

Cobertura intencional:
  - status_funil: Inscrito, Confirmado, Presente, Reunião Agendada
  - origem: LP_Organico e Remarketing
  - setores: todos os da LP + Outro
  - cargos ICP: CISO, CTO, Diretor de TI, VP Segurança
  - porte: +200, 201-500, 1000+
  - mix enriquecido / pendente de Fase 2

Uso local:
    py -X utf8 leads_simulacao.py

Uso remoto (API Render):
    py -X utf8 leads_simulacao.py --remoto
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

import database

# 22 leads — inclui ramon@pareto.io (case) + 21 personas B2B variadas.
SIMULATION_LEADS: list[dict] = [
    {
        "nome": "Ramon Souza",
        "email": "ramon@pareto.io",
        "telefone": "+55 11 91234-5678",
        "cargo_declarado": "Head of Growth",
        "empresa": "Pareto",
        "cargo_real": "Head of Growth",
        "setor": "Tecnologia",
        "tamanho_empresa": "+200 funcionários",
        "linkedin_perfil": "https://www.linkedin.com/in/ramon-pareto",
        "sinais_interesse": "Interesse em IA aplicada a funis B2B e automação de SDR",
        "origem": "LP_Organico",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Mariana Lima",
        "email": "mariana.lima@techcorp.com",
        "telefone": "+55 21 99876-5432",
        "cargo_declarado": "Diretora de Operações",
        "empresa": "TechCorp",
        "cargo_real": "COO",
        "setor": "Tecnologia",
        "tamanho_empresa": "201-500",
        "linkedin_perfil": "https://www.linkedin.com/in/mariana-lima",
        "sinais_interesse": "Participou de webinar anterior; abriu 3 e-mails",
        "origem": "Remarketing",
        "status_funil": "Confirmado",
    },
    {
        "nome": "Carlos Mendes",
        "email": "carlos.mendes@varejomais.com.br",
        "telefone": "+55 31 98765-1234",
        "cargo_declarado": "Gerente de Vendas",
        "empresa": "Varejo Mais",
        "cargo_real": "Gerente Comercial Sênior",
        "setor": "Varejo",
        "tamanho_empresa": "1000+",
        "linkedin_perfil": "https://www.linkedin.com/in/carlos-mendes",
        "sinais_interesse": "Clicou no link de inscrição via WhatsApp",
        "origem": "Remarketing",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Ana Costa",
        "email": "ana.costa@banksecure.com.br",
        "telefone": "+55 11 97654-3210",
        "cargo_declarado": "CISO",
        "empresa": "BankSecure",
        "cargo_real": "Chief Information Security Officer",
        "setor": "Financeiro",
        "tamanho_empresa": "1000+",
        "linkedin_perfil": "https://www.linkedin.com/in/ana-costa-ciso",
        "sinais_interesse": "Pressão regulatória Bacen e PCI-DSS; auditoria trimestral",
        "origem": "LP_Organico",
        "status_funil": "Confirmado",
    },
    {
        "nome": "Pedro Alves",
        "email": "pedro.alves@techflow.io",
        "telefone": "+55 11 94567-8901",
        "cargo_declarado": "CTO",
        "empresa": "TechFlow",
        "cargo_real": None,
        "setor": "Tecnologia",
        "tamanho_empresa": None,
        "linkedin_perfil": None,
        "sinais_interesse": None,
        "origem": "LP_Organico",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Juliana Ferreira",
        "email": "juliana.ferreira@healthguard.com",
        "telefone": "+55 21 93456-7890",
        "cargo_declarado": "Diretora de TI",
        "empresa": "HealthGuard",
        "cargo_real": "Diretora de Tecnologia da Informação",
        "setor": "Saúde",
        "tamanho_empresa": "501-1000",
        "linkedin_perfil": "https://www.linkedin.com/in/juliana-ferreira-ti",
        "sinais_interesse": "Proteção de prontuários eletrônicos e LGPD na saúde",
        "origem": "Remarketing",
        "status_funil": "Presente",
    },
    {
        "nome": "Roberto Silva",
        "email": "roberto.silva@industriamax.com",
        "telefone": "+55 19 92345-6789",
        "cargo_declarado": "CISO",
        "empresa": "Indústria Max",
        "cargo_real": "CISO",
        "setor": "Indústria",
        "tamanho_empresa": "1000+",
        "linkedin_perfil": "https://www.linkedin.com/in/roberto-silva-ciso",
        "sinais_interesse": "Segurança OT/ICS e continuidade de produção",
        "origem": "LP_Organico",
        "status_funil": "Reunião Agendada",
    },
    {
        "nome": "Fernanda Oliveira",
        "email": "fernanda.oliveira@edutech.edu",
        "telefone": "+55 11 91234-0001",
        "cargo_declarado": "Diretora de TI",
        "empresa": "EduTech Brasil",
        "cargo_real": None,
        "setor": "Educação",
        "tamanho_empresa": None,
        "linkedin_perfil": None,
        "sinais_interesse": None,
        "origem": "LP_Organico",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Lucas Mendes",
        "email": "lucas.mendes@energianorte.com",
        "telefone": "+55 85 98765-4321",
        "cargo_declarado": "CTO",
        "empresa": "Energia Norte",
        "cargo_real": "Chief Technology Officer",
        "setor": "Energia",
        "tamanho_empresa": "+500 funcionários",
        "linkedin_perfil": "https://www.linkedin.com/in/lucas-mendes-cto",
        "sinais_interesse": "Infraestrutura crítica e resposta a incidentes",
        "origem": "Remarketing",
        "status_funil": "Confirmado",
    },
    {
        "nome": "Patricia Santos",
        "email": "patricia.santos@telecomplus.com",
        "telefone": "+55 11 99887-7665",
        "cargo_declarado": "VP de Segurança",
        "empresa": "Telecom Plus",
        "cargo_real": "VP de Segurança da Informação",
        "setor": "Telecomunicações",
        "tamanho_empresa": "1000+",
        "linkedin_perfil": "https://www.linkedin.com/in/patricia-santos-security",
        "sinais_interesse": "Fraude em rede móvel e conformidade ANATEL",
        "origem": "LP_Organico",
        "status_funil": "Presente",
    },
    {
        "nome": "Ricardo Gomes",
        "email": "ricardo.gomes@varejounico.com",
        "telefone": "+55 51 97654-3210",
        "cargo_declarado": "Diretor de Risco",
        "empresa": "Varejo Único",
        "cargo_real": "Diretor de Riscos e Compliance",
        "setor": "Varejo",
        "tamanho_empresa": "+200 funcionários",
        "linkedin_perfil": "https://www.linkedin.com/in/ricardo-gomes-risco",
        "sinais_interesse": "Vazamento de dados de clientes no e-commerce",
        "origem": "Remarketing",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Beatriz Nunes",
        "email": "beatriz.nunes@fintechpay.com",
        "telefone": "+55 11 96543-2109",
        "cargo_declarado": "CISO",
        "empresa": "FinTech Pay",
        "cargo_real": "CISO",
        "setor": "Financeiro",
        "tamanho_empresa": "201-500",
        "linkedin_perfil": "https://www.linkedin.com/in/beatriz-nunes-ciso",
        "sinais_interesse": "SOC 2 e prevenção a fraudes transacionais",
        "origem": "LP_Organico",
        "status_funil": "Confirmado",
    },
    {
        "nome": "Gustavo Ramos",
        "email": "gustavo.ramos@cloudscale.io",
        "telefone": "+55 21 95432-1098",
        "cargo_declarado": "CTO",
        "empresa": "CloudScale",
        "cargo_real": "CTO",
        "setor": "Tecnologia",
        "tamanho_empresa": "201-500",
        "linkedin_perfil": "https://www.linkedin.com/in/gustavo-ramos-cto",
        "sinais_interesse": "Postura multi-cloud e gestão de vulnerabilidades",
        "origem": "LP_Organico",
        "status_funil": "Presente",
    },
    {
        "nome": "Camila Rosa",
        "email": "camila.rosa@pharmatech.com",
        "telefone": "+55 31 94321-0987",
        "cargo_declarado": "Diretora de TI",
        "empresa": "PharmaTech",
        "cargo_real": None,
        "setor": "Saúde",
        "tamanho_empresa": None,
        "linkedin_perfil": None,
        "sinais_interesse": None,
        "origem": "Remarketing",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Diego Castro",
        "email": "diego.castro@manufpro.com",
        "telefone": "+55 47 93210-9876",
        "cargo_declarado": "CISO",
        "empresa": "ManufPro",
        "cargo_real": "CISO",
        "setor": "Indústria",
        "tamanho_empresa": "+500 funcionários",
        "linkedin_perfil": "https://www.linkedin.com/in/diego-castro-ciso",
        "sinais_interesse": "Supply chain attacks e segurança de fornecedores",
        "origem": "LP_Organico",
        "status_funil": "Confirmado",
    },
    {
        "nome": "Larissa Pires",
        "email": "larissa.pires@univ.edu.br",
        "telefone": "+55 61 92109-8765",
        "cargo_declarado": "Diretora de TI",
        "empresa": "Universidade Federal Digital",
        "cargo_real": "Diretora de TI",
        "setor": "Educação",
        "tamanho_empresa": "1000+",
        "linkedin_perfil": "https://www.linkedin.com/in/larissa-pires-ti",
        "sinais_interesse": "Proteção de dados de alunos e pesquisa acadêmica",
        "origem": "Remarketing",
        "status_funil": "Presente",
    },
    {
        "nome": "Marcos Vieira",
        "email": "marcos.vieira@powergrid.com",
        "telefone": "+55 62 91098-7654",
        "cargo_declarado": "CTO",
        "empresa": "PowerGrid",
        "cargo_real": "CTO",
        "setor": "Energia",
        "tamanho_empresa": "1000+",
        "linkedin_perfil": "https://www.linkedin.com/in/marcos-vieira-cto",
        "sinais_interesse": "Continuidade operacional e SCADA seguro",
        "origem": "LP_Organico",
        "status_funil": "Reunião Agendada",
    },
    {
        "nome": "Simone Lopes",
        "email": "simone.lopes@mobilenet.com",
        "telefone": "+55 11 90987-6543",
        "cargo_declarado": "CISO",
        "empresa": "MobileNet",
        "cargo_real": "CISO",
        "setor": "Telecomunicações",
        "tamanho_empresa": "+200 funcionários",
        "linkedin_perfil": "https://www.linkedin.com/in/simone-lopes-ciso",
        "sinais_interesse": "5G core security e privacidade de assinantes",
        "origem": "LP_Organico",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Thiago Barbosa",
        "email": "thiago.barbosa@retailmax.com",
        "telefone": "+55 41 90876-5432",
        "cargo_declarado": "Diretor de TI",
        "empresa": "RetailMax",
        "cargo_real": "Diretor de TI",
        "setor": "Varejo",
        "tamanho_empresa": "501-1000",
        "linkedin_perfil": "https://www.linkedin.com/in/thiago-barbosa-ti",
        "sinais_interesse": "PCI-DSS em PDV e lojas omnichannel",
        "origem": "Remarketing",
        "status_funil": "Confirmado",
    },
    {
        "nome": "Renata Freitas",
        "email": "renata.freitas@insurtech.io",
        "telefone": "+55 11 90765-4321",
        "cargo_declarado": "CISO",
        "empresa": "InsurTech",
        "cargo_real": "CISO",
        "setor": "Financeiro",
        "tamanho_empresa": "201-500",
        "linkedin_perfil": "https://www.linkedin.com/in/renata-freitas-ciso",
        "sinais_interesse": "Underwriting digital e prevenção a fraudes",
        "origem": "LP_Organico",
        "status_funil": "Presente",
    },
    {
        "nome": "André Moura",
        "email": "andre.moura@logistech.com",
        "telefone": "+55 48 90654-3210",
        "cargo_declarado": "CTO",
        "empresa": "LogisTech",
        "cargo_real": None,
        "setor": "Outro",
        "tamanho_empresa": None,
        "linkedin_perfil": None,
        "sinais_interesse": None,
        "origem": "Remarketing",
        "status_funil": "Inscrito",
    },
    {
        "nome": "Vanessa Cardoso",
        "email": "vanessa.cardoso@govtech.gov.br",
        "telefone": "+55 61 90543-2109",
        "cargo_declarado": "Diretora de Segurança",
        "empresa": "GovTech Brasil",
        "cargo_real": "Diretora de Segurança da Informação",
        "setor": "Outro",
        "tamanho_empresa": "1000+",
        "linkedin_perfil": "https://www.linkedin.com/in/vanessa-cardoso-gov",
        "sinais_interesse": "Soberania de dados e conformidade em órgãos públicos",
        "origem": "LP_Organico",
        "status_funil": "Reunião Agendada",
    },
]


def _upsert_lead_simulacao(lead: dict) -> str:
    """Insere ou atualiza lead de simulação por e-mail (idempotente)."""
    conn = database.get_connection()
    try:
        existente = conn.execute(
            "SELECT id FROM leads WHERE email = ?;",
            (lead["email"],),
        ).fetchone()
        if existente is None:
            return "inserido" if database.insert_lead(**lead) is not None else "ignorado"

        conn.execute(
            """
            UPDATE leads SET
                nome = ?, telefone = ?, cargo_declarado = ?, empresa = ?,
                cargo_real = ?, setor = ?, tamanho_empresa = ?, linkedin_perfil = ?,
                sinais_interesse = ?, origem = ?, status_funil = ?
            WHERE email = ?;
            """,
            (
                lead["nome"],
                lead.get("telefone"),
                lead.get("cargo_declarado"),
                lead.get("empresa"),
                lead.get("cargo_real"),
                lead.get("setor"),
                lead.get("tamanho_empresa"),
                lead.get("linkedin_perfil"),
                lead.get("sinais_interesse"),
                lead.get("origem", "LP_Organico"),
                lead.get("status_funil", "Inscrito"),
                lead["email"],
            ),
        )
        conn.commit()
        return "atualizado"
    finally:
        conn.close()


def seed_simulation_leads() -> dict[str, int]:
    """Popula a base de simulação (insert ou update por e-mail)."""
    database.init_db()
    inseridos = atualizados = 0
    for lead in SIMULATION_LEADS:
        resultado = _upsert_lead_simulacao(lead)
        if resultado == "inserido":
            inseridos += 1
        elif resultado == "atualizado":
            atualizados += 1

    conn = database.get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM leads;").fetchone()[0]
    finally:
        conn.close()

    resultado = {
        "inseridos": inseridos,
        "atualizados": atualizados,
        "catalogo": len(SIMULATION_LEADS),
        "total_no_banco": total,
    }
    print(
        f"[simulacao] Inseridos: {inseridos} | Atualizados: {atualizados} "
        f"| Catálogo: {resultado['catalogo']} | Total no banco: {resultado['total_no_banco']}"
    )
    return resultado


def enviar_inscricoes_remotas() -> dict[str, int]:
    """Envia leads via POST /api/inscricao (campos básicos; útil antes do redeploy)."""
    load_dotenv()
    base = os.getenv("VIGIL_API_URL", "https://vigil-summit-api.onrender.com").strip().rstrip("/")
    url = f"{base}/api/inscricao"
    novos = duplicados = erros = 0
    for lead in SIMULATION_LEADS:
        payload = {
            "nome": lead["nome"],
            "email": lead["email"],
            "cargo": lead["cargo_declarado"] or "Decisor",
            "setor": lead["setor"] or "Tecnologia",
            "empresa": lead["empresa"] or "Empresa",
            "telefone": lead["telefone"] or "+55 11 90000-0000",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90):
                novos += 1
        except urllib.error.HTTPError as erro:
            if erro.code == 409:
                duplicados += 1
            else:
                erros += 1
        except urllib.error.URLError:
            erros += 1
    resumo = {
        "novos": novos,
        "duplicados": duplicados,
        "erros": erros,
        "catalogo": len(SIMULATION_LEADS),
    }
    print(
        f"[inscricao remota] Novos: {novos} | Já existiam: {duplicados} "
        f"| Erros: {erros} | Catálogo: {resumo['catalogo']}"
    )
    return resumo


def _enviar_para_api_remota() -> dict:
    load_dotenv()
    base = os.getenv("VIGIL_API_URL", "").strip().rstrip("/")
    chave = os.getenv("VIGIL_API_KEY", "").strip()
    if not base:
        raise RuntimeError("Defina VIGIL_API_URL no .env")
    if not chave or chave.startswith("COLE_AQUI"):
        raise RuntimeError("Defina VIGIL_API_KEY no .env (mesma chave do Render)")

    url = f"{base}/api/admin/seed-simulation"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": chave,
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        corpo = erro.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {erro.code}: {corpo}") from erro
    except urllib.error.URLError as erro:
        raise RuntimeError(
            "API indisponível (Render free tier pode levar ~1 min no cold start)."
        ) from erro


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed da base de leads de simulação")
    parser.add_argument(
        "--remoto",
        action="store_true",
        help="Seed completo na API Render (POST /api/admin/seed-simulation)",
    )
    parser.add_argument(
        "--inscricao-remoto",
        action="store_true",
        help="Envia campos básicos via POST /api/inscricao (sem VIGIL_API_KEY)",
    )
    args = parser.parse_args()

    if args.remoto:
        print(f"☁️  Seed completo de {len(SIMULATION_LEADS)} leads na API...")
        resultado = _enviar_para_api_remota()
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    elif args.inscricao_remoto:
        print(f"☁️  Inscrição remota de {len(SIMULATION_LEADS)} leads...")
        resultado = enviar_inscricoes_remotas()
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        seed_simulation_leads()


if __name__ == "__main__":
    main()
