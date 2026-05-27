# Click Insight AI — Guia de Deploy (Streamlit Community Cloud)

**Custo:** R$ 0,00 (grátis).
**Tempo estimado:** 15-30 minutos no primeiro deploy.
**Hibernação:** o app dorme após ~30 min sem uso; primeiro acesso depois leva ~5-10s para acordar.

> Migração futura para plano pago (Render Starter US$ 7/mês, sem hibernação): o arquivo `render.yaml` já está pronto. Quando quiser, seguimos esse caminho.

---

## Antes de começar — você vai precisar de:

1. Conta no **GitHub** (gratuita) — https://github.com/signup
2. Conta no **Streamlit Community Cloud** (loga via GitHub) — https://share.streamlit.io
3. **Git** instalado — https://git-scm.com/download/win
4. As chaves: HubSpot Token, Zendesk Token, Zendesk Email, Claude API Key

---

## Fase 1 — Criar repositório PÚBLICO no GitHub

1. Acesse https://github.com/new
2. Repository name: `click-insight-ai`
3. Marque **Public** (necessário para o plano grátis do Streamlit Cloud).
   - Por que é seguro: nenhum segredo está no código. Eles ficam em `st.secrets` no painel da Streamlit Cloud. O `auth_config.yaml` contém apenas hashes bcrypt (irreversíveis).
   - O que ficará visível: a estrutura do código, a lógica de oportunidades, o dicionário de equipe. Para um MVP interno, geralmente é aceitável.
4. **NÃO** marque "Initialize with README" (já temos os arquivos).
5. Clique em **Create repository**.
6. Copie a URL HTTPS (ex.: `https://github.com/seu-usuario/click-insight-ai.git`).

---

## Fase 2 — Subir o código

Abra o PowerShell em `C:\IA_Projects\P1`:

```powershell
cd C:\IA_Projects\P1

# Inicializa o Git (só na primeira vez)
git init
git branch -M main

# CRÍTICO: confira que .env NÃO está na lista
git status
# Se aparecer .env ou .streamlit/secrets.toml na lista de "to be committed", PARE
# e me avise. Eles têm que estar no .gitignore.

# Primeiro commit
git add .
git commit -m "Initial deploy: Click Insight AI v1"

# Conecta no GitHub e faz push
git remote add origin https://github.com/SEU-USUARIO/click-insight-ai.git
git push -u origin main
```

Quando o GitHub pedir senha, use um **Personal Access Token** (não a senha da conta):
- https://github.com/settings/tokens → **Generate new token (classic)** → marque o escopo `repo`.

---

## Fase 3 — Deploy no Streamlit Community Cloud

1. Acesse https://share.streamlit.io
2. Login com sua conta do GitHub
3. Autorize o Streamlit a acessar seus repositórios
4. Clique em **New app**
5. Preencha:
   - **Repository:** `seu-usuario/click-insight-ai`
   - **Branch:** `main`
   - **Main file path:** `integracao.py`
   - **App URL:** escolha um slug, ex: `click-insight-clickdigital` (vai virar `https://click-insight-clickdigital.streamlit.app`)
6. Clique em **Advanced settings**
7. Em **Python version**, selecione `3.11`
8. Em **Secrets**, monte e cole o bloco TOML com os valores do seu arquivo local `.env` (esse arquivo NAO esta neste repositorio, fica so na sua maquina). O formato eh:

```toml
HUBSPOT_TOKEN = "<valor do HUBSPOT_TOKEN do .env>"
ZENDESK_SUBDOMAIN = "<valor do ZENDESK_SUBDOMAIN>"
ZENDESK_EMAIL = "<valor do ZENDESK_EMAIL>"
ZENDESK_TOKEN = "<valor do ZENDESK_TOKEN>"
ANTHROPIC_API_KEY = "<valor do ANTHROPIC_API_KEY>"
CLAUDE_MODEL = "claude-sonnet-4-5"
STREAMLIT_AUTH_COOKIE_KEY = "<gerar com o comando abaixo>"
```

NUNCA cole valores reais aqui no repositorio. Copie do `.env` local para o painel Secrets do Streamlit Cloud.

Para gerar a `STREAMLIT_AUTH_COOKIE_KEY` (uma vez só), rode no PowerShell:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Cole a saída no campo correspondente.

9. Clique em **Deploy!**
10. Aguarde 3-5 minutos. A primeira instalação de dependências leva mais.

---

## Fase 4 — Primeiro acesso

1. Quando o status mudar para verde, acesse a URL do seu app (ex.: `https://click-insight-clickdigital.streamlit.app`).
2. Faça login com:
   - **Usuário:** `gleiberson`
   - **Senha:** `ClickInsight2026!`
3. **TROQUE A SENHA NO MESMO DIA** — siga a seção abaixo.

---

## Trocar senha ou adicionar novo usuário

1. Na sua máquina, na pasta do projeto:
   ```powershell
   python gerar_hash.py
   ```
2. Digite a senha desejada (>= 12 caracteres).
3. Copie o hash bcrypt que o script imprime.
4. Abra `auth_config.yaml` e cole o hash no campo `password` do usuário, ou adicione um novo bloco:
   ```yaml
   credentials:
     usernames:
       maria:
         email: maria@clickdigital.com.br
         name: Maria Silva
         password: $2b$12$...hash_aqui...
         roles: [user]
   ```
5. Commit e push:
   ```powershell
   git add auth_config.yaml
   git commit -m "Update users"
   git push
   ```
6. O Streamlit Cloud faz redeploy automático em ~1-2 min.

---

## Compartilhando com a equipe

- URL pública do app (qualquer pessoa com a URL pode tentar logar, mas só quem tem usuário/senha entra).
- Crie um usuário por pessoa no `auth_config.yaml` e mande a senha temporária via WhatsApp/Slack — peça para trocarem no primeiro login.
- O Streamlit Cloud não tem reset de senha automatizado. Para resetar, você gera um novo hash e atualiza o YAML.

---

## Atualizando o app no futuro

Sempre que você (ou eu) ajustar o código:
```powershell
cd C:\IA_Projects\P1
git add .
git commit -m "Descrição da mudança"
git push
```

O Streamlit Cloud faz redeploy automático em ~2 minutos.

---

## Limites do plano gratuito (importante saber):

| Recurso | Limite Free | Quando vira problema |
|---|---|---|
| RAM | 1 GB | App fica lento com 5+ usuários simultâneos |
| CPU | Compartilhado | Picos podem deixar travado |
| Apps por conta | 1 ativo | Não tem outro Streamlit grátis na mesma conta |
| Hibernação | Após ~30 min ocioso | Primeiro acesso do dia leva 5-10s |
| Repositório | Público obrigatório no free | Já tratado |
| Domínio próprio | Não suportado no free | Vai ser `*.streamlit.app` |
| Logs | Apenas em tempo real | Sem histórico além da sessão |

**Conclusão honesta:** funciona perfeitamente para um piloto com 5-10 usuários internos. Se virar ferramenta de uso diário pesado da equipe, migrar para Render Starter US$ 7/mês (sem hibernação, domínio próprio, repo privado) vai ser um upgrade natural.

---

## Migrar para Render Starter (quando o piloto for um sucesso)

Já está tudo pronto. O `render.yaml` está no repo. Passos:

1. Crie conta no Render: https://dashboard.render.com/register
2. **New + → Blueprint** → conecte o mesmo repo
3. Render lê o `render.yaml` automaticamente
4. Configure as mesmas 7 variáveis no painel (Environment)
5. Aponte seu DNS (`insight.clickdigital.com.br`) para o Render quando quiser

Você pode rodar Render e Streamlit Cloud em paralelo durante a transição — usuários acessam pelo domínio próprio, e o app no Streamlit Cloud vira backup grátis.

---

## Problemas comuns

**Build falha com "ModuleNotFoundError"**
→ Verifique que `requirements.txt` está commitado e contém todas as libs.

**"STREAMLIT_AUTH_COOKIE_KEY não configurado"**
→ Volte em Settings → Secrets e confirme que a chave está lá com 32+ caracteres.

**Login não persiste (cai toda hora)**
→ Cookie key mudou entre deploys, ou está vazia. Use sempre o mesmo valor.

**App muito lento ao acordar**
→ Normal no free. Considere o plano pago se virar gargalo.

**Erro 403/CORS no HubSpot**
→ Token expirou ou foi revogado. Gere um novo Private App no HubSpot e atualize o secret.

---

## Próximos passos sugeridos

1. **Hoje:** seguir Fase 1-4, app no ar.
2. **Esta semana:** trocar senha temporária, cadastrar usuários da equipe.
3. **2 semanas:** medir engajamento. Quantas consultas/dia? Quantos usuários ativos?
4. **Mês 1:** se uso for diário com 5+ pessoas, migrar para Render Starter ou Streamlit Cloud Teams.
5. **Quando migrar:** definir subdomínio (`insight.clickdigital.com.br`?), domínio aponta para Render.
