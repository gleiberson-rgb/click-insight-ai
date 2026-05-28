"""
Click Insight AI - Dashboard RevOps Premium v2
==================================================
Camadas:
  1. Integracoes (HubSpot + Zendesk) - dados brutos
  2. Inteligencia deterministica em Python (LTV, saude, timeline, analise
     tematica de tickets, diagnostico operacional, segmento, oportunidades,
     health score)
  3. IA Claude - apenas sintese consultiva (diagnostico + recomendacao + WhatsApp)
  4. UI Streamlit em secoes executivas + graficos Plotly
  5. Export PDF executivo com ReportLab

Criterios de classificacao:
  VIP:     receita >= R$ 8.000 OU plano Platina (ticket >= R$ 249/mes)
  PREMIUM: receita >= R$ 3.000 OU plano Ouro    (ticket >= R$ 199/mes)

Observacao sobre LTV: detecta pagamento anual antecipado para nao inflar
o ticket medio mensal. Heuristica: ticket bruto > R$ 500 com < 12 meses
de relacionamento vira receita/12.
"""

import os
import json
import unicodedata
import requests
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from collections import Counter
from io import BytesIO
from dateutil import parser as dtparser

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    import yaml
    import streamlit_authenticator as stauth
    AUTH_DISPONIVEL = True
except ImportError:
    AUTH_DISPONIVEL = False

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage,
)

# ============================================================
# CONFIGURACOES E CHAVES
# ============================================================
# Todas as credenciais vem de st.secrets (Streamlit Cloud) ou variaveis de ambiente
# (Render/local). NAO commitar segredos no codigo.
def _get_secret(nome, default=""):
    # Streamlit Cloud expoe st.secrets; em outros lugares cai pra os.environ.
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass
    return os.environ.get(nome, default)

HUBSPOT_TOKEN = _get_secret("HUBSPOT_TOKEN")
ZENDESK_SUBDOMAIN = _get_secret("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = _get_secret("ZENDESK_EMAIL")
ZENDESK_TOKEN = _get_secret("ZENDESK_TOKEN")
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get_secret("CLAUDE_MODEL", "claude-sonnet-4-5")

DICIONARIO_EQUIPE_RESERVA = {
    "351788846": "Gleiberson (Pre-Vendedor)",
    "40698050": "Consultor Betel",
    "209275297": "Atendente Click",
    "689087808": "Gestor Comercial",
    "1652636290": "Equipe Comercial",
    "137216590": "Consultoria Click",
}

APP_NAME = "Click Insight AI"
BRAND_PRIMARY = "#012761"

PLANOS_GESTAOCLICK = {
    "PLATINA": {"min_ticket": 249, "label": "Platina", "badge": "badge-purple"},
    "OURO":    {"min_ticket": 199, "label": "Ouro",    "badge": "badge-blue"},
    "PRATA":   {"min_ticket": 129, "label": "Prata",   "badge": "badge-gray"},
    "BRONZE":  {"min_ticket":  79, "label": "Bronze",  "badge": "badge-gray"},
}

# Catalogo ClickNotas: hoje vende apenas um plano unico.
PLANOS_CLICKNOTAS = {
    "ESSENCIAL": {"label": "Essencial", "badge": "badge-yellow"},
}

CATEGORIAS_TICKETS = {
    "Fiscal/NF": ["nota", "nfe", "nfse", "nfc", "fiscal", "imposto", "icms", "csosn", "csc", "certificado", "danfe", "sefaz"],
    "Financeiro/Boleto": ["boleto", "cobranca", "pagamento", "receber", "pagar", "conta corrente", "conciliac", "remessa", "retorno", "pix", "cartao", "fluxo de caixa"],
    "Estoque/Produto": ["estoque", "produto", "inventario", "saida", "entrada", "compra", "fornecedor", "kit", "variacao", "grade"],
    "Integracao": ["integrac", "marketplace", "mercado livre", "nuvemshop", "loja integrada", "shopify", "api", "webhook", "sincroniz"],
    "Acesso/Usuario": ["login", "senha", "acesso", "usuario", "permissao", "perfil", "bloqueado"],
    "Performance/Bug": ["lento", "trava", "demora", "carregando", "erro", "bug", "falha", "nao abre", "nao carrega", "indisponivel"],
    "Duvida/Treinamento": ["como ", "duvida", "ajuda", "tutorial", "treinamento", "aprender", "ensinar", "explicar"],
    "Cancelamento": ["cancelar", "cancelamento", "encerrar", "desistir", "rescindir"],
}

# ============================================================
# STREAMLIT SETUP + CSS
# ============================================================
st.set_page_config(page_title=APP_NAME, page_icon="📊", layout="wide")


# ============================================================
# AUTENTICACAO (Login gate)
# ============================================================
def _exigir_login():
    if not AUTH_DISPONIVEL:
        st.error("streamlit-authenticator nao instalado. Rode: pip install streamlit-authenticator")
        st.stop()
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_config.yaml")
    if not os.path.exists(config_path):
        st.error("Arquivo auth_config.yaml nao encontrado.")
        st.stop()
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    cookie_key = _get_secret("STREAMLIT_AUTH_COOKIE_KEY")
    if not cookie_key:
        st.error("STREAMLIT_AUTH_COOKIE_KEY nao configurado nas variaveis de ambiente.")
        st.stop()
    config["cookie"]["key"] = cookie_key
    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )
    try:
        authenticator.login(location="main")
    except Exception as e:
        st.error(f"Erro no login: {e}")
        st.stop()
    auth_status = st.session_state.get("authentication_status")
    nome = st.session_state.get("name", "")
    if auth_status is False:
        st.error("Usuario ou senha incorretos.")
        st.stop()
    if auth_status is None:
        st.info("Faca login para acessar o Click Insight AI.")
        st.stop()
    return True, authenticator, nome


_AUTENTICADO, _AUTH, _NOME_USUARIO = _exigir_login()

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    .stApp { background-color: #F8FAFC; font-family: 'Inter', sans-serif; color: #334155; }
    h1, h2, h3, h4 { font-family: 'Inter', sans-serif; color: #0F172A !important; font-weight: 700; letter-spacing: -0.02em; }
    [data-testid="stSidebar"] { background-color: #0F172A; border-right: none; }
    [data-testid="stSidebar"] * { color: #F8FAFC !important; }
    [data-testid="stSidebar"] button { background-color: #FFFFFF !important; border-radius: 8px !important; border: none !important; }
    [data-testid="stSidebar"] button * { color: #0F172A !important; font-weight: 600; }
    .stTabs [data-baseweb="tab-list"] { gap: 12px; border-bottom: 1px solid #E2E8F0; padding-bottom: 4px; }
    .stTabs [data-baseweb="tab"] { height: 46px; background-color: transparent; border: none; padding: 10px 16px; font-weight: 500; color: #64748B !important; font-size: 15px; }
    .stTabs [data-baseweb="tab"]:hover { color: #0284C7 !important; }
    .stTabs [data-baseweb="tab"][aria-selected="true"] { color: #0F172A !important; font-weight: 600; border-bottom: 2px solid #0F172A !important; }
    .hero { background: linear-gradient(135deg, #0F172A 0%, #012761 100%); color: #F8FAFC; padding: 28px 32px; border-radius: 16px; margin-bottom: 24px; box-shadow: 0 4px 16px rgba(1,39,97,0.18); }
    .hero h2 { color: #FFFFFF !important; margin: 0 0 4px 0; font-size: 28px; font-weight: 800; }
    .hero .sub { color: #CBD5E1; font-size: 14px; margin-bottom: 16px; }
    .section-card { background: #FFFFFF; border-radius: 12px; padding: 24px; border: 1px solid #E2E8F0; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 18px; }
    .section-header { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 700; color: #64748B; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid #F1F5F9; }
    .section-header .dot { width: 8px; height: 8px; border-radius: 50%; background: #0284C7; }
    .kpi-card { background: #FFFFFF; padding: 20px; border-radius: 12px; border: 1px solid #E2E8F0; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 12px; }
    .info-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #F1F5F9; font-size: 14px; }
    .info-row:last-child { border-bottom: none; }
    .info-row .label { color: #64748B; font-weight: 500; }
    .info-row .value { color: #0F172A; font-weight: 600; }
    .insight-card-blue { background: #FFFFFF; padding: 20px; border-radius: 12px; border: 1px solid #E2E8F0; border-left: 5px solid #0284C7; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 16px; }
    .insight-card-green { background: #FFFFFF; padding: 20px; border-radius: 12px; border: 1px solid #E2E8F0; border-left: 5px solid #10B981; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 16px; }
    .insight-card-red { background: #FFFFFF; padding: 20px; border-radius: 12px; border: 1px solid #E2E8F0; border-left: 5px solid #DC2626; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 16px; }
    .insight-card-yellow { background: #FFFFFF; padding: 20px; border-radius: 12px; border: 1px solid #E2E8F0; border-left: 5px solid #F59E0B; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 16px; }
    .badge { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; letter-spacing: 0.03em; margin-right: 6px; margin-bottom: 4px; }
    .badge-light { background: rgba(255,255,255,0.18); color: #FFFFFF; }
    .badge-blue { background: #DBEAFE; color: #1E40AF; }
    .badge-green { background: #DCFCE7; color: #166534; }
    .badge-yellow { background: #FEF3C7; color: #92400E; }
    .badge-red { background: #FEE2E2; color: #991B1B; }
    .badge-gray { background: #E5E7EB; color: #374151; }
    .badge-purple { background: #EDE9FE; color: #5B21B6; }
    .timeline-item { padding: 12px 16px; margin-bottom: 8px; border-radius: 8px; background: #F8FAFC; border-left: 4px solid #94A3B8; }
    .timeline-item.comercial { border-left-color: #0284C7; background: #F0F9FF; }
    .timeline-item.conversao { border-left-color: #10B981; background: #F0FDF4; }
    .timeline-item.suporte { border-left-color: #F59E0B; background: #FFFBEB; }
    .timeline-when { font-size: 11px; color: #64748B; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
    .timeline-title { font-size: 14px; color: #0F172A; font-weight: 600; margin: 2px 0; }
    .timeline-desc { font-size: 12.5px; color: #475569; }
    .opp-card { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; display: flex; align-items: flex-start; gap: 12px; }
    .opp-card .opp-icon { flex-shrink: 0; width: 38px; height: 38px; border-radius: 8px; background: #DBEAFE; color: #1E40AF; display: flex; align-items: center; justify-content: center; font-weight: 700; }
    .opp-card.alta { border-left: 4px solid #DC2626; }
    .opp-card.alta .opp-icon { background: #FEE2E2; color: #991B1B; }
    .opp-card.media { border-left: 4px solid #F59E0B; }
    .opp-card.media .opp-icon { background: #FEF3C7; color: #92400E; }
    .opp-card.critica { border-left: 4px solid #7C2D12; background: #FFF7ED; }
    .opp-card.critica .opp-icon { background: #FED7AA; color: #7C2D12; }
    .opp-title { font-weight: 700; font-size: 14px; color: #0F172A; margin: 0 0 3px 0; }
    .opp-desc { font-size: 12.5px; color: #475569; }
    .whatsapp-box { background-color: #0F172A; color: #E2E8F0 !important; padding: 20px; border-radius: 10px; border: 1px solid #1E293B; font-family: monospace; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-wrap: break-word; margin-bottom: 15px; }
    .whatsapp-box * { color: #E2E8F0 !important; }
    header { background-color: transparent !important; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "ultimo_relatorio" not in st.session_state:
    st.session_state.ultimo_relatorio = None

# ============================================================
# UTILIDADES
# ============================================================
def normalizar(texto):
    if not texto:
        return ""
    s = str(texto).lower()
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")
    return s


def parse_data(valor):
    if not valor:
        return None
    try:
        if isinstance(valor, (int, float)):
            return datetime.fromtimestamp(int(valor) / 1000, tz=timezone.utc)
        s = str(valor).strip()
        if s.isdigit() and len(s) >= 10:
            ts = int(s)
            if len(s) > 10:
                ts = ts / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        dt = dtparser.parse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def humanizar_delta(dt):
    if not dt:
        return "-"
    agora = datetime.now(timezone.utc)
    delta = (agora - dt).days
    if delta < 0:
        return "Em " + str(abs(delta)) + " dias"
    if delta == 0:
        return "Hoje"
    if delta == 1:
        return "Ontem"
    if delta < 30:
        return "Há " + str(delta) + " dias"
    if delta < 365:
        meses = delta // 30
        return "Há " + str(meses) + (" mês" if meses == 1 else " meses")
    anos = delta // 365
    return "Há " + str(anos) + (" ano" if anos == 1 else " anos")


def formatar_brl(valor):
    try:
        s = "R$ {:,.2f}".format(valor)
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def to_float(v):
    try:
        if v in (None, "", "null"):
            return 0.0
        return float(v)
    except Exception:
        return 0.0


# ============================================================
# INTEGRACAO
# ============================================================
def traduzir_id_por_api(owner_id):
    if not owner_id or not str(owner_id).isdigit():
        return "Não informado"
    str_id = str(owner_id).strip()
    try:
        r = requests.get(
            "https://api.hubapi.com/crm/v3/owners/" + str_id,
            headers={"Authorization": "Bearer " + HUBSPOT_TOKEN}, timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            nome = (data.get("firstName", "") + " " + data.get("lastName", "")).strip()
            if nome:
                return nome
    except Exception:
        pass
    return DICIONARIO_EQUIPE_RESERVA.get(str_id, "Colaborador (ID: " + str_id + ")")


def buscar_dados_comerciais_hubspot(identificador):
    url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    headers = {"Authorization": "Bearer " + HUBSPOT_TOKEN, "Content-Type": "application/json"}
    propriedades = [
        "firstname", "lastname", "email", "company", "lifecyclestage", "total_revenue",
        "hubspot_owner_id", "responsavel_pelo_contato", "link_intranet", "phone", "mobilephone",
        "createdate", "hs_lifecyclestage_customer_date", "closedate",
        "notes_last_contacted", "website", "city", "state", "industry",
        # Detectar produto: hs_all_assigned_business_unit_ids vem preenchido SOMENTE
        # para ClickNotas. Vazio = GestaoClick (default da empresa).
        "hs_all_assigned_business_unit_ids",
    ]
    if "@" in identificador:
        payload = {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": identificador}]}], "properties": propriedades, "limit": 1}
    elif "http" in identificador or "/" in identificador:
        payload = {"filterGroups": [{"filters": [{"propertyName": "link_intranet", "operator": "EQ", "value": identificador}]}], "properties": propriedades, "limit": 1}
    else:
        payload = {"query": identificador, "properties": propriedades, "limit": 1}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=12)
        if r.status_code == 200 and r.json().get("results"):
            props = r.json()["results"][0]["properties"]
            props["responsavel_pelo_contato"] = traduzir_id_por_api(props.get("responsavel_pelo_contato"))
            props["hubspot_owner_id"] = traduzir_id_por_api(props.get("hubspot_owner_id"))
            return props
        return {"_status": "vazio", "Aviso": "Nenhum registro localizado."}
    except Exception as e:
        return {"_status": "erro", "Erro HubSpot": str(e)}


# Lista de primeiros nomes/sobrenomes muito comuns no Brasil.
# Se um nome eh composto APENAS por palavras dessa lista, consideramos generico demais
# para fazer busca por nome no Zendesk (risco alto de falso positivo).
NOMES_MUITO_COMUNS = {
    "joao", "joao", "maria", "jose", "ana", "pedro", "paulo", "lucas", "carlos",
    "antonio", "francisco", "luiz", "luis", "felipe", "bruno", "marcos", "marcio",
    "thiago", "tiago", "rafael", "diego", "matheus", "gabriel", "rodrigo",
    "fernando", "ricardo", "andre", "leandro", "vinicius", "daniel", "marcelo",
    "alexandre", "eduardo", "roberto", "henrique", "guilherme", "vitor", "victor",
    "julio", "renato", "gustavo", "raphael", "raul", "samuel", "simone", "patricia",
    "fernanda", "juliana", "amanda", "camila", "carla", "claudia", "cristina",
    "daniela", "debora", "eliane", "isabela", "isabel", "joana", "leticia",
    "luciana", "marcia", "mariana", "monica", "natalia", "renata", "sandra",
    "silvana", "tatiana", "vanessa", "viviane",
    # sobrenomes muito comuns
    "silva", "santos", "oliveira", "souza", "sousa", "lima", "pereira", "costa",
    "rodrigues", "almeida", "nascimento", "carvalho", "gomes", "fernandes",
    "ribeiro", "ferreira", "barbosa", "cardoso", "rocha", "dias", "monteiro",
    "mendes", "moreira", "araujo", "barros", "freitas", "martins", "alves",
    "correia", "correa", "pinto", "moura", "campos", "teixeira", "machado",
    "andrade", "vieira", "duarte", "castro", "melo", "mello", "ramos",
}

LIMITE_RESULTADOS_BUSCA_NOME = 8  # Acima disso, descarta como falso positivo provavel


def _nome_eh_generico(nome_completo):
    """True se TODAS as palavras do nome estao na lista de comuns,
    OU se o nome tem menos de 2 palavras, OU comprimento total < 10 chars."""
    if not nome_completo:
        return True
    partes = nome_completo.strip().split()
    if len(partes) < 2:
        return True
    if len(nome_completo.strip()) < 10:
        return True
    todas_comuns = all(normalizar(p) in NOMES_MUITO_COMUNS for p in partes)
    return todas_comuns


def buscar_tickets_suporte_zendesk(email="", nome="", telefone="",
                                    permitir_fallback_nome=True):
    """Busca tickets no Zendesk com prioridade: email > telefone > nome.

    Args:
        email: e-mail do contato (busca mais confiavel).
        nome: nome completo do contato (usado so como fallback).
        telefone: telefone do contato (busca confiavel).
        permitir_fallback_nome: se False, NAO cai para busca por nome quando
            email/telefone nao retornam nada. Use False quando o usuario buscou
            por email explicito -- a resposta correta nesse caso eh "zero tickets".

    Cada ticket retornado vem com o campo `match_por` indicando como foi encontrado:
    'email' | 'telefone' | 'nome'. Quando for 'nome', a UI deve avisar que pode
    haver falsos positivos.
    """
    auth = (ZENDESK_EMAIL + "/token", ZENDESK_TOKEN)
    tickets = []
    metodo_match = None
    base_url = "https://" + ZENDESK_SUBDOMAIN + ".zendesk.com/api/v2/search.json"

    # 1) Por email (autoritativo)
    if email and "@" in email:
        try:
            r = requests.get(base_url,
                             params={"query": "type:ticket requester:" + email},
                             auth=auth, timeout=12)
            if r.status_code == 200:
                tickets = r.json().get("results", [])
                if tickets:
                    metodo_match = "email"
        except Exception:
            pass

    # 2) Por telefone (confiavel se telefone tem ao menos 8 digitos)
    if not tickets and telefone:
        num_limpo = "".join(filter(str.isdigit, telefone))
        if len(num_limpo) >= 8:
            if num_limpo.startswith("55"):
                query_phone = 'type:ticket ("' + num_limpo + '" OR "' + num_limpo[2:] + '")'
            elif len(num_limpo) >= 10:
                query_phone = 'type:ticket ("' + num_limpo + '" OR "55' + num_limpo + '")'
            else:
                query_phone = 'type:ticket "' + num_limpo + '"'
            try:
                r = requests.get(base_url, params={"query": query_phone},
                                 auth=auth, timeout=12)
                if r.status_code == 200:
                    tickets = r.json().get("results", [])
                    if tickets:
                        metodo_match = "telefone"
            except Exception:
                pass

    # 3) Por nome -- APENAS quando permitido E nome eh especifico o suficiente
    if not tickets and permitir_fallback_nome and nome and nome.strip():
        nome_limpo = nome.strip()
        if not _nome_eh_generico(nome_limpo):
            try:
                r = requests.get(base_url,
                                 params={"query": 'type:ticket requester:"' + nome_limpo + '"'},
                                 auth=auth, timeout=12)
                if r.status_code == 200:
                    candidatos = r.json().get("results", [])
                    # Se a busca por nome trouxe muitos resultados, eh quase certo que
                    # sao varios homonimos misturados. Descarta -- melhor 0 que 50 errados.
                    if 0 < len(candidatos) <= LIMITE_RESULTADOS_BUSCA_NOME:
                        tickets = candidatos
                        metodo_match = "nome"
            except Exception:
                pass

    lista = []
    for t in tickets:
        lista.append({
            "id": t.get("id"),
            "assunto": t.get("subject") or "Sem assunto",
            "status": (t.get("status") or "").lower(),
            "prioridade": (t.get("priority") or "normal").lower(),
            "criado_em": t.get("created_at"),
            "atualizado_em": t.get("updated_at"),
            "descricao": (t.get("description") or "")[:400],
            "match_por": metodo_match,
        })
    return lista


# ============================================================
# INTELIGENCIA
# ============================================================
# ============================================================
# PRODUTO E ROTEAMENTO DE ACOES
# ============================================================
# A Click Digital opera com produtos distintos que tem ciclos pos-venda diferentes:
#   - GestaoClick: ERP principal. Carteira de CS atua nos clientes Ouro/Platina.
#                  Clientes Bronze/Prata sao atendidos pelo Consultor Responsavel.
#   - ClickNotas: emissor fiscal standalone. NAO tem CS dedicado em momento algum --
#                 todo ciclo (lead, ativacao, retencao) eh do Consultor Responsavel.
#   - Leads (qualquer produto): NUNCA acionam CS. Sao tratados por Pre-vendas/Consultor.

def detectar_produto(properties):
    """Infere o produto a partir das propriedades do HubSpot.
    Retorna: 'CLICKNOTAS' | 'GESTAOCLICK'.

    REGRA OFICIAL (Click Digital):
        - Se hs_all_assigned_business_unit_ids estiver PREENCHIDO -> ClickNotas.
        - Se estiver VAZIO -> GestaoClick (produto principal, default da empresa).
    """
    bu = (properties.get("hs_all_assigned_business_unit_ids") or "").strip()
    if bu and bu.lower() not in ("null", "none", "0"):
        return "CLICKNOTAS"
    return "GESTAOCLICK"


def definir_responsavel_acao(properties, ltv, produto):
    """Decide quem deve executar a proxima acao baseado em produto + estagio + plano.
    Retorna dict: {area, justificativa, evitar_cs}.
    """
    is_cliente = ltv["is_cliente"]
    plano = ltv.get("plano_chave")

    # Regra 1: ClickNotas NUNCA tem CS, em nenhuma fase
    if produto == "CLICKNOTAS":
        return {
            "area": "Consultor Responsavel",
            "justificativa": "ClickNotas e produto sem CS dedicado. Todo ciclo (lead, ativacao, retencao, expansao) e do consultor responsavel pelo contato.",
            "evitar_cs": True,
        }

    # Regra 2: Lead (qualquer produto) NUNCA aciona CS
    if not is_cliente:
        return {
            "area": "Pre-vendas / Consultor",
            "justificativa": "Lead ainda nao virou cliente. CS so atua apos a venda. Quem deve agir agora e a equipe comercial (pre-vendedor + consultor responsavel).",
            "evitar_cs": True,
        }

    # Regra 3: Cliente GestaoClick Ouro/Platina -> CS dedicado
    if plano in ("OURO", "PLATINA"):
        return {
            "area": "Customer Success (CS)",
            "justificativa": "Cliente " + (plano.title()) + " entra na carteira de CS (alto ticket, atencao dedicada).",
            "evitar_cs": False,
        }

    # Regra 4: Cliente GestaoClick Bronze/Prata -> Consultor responsavel
    if plano in ("BRONZE", "PRATA"):
        return {
            "area": "Consultor Responsavel",
            "justificativa": "Clientes Bronze/Prata sao atendidos pelo consultor responsavel pelo fechamento. CS so atua sob demanda especifica (escalation).",
            "evitar_cs": True,
        }

    # Default conservador: consultor
    return {
        "area": "Consultor Responsavel",
        "justificativa": "Sem indicacao clara de plano ou estagio. Consultor responsavel pelo contato e o ponto de contato padrao.",
        "evitar_cs": True,
    }


def inferir_plano(ticket_mensal, produto="GESTAOCLICK", is_cliente=False):
    """Infere o plano. Para ClickNotas, retorna Essencial (catalogo de plano unico).
    Para GestaoClick, infere pela faixa de ticket mensal."""
    if produto == "CLICKNOTAS":
        if is_cliente or ticket_mensal > 0:
            info = PLANOS_CLICKNOTAS["ESSENCIAL"]
            return {"chave": "ESSENCIAL", "label": info["label"], "badge": info["badge"]}
        return {"chave": None, "label": "Sem plano ativo", "badge": "badge-gray"}
    # GestaoClick (default)
    if ticket_mensal >= PLANOS_GESTAOCLICK["PLATINA"]["min_ticket"]:
        chave = "PLATINA"
    elif ticket_mensal >= PLANOS_GESTAOCLICK["OURO"]["min_ticket"]:
        chave = "OURO"
    elif ticket_mensal >= PLANOS_GESTAOCLICK["PRATA"]["min_ticket"]:
        chave = "PRATA"
    elif ticket_mensal > 0:
        chave = "BRONZE"
    else:
        return {"chave": None, "label": "Sem plano ativo", "badge": "badge-gray"}
    info = PLANOS_GESTAOCLICK[chave]
    return {"chave": chave, "label": info["label"], "badge": info["badge"]}


def calcular_ltv(properties, produto="GESTAOCLICK"):
    """Calcula LTV com heuristica anti-distorcao de pagamento anual antecipado.

    Se o cliente paga anuidade (ex: Platina Anual R$ 5170), dividir o
    total_revenue acumulado pelos poucos meses de relacionamento inflaria
    artificialmente o ticket mensal. Regra:
      - ticket bruto = receita / meses
      - Se ticket bruto > R$ 500 E meses < 12 E receita >= 800
        -> trata como anuidade: ticket = receita / 12
    """
    receita = to_float(properties.get("total_revenue"))
    createdate = parse_data(properties.get("createdate"))
    cliente_desde = parse_data(properties.get("hs_lifecyclestage_customer_date"))
    base_data = cliente_desde or createdate
    meses = max(1.0, (datetime.now(timezone.utc) - base_data).days / 30.0) if base_data else 0.0
    ticket_bruto = (receita / meses) if meses > 0 else 0.0

    LIMITE_TICKET_REALISTA = 500.0
    if ticket_bruto > LIMITE_TICKET_REALISTA and meses < 12 and receita >= 800:
        ticket_mensal = round(receita / 12.0, 2)
        ticket_observacao = "Estimado como anuidade (receita / 12 meses)"
    else:
        ticket_mensal = round(ticket_bruto, 2)
        ticket_observacao = ""

    ltv_12m = ticket_mensal * 12
    ltv_24m = ticket_mensal * 24
    ltv_36m = ticket_mensal * 36
    lifecycle_tmp = (properties.get("lifecyclestage") or "").lower()
    is_cliente_tmp = "customer" in lifecycle_tmp or "cliente" in lifecycle_tmp
    plano = inferir_plano(ticket_mensal, produto=produto, is_cliente=is_cliente_tmp)
    lifecycle = (properties.get("lifecyclestage") or "").lower()
    is_cliente = "customer" in lifecycle or "cliente" in lifecycle

    if is_cliente:
        if receita >= 8000 or plano["chave"] == "PLATINA":
            categoria, badge_classe, categoria_label = "VIP", "badge-purple", "Cliente VIP — Alto LTV"
        elif receita >= 3000 or plano["chave"] == "OURO":
            categoria, badge_classe, categoria_label = "PREMIUM", "badge-blue", "Cliente Premium"
        elif receita > 0:
            categoria, badge_classe, categoria_label = "PADRAO", "badge-gray", "Cliente Padrão"
        else:
            categoria, badge_classe, categoria_label = "SEM_HISTORICO", "badge-yellow", "Cliente sem receita registrada"
    else:
        if receita > 0:
            categoria, badge_classe, categoria_label = "LEAD_ESTRATEGICO", "badge-blue", "Lead Estratégico"
        else:
            categoria, badge_classe, categoria_label = "PROSPECT", "badge-gray", "Prospect inicial"

    return {
        "receita_acumulada": receita,
        "receita_acumulada_fmt": formatar_brl(receita),
        "meses_relacionamento": round(meses, 1),
        "ticket_medio_mensal": ticket_mensal,
        "ticket_medio_mensal_fmt": formatar_brl(ticket_mensal),
        "ticket_observacao": ticket_observacao,
        "ltv_projetado_12m": round(ltv_12m, 2),
        "ltv_projetado_12m_fmt": formatar_brl(ltv_12m),
        "ltv_projetado_24m": round(ltv_24m, 2),
        "ltv_projetado_24m_fmt": formatar_brl(ltv_24m),
        "ltv_projetado_36m": round(ltv_36m, 2),
        "ltv_projetado_36m_fmt": formatar_brl(ltv_36m),
        "categoria": categoria, "categoria_label": categoria_label,
        "badge_classe": badge_classe, "is_cliente": is_cliente,
        "plano_chave": plano["chave"], "plano_label": plano["label"], "plano_badge": plano["badge"],
    }


def classificar_saude(properties, tickets, ltv):
    motivos = []
    nivel = "SAUDAVEL"
    abertos = [t for t in tickets if t["status"] in ("new", "open", "pending", "hold")]
    urgentes = [t for t in tickets if t["prioridade"] in ("urgent", "high") and t["status"] not in ("solved", "closed")]
    hoje = datetime.now(timezone.utc)
    recentes_30d = []
    for t in tickets:
        dt = parse_data(t.get("criado_em"))
        if dt and (hoje - dt).days <= 30:
            recentes_30d.append(t)
    if ltv["is_cliente"]:
        if len(recentes_30d) >= 4:
            nivel = "ALTO_RISCO"
            motivos.append(str(len(recentes_30d)) + " chamados nos últimos 30 dias")
        elif len(urgentes) >= 1:
            nivel = "ATENCAO"
            motivos.append(str(len(urgentes)) + " ticket(s) de alta prioridade em aberto")
        elif len(abertos) >= 3:
            nivel = "ATENCAO"
            motivos.append(str(len(abertos)) + " chamados pendentes acumulados")
        else:
            motivos.append("Sem sinais de churn — relacionamento estável")
    else:
        lifecycle = (properties.get("lifecyclestage") or "").lower()
        if "opportunity" in lifecycle:
            nivel = "OPORTUNIDADE"
            motivos.append("Oportunidade aberta no funil — janela ativa de conversão")
        elif "lead" in lifecycle or "subscriber" in lifecycle:
            nivel = "OPORTUNIDADE"
            motivos.append("Lead engajado — qualificar e mover no funil")
        else:
            motivos.append("Contato sem indicadores de risco")
    mapa = {
        "ALTO_RISCO":   ("Alto risco de churn", "badge-red", "insight-card-red"),
        "ATENCAO":      ("Atenção", "badge-yellow", "insight-card-yellow"),
        "OPORTUNIDADE": ("Oportunidade ativa", "badge-blue", "insight-card-blue"),
        "SAUDAVEL":     ("Saudável", "badge-green", "insight-card-green"),
    }
    label, badge, card = mapa[nivel]
    return {
        "nivel": nivel, "label": label, "badge_classe": badge, "card_classe": card,
        "motivos": motivos, "tickets_abertos": len(abertos),
        "tickets_urgentes": len(urgentes), "tickets_30d": len(recentes_30d),
    }


def montar_timeline_unificada(properties, tickets):
    eventos = []
    dt_create = parse_data(properties.get("createdate"))
    if dt_create:
        eventos.append({"data": dt_create, "origem": "HubSpot", "tipo": "comercial",
                        "titulo": "Contato criado no CRM",
                        "descricao": "Lead capturado no funil comercial"})
    dt_cliente = parse_data(properties.get("hs_lifecyclestage_customer_date"))
    if dt_cliente:
        eventos.append({"data": dt_cliente, "origem": "HubSpot", "tipo": "conversao",
                        "titulo": "Convertido em Cliente",
                        "descricao": "Marco de fechamento — virou cliente Click"})
    dt_close = parse_data(properties.get("closedate"))
    if dt_close and (not dt_cliente or abs((dt_close - dt_cliente).days) > 1):
        eventos.append({"data": dt_close, "origem": "HubSpot", "tipo": "comercial",
                        "titulo": "Data de fechamento registrada no negócio",
                        "descricao": "Marco de venda no CRM"})
    dt_contato = parse_data(properties.get("notes_last_contacted"))
    if dt_contato:
        eventos.append({"data": dt_contato, "origem": "HubSpot", "tipo": "comercial",
                        "titulo": "Último contato comercial registrado",
                        "descricao": "Atividade da equipe de vendas"})
    for t in tickets:
        dt = parse_data(t.get("criado_em"))
        if dt:
            eventos.append({"data": dt, "origem": "Zendesk", "tipo": "suporte",
                            "titulo": "Ticket #" + str(t["id"]) + " aberto",
                            "descricao": t["assunto"] + " — status: " + t["status"]})
    eventos.sort(key=lambda x: x["data"], reverse=True)
    for e in eventos:
        e["quando"] = humanizar_delta(e["data"])
        e["data_iso"] = e["data"].strftime("%d/%m/%Y")
    return eventos


def agregar_status_tickets(tickets):
    mapa = {"new": "Novo", "open": "Aberto", "pending": "Pendente",
            "hold": "Em espera", "solved": "Resolvido", "closed": "Fechado"}
    # Mantemos as chaves sem acento porque elas batem com os retornos da API.
    contagem = {}
    for t in tickets:
        s = t["status"]
        rotulo = mapa.get(s, s.title() if s else "Desconhecido")
        contagem[rotulo] = contagem.get(rotulo, 0) + 1
    return contagem


def categorizar_ticket(assunto, descricao):
    texto = normalizar(assunto + " " + descricao)
    for cat, keywords in CATEGORIAS_TICKETS.items():
        for kw in keywords:
            if kw in texto:
                return cat
    return "Outros"


def analisar_tickets(tickets):
    categorias = {}
    gravidade_alta = 0
    hoje = datetime.now(timezone.utc)
    por_mes = Counter()
    assuntos_repetidos = Counter()
    for t in tickets:
        cat = categorizar_ticket(t["assunto"], t["descricao"])
        categorias[cat] = categorias.get(cat, 0) + 1
        if t["prioridade"] in ("urgent", "high"):
            gravidade_alta += 1
        dt = parse_data(t.get("criado_em"))
        if dt:
            meses_atras = (hoje.year - dt.year) * 12 + (hoje.month - dt.month)
            if 0 <= meses_atras < 12:
                label = dt.strftime("%b/%y")
                por_mes[label] += 1
        assunto_norm = normalizar(t["assunto"])[:50]
        assuntos_repetidos[assunto_norm] += 1
    recorrentes = [(a, c) for a, c in assuntos_repetidos.items() if c >= 2]
    recorrentes.sort(key=lambda x: -x[1])
    serie_mensal = []
    for i in range(11, -1, -1):
        ref = hoje - timedelta(days=i * 30)
        label = ref.strftime("%b/%y")
        serie_mensal.append((label, por_mes.get(label, 0)))
    total = len(tickets) or 1
    cat_principal = max(categorias.items(), key=lambda x: x[1])[0] if categorias else None
    return {
        "categorias": categorias,
        "gravidade_alta": gravidade_alta,
        "gravidade_pct": round((gravidade_alta / total) * 100, 0),
        "cat_principal": cat_principal,
        "serie_mensal": serie_mensal,
        "recorrentes": recorrentes[:5],
        "total": len(tickets),
        "duvida_count": categorias.get("Duvida/Treinamento", 0),
        "bug_count": categorias.get("Performance/Bug", 0),
        "fiscal_count": categorias.get("Fiscal/NF", 0),
        "financeiro_count": categorias.get("Financeiro/Boleto", 0),
        "estoque_count": categorias.get("Estoque/Produto", 0),
        "integracao_count": categorias.get("Integracao", 0),
        "cancelamento_count": categorias.get("Cancelamento", 0),
    }


def diagnosticar_operacao(properties, tickets, an_tickets, ltv):
    if not ltv["is_cliente"]:
        return {"nivel": "NAO_CLIENTE", "label": "Lead / Prospect",
                "perfil": "Ainda não é cliente — análise operacional não se aplica.",
                "sinais": [], "badge": "badge-gray"}
    total = an_tickets["total"]
    ultimo_ticket = None
    for t in tickets:
        dt = parse_data(t.get("criado_em"))
        if dt and (ultimo_ticket is None or dt > ultimo_ticket):
            ultimo_ticket = dt
    dias_sem_ticket = (datetime.now(timezone.utc) - ultimo_ticket).days if ultimo_ticket else 999
    meses_rel = ltv["meses_relacionamento"]
    duvida_pct = round((an_tickets["duvida_count"] / max(total, 1)) * 100, 0)
    bug_pct = round((an_tickets["bug_count"] / max(total, 1)) * 100, 0)
    sinais = []
    if an_tickets["cancelamento_count"] >= 1:
        nivel, label = "RISCO_CANCELAMENTO", "Risco de cancelamento"
        perfil = "Cliente abriu ticket mencionando cancelamento/encerramento. Acionar retenção imediatamente."
        sinais.append(str(an_tickets["cancelamento_count"]) + " ticket(s) mencionando cancelamento")
        badge = "badge-red"
    elif meses_rel < 3 and total >= 5:
        nivel, label = "ONBOARDING_INTENSO", "Onboarding intenso"
        perfil = "Cliente em fase de onboarding — alta demanda inicial é esperada, mas precisa de acompanhamento próximo."
        sinais.append(str(total) + " tickets em menos de 3 meses")
        if duvida_pct >= 50:
            sinais.append(str(int(duvida_pct)) + "% são dúvidas — recomendar treinamento estruturado")
        badge = "badge-yellow"
    elif dias_sem_ticket > 180 and meses_rel > 6:
        nivel, label = "CHURN_SILENCIOSO", "Churn silencioso"
        perfil = "Cliente sem qualquer interação há mais de 6 meses. Risco real de uso interrompido sem cancelamento formal."
        sinais.append("Último ticket há " + str(dias_sem_ticket) + " dias")
        sinais.append("CS deve validar se o cliente ainda usa o sistema ativamente")
        badge = "badge-red"
    elif bug_pct >= 40 and total >= 3:
        nivel, label = "DIFICULDADE_TECNICA", "Dificuldade técnica recorrente"
        perfil = "Cliente enfrentando problemas técnicos persistentes. Pode estar acumulando frustração."
        sinais.append(str(int(bug_pct)) + "% dos tickets são performance/bug")
        if an_tickets["gravidade_alta"] >= 2:
            sinais.append(str(an_tickets["gravidade_alta"]) + " ticket(s) com prioridade alta/urgente")
        badge = "badge-red"
    elif duvida_pct >= 60 and meses_rel > 6:
        nivel, label = "BAIXA_AUTONOMIA", "Baixa autonomia operacional"
        perfil = "Cliente depende muito do suporte para tarefas básicas. Oportunidade de treinamento e Customer Success ativo."
        sinais.append(str(int(duvida_pct)) + "% são dúvidas básicas")
        sinais.append("Investir em capacitação reduz custo de suporte e melhora retenção")
        badge = "badge-yellow"
    elif total > 0 and dias_sem_ticket <= 30:
        nivel, label = "ATIVO_SAUDAVEL", "Ativo e saudável"
        perfil = "Cliente operando ativamente, com interações normais de suporte."
        sinais.append("Última interação há " + str(dias_sem_ticket) + " dias")
        sinais.append(str(total) + " ticket(s) no histórico — uso real do sistema")
        badge = "badge-green"
    elif total == 0:
        nivel, label = "SEM_HISTORICO_SUPORTE", "Sem histórico de suporte"
        perfil = "Sem tickets registrados. Pode indicar uso autônomo OU baixo engajamento — vale acionar CS para confirmar."
        sinais.append("Nenhum ticket nos sistemas conectados")
        badge = "badge-gray"
    else:
        nivel, label = "ESTAVEL", "Operação estável"
        perfil = "Sem sinais de risco operacional. Uso padrão."
        sinais.append("Último ticket há " + str(dias_sem_ticket) + " dias")
        badge = "badge-green"
    return {
        "nivel": nivel, "label": label, "perfil": perfil, "sinais": sinais,
        "dias_sem_ticket": dias_sem_ticket, "duvida_pct": duvida_pct, "bug_pct": bug_pct,
        "badge": badge,
    }


def inferir_segmento(properties):
    email = (properties.get("email") or "").lower()
    website = properties.get("website") or ""
    industry = properties.get("industry") or ""
    sinais = []
    maturidade = "DESCONHECIDA"
    dominio = email.split("@")[1] if "@" in email else ""
    pessoais = ("gmail.com", "hotmail.com", "yahoo.com.br", "yahoo.com",
                "outlook.com", "live.com", "bol.com.br", "uol.com.br")
    if dominio:
        if dominio in pessoais:
            sinais.append("E-mail pessoal (" + dominio + ") — perfil MEI ou pequena empresa")
            maturidade = "BAIXA"
        else:
            sinais.append("E-mail corporativo (" + dominio + ")")
            maturidade = "MEDIA_ALTA"
    if website:
        sinais.append("Tem site próprio (" + website + ") — investe em presença digital")
        if maturidade == "BAIXA":
            maturidade = "MEDIA"
    else:
        sinais.append("Sem website registrado no CRM")
    if industry:
        sinais.append("Setor declarado: " + industry)
    if properties.get("city") or properties.get("state"):
        loc = (properties.get("city") or "-") + "/" + (properties.get("state") or "-")
        sinais.append("Localização: " + loc)
    mat_label = {"BAIXA": "Baixa", "MEDIA": "Média", "MEDIA_ALTA": "Média-Alta",
                 "DESCONHECIDA": "Não inferida"}[maturidade]
    mat_badge = {"BAIXA": "badge-gray", "MEDIA": "badge-blue",
                 "MEDIA_ALTA": "badge-purple", "DESCONHECIDA": "badge-gray"}[maturidade]
    return {"maturidade": maturidade, "maturidade_label": mat_label,
            "maturidade_badge": mat_badge, "sinais": sinais, "industry": industry}


def calcular_health_score(ltv, saude, diag_op, an_tickets):
    score = 50
    if ltv["plano_chave"] == "PLATINA":
        score += 25
    elif ltv["plano_chave"] == "OURO":
        score += 18
    elif ltv["plano_chave"] == "PRATA":
        score += 10
    elif ltv["plano_chave"] == "BRONZE":
        score += 4
    score += {"SAUDAVEL": 15, "ATENCAO": -5, "ALTO_RISCO": -25, "OPORTUNIDADE": 5}.get(saude["nivel"], 0)
    score += {
        "ATIVO_SAUDAVEL": 15, "ESTAVEL": 10, "ONBOARDING_INTENSO": -5,
        "BAIXA_AUTONOMIA": -10, "DIFICULDADE_TECNICA": -20, "CHURN_SILENCIOSO": -30,
        "RISCO_CANCELAMENTO": -40, "SEM_HISTORICO_SUPORTE": -5, "NAO_CLIENTE": 0,
    }.get(diag_op["nivel"], 0)
    if an_tickets["gravidade_pct"] > 30:
        score -= 10
    score = max(0, min(100, score))
    if score >= 80:
        zona, cor = "Excelente", "#10B981"
    elif score >= 60:
        zona, cor = "Boa", "#0284C7"
    elif score >= 40:
        zona, cor = "Atenção", "#F59E0B"
    else:
        zona, cor = "Crítica", "#DC2626"
    return {"score": score, "zona": zona, "cor": cor}


UPGRADES_PLANO = {
    "BRONZE": ("Prata", "Habilitar emissão ilimitada de NF-e/NFS-e/NFC-e e geração de boletos."),
    "PRATA": ("Ouro", "Liberar Portal do Cliente (segunda via de faturas) e Multi-empresa/Filial."),
    "OURO": ("Platina", "Ativar Assinatura Digital de documentos nativa — elimina dependência de DocuSign/ClickSign."),
}


def sugerir_oportunidades(properties, ltv, an_tickets, diag_op, segmento, produto="GESTAOCLICK", responsavel=None):
    """Gera carteira de oportunidades contextual, priorizando:
       1) Estabilização operacional quando há risco;
       2) Educação/enablement quando há baixa adoção;
       3) Assistente de IA como diferencial transversal (cross-sell de alto valor);
       4) Banco Inter PRIORITÁRIO sobre Cora — Cora só entra como complemento;
       5) Cross-sell/up-sell criativo, ancorado no padrão de uso do cliente.
    """
    ops = []
    prioridade_ordem = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    industry = normalizar(segmento.get("industry") or "")
    has_website = bool(properties.get("website"))
    cliente_ativo = ltv["is_cliente"] and diag_op["nivel"] in ("ATIVO_SAUDAVEL", "ESTAVEL")

    # Roteamento: quem deve agir? Bloqueia recomendacoes de CS quando inadequado.
    evitar_cs = bool(responsavel and responsavel.get("evitar_cs"))
    area_padrao = (responsavel or {}).get("area", "Consultor Responsavel")
    is_clicknotas = produto == "CLICKNOTAS"
    is_lead = not ltv["is_cliente"]

    # ====== 1) Retenção / estabilização (vem antes de qualquer venda) ======
    if diag_op["nivel"] in ("RISCO_CANCELAMENTO", "CHURN_SILENCIOSO"):
        if evitar_cs:
            ops.append({"tipo": "RETENCAO", "icon": "!",
                        "titulo": "Acao de retencao imediata",
                        "descricao": "Cliente em risco real - acionar " + area_padrao + " imediatamente. Estabilizar primeiro, vender depois.",
                        "prioridade": "critica"})
        else:
            ops.append({"tipo": "RETENCAO", "icon": "!",
                        "titulo": "Acao de retencao imediata",
                        "descricao": "Cliente em risco real - acionar CS senior antes de qualquer acao comercial. Estabilizar primeiro, vender depois.",
                        "prioridade": "critica"})

    if diag_op["nivel"] == "DIFICULDADE_TECNICA":
        ops.append({"tipo": "RETENCAO", "icon": "!",
                    "titulo": "Triagem tecnica + alinhamento Suporte/Produto",
                    "descricao": "Tickets de bug/performance recorrentes sugerem desgaste. " + area_padrao + " deve mobilizar Suporte e Produto para alinhar root cause antes de qualquer movimento de expansao.",
                    "prioridade": "critica"})

    # ====== 2) Educação / Onboarding / Enablement ======
    if diag_op["nivel"] in ("BAIXA_AUTONOMIA", "ONBOARDING_INTENSO"):
        ops.append({"tipo": "ONBOARDING", "icon": "T",
                    "titulo": "Trilha de treinamento estruturada + Academy",
                    "descricao": "Alta proporcao de tickets de duvida - capacitacao reduz atrito, derruba custo de suporte e abre espaco futuro para upsell. Conducao: " + area_padrao + ".",
                    "prioridade": "alta"})

    if diag_op["nivel"] == "BAIXA_AUTONOMIA" and not is_clicknotas:
        ops.append({"tipo": "IA", "icon": "AI",
                    "titulo": "Assistente de IA GestaoClick como copiloto operacional",
                    "descricao": "IA responde duvidas operacionais in-app em tempo real - reduz tickets basicos e acelera autonomia da equipe do cliente. Cross-sell que substitui custo de suporte por valor percebido. Oferta conduzida pelo " + area_padrao + ".",
                    "prioridade": "alta"})

    # ====== 3) Assistente de IA (cross-sell transversal — adaptado ao perfil) ======
    if cliente_ativo and ltv["plano_chave"] in ("OURO", "PLATINA"):
        ops.append({"tipo": "IA", "icon": "AI",
                    "titulo": "Assistente de IA — camada analítica sobre vendas, financeiro e estoque",
                    "descricao": "Cliente maduro e operando — IA aplicada aos dados do ERP gera insights de margem, ruptura, inadimplência e sazonalidade. Eleva valor percebido e blinda contra churn.",
                    "prioridade": "alta"})
    elif cliente_ativo and ltv["plano_chave"] == "PRATA":
        ops.append({"tipo": "IA", "icon": "AI",
                    "titulo": "Assistente de IA — produtividade na rotina",
                    "descricao": "IA automatiza tarefas repetitivas (resposta a clientes, montagem de orçamentos, lembretes de cobrança). Diferencial competitivo claro em um plano Prata.",
                    "prioridade": "media"})

    if an_tickets["fiscal_count"] >= 2:
        ops.append({"tipo": "IA", "icon": "AI",
                    "titulo": "IA fiscal: antecipação de bloqueios e validação pré-emissão",
                    "descricao": "Histórico fiscal denso — IA valida CST/CFOP/CSOSN antes da emissão e reduz rejeição na SEFAZ. Resolve dor real do cliente e cria dependência operacional positiva.",
                    "prioridade": "alta"})

    # ====== 4) Banco Inter PRIORITÁRIO (financeiro/cobrança) ======
    if an_tickets["financeiro_count"] >= 1 or an_tickets["fiscal_count"] >= 2:
        ops.append({"tipo": "INTEGRACAO", "icon": "$",
                    "titulo": "Integração Banco Inter (100 boletos grátis/mês)",
                    "descricao": "Reduz custo de boleto a zero até 100/mês, elimina conciliação manual e responde direto na dor de cobrança. Cross-sell prioritário no financeiro.",
                    "prioridade": "alta"})

    # ====== 5) Cora — apenas como COMPLEMENTO do Inter em cenário Platina+financeiro pesado ======
    if ltv["plano_chave"] == "PLATINA" and an_tickets["financeiro_count"] >= 3:
        ops.append({"tipo": "INTEGRACAO", "icon": "$",
                    "titulo": "Combo Banco Inter + Cora (financeiro completo)",
                    "descricao": "Operação financeira pesada — Inter resolve cobrança (boletos baratos), Cora cobre conta corrente PJ com extrato em tempo real e geração de DARFs. Os dois juntos cobrem ponta a ponta.",
                    "prioridade": "media"})

    # ====== 6) Marketplaces e e-commerce (GestaoClick-only) ======
    if not is_clicknotas and ((has_website and an_tickets["estoque_count"] >= 1) or an_tickets["integracao_count"] >= 1):
        ops.append({"tipo": "INTEGRACAO", "icon": "M",
                    "titulo": "Marketplaces: Mercado Livre, Nuvemshop ou Loja Integrada",
                    "descricao": "Sinais de operação com estoque ou pedido de integração — sincronizar com marketplaces escala vendas sem custo operacional adicional.",
                    "prioridade": "media"})

    # ====== 7) Portal do Cliente (GestaoClick Ouro+) ======
    if not is_clicknotas and ltv["plano_chave"] in ("OURO", "PLATINA") and an_tickets["financeiro_count"] >= 2:
        ops.append({"tipo": "PRODUTO", "icon": "P",
                    "titulo": "Ativar Portal do Cliente (segunda via, contratos, NF-e)",
                    "descricao": "Reduz volume de tickets de 'me manda o boleto/nota' — cliente do cliente se serve sozinho. Ganho duplo: experiência + custo de suporte.",
                    "prioridade": "media"})

    # ====== 8) Assinatura Digital nativa (GestaoClick Platina) ======
    if not is_clicknotas and ltv["plano_chave"] == "PLATINA" and cliente_ativo:
        ops.append({"tipo": "PRODUTO", "icon": "S",
                    "titulo": "Ativar Assinatura Digital nativa (substitui DocuSign/ClickSign)",
                    "descricao": "Cliente Platina ativo — recurso já incluso costuma estar subutilizado. Eliminar SaaS externo de assinatura é ganho operacional rápido e justifica o plano.",
                    "prioridade": "media"})

    # ====== 9) Recorrência (GestaoClick) ======
    if not is_clicknotas and an_tickets["financeiro_count"] >= 2 and ltv["plano_chave"] in ("PRATA", "OURO", "PLATINA"):
        ops.append({"tipo": "PRODUTO", "icon": "R",
                    "titulo": "Módulo de Recorrência / Cobrança Recorrente",
                    "descricao": "Cliente já lida bem com cobrança — ativar cobrança recorrente (mensalidade/assinatura) transforma vendas pontuais em receita previsível. Receita expansiva direta.",
                    "prioridade": "media"})

    # ====== 10) Cross-sell vertical: serviços vs varejo (GestaoClick) ======
    if not is_clicknotas and any(termo in industry for termo in ("servic", "consultoria", "agencia", "assistencia", "manutenc")):
        ops.append({"tipo": "PRODUTO", "icon": "OS",
                    "titulo": "Módulo Ordem de Serviço (OS) + Agendamento",
                    "descricao": "Perfil de serviços — OS centraliza atendimentos, equipamentos e checklist técnico. Agendamento online evita ligações e reduz no-show.",
                    "prioridade": "media"})

    if not is_clicknotas and any(termo in industry for termo in ("varejo", "loja", "comercio", "supermerc", "mercad", "vestuario", "calcad")):
        ops.append({"tipo": "PRODUTO", "icon": "#",
                    "titulo": "PDV + Frente de Caixa GestãoClick",
                    "descricao": "Perfil de varejo — PDV integrado ao estoque elimina divergência entre venda e inventário. Ganho operacional imediato em qualquer loja física.",
                    "prioridade": "media"})

    # ====== 11) Multi-empresa / Filial (GestaoClick Platina) ======
    if not is_clicknotas and ltv["plano_chave"] == "PLATINA" and cliente_ativo:
        ops.append({"tipo": "PRODUTO", "icon": "F",
                    "titulo": "Ativar Multi-empresa / Filiais (até 3 CNPJs)",
                    "descricao": "Recurso Platina frequentemente subutilizado — se o cliente tem mais de um CNPJ ou planeja abrir filial, consolidar tudo no mesmo ambiente é vantagem competitiva.",
                    "prioridade": "baixa"})

    # ====== 12) Automação de WhatsApp / comunicação ======
    if cliente_ativo and an_tickets["total"] >= 3:
        ops.append({"tipo": "AUTOMACAO", "icon": "W",
                    "titulo": "Automação de WhatsApp: cobrança, lembretes e pós-venda",
                    "descricao": "Cliente engajado — automatizar lembretes de boleto, NF-e enviada e pós-venda gera retorno mensurável em D+7. Cross-sell rápido de entregar.",
                    "prioridade": "media"})

    # ====== 13) Upgrades de plano (GestaoClick) ======
    if not is_clicknotas and ltv["plano_chave"] and ltv["plano_chave"] in UPGRADES_PLANO and ltv["is_cliente"]:
        proximo, motivo = UPGRADES_PLANO[ltv["plano_chave"]]
        ops.append({"tipo": "UPGRADE", "icon": "+",
                    "titulo": "Upgrade " + ltv["plano_label"] + " → " + proximo,
                    "descricao": motivo,
                    "prioridade": "alta" if diag_op["nivel"] == "ATIVO_SAUDAVEL" else "media"})

    if not is_clicknotas and an_tickets["fiscal_count"] >= 3 and ltv["plano_chave"] == "BRONZE":
        ops.append({"tipo": "UPGRADE", "icon": "F",
                    "titulo": "Migrar Bronze → Prata (NF-e ilimitada)",
                    "descricao": "Cliente Bronze com múltiplos tickets fiscais — Prata libera emissão ilimitada de notas e elimina o gargalo. Up-sell com ROI direto.",
                    "prioridade": "alta"})

    # ====== 14) Programas educacionais / advocacy ======
    if not is_clicknotas and segmento["maturidade"] == "BAIXA" and ltv["plano_chave"] in ("BRONZE", None):
        ops.append({"tipo": "MARKETING", "icon": "i",
                    "titulo": "Conteúdo educativo direcionado (e-mail / WhatsApp)",
                    "descricao": "Baixa maturidade digital — onboarding via conteúdo simples (vídeos curtos, checklists) aumenta engajamento e prepara terreno para upsell futuro.",
                    "prioridade": "baixa"})

    if cliente_ativo and ltv["categoria"] == "VIP" and an_tickets["total"] <= 2:
        ops.append({"tipo": "ADVOCACY", "icon": "*",
                    "titulo": "Convidar para programa de Advocacy / Case",
                    "descricao": "VIP estável e silencioso — perfil ideal para case de sucesso, depoimento em vídeo ou indicação. Receita indireta + ativo de marketing.",
                    "prioridade": "baixa"})

    # ====== 14.5) Oportunidades ESPECIFICAS para ClickNotas ======
    if is_clicknotas and ltv["is_cliente"]:
        ops.append({"tipo": "CROSS_PRODUTO", "icon": ">>",
                    "titulo": "Cross-sell: migrar/expandir para GestaoClick (ERP completo)",
                    "descricao": "Cliente ClickNotas ja confia na marca e emite notas com a gente. Apresentar GestaoClick como evolucao natural (estoque, financeiro, OS, PDV) abre receita expansiva muito maior que o plano Essencial atual.",
                    "prioridade": "media"})
    if is_clicknotas and an_tickets["fiscal_count"] >= 2:
        ops.append({"tipo": "AUTOMACAO", "icon": "AI",
                    "titulo": "Envio automatico de NF por WhatsApp / e-mail",
                    "descricao": "Cliente emite muitas NFs. Automatizar entrega ao destinatario reduz retrabalho e melhora percepcao de servico.",
                    "prioridade": "media"})

    # ====== 15) Pré-vendas ======
    if is_lead:
        nome_prod = "ClickNotas" if is_clicknotas else "GestaoClick"
        if ltv["receita_acumulada"] > 0:
            ops.append({"tipo": "PRE_VENDAS", "icon": ">",
                        "titulo": "Avancar lead " + nome_prod + " no funil - proposta comercial",
                        "descricao": "Lead estrategico com sinal de receita - priorizar abordagem consultiva conduzida pelo " + area_padrao + ".",
                        "prioridade": "alta"})
        else:
            ops.append({"tipo": "PRE_VENDAS", "icon": ">",
                        "titulo": "Engajar lead " + nome_prod + " e validar interesse real",
                        "descricao": "Lead em estagio inicial sem receita ainda. " + area_padrao + " deve fazer contato leve (WhatsApp/email), mapear dor real e validar fit antes de propor planos.",
                        "prioridade": "alta"})

    ops.sort(key=lambda x: prioridade_ordem.get(x["prioridade"], 9))
    return ops

# ============================================================
# CLAUDE
# ============================================================
def gerar_diagnostico_claude(properties, ltv, saude, timeline, tickets,
                              an_tickets, diag_op, segmento, oportunidades, health,
                              produto="GESTAOCLICK", responsavel=None):
    if not ANTHROPIC_API_KEY:
        return {"diagnostico": "_Chave Claude nao configurada._",
                "recomendacao": "_Configure CLAUDE_API_KEY_FIXA no topo do arquivo._",
                "whatsapp": "_Sem chave Claude._"}
    if Anthropic is None:
        return {"diagnostico": "_Instale: pip install anthropic_", "recomendacao": "", "whatsapp": ""}

    tl_partes = ["- " + e["quando"] + " (" + e["data_iso"] + ") [" + e["origem"] + "] " +
                 e["titulo"] + ": " + e["descricao"] for e in timeline[:8]]
    timeline_resumo = "\n".join(tl_partes) or "Sem eventos."

    tk_partes = ["- #" + str(t["id"]) + " [" + t["status"] + "/" + t["prioridade"] + "] " + t["assunto"]
                 for t in tickets[:10]]
    tickets_resumo = "\n".join(tk_partes) or "Nenhum ticket."

    cat_partes = [k + ": " + str(v) for k, v in an_tickets["categorias"].items()]
    cat_resumo = ", ".join(cat_partes) or "-"

    ops_partes = ["- [" + o["prioridade"].upper() + "] " + o["titulo"] + " - " + o["descricao"]
                  for o in oportunidades]
    ops_resumo = "\n".join(ops_partes) or "Nenhuma oportunidade clara mapeada."

    nome = ((properties.get("firstname") or "") + " " + (properties.get("lastname") or "")).strip()

    obs_ticket_linha = ""
    if ltv.get("ticket_observacao"):
        obs_ticket_linha = "  (" + ltv["ticket_observacao"] + ")"

    contexto = (
        "DADOS JÁ CALCULADOS — NÃO RECALCULE NADA.\n\n"
        "IDENTIFICAÇÃO\n"
        "- Nome: " + nome + "\n"
        "- Empresa: " + (properties.get("company") or "-") + "\n"
        "- E-mail: " + (properties.get("email") or "-") + "\n"
        "- Setor declarado: " + (segmento["industry"] or "não informado") + "\n"
        "- Localização: " + (properties.get("city") or "-") + "/" + (properties.get("state") or "-") + "\n"
        "- Pré-vendedor (responsável pelo contato inicial): " + (properties.get("responsavel_pelo_contato") or "-") + "\n"
        "- Consultor Responsável: " + (properties.get("hubspot_owner_id") or "-") + "\n"
        "- IMPORTANTE: ambos os nomes acima são da EQUIPE DE VENDAS. Quando recomendar ações, siga as REGRAS DE ROTEAMENTO logo abaixo - elas dizem quem deve agir em cada caso. Nunca atribua ações de pós-venda nominalmente ao pré-vendedor ou consultor de venda; use o tipo de área (CS / Consultor / Pré-vendas) genericamente.\n\n"
        "PRODUTO E ROTEAMENTO (CRÍTICO - obedeça sem exceção)\n"
        "- Produto detectado: " + produto + "\n"
        "- Área responsável pela próxima ação: " + ((responsavel or {}).get("area", "Consultor Responsável")) + "\n"
        "- Por quê: " + ((responsavel or {}).get("justificativa", "Padrão.")) + "\n"
        "REGRAS QUE VOCÊ DEVE OBEDECER:\n"
        "  1. ClickNotas NÃO TEM CS em momento algum. Todo ciclo é do Consultor Responsável. NÃO recomende ação de CS para ClickNotas, NEM em diagnóstico, NEM em recomendação.\n"
        "  2. LEAD (qualquer produto, lifecycle != customer) NUNCA tem CS atuando. Pré-vendas e Comercial conduzem. CS só entra depois da venda.\n"
        "  3. Cliente GestãoClick Bronze/Prata: ação rotineira é do CONSULTOR RESPONSÁVEL. CS só entra em escalation pontual.\n"
        "  4. Cliente GestãoClick Ouro/Platina: aí sim CS é o ponto de contato natural.\n"
        "  5. Quando a regra acima disser 'evitar CS', você NÃO PODE escrever 'CS deve...', 'aciono CS...', 'CS faça...'. Use 'consultor responsável', 'pré-vendedor' ou 'time comercial' como sujeito da ação.\n\n"
        "VALOR FINANCEIRO\n"
        "- Receita acumulada: " + ltv["receita_acumulada_fmt"] + "\n"
        "- Meses de relacionamento: " + str(ltv["meses_relacionamento"]) + "\n"
        "- Ticket médio mensal: " + ltv["ticket_medio_mensal_fmt"] + obs_ticket_linha + "\n"
        "- LTV projetado 12 meses: " + ltv["ltv_projetado_12m_fmt"] + "\n"
        "- LTV projetado 24 meses: " + ltv["ltv_projetado_24m_fmt"] + "\n"
        "- LTV projetado 36 meses: " + ltv["ltv_projetado_36m_fmt"] + "\n"
        "- Categoria: " + ltv["categoria_label"] + "\n"
        "- Plano inferido: " + (ltv["plano_label"] or "-") + "\n\n"
        "SEGMENTO E MATURIDADE\n"
        "- Maturidade digital: " + segmento["maturidade_label"] + "\n"
        "- Sinais: " + "; ".join(segmento["sinais"]) + "\n\n"
        "SAÚDE GERAL: " + saude["label"] + " — " + "; ".join(saude["motivos"]) + "\n"
        "Tickets abertos/urgentes/30d: " + str(saude["tickets_abertos"]) + "/" +
        str(saude["tickets_urgentes"]) + "/" + str(saude["tickets_30d"]) + "\n\n"
        "DIAGNÓSTICO OPERACIONAL: " + diag_op["label"] + "\n"
        "Perfil: " + diag_op["perfil"] + "\n"
        "Sinais: " + "; ".join(diag_op["sinais"]) + "\n"
        "Dúvidas: " + str(diag_op.get("duvida_pct", 0)) + "% | Bugs: " +
        str(diag_op.get("bug_pct", 0)) + "% | Dias sem ticket: " +
        str(diag_op.get("dias_sem_ticket", "-")) + "\n\n"
        "ANÁLISE DE TICKETS (" + str(an_tickets["total"]) + " no total)\n"
        "- Por categoria: " + cat_resumo + "\n"
        "- Categoria dominante: " + (an_tickets["cat_principal"] or "-") + "\n"
        "- % gravidade alta: " + str(an_tickets["gravidade_pct"]) + "%\n\n"
        "HEALTH SCORE: " + str(health["score"]) + "/100 (" + health["zona"] + ")\n\n"
        "TIMELINE RECENTE:\n" + timeline_resumo + "\n\n"
        "TICKETS:\n" + tickets_resumo + "\n\n"
        "OPORTUNIDADES MAPEADAS (já priorizadas):\n" + ops_resumo + "\n"
    )

    system_prompt = (
        "Você é o Click Insight AI, gerente sênior de Customer Success e Revenue da Click Digital (ERP GestãoClick para PMEs). Escreve como um operador experiente, não como um sistema resumindo dados.\n\n"
        "REGRAS CRÍTICAS:\n"
        "- Todos os dados quantitativos já vieram calculados. NÃO recalcule. NÃO invente datas. NÃO classifique saúde de novo.\n"
        "- Os nomes do CRM são da EQUIPE DE VENDAS; nunca atribua ações de pós-venda nominalmente a eles. CS é equipe separada.\n"
        "- Use o diagnóstico operacional e as oportunidades já mapeadas como insumo — você interpreta, não substitui.\n"
        "- Tom: analítico, executivo, brasileiro. Sem clichês corporativos. Sem emojis. Português correto e natural.\n\n"
        "DIRETRIZES PARA A ANÁLISE ESTRATÉGICA (campo 'diagnostico'):\n"
        "- NÃO resuma dados brutos. INTERPRETE sinais comerciais, operacionais e comportamentais.\n"
        "- Diferencie sempre três planos: FATOS observáveis (o que está no CRM/Zendesk), HIPÓTESES prováveis (o que os sinais sugerem) e CONCLUSÕES estratégicas (a leitura combinada). Quando estiver em hipótese ou conclusão, sinalize isso na linguagem.\n"
        "- Use linguagem probabilística obrigatoriamente nas hipóteses: 'indica possível...', 'sugere...', 'há sinais de...', 'demonstra potencial para...', 'a leitura mais provável é...'. Nunca trate inferência como certeza.\n"
        "- NÃO conclua automaticamente que poucos tickets = saudável OU muitos tickets = problemático. Interprete pelo IMPACTO operacional e comportamental, não pelo volume.\n"
        "- Ao ler tickets, observe se há: retrabalho, fricção operacional, baixa adoção, dificuldade de uso, dependência do sistema, sensibilidade a falhas, risco de desgaste, potencial de expansão ou estabilidade operacional. Considere o CONTEXTO do problema, não só a existência.\n"
        "- Considere sempre: tempo de relacionamento, estágio da jornada, frequência de interação, histórico comercial, padrão dos tickets, sinais de adoção, recorrência de problemas, uso percebido do sistema, dependência operacional da plataforma, maturidade operacional, maturidade digital, engajamento e valor percebido.\n"
        "- Evite: julgamentos, especulações excessivas, afirmações categóricas sem evidência, redundâncias, descrição sem interpretação.\n"
        "- Cada bloco deve gerar LEITURA estratégica, não apenas reportar números.\n\n"
        "ESTRUTURA OBRIGATÓRIA do campo 'diagnostico' — use EXATAMENTE estes 7 cabeçalhos, em ordem, cada um precedido por '## ':\n"
        "## Contexto geral\n"
        "   1-2 linhas: quem é o cliente, há quanto tempo, em que fase da jornada está, plano e categoria.\n"
        "## Leitura operacional e comportamental\n"
        "   2-3 linhas interpretando o padrão de uso e tickets — o que isso sugere sobre como o cliente opera de fato. Use linguagem probabilística.\n"
        "## Pontos positivos\n"
        "   1-2 linhas com sinais favoráveis (longevidade, plano elevado, baixa fricção, autonomia, integrações em uso, engajamento, etc.) — só o que está sustentado por evidência.\n"
        "## Pontos de atenção\n"
        "   1-2 linhas com sinais a monitorar — sem dramatizar e diferenciando fato de hipótese.\n"
        "## Maturidade percebida\n"
        "   1-2 linhas com leitura combinada de maturidade digital + operacional, considerando segmento, plano e padrão de interação.\n"
        "## Estabilidade ou risco percebido\n"
        "   1-2 linhas com o cenário mais provável nos próximos 60-90 dias e por quê.\n"
        "## Potencial percebido\n"
        "   1-2 linhas indicando onde está a maior alavanca (expansão, upgrade, integração, advocacia) com base no que o cliente JÁ demonstra — não em desejo.\n\n"
        "DIRETRIZES PARA A RECOMENDAÇÃO DE AÇÃO (campo 'recomendacao'):\n"
        "- Gere recomendação PRÁTICA, ESTRATÉGICA e ACIONÁVEL, ancorada nos sinais reais do cliente (histórico, comportamento, tickets, adoção, estágio).\n"
        "- Não invente ação genérica sem conexão clara com o cenário. UMA recomendação principal, não três simultâneas.\n"
        "- Classifique a ação em UM dos tipos: corretiva, preventiva, consultiva, expansão, retenção, educação/onboarding. Explicite o tipo no campo 'Objetivo estratégico'.\n"
        "- Priorize considerando: impacto operacional, risco percebido, urgência, oportunidade de expansão, valor percebido, momento da jornada.\n"
        "- Considere sempre: dependência operacional do sistema, maturidade, sensibilidade a falhas, frequência de suporte, risco de desgaste, potencial de aprofundamento de uso, timing comercial.\n"
        "- REGRAS DE PRIORIZAÇÃO obrigatórias:\n"
        "  · Com problema crítico (cancelamento, churn silencioso, dificuldade técnica recorrente) → estabilização operacional ANTES de expansão comercial.\n"
        "  · Com baixa adoção ou onboarding intenso → educação/enablement ANTES de upsell.\n"
        "  · Com maturidade e estabilidade → identificar oportunidade consultiva de expansão, integração ou automação.\n"
        "- Use problemas reais como gatilho consultivo quando fizer sentido — sem soar oportunista.\n"
        "- Evite: recomendações vagas, excesso de ações simultâneas, linguagem agressivamente comercial, ações desconectadas do contexto, upsell prematuro, recomendações sem prioridade clara.\n"
        "- Escreva como um gerente experiente de CS/Revenue Operations definindo a próxima jogada — não como um sistema sugerindo cross-sell.\n\n"
        "ESTRUTURA OBRIGATÓRIA do campo 'recomendacao' — use EXATAMENTE estes 6 cabeçalhos, em ordem, cada um precedido por '## ':\n"
        "## Prioridade imediata\n"
        "   1 frase nomeando a ação principal a executar agora (verbo no infinitivo + objeto concreto).\n"
        "## Objetivo estratégico da ação\n"
        "   1-2 linhas. Comece declarando o TIPO entre colchetes — ex.: '[Retenção]', '[Consultiva]', '[Expansão]', '[Educação/Onboarding]', '[Corretiva]', '[Preventiva]' — e depois explique o resultado pretendido.\n"
        "## Área responsável\n"
        "   1 linha indicando quem executa: CS, Pré-vendas, Comercial, Suporte, Produto. Quando for pós-venda/CS, NÃO atribua nominalmente ao vendedor do CRM.\n"
        "## Justificativa contextual\n"
        "   2-3 linhas conectando os sinais do cliente (tickets, plano, tempo, padrão de uso, maturidade) à escolha da ação. Diferencie fato de hipótese.\n"
        "## Oportunidade percebida\n"
        "   1-2 linhas com o ganho concreto esperado se a ação for executada (retenção, expansão de receita, redução de fricção, aceleração de adoção, etc.).\n"
        "## Nível de urgência ou timing\n"
        "   1 linha com a janela recomendada: 'imediato (próximas 48h)', 'curto prazo (7 dias)', 'médio prazo (30 dias)' ou 'aguardar gatilho específico — descrever qual'. Justifique brevemente.\n\n"
        "PLANOS GESTÃOCLICK:\n"
        "- BRONZE (R$ 79-119): 1 usuário, controles básicos, OS, PDV.\n"
        "- PRATA (R$ 129-199): 3 usuários, NF-e/NFS-e/NFC-e ilimitadas, boletos.\n"
        "- OURO (R$ 199-289): 6 usuários, 2 empresas, portal do cliente, white label.\n"
        "- PLATINA (R$ 249-379): 12 usuários, 3 empresas, assinatura digital nativa.\n"
        "Integrações disponíveis: Mercado Livre, Nuvemshop, Loja Integrada, Banco Inter, Cora.\n\n"
        "REGRAS OBRIGATÓRIAS PARA A MENSAGEM DE WHATSAPP (são as 4 diretrizes que fazem a abordagem realmente convincente):\n"
        "1) DOR ESPECÍFICA: nada de 'gestão' ou 'faturamento' genérico. Use dores concretas extraídas dos sinais reais do cliente — escolha uma destas (a que mais combinar com o histórico de tickets, plano, segmento ou tempo de relacionamento):\n"
        "   • atraso em cobrança\n"
        "   • retrabalho operacional\n"
        "   • perda de informação entre áreas\n"
        "   • dificuldade de acompanhar o financeiro\n"
        "   • operação crescendo sem controle\n"
        "   • equipe dependente de planilha\n"
        "2) BENEFÍCIO CONCRETO: nada abstrato como 'decolar' ou 'transformar'. Use ganhos palpáveis — escolha um:\n"
        "   • ganhar tempo\n"
        "   • reduzir erros\n"
        "   • acelerar faturamento\n"
        "   • centralizar a operação\n"
        "   • ter visão financeira em tempo real\n"
        "3) QUEBRA DE RESISTÊNCIA: encerre com uma frase que reduza fricção. Use uma destas (não invente outras):\n"
        "   • 'mesmo que não avancem agora'\n"
        "   • 'só pra vocês terem referência'\n"
        "   • 'vale até como benchmark'\n"
        "4) CTA FÁCIL DE RESPONDER: NÃO use 'Vale a conversa?'. Use uma destas perguntas leves:\n"
        "   • 'Posso te mostrar?'\n"
        "   • 'Faz sentido olhar isso?'\n"
        "   • 'Tem abertura pra uma conversa rápida essa semana?'\n\n"
        "ESTRUTURA RECOMENDADA DO WHATSAPP (4 a 6 linhas, sem saudação corporativa):\n"
        "Linha 1: saudação curta + nome (use o primeiro nome).\n"
        "Linha 2: gancho concreto (cita um ticket recorrente, plano, tempo de casa, integração — algo REAL do contexto).\n"
        "Linha 3: dor específica conectada ao gancho.\n"
        "Linha 4: benefício concreto que a Click resolve nesse caso.\n"
        "Linha 5: quebra de resistência (escolha uma das 3).\n"
        "Linha 6: CTA fácil (escolha uma das 3).\n\n"
        "FORMATO DE SAÍDA (APENAS JSON válido, sem ``` e sem texto fora do JSON):\n"
        '{\n'
        '  "diagnostico": "## Contexto geral\\n<texto>\\n\\n## Leitura operacional e comportamental\\n<texto>\\n\\n## Pontos positivos\\n<texto>\\n\\n## Pontos de atenção\\n<texto>\\n\\n## Maturidade percebida\\n<texto>\\n\\n## Estabilidade ou risco percebido\\n<texto>\\n\\n## Potencial percebido\\n<texto>",\n'
        '  "recomendacao": "## Prioridade imediata\\n<texto>\\n\\n## Objetivo estratégico da ação\\n<texto>\\n\\n## Área responsável\\n<texto>\\n\\n## Justificativa contextual\\n<texto>\\n\\n## Oportunidade percebida\\n<texto>\\n\\n## Nível de urgência ou timing\\n<texto>",\n'
        '  "whatsapp": "Mensagem pronta para copiar, seguindo OBRIGATORIAMENTE as 4 diretrizes da seção WhatsApp. Tom consultivo, não vendedor. Português correto."\n'
        '}'
    )

    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=1800,
            system=system_prompt,
            messages=[{"role": "user", "content": contexto}],
        )
        texto = response.content[0].text.strip()
        payload = _extrair_payload_claude(texto)
        return {
            "diagnostico": _normalizar_campo_estruturado(payload.get("diagnostico", "")),
            "recomendacao": _normalizar_campo_estruturado(payload.get("recomendacao", "")),
            "whatsapp": _normalizar_campo_estruturado(payload.get("whatsapp", "")),
        }
    except Exception as e:
        return {"diagnostico": "_Erro Claude: " + str(e) + "_", "recomendacao": "", "whatsapp": ""}


def _limpar_fences_markdown(texto):
    """Remove fences ```json ... ``` ou ``` ... ``` em volta do conteudo."""
    t = texto.strip()
    if t.startswith("```"):
        t = t[3:]
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.lstrip("\r\n").rstrip()
        if t.endswith("```"):
            t = t[:-3].rstrip()
    return t


def _extrair_payload_claude(texto):
    """Extrai o dict JSON da resposta do Claude tolerando:
       - fences markdown ```json ... ```
       - texto fora do JSON
       - JSON aninhado dentro do campo 'diagnostico' (loop do modelo)
    """
    bruto = _limpar_fences_markdown(texto)
    inicio = bruto.find("{")
    fim = bruto.rfind("}")
    if inicio < 0 or fim <= inicio:
        return {"diagnostico": bruto, "recomendacao": "", "whatsapp": ""}
    try:
        payload = json.loads(bruto[inicio:fim + 1])
    except Exception:
        return {"diagnostico": bruto, "recomendacao": "", "whatsapp": ""}
    if not isinstance(payload, dict):
        return {"diagnostico": bruto, "recomendacao": "", "whatsapp": ""}

    diag = payload.get("diagnostico", "")
    if isinstance(diag, str):
        d = diag.lstrip()
        if d.startswith("```") or (d.startswith("{") and '"diagnostico"' in d):
            try:
                sub_str = _limpar_fences_markdown(d)
                sub = json.loads(sub_str)
                if isinstance(sub, dict) and "diagnostico" in sub:
                    payload = sub
            except Exception:
                pass
    return payload


def _normalizar_campo_estruturado(valor):
    """Converte escape literal '\\n' em newline real se o campo veio mal serializado.
    Preserva os cabecalhos '## Secao'."""
    if not isinstance(valor, str):
        return ""
    v = valor.strip()
    if not v:
        return ""
    n_lit = v.count("\\n")
    n_real = v.count("\n")
    if n_lit > 0 and n_real < max(1, n_lit // 2):
        v = v.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
    return v.strip()


# ============================================================
# PDF
# ============================================================
def gerar_pdf_executivo(properties, ltv, saude, timeline, tickets, ia,
                         an_tickets, diag_op, segmento, oportunidades, health):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="Relatório Executivo - Click Insight AI",
    )
    styles = getSampleStyleSheet()
    style_h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=20,
                              textColor=HexColor(BRAND_PRIMARY), spaceAfter=4, leading=24, alignment=TA_LEFT)
    style_h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13,
                              textColor=HexColor(BRAND_PRIMARY), spaceBefore=12, spaceAfter=6, leading=16)
    style_meta = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9,
                                textColor=HexColor("#64748B"), spaceAfter=10)
    style_body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10,
                                textColor=HexColor("#1E293B"), leading=13.5, alignment=TA_JUSTIFY)
    style_label = ParagraphStyle("Label", parent=styles["Normal"], fontSize=8,
                                 textColor=HexColor("#64748B"))
    style_value = ParagraphStyle("Value", parent=styles["Normal"], fontSize=10.5,
                                 textColor=HexColor("#0F172A"))
    style_whats = ParagraphStyle("Whats", parent=styles["Normal"], fontSize=10,
                                 textColor=HexColor("#F8FAFC"), leading=14,
                                 backColor=HexColor("#0F172A"), borderPadding=12)
    story = []
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
    if os.path.exists(logo_path):
        try:
            story.append(RLImage(logo_path, width=4 * cm, height=2 * cm))
            story.append(Spacer(1, 4))
        except Exception:
            pass
    story.append(Paragraph("Relatório Executivo de Cliente", style_h1))
    story.append(Paragraph(
        "Gerado em " + datetime.now().strftime("%d/%m/%Y %H:%M") + " · " + APP_NAME +
        " | Health Score: <b>" + str(health["score"]) + "/100 (" + health["zona"] + ")</b>",
        style_meta,
    ))
    nome = ((properties.get("firstname") or "") + " " + (properties.get("lastname") or "")).strip() or "-"
    empresa = properties.get("company") or "-"
    stage = properties.get("lifecyclestage") or "-"
    faixa_dados = [
        [Paragraph("CONTATO", style_label), Paragraph("EMPRESA", style_label), Paragraph("ESTÁGIO", style_label)],
        [Paragraph("<b>" + nome + "</b>", style_value),
         Paragraph("<b>" + empresa + "</b>", style_value),
         Paragraph("<b>" + stage + "</b>", style_value)],
    ]
    faixa = Table(faixa_dados, colWidths=[6.0 * cm, 6.0 * cm, 5.5 * cm])
    faixa.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(faixa)

    story.append(Paragraph("Valor financeiro e LTV", style_h2))
    kpi_data = [
        [Paragraph("Receita", style_label), Paragraph("Ticket mensal", style_label),
         Paragraph("Plano", style_label), Paragraph("Categoria", style_label)],
        [Paragraph("<b>" + ltv["receita_acumulada_fmt"] + "</b>", style_value),
         Paragraph("<b>" + ltv["ticket_medio_mensal_fmt"] + "</b>", style_value),
         Paragraph("<b>" + (ltv.get("plano_label") or "-") + "</b>", style_value),
         Paragraph("<b>" + ltv["categoria_label"] + "</b>", style_value)],
    ]
    t_kpi = Table(kpi_data, colWidths=[4.3 * cm, 4.3 * cm, 4.3 * cm, 4.6 * cm])
    t_kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FFFFFF")),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(t_kpi)
    if ltv.get("ticket_observacao"):
        story.append(Paragraph("<i>Ticket: " + ltv["ticket_observacao"] + "</i>", style_meta))

    story.append(Spacer(1, 6))
    ltv_data = [
        [Paragraph("LTV projetado 12 meses", style_label),
         Paragraph("LTV projetado 24 meses", style_label),
         Paragraph("LTV projetado 36 meses", style_label)],
        [Paragraph("<b>" + ltv["ltv_projetado_12m_fmt"] + "</b>", style_value),
         Paragraph("<b>" + ltv["ltv_projetado_24m_fmt"] + "</b>", style_value),
         Paragraph("<b>" + ltv["ltv_projetado_36m_fmt"] + "</b>", style_value)],
    ]
    t_ltv = Table(ltv_data, colWidths=[5.8 * cm, 5.8 * cm, 5.9 * cm])
    t_ltv.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F0F9FF")),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#BAE6FD")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor("#E0F2FE")),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(t_ltv)

    story.append(Paragraph("Diagnóstico operacional", style_h2))
    story.append(Paragraph("<b>" + diag_op["label"] + "</b> — " + diag_op["perfil"], style_body))
    if diag_op["sinais"]:
        story.append(Paragraph("Sinais: " + "; ".join(diag_op["sinais"]), style_body))

    story.append(Paragraph("Segmento e maturidade digital", style_h2))
    story.append(Paragraph("<b>Maturidade:</b> " + segmento["maturidade_label"] +
                           " — " + "; ".join(segmento["sinais"]), style_body))

    if an_tickets["categorias"]:
        story.append(Paragraph("Análise temática de tickets", style_h2))
        cat_partes = [k + " (" + str(v) + ")" for k, v in
                      sorted(an_tickets["categorias"].items(), key=lambda x: -x[1])]
        story.append(Paragraph("<b>Distribuição:</b> " + " · ".join(cat_partes), style_body))
        if an_tickets["recorrentes"]:
            rec_partes = [a + " (" + str(c) + "x)" for a, c in an_tickets["recorrentes"]]
            story.append(Paragraph("<b>Assuntos recorrentes:</b> " + "; ".join(rec_partes), style_body))

    if timeline:
        story.append(Paragraph("Linha do tempo cruzada", style_h2))
        tl_data = [["Quando", "Origem", "Evento"]]
        for e in timeline[:12]:
            tl_data.append([
                e["quando"] + "\n(" + e["data_iso"] + ")",
                e["origem"],
                e["titulo"] + "\n" + e["descricao"][:80],
            ])
        t_tl = Table(tl_data, colWidths=[3.2 * cm, 2.3 * cm, 12 * cm])
        t_tl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor(BRAND_PRIMARY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F8FAFC")]),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t_tl)

    if oportunidades:
        story.append(PageBreak())
        story.append(Paragraph("Oportunidades de ação (cross-sell e CS)", style_h2))
        for o in oportunidades:
            story.append(Paragraph(
                "<b>[" + o["prioridade"].upper() + "] " + o["titulo"] + "</b> — " + o["descricao"],
                style_body))
            story.append(Spacer(1, 4))

    if tickets:
        story.append(Paragraph("Histórico de chamados", style_h2))
        tk_data = [["ID", "Assunto", "Status", "Pri"]]
        for t in tickets[:20]:
            tk_data.append([str(t["id"]), t["assunto"][:60], t["status"], t["prioridade"]])
        t_tk = Table(tk_data, colWidths=[1.8 * cm, 10.5 * cm, 2.6 * cm, 2.6 * cm])
        t_tk.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor(BRAND_PRIMARY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F8FAFC")]),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t_tk)

    if ia.get("diagnostico"):
        story.append(Paragraph("Análise estratégica (CS / Revenue)", style_h2))
        blocos_diag = parsear_analise_estrategica(ia["diagnostico"])
        for sec, corpo in blocos_diag:
            if not corpo:
                continue
            corpo_pdf = corpo.replace("\n", "<br/>")
            story.append(Paragraph("<b>" + sec["titulo"] + "</b>", style_body))
            story.append(Paragraph(corpo_pdf, style_body))
            story.append(Spacer(1, 4))
    if ia.get("recomendacao"):
        story.append(Paragraph("Recomendação de ação (próxima jogada)", style_h2))
        blocos_rec = parsear_recomendacao(ia["recomendacao"])
        for sec, corpo in blocos_rec:
            if not corpo:
                continue
            corpo_pdf = corpo.replace("\n", "<br/>")
            story.append(Paragraph("<b>" + sec["titulo"] + "</b>", style_body))
            story.append(Paragraph(corpo_pdf, style_body))
            story.append(Spacer(1, 4))
    if ia.get("whatsapp"):
        story.append(Paragraph("Mensagem de Abordagem Consultiva (WhatsApp)", style_h2))
        story.append(Paragraph(ia["whatsapp"].replace("\n", "<br/>"), style_whats))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<i>" + APP_NAME + " · Click Digital. Dados de HubSpot CRM e Zendesk Support.</i>",
        style_meta))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ============================================================
# UI HELPERS
# ============================================================
STAGE_MAP = {
    "subscriber": ("Subscriber", "badge-gray"),
    "lead": ("Lead", "badge-blue"),
    "marketingqualifiedlead": ("MQL", "badge-blue"),
    "salesqualifiedlead": ("SQL", "badge-purple"),
    "opportunity": ("Oportunidade", "badge-purple"),
    "customer": ("Cliente", "badge-green"),
    "evangelist": ("Evangelist", "badge-green"),
    "other": ("Outro", "badge-gray"),
}


# Esquema visual de cada bloco da Análise Estratégica
ANALISE_SECOES = [
    {"titulo": "Contexto geral",                    "cor": "#0F172A", "bg": "#F8FAFC", "icone": "1"},
    {"titulo": "Leitura operacional e comportamental", "cor": "#1E40AF", "bg": "#EFF6FF", "icone": "2"},
    {"titulo": "Pontos positivos",                  "cor": "#047857", "bg": "#ECFDF5", "icone": "+"},
    {"titulo": "Pontos de atenção",                 "cor": "#B45309", "bg": "#FFFBEB", "icone": "!"},
    {"titulo": "Maturidade percebida",              "cor": "#0E7490", "bg": "#ECFEFF", "icone": "M"},
    {"titulo": "Estabilidade ou risco percebido",   "cor": "#7C3AED", "bg": "#F5F3FF", "icone": "R"},
    {"titulo": "Potencial percebido",               "cor": "#0284C7", "bg": "#F0F9FF", "icone": ">"},
]


def parsear_analise_estrategica(texto):
    """Recebe texto com cabeçalhos '## Seção' e retorna lista [(titulo, corpo), ...]
    preservando a ordem do esquema ANALISE_SECOES. Seções ausentes ficam com corpo vazio
    para que a UI não exiba blocos quebrados."""
    if not texto:
        return []
    raw = texto.strip()
    # Quebra por linhas que comecem com '## '
    import re
    partes = re.split(r"(?:^|\n)##\s+", raw)
    partes = [p for p in partes if p.strip()]
    extraidos = {}
    for parte in partes:
        linhas = parte.split("\n", 1)
        titulo = linhas[0].strip().rstrip(":").strip()
        corpo = (linhas[1].strip() if len(linhas) > 1 else "")
        extraidos[titulo.lower()] = corpo
    ordenados = []
    for sec in ANALISE_SECOES:
        corpo = extraidos.get(sec["titulo"].lower(), "")
        ordenados.append((sec, corpo))
    # Se nenhuma seção foi reconhecida, devolve uma única linha como fallback bruto
    if not any(c for _, c in ordenados):
        return [(ANALISE_SECOES[0], raw)]
    return ordenados


def renderizar_diagnostico_html(texto):
    """Renderiza a análise estratégica como blocos HTML estilizados, um por seção."""
    blocos = parsear_analise_estrategica(texto)
    if not blocos:
        return ""
    partes = []
    for sec, corpo in blocos:
        if not corpo:
            continue
        corpo_html = corpo.replace("\n\n", "</p><p style='margin:6px 0 0 0;'>").replace("\n", "<br>")
        partes.append(
            "<div style='background:" + sec["bg"] + ";border-left:4px solid " + sec["cor"] +
            ";border-radius:8px;padding:12px 14px;margin-bottom:10px;'>"
            "<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;'>"
            "<span style='display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:6px;background:" + sec["cor"] + ";color:#FFFFFF;font-size:11px;font-weight:700;'>" + sec["icone"] + "</span>"
            "<span style='font-size:13px;font-weight:700;color:" + sec["cor"] + ";letter-spacing:0.02em;text-transform:uppercase;'>" + sec["titulo"] + "</span>"
            "</div>"
            "<p style='margin:0;font-size:13.5px;line-height:1.55;color:#1E293B;'>" + corpo_html + "</p>"
            "</div>"
        )
    return "".join(partes) or ""


# Esquema visual de cada bloco da Recomendação de Ação
RECOMENDACAO_SECOES = [
    {"titulo": "Prioridade imediata",            "cor": "#DC2626", "bg": "#FEF2F2", "icone": "1"},
    {"titulo": "Objetivo estratégico da ação",   "cor": "#1E40AF", "bg": "#EFF6FF", "icone": "O"},
    {"titulo": "Área responsável",               "cor": "#475569", "bg": "#F1F5F9", "icone": "R"},
    {"titulo": "Justificativa contextual",       "cor": "#B45309", "bg": "#FFFBEB", "icone": "J"},
    {"titulo": "Oportunidade percebida",         "cor": "#047857", "bg": "#ECFDF5", "icone": "+"},
    {"titulo": "Nível de urgência ou timing",    "cor": "#7C3AED", "bg": "#F5F3FF", "icone": "T"},
]


def parsear_recomendacao(texto):
    """Recebe texto com cabeçalhos '## Seção' e retorna lista [(meta, corpo), ...]
    seguindo a ordem fixa de RECOMENDACAO_SECOES. Aceita variações de acentuação
    no título e preserva a robustez para fallback."""
    if not texto:
        return []
    raw = texto.strip()
    import re
    partes = re.split(r"(?:^|\n)##\s+", raw)
    partes = [p for p in partes if p.strip()]
    extraidos = {}
    for parte in partes:
        linhas = parte.split("\n", 1)
        titulo = linhas[0].strip().rstrip(":").strip()
        corpo = (linhas[1].strip() if len(linhas) > 1 else "")
        extraidos[normalizar(titulo)] = corpo
    ordenados = []
    for sec in RECOMENDACAO_SECOES:
        corpo = extraidos.get(normalizar(sec["titulo"]), "")
        ordenados.append((sec, corpo))
    if not any(c for _, c in ordenados):
        return [(RECOMENDACAO_SECOES[0], raw)]
    return ordenados


def renderizar_recomendacao_html(texto):
    """Renderiza a recomendação de ação como cards HTML, um por seção."""
    blocos = parsear_recomendacao(texto)
    if not blocos:
        return ""
    partes = []
    for sec, corpo in blocos:
        if not corpo:
            continue
        corpo_html = corpo.replace("\n\n", "</p><p style='margin:6px 0 0 0;'>").replace("\n", "<br>")
        partes.append(
            "<div style='background:" + sec["bg"] + ";border-left:4px solid " + sec["cor"] +
            ";border-radius:8px;padding:12px 14px;margin-bottom:10px;'>"
            "<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;'>"
            "<span style='display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:6px;background:" + sec["cor"] + ";color:#FFFFFF;font-size:11px;font-weight:700;'>" + sec["icone"] + "</span>"
            "<span style='font-size:13px;font-weight:700;color:" + sec["cor"] + ";letter-spacing:0.02em;text-transform:uppercase;'>" + sec["titulo"] + "</span>"
            "</div>"
            "<p style='margin:0;font-size:13.5px;line-height:1.55;color:#1E293B;'>" + corpo_html + "</p>"
            "</div>"
        )
    return "".join(partes) or ""


def section_open(titulo):
    st.markdown(
        "<div class='section-card'><div class='section-header'><span class='dot'></span>" +
        titulo + "</div>",
        unsafe_allow_html=True,
    )


def section_close():
    st.markdown("</div>", unsafe_allow_html=True)


def grafico_gauge(score, cor):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score,
        domain={"x": [0, 1], "y": [0, 1]},
        number={"font": {"size": 36, "color": "#0F172A"}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#94A3B8"},
            "bar": {"color": cor, "thickness": 0.3},
            "bgcolor": "#F1F5F9", "borderwidth": 0,
            "steps": [
                {"range": [0, 40], "color": "#FEE2E2"},
                {"range": [40, 60], "color": "#FEF3C7"},
                {"range": [60, 80], "color": "#DBEAFE"},
                {"range": [80, 100], "color": "#DCFCE7"},
            ],
        },
    ))
    fig.update_layout(height=210, margin=dict(l=20, r=20, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def grafico_categorias(categorias):
    if not categorias:
        return None
    itens = sorted(categorias.items(), key=lambda x: x[1])
    labels = [k for k, _ in itens]
    values = [v for _, v in itens]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color="#0284C7", line=dict(color="#012761", width=0.5)),
        text=values, textposition="auto",
    ))
    fig.update_layout(
        height=max(220, 30 * len(labels) + 60),
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=True, gridcolor="#E2E8F0"),
        yaxis=dict(showgrid=False),
        font=dict(family="Inter", color="#334155", size=12),
    )
    return fig


def grafico_serie_mensal(serie):
    if not serie:
        return None
    labels = [s[0] for s in serie]
    values = [s[1] for s in serie]
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color="#F59E0B", line=dict(color="#B45309", width=0.5)),
        text=values, textposition="outside",
    ))
    fig.update_layout(
        height=220, margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#E2E8F0"),
        font=dict(family="Inter", color="#334155", size=11),
    )
    return fig


def grafico_pizza_status(agreg):
    cores = {"Novo": "#3B82F6", "Aberto": "#F59E0B", "Pendente": "#FB923C",
             "Em espera": "#A78BFA", "Resolvido": "#10B981", "Fechado": "#64748B"}
    labels = list(agreg.keys())
    values = list(agreg.values())
    cs = [cores.get(k, "#94A3B8") for k in labels]
    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values, hole=0.55,
        marker=dict(colors=cs, line=dict(color="#FFFFFF", width=2)),
        textinfo="label+percent", textfont=dict(size=11),
    )])
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(l=10, r=10, t=10, b=10),
        height=260, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#334155", size=11),
    )
    return fig


def renderizar_analise(properties, ltv, saude, timeline, tickets, ia,
                        an_tickets, diag_op, segmento, oportunidades, health,
                        produto="GESTAOCLICK", responsavel=None):
    nome = ((properties.get("firstname") or "") + " " + (properties.get("lastname") or "")).strip() or "Cliente"
    empresa = properties.get("company") or "Empresa nao informada"
    stage = properties.get("lifecyclestage") or "-"
    stage_label, _ = STAGE_MAP.get(stage.lower(), (stage.title(), "badge-gray"))

    # Badge de PRODUTO sempre visivel no topo (cor diferenciada por produto)
    if produto == "CLICKNOTAS":
        produto_label = "ClickNotas"
        produto_cor_bg = "#FEF3C7"
        produto_cor_tx = "#92400E"
    else:
        produto_label = "GestaoClick"
        produto_cor_bg = "#DBEAFE"
        produto_cor_tx = "#1E40AF"
    badge_produto = (
        "<span style='display:inline-block;padding:5px 12px;border-radius:999px;"
        "background:" + produto_cor_bg + ";color:" + produto_cor_tx + ";"
        "font-size:12px;font-weight:700;letter-spacing:0.04em;margin-right:8px;"
        "margin-bottom:6px;'>Produto: " + produto_label + "</span>"
    )

    hero_badges = [badge_produto]
    hero_badges.append("<span class='badge badge-light'>" + stage_label + "</span>")
    hero_badges.append("<span class='badge badge-light'>" + ltv["categoria_label"] + "</span>")
    # Plano contratado: SOMENTE quando ja eh cliente (negocio fechado)
    if ltv["is_cliente"] and ltv.get("plano_chave"):
        hero_badges.append("<span class='badge badge-light'>Plano " + ltv["plano_label"] + "</span>")
    hero_badges.append("<span class='badge badge-light'>" + saude["label"] + "</span>")
    hero_badges.append("<span class='badge badge-light'>" + diag_op["label"] + "</span>")

    st.markdown(
        "<div class='hero'>"
        "<h2>" + empresa + "</h2>"
        "<div class='sub'>" + nome + " - Health Score <b style='color:#FFFFFF'>" +
        str(health["score"]) + "/100</b> (" + health["zona"] + ")</div>"
        + "".join(hero_badges) +
        "</div>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs([
        "Visão 360 do Cliente",
        "Performance & Suporte",
        "Inteligência Consultiva",
    ])

    with tab1:
        section_open("Identificação")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(
                "<div class='info-row'><span class='label'>Nome</span><span class='value'>" + nome + "</span></div>"
                "<div class='info-row'><span class='label'>E-mail</span><span class='value'>" + (properties.get("email") or "-") + "</span></div>"
                "<div class='info-row'><span class='label'>Telefone</span><span class='value'>" + (properties.get("phone") or properties.get("mobilephone") or "-") + "</span></div>"
                "<div class='info-row'><span class='label'>Cidade/UF</span><span class='value'>" + (properties.get("city") or "-") + " / " + (properties.get("state") or "-") + "</span></div>",
                unsafe_allow_html=True,
            )
        with col_b:
            link = properties.get("link_intranet") or ""
            link_html = ("<a href='" + link + "' target='_blank'>Abrir cadastro</a>") if link else "-"
            site = properties.get("website") or "-"
            st.markdown(
                "<div class='info-row'><span class='label'>Empresa</span><span class='value'>" + empresa + "</span></div>"
                "<div class='info-row'><span class='label'>Site</span><span class='value'>" + site + "</span></div>"
                "<div class='info-row'><span class='label'>Setor</span><span class='value'>" + (segmento["industry"] or "Nao informado") + "</span></div>"
                "<div class='info-row'><span class='label'>Intranet</span><span class='value'>" + link_html + "</span></div>",
                unsafe_allow_html=True,
            )
        section_close()

        section_open("Equipe de Vendas/Atendimento")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                "<div class='info-row'><span class='label'>Pré-Vendedor</span><span class='value'>" +
                (properties.get("responsavel_pelo_contato") or "-") + "</span></div>",
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                "<div class='info-row'><span class='label'>Consultor Responsável</span><span class='value'>" +
                (properties.get("hubspot_owner_id") or "-") + "</span></div>",
                unsafe_allow_html=True,
            )
        st.caption("Pós-venda e Customer Success são executados por equipe separada do Comercial.")
        section_close()

        section_open("Sinais de Operação Real")
        col_d1, col_d2 = st.columns([1.3, 1])
        with col_d1:
            card_classe = {"badge-red": "insight-card-red", "badge-yellow": "insight-card-yellow",
                            "badge-green": "insight-card-green", "badge-blue": "insight-card-blue",
                            "badge-gray": "insight-card-blue"}[diag_op["badge"]]
            sinais_html = "".join("<li>" + s + "</li>" for s in diag_op["sinais"])
            st.markdown(
                "<div class='" + card_classe + "'>"
                "<div style='font-weight:700;font-size:15px;color:#0F172A;margin-bottom:4px;'>" + diag_op["label"] + "</div>"
                "<div style='font-size:13px;color:#475569;margin-bottom:10px;'>" + diag_op["perfil"] + "</div>"
                "<ul style='margin:0;padding-left:18px;font-size:13px;color:#334155;'>" + sinais_html + "</ul>"
                "</div>",
                unsafe_allow_html=True,
            )
            seg_sinais = "".join("<li>" + s + "</li>" for s in segmento["sinais"])
            st.markdown(
                "<div class='insight-card-blue'>"
                "<div style='font-weight:700;font-size:14px;color:#0F172A;margin-bottom:4px;'>Maturidade digital: " +
                segmento["maturidade_label"] + "</div>"
                "<ul style='margin:0;padding-left:18px;font-size:13px;color:#334155;'>" + seg_sinais + "</ul>"
                "</div>",
                unsafe_allow_html=True,
            )
        with col_d2:
            st.plotly_chart(grafico_gauge(health["score"], health["cor"]), width="stretch")
            st.markdown(
                "<div style='text-align:center;font-size:12px;color:#64748B;margin-top:-10px;'>Health Score (composto)</div>",
                unsafe_allow_html=True,
            )
        section_close()

        section_open("Linha do Tempo Cruzada (HubSpot × Zendesk)")
        if timeline:
            for e in timeline[:15]:
                st.markdown(
                    "<div class='timeline-item " + e["tipo"] + "'>"
                    "<div class='timeline-when'>" + e["quando"] + " — " + e["data_iso"] + " — " + e["origem"] + "</div>"
                    "<div class='timeline-title'>" + e["titulo"] + "</div>"
                    "<div class='timeline-desc'>" + e["descricao"] + "</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Nenhum evento cronológico mapeado.")
        section_close()

    with tab2:
        section_open("Indicadores Financeiros")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(
                "<div class='kpi-card'>"
                "<small style='color:#64748B;font-weight:600;text-transform:uppercase;font-size:11px;'>Receita Acumulada</small>"
                "<h2 style='margin:6px 0 4px 0;font-size:22px;color:#0F172A;'>" + ltv["receita_acumulada_fmt"] + "</h2>"
                "<span class='badge " + ltv["badge_classe"] + "'>" + ltv["categoria_label"] + "</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        with col2:
            seta = "^" if ltv["ticket_medio_mensal"] >= 200 else ">"
            cor = "#10B981" if ltv["ticket_medio_mensal"] >= 200 else "#64748B"
            plano_html = ""
            if ltv.get("plano_chave"):
                plano_html = "<br><span class='badge " + ltv["plano_badge"] + "' style='margin-top:4px;display:inline-block;'>Plano " + ltv["plano_label"] + "</span>"
            obs_html = ""
            if ltv.get("ticket_observacao"):
                obs_html = "<br><span style='color:#92400E;font-size:11px;font-style:italic;'>" + ltv["ticket_observacao"] + "</span>"
            st.markdown(
                "<div class='kpi-card'>"
                "<small style='color:#64748B;font-weight:600;text-transform:uppercase;font-size:11px;'>Ticket Médio Mensal</small>"
                "<h2 style='margin:6px 0 4px 0;font-size:22px;color:#0F172A;'>" + ltv["ticket_medio_mensal_fmt"] + "</h2>"
                "<span style='color:" + cor + ";font-weight:600;font-size:13px;'>" + seta + " " + str(ltv["meses_relacionamento"]) + " meses</span>"
                + plano_html + obs_html +
                "</div>",
                unsafe_allow_html=True,
            )
        with col3:
            st.markdown(
                "<div class='kpi-card'>"
                "<small style='color:#64748B;font-weight:600;text-transform:uppercase;font-size:11px;'>Health Score</small>"
                "<h2 style='margin:6px 0 4px 0;font-size:22px;color:" + health["cor"] + ";'>" + str(health["score"]) + "/100</h2>"
                "<span style='color:#64748B;font-size:12px;'>" + health["zona"] + "</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        section_close()

        section_open("Projeção de LTV")
        ltv_c1, ltv_c2, ltv_c3 = st.columns(3)
        with ltv_c1:
            st.markdown(
                "<div class='kpi-card' style='border-left:4px solid #93C5FD;'>"
                "<small style='color:#64748B;font-weight:600;text-transform:uppercase;font-size:11px;'>LTV 12 meses</small>"
                "<h2 style='margin:6px 0 4px 0;font-size:20px;color:#1E40AF;'>" + ltv["ltv_projetado_12m_fmt"] + "</h2>"
                "<span style='color:#64748B;font-size:12px;'>Ticket × 12</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        with ltv_c2:
            st.markdown(
                "<div class='kpi-card' style='border-left:4px solid #60A5FA;'>"
                "<small style='color:#64748B;font-weight:600;text-transform:uppercase;font-size:11px;'>LTV 24 meses</small>"
                "<h2 style='margin:6px 0 4px 0;font-size:20px;color:#1D4ED8;'>" + ltv["ltv_projetado_24m_fmt"] + "</h2>"
                "<span style='color:#64748B;font-size:12px;'>Ticket × 24</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        with ltv_c3:
            st.markdown(
                "<div class='kpi-card' style='border-left:4px solid #0284C7;'>"
                "<small style='color:#64748B;font-weight:600;text-transform:uppercase;font-size:11px;'>LTV 36 meses</small>"
                "<h2 style='margin:6px 0 4px 0;font-size:20px;color:#0284C7;'>" + ltv["ltv_projetado_36m_fmt"] + "</h2>"
                "<span style='color:#64748B;font-size:12px;'>Ticket × 36 (referência)</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        section_close()

        # Aviso quando os tickets vieram de match por NOME (risco de falso positivo)
        match_por = (tickets[0].get("match_por") if tickets else None)
        if match_por == "nome":
            st.warning(
                "⚠ Tickets encontrados via match por **nome**, não por e-mail ou telefone. "
                "Pode haver falsos positivos (homônimos). Confirme manualmente cada ticket antes "
                "de usar como base para decisão."
            )

        section_open("Análise de Suporte — Categorias e Frequência")
        cg1, cg2 = st.columns(2)
        with cg1:
            st.markdown("<div style='font-size:12px;color:#64748B;font-weight:600;text-transform:uppercase;margin-bottom:6px;'>Tickets por Categoria</div>", unsafe_allow_html=True)
            fig_cat = grafico_categorias(an_tickets["categorias"])
            if fig_cat:
                st.plotly_chart(fig_cat, width="stretch")
            else:
                st.info("Sem tickets para categorizar.")
        with cg2:
            st.markdown("<div style='font-size:12px;color:#64748B;font-weight:600;text-transform:uppercase;margin-bottom:6px;'>Tickets nos Últimos 12 Meses</div>", unsafe_allow_html=True)
            fig_mes = grafico_serie_mensal(an_tickets["serie_mensal"])
            if fig_mes:
                st.plotly_chart(fig_mes, width="stretch")
        if an_tickets["recorrentes"]:
            rec_html = "<div style='margin-top:8px;font-size:13px;color:#475569;'><b>Assuntos recorrentes:</b> "
            rec_html += " — ".join([a + " <b>(" + str(c) + "x)</b>" for a, c in an_tickets["recorrentes"]])
            rec_html += "</div>"
            st.markdown(rec_html, unsafe_allow_html=True)
        section_close()

        section_open("Distribuição de Status do Suporte")
        agreg = agregar_status_tickets(tickets)
        if agreg:
            st.plotly_chart(grafico_pizza_status(agreg), width="stretch")
            st.caption("Total: " + str(len(tickets)) + " chamados no Zendesk")
        else:
            st.info("Nenhum ticket no Zendesk.")
        section_close()

    with tab3:
        if ia.get("diagnostico"):
            section_open("Análise Estratégica (CS / Revenue)")
            st.markdown(
                "<p style='font-size:12.5px;color:#64748B;margin:-4px 0 12px 0;'>"
                "Leitura interpretativa do cliente: fatos observáveis, hipóteses prováveis e conclusões estratégicas. "
                "Linguagem probabilística onde apropriado.</p>",
                unsafe_allow_html=True,
            )
            st.markdown(renderizar_diagnostico_html(ia["diagnostico"]), unsafe_allow_html=True)
            section_close()

        if ia.get("recomendacao"):
            section_open("Recomendação de Ação (próxima jogada)")
            st.markdown(
                "<p style='font-size:12.5px;color:#64748B;margin:-4px 0 12px 0;'>"
                "Ação prioritária definida no padrão de gerente sênior de CS/Revenue: tipo classificado, área responsável, "
                "justificativa contextual, ganho esperado e janela recomendada.</p>",
                unsafe_allow_html=True,
            )
            st.markdown(renderizar_recomendacao_html(ia["recomendacao"]), unsafe_allow_html=True)
            section_close()

        if oportunidades:
            section_open("Oportunidades Mapeadas (Cross-sell, CS e Retenção)")
            for o in oportunidades:
                st.markdown(
                    "<div class='opp-card " + o["prioridade"] + "'>"
                    "<div class='opp-icon'>" + o["icon"] + "</div>"
                    "<div>"
                    "<div class='opp-title'>" + o["titulo"] + " <span class='badge badge-gray' style='margin-left:6px;font-size:10px;'>" + o["prioridade"].upper() + "</span></div>"
                    "<div class='opp-desc'>" + o["descricao"] + "</div>"
                    "</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            section_close()

        if ia.get("whatsapp"):
            section_open("Mensagem de Abordagem Consultiva (WhatsApp)")
            whats_clean = ia["whatsapp"].replace("```text", "").replace("```", "").strip()
            st.markdown("<div class='whatsapp-box'>" + whats_clean + "</div>", unsafe_allow_html=True)
            st.download_button(label="Copiar texto", data=whats_clean,
                                file_name="mensagem_whatsapp.txt", mime="text/plain")
            section_close()


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    try:
        st.image("logo.png", width=180)
        st.markdown("<br>", unsafe_allow_html=True)
    except Exception:
        st.markdown("<h2 style='text-align: center;'>" + APP_NAME + "</h2>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("Sessao: **" + _NOME_USUARIO + "**")
    st.markdown("---")
    st.markdown("**HubSpot CRM** " + ("OK" if HUBSPOT_TOKEN else "off"))
    st.markdown("**Zendesk Support** " + ("OK" if ZENDESK_TOKEN else "off"))
    st.markdown("**Claude API** " + ("OK" if ANTHROPIC_API_KEY else "off"))
    st.markdown("---")
    if st.button("Atualizar Sistema (Rerun)"):
        st.rerun()
    if st.button("Limpar Conversa"):
        st.session_state.messages = []
        st.session_state.ultimo_relatorio = None
        st.rerun()
    _AUTH.logout(button_name="Sair", location="sidebar")
    if st.session_state.ultimo_relatorio:
        st.markdown("---")
        st.markdown("### Exportar")
        rel = st.session_state.ultimo_relatorio
        try:
            pdf_bytes = gerar_pdf_executivo(
                rel["properties"], rel["ltv"], rel["saude"], rel["timeline"],
                rel["tickets"], rel["ia"], rel["an_tickets"], rel["diag_op"],
                rel["segmento"], rel["oportunidades"], rel["health"],
            )
            nome_raw = (rel["properties"].get("company") or rel["properties"].get("email") or "cliente").strip()
            nome_arq = "".join(c for c in nome_raw if c.isalnum() or c in " -_")[:40]
            st.download_button(
                label="Baixar PDF Executivo", data=pdf_bytes,
                file_name="relatorio_" + nome_arq + "_" + datetime.now().strftime("%Y%m%d") + ".pdf",
                mime="application/pdf",
            )
        except Exception as e:
            st.warning("Erro ao gerar PDF: " + str(e))


# ============================================================
# FLUXO PRINCIPAL
# ============================================================
st.markdown("<h1 style='margin-bottom:4px;'>" + APP_NAME + "</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='font-size: 16px; color: #475569; margin-bottom:24px; line-height:1.5;'>"
    "Tudo o que você precisa saber sobre o cliente em uma única tela. "
    "Cruzamos CRM e suporte para entregar diagnóstico operacional, sinais de risco, "
    "oportunidades de receita e a próxima ação consultiva — pronta para executar.</p>",
    unsafe_allow_html=True,
)

if st.session_state.ultimo_relatorio:
    rel = st.session_state.ultimo_relatorio
    renderizar_analise(
        rel["properties"], rel["ltv"], rel["saude"], rel["timeline"],
        rel["tickets"], rel["ia"], rel["an_tickets"], rel["diag_op"],
        rel["segmento"], rel["oportunidades"], rel["health"],
        produto=rel.get("produto", "GESTAOCLICK"),
        responsavel=rel.get("responsavel"),
    )

prompt = st.chat_input("Cole o e-mail, nome ou link da intranet do cliente...")
if prompt:
    with st.spinner("Consultando CRM..."):
        properties = buscar_dados_comerciais_hubspot(prompt)
    if properties.get("_status") in ("vazio", "erro"):
        st.warning(properties.get("Aviso") or properties.get("Erro HubSpot") or "Sem dados.")
        st.stop()
    with st.spinner("Cruzando tickets no atendimento..."):
        nome_busca = ((properties.get("firstname") or "") + " " + (properties.get("lastname") or "")).strip()
        # Se o usuario buscou por e-mail especifico no chat, NAO usa nome como fallback
        # (evita falsos positivos quando o e-mail nao tem ticket no Zendesk).
        usuario_buscou_email = "@" in (prompt or "")
        tickets = buscar_tickets_suporte_zendesk(
            email=properties.get("email", ""), nome=nome_busca,
            telefone=properties.get("phone") or properties.get("mobilephone") or "",
            permitir_fallback_nome=not usuario_buscou_email,
        )
    with st.spinner("Calculando inteligência..."):
        produto = detectar_produto(properties)
        ltv = calcular_ltv(properties, produto=produto)
        saude = classificar_saude(properties, tickets, ltv)
        timeline = montar_timeline_unificada(properties, tickets)
        an_tickets = analisar_tickets(tickets)
        diag_op = diagnosticar_operacao(properties, tickets, an_tickets, ltv)
        segmento = inferir_segmento(properties)
        responsavel = definir_responsavel_acao(properties, ltv, produto)
        health = calcular_health_score(ltv, saude, diag_op, an_tickets)
        oportunidades = sugerir_oportunidades(properties, ltv, an_tickets, diag_op, segmento, produto, responsavel)
    with st.spinner("Gerando diagnóstico do cliente..."):
        ia = gerar_diagnostico_claude(
            properties, ltv, saude, timeline, tickets,
            an_tickets, diag_op, segmento, oportunidades, health,
            produto=produto, responsavel=responsavel,
        )
    st.session_state.ultimo_relatorio = {
        "properties": properties, "ltv": ltv, "saude": saude,
        "timeline": timeline, "tickets": tickets, "ia": ia,
        "an_tickets": an_tickets, "diag_op": diag_op,
        "segmento": segmento, "oportunidades": oportunidades, "health": health,
        "produto": produto, "responsavel": responsavel,
    }
    st.rerun()
