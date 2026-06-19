"""
database.py
-----------
Inicialização e população do banco de dados SQLite do projeto
"Case AI Engineer - Vigil Summit" (Pareto).

Banco: vigil_summit.db
Tabelas: leads, interaction_logs, users

Execute diretamente para criar o banco e popular leads de teste:
    python database.py
"""

import os
import hashlib
import secrets
import sqlite3

# Caminho do banco sempre relativo a este arquivo (evita problemas de cwd).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "vigil_summit.db")

# Hash de senha: PBKDF2-HMAC-SHA256 com salt por usuário (apenas stdlib).
PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 6


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
        if "evento_id" not in colunas_leads:
            cursor.execute(
                "ALTER TABLE leads ADD COLUMN evento_id TEXT DEFAULT 'vigil_summit_2026';"
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

        # Usuários do painel (login por usuário/senha). Guarda apenas o hash.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT    UNIQUE NOT NULL,
                password_salt   TEXT    NOT NULL,
                password_hash   TEXT    NOT NULL,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        conn.commit()
    finally:
        conn.close()


def insert_lead(
    nome: str,
    email: str,
    telefone: str | None = None,
    cargo_declarado: str | None = None,
    empresa: str | None = None,
    cargo_real: str | None = None,
    setor: str | None = None,
    tamanho_empresa: str | None = None,
    linkedin_perfil: str | None = None,
    sinais_interesse: str | None = None,
    origem: str = "LP_Organico",
    status_funil: str = "Inscrito",
) -> int | None:
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
            "tamanho_empresa": "+200 funcionários",
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

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE leads SET tamanho_empresa = ? WHERE email = ?;",
            ("+200 funcionários", "ramon@pareto.io"),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"[seed] Leads de teste inseridos: {inserted}/{len(test_leads)}")


# ----------------------------------------------------------------------
# Usuários do painel (autenticação)
# ----------------------------------------------------------------------
def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Deriva (salt, hash) de uma senha. Gera um salt novo se não for fornecido."""
    if salt is None:
        salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return salt, derived.hex()


def create_user(username: str, password: str) -> int | None:
    """Cria um usuário. Retorna o id ou None se o nome de usuário já existir."""
    salt, password_hash = _hash_password(password)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, password_salt, password_hash)
            VALUES (?, ?, ?);
            """,
            (username, salt, password_hash),
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def verify_user(username: str, password: str) -> bool:
    """Confere as credenciais contra o hash armazenado (comparação constante)."""
    conn = get_connection()
    try:
        usuario = conn.execute(
            "SELECT password_salt, password_hash FROM users WHERE username = ?;",
            (username,),
        ).fetchone()
    finally:
        conn.close()

    if usuario is None:
        return False
    _, esperado = _hash_password(password, usuario["password_salt"])
    return secrets.compare_digest(esperado, usuario["password_hash"])


def list_users() -> list[sqlite3.Row]:
    """Retorna todos os usuários (sem dados sensíveis de senha)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, username, created_at FROM users ORDER BY username;"
        ).fetchall()
    finally:
        conn.close()


def count_users() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0]
    finally:
        conn.close()


def delete_user(username: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM users WHERE username = ?;", (username,))
        conn.commit()
    finally:
        conn.close()


def ensure_default_user(username: str, password: str) -> None:
    """Garante um usuário inicial quando ainda não há nenhum cadastrado."""
    if count_users() == 0:
        create_user(username, password)


if __name__ == "__main__":
    init_db()
    print(f"[init] Banco criado/verificado em: {DB_PATH}")
    seed_test_leads()
    print("[ok] database.py executado com sucesso.")
