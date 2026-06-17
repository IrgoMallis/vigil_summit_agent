"""
database.py
-----------
Inicialização e população do banco de dados SQLite do projeto
"Case AI Engineer - Vigil Summit" (Pareto).

Banco: vigil_summit.db
Tabelas: leads, interaction_logs

Execute diretamente para criar o banco e popular leads de teste:
    python database.py
"""

import os
import sqlite3
from typing import Optional

# Caminho do banco sempre relativo a este arquivo (evita problemas de cwd).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "vigil_summit.db")


def get_connection() -> sqlite3.Connection:
    """Retorna uma conexão SQLite com chaves estrangeiras habilitadas."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Cria as tabelas `leads` e `interaction_logs` caso não existam."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                nome                TEXT    NOT NULL,
                email               TEXT    UNIQUE NOT NULL,
                telefone            TEXT,
                cargo_declarado     TEXT,
                empresa             TEXT,
                cargo_real          TEXT,
                setor               TEXT,
                tamanho_empresa     TEXT,
                linkedin_perfil     TEXT,
                sinais_interesse    TEXT,
                origem              TEXT    DEFAULT 'Remarketing',
                status_funil        TEXT    DEFAULT 'Inscrito',
                data_inscricao      DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Migração leve: garante a coluna `origem` em bancos já existentes
        # (CREATE TABLE IF NOT EXISTS não altera tabelas pré-existentes).
        colunas_leads = [linha[1] for linha in cursor.execute("PRAGMA table_info(leads);")]
        if "origem" not in colunas_leads:
            cursor.execute(
                "ALTER TABLE leads ADD COLUMN origem TEXT DEFAULT 'Remarketing';"
            )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS interaction_logs (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id             INTEGER,
                fase_funil          TEXT,
                canal               TEXT,
                tipo_mensagem       TEXT,
                conteudo_enviado    TEXT,
                resposta_lead       TEXT,
                data_envio          DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES leads (id)
            );
            """
        )

        # Mantém updated_at sincronizado em qualquer UPDATE na tabela leads.
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_leads_updated_at
            AFTER UPDATE ON leads
            FOR EACH ROW
            BEGIN
                UPDATE leads
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = OLD.id;
            END;
            """
        )

        conn.commit()
    finally:
        conn.close()


def insert_lead(
    nome: str,
    email: str,
    telefone: Optional[str] = None,
    cargo_declarado: Optional[str] = None,
    empresa: Optional[str] = None,
    cargo_real: Optional[str] = None,
    setor: Optional[str] = None,
    tamanho_empresa: Optional[str] = None,
    linkedin_perfil: Optional[str] = None,
    sinais_interesse: Optional[str] = None,
    origem: str = "LP_Organico",
    status_funil: str = "Inscrito",
) -> Optional[int]:
    """Insere um lead. Retorna o id criado ou None se o e-mail já existir.

    `origem` define o segmento de comunicação ('LP_Organico' para leads novos
    captados pela landing page; 'Remarketing' para base de edições anteriores).
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO leads (
                nome, email, telefone, cargo_declarado, empresa,
                cargo_real, setor, tamanho_empresa, linkedin_perfil,
                sinais_interesse, origem, status_funil
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                nome,
                email,
                telefone,
                cargo_declarado,
                empresa,
                cargo_real,
                setor,
                tamanho_empresa,
                linkedin_perfil,
                sinais_interesse,
                origem,
                status_funil,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # E-mail já cadastrado (UNIQUE): ignora silenciosamente.
        return None
    finally:
        conn.close()


def seed_test_leads() -> None:
    """Insere 3 leads sintéticos para testes (idempotente via e-mail UNIQUE)."""
    test_leads = [
        {
            "nome": "Ramon Souza",
            "email": "ramon@pareto.io",
            "telefone": "+55 11 91234-5678",
            "cargo_declarado": "Head of Growth",
            "empresa": "Pareto",
            "cargo_real": "Head of Growth",
            "setor": "Marketing / Tecnologia",
            "tamanho_empresa": "51-200",
            "linkedin_perfil": "https://www.linkedin.com/in/ramon-pareto",
            "sinais_interesse": "Baixou material sobre IA aplicada a vendas",
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
            "setor": "SaaS B2B",
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
    ]

    inserted = 0
    for lead in test_leads:
        if insert_lead(**lead) is not None:
            inserted += 1

    print(f"[seed] Leads de teste inseridos: {inserted}/{len(test_leads)}")


if __name__ == "__main__":
    init_db()
    print(f"[init] Banco criado/verificado em: {DB_PATH}")
    seed_test_leads()
    print("[ok] database.py executado com sucesso.")
