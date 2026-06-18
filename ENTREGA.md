# Entrega — Case AI Engineer · Vigil Summit Agent

Documento de entrega para o time de avaliação da **Pareto** (Vigil.AI).

---

## Links de acesso

| Recurso | URL |
|---------|-----|
| **Repositório GitHub** | https://github.com/IrgoMallis/vigil_summit_agent |
| **Documentação técnica** | https://github.com/IrgoMallis/vigil_summit_agent#readme |
| **Landing Page (captação)** | https://irgomallis.github.io/vigil_summit_agent/ |
| **API (captação + agente)** | https://vigil-summit-api.onrender.com |
| **Painel Streamlit** | https://vigilsummitagent.streamlit.app/ |

---

## Credenciais de teste

| Sistema | Usuário | Senha |
|---------|---------|-------|
| **Painel Streamlit** | `admin` | `vigil2026` |

Lead de teste pré-carregado: **`ramon@pareto.io`** (status `Inscrito`).

---

## Configuração necessária (primeiro deploy)

### 1. API no Render

1. Acesse [Deploy to Render](https://render.com/deploy?repo=https://github.com/IrgoMallis/vigil_summit_agent).
2. Configure as variáveis:
   - **`VIGIL_API_KEY`** — senha compartilhada com o Streamlit (ex.: `vigil-api-2026`)
   - **`LLM_PROVIDER`** — `anthropic` ou `groq`
   - **`ANTHROPIC_API_KEY`** ou **`GROQ_API_KEY`** — chave do provedor escolhido
3. Valide: `GET https://vigil-summit-api.onrender.com/health` → `"status": "ok"`.

### 2. Streamlit Cloud

Em **Settings → Secrets**:

```toml
VIGIL_API_URL = "https://vigil-summit-api.onrender.com"
VIGIL_API_KEY = "mesma_chave_do_Render"
APP_PASSWORD = "vigil2026"
```

> O LLM roda **na API (Render)**. O painel Streamlit chama `/api/agent/*` remotamente.

---

## Roteiro de teste (15 min)

1. **Captação:** inscreva-se pela [LP](https://irgomallis.github.io/vigil_summit_agent/) → confirme sucesso.
2. **Painel:** login em [Streamlit](https://vigilsummitagent.streamlit.app/) → aba **Leads** → veja o novo lead.
3. **Enriquecimento:** aba **Operar o agente** → **Fase 2 · Enriquecer**.
4. **Engajamento:** **Fase 3 · Engajar + respostas** → leads viram `Confirmado`.
5. **Demo completa:** **🎬 Demo ponta a ponta** → funil inteiro em um clique.
6. **Detalhe:** aba **Leads** → inspecione histórico e simule respostas.

**Alternativa local (recomendada para demo ao vivo):**

```powershell
cd vigil_summit_agent
copy .env.example .env
# Preencha ANTHROPIC_API_KEY ou GROQ_API_KEY
py -X utf8 database.py
py run_dev.py
```

- LP: http://localhost:8080  
- Painel: http://localhost:8501  

---

## Integração LLM (critério do case)

| Provedor | Variáveis | Onde obter chave |
|----------|-----------|------------------|
| **Anthropic (recomendado)** | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) |
| **Groq (free tier)** | `LLM_PROVIDER=groq` + `GROQ_API_KEY` | [console.groq.com](https://console.groq.com/) |

Instruções detalhadas no [README § Integração com LLM](https://github.com/IrgoMallis/vigil_summit_agent#integração-com-llm-anthropic-ou-groq).

---

## O que a solução entrega

- Funil completo: Captação → Enriquecimento → Engajamento → Follow-up
- Réguas pré/pós personalizadas + gatilho de compromisso + classificação de intenção (LLM)
- Memória de contexto em `interaction_logs`
- Painel com KPIs, funil, operação do agente e login multiusuário
- Documentação técnica completa (README — 6 seções + bônus escala)
- Scheduler automático de réguas na API (`ENABLE_SCHEDULER=true` no Render)

---

## Contato

Dúvidas sobre o case: **gabriel@pareto.io**  
E-mail de teste sugerido no enunciado: **ramon@pareto.io**
