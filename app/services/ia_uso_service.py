"""
"Calculador de uso de IA" — mede o consumo de cada chamada de IA (OpenAI
GPT-5.6, principalmente) e decide se aquele uso é grátis (crédito de
boas-vindas, teto de uso grátis, ou trial de 30 dias do módulo) ou se
deve debitar da carteira do médico (a mesma carteira de horas/créditos
que já existe — saldo único, como decidido).

Regra de negócio (confirmada com o Paulo em 03/09/2026):

  1. Primeiro acesso do médico: ganha um crédito de boas-vindas único
     (R$ 5,00 por padrão) na carteira normal — só uma vez.
  2. Cada módulo de IA ('secretaria', 'prontuario', 'financeiro') ganha
     30 dias grátis a partir do PRIMEIRO uso daquele módulo especificamente
     — não é uma data única pro médico inteiro, é por módulo.
  3. Duas ações específicas (as mais caras) têm teto de uso grátis À PARTE,
     válido uma vez só por médico, pra sempre (não é por mês, conta mesmo
     dentro do trial de 30 dias):
       - 'prontuario_analise'          -> 3 grátis
       - 'secretaria_envio_paciente'   -> 10 grátis
  4. Quando o trial de 30 dias de um módulo termina (e não há mais teto
     grátis disponível pra ação em questão), o sistema BLOQUEIA o uso de
     IA daquele módulo e avisa o médico — não deixa continuar de graça
     "por fora".

Como usar isso nos pontos que chamam IA:

    from app.services import ia_uso_service as ia_uso

    ia_uso.verificar_acesso(medico["id"], "prontuario", "prontuario_analise")
    # ... chama o provider (ai_provider.py), pega o resultado ...
    ia_uso.registrar_uso_ia(
        medico_id=medico["id"], modulo_slug="prontuario", acao="prontuario_analise",
        provedor="claude", modelo=provider.nome_modelo,
        tokens_entrada=resultado.get("tokens_entrada", 0),
        tokens_saida=resultado.get("tokens_saida", 0),
        descricao="Análise de prontuário",
    )

`verificar_acesso` levanta AcessoIABloqueadoError ANTES de gastar dinheiro
de verdade com o provedor de IA, se o médico já não tem mais direito a uso
grátis e o saldo está zerado/negativo. `registrar_uso_ia` é chamado DEPOIS
da chamada de IA (só aí se sabe quantos tokens foram usados de verdade) e
é quem decide se cobra ou não, grava o extrato e debita a carteira.
"""
import os
from datetime import datetime, timedelta, timezone

from app.services.supabase_client import get_client
from app.services import creditos_service


# Preço de cada modelo é cobrado pela OpenAI/Google/Anthropic em DÓLAR,
# por 1 MILHÃO de tokens — por isso guardamos aqui em USD por 1.000
# tokens (preço oficial ÷ 1000) e convertemos pra R$ na hora de calcular,
# usando USD_PARA_BRL logo abaixo. ATUALIZE quando o preço mudar:
#   OpenAI: https://platform.openai.com/docs/models (aba de preços)
#   Gemini: https://ai.google.dev/gemini-api/docs/pricing
#   Claude: https://platform.claude.com/docs/en/about-claude/pricing
# Conferido em 03/09/2026. Cada modelo pode ter uma variável de ambiente
# própria (ex: GEMINI_35_FLASH_LITE_ENTRADA_USD_POR_1K) — se um modelo
# não estiver na tabela (ex: você trocou OPENAI_MODEL pra um lançado
# depois), cai no preço genérico do provedor (menos preciso, mas não
# quebra o cálculo).
PRECOS_USD_POR_1K = {
    # modelo -> (entrada, saída), em USD por 1.000 tokens
    # OpenAI (GPT-5.6) — provedor padrão do serviço pago de IA desde 03/09/2026
    "gpt-5.6-luna": (0.00020, 0.00120),   # cost-optimized — padrão pra quase tudo
    "gpt-5.6-terra": (0.00200, 0.01200),  # balanced — não usado por padrão hoje, fica disponível
    "gpt-5.6-sol": (0.00400, 0.02000),    # flagship — só análise de prontuário/exame complexa
    # Gemini — opção alternativa (não usado por padrão desde a virada pra OpenAI)
    "gemini-3.5-flash-lite": (0.00030, 0.00250),
    "gemini-3.1-flash-lite": (0.00025, 0.00150),
    "gemini-3.5-flash": (0.00150, 0.00900),
    "gemini-2.5-flash": (0.00030, 0.00250),
    "gemini-3.1-pro-preview": (0.00200, 0.01200),
    "gemini-2.5-pro": (0.00125, 0.01000),
    # Claude
    "claude-sonnet-4-6": (0.00300, 0.01500),
    "claude-haiku-4-5": (0.00100, 0.00500),
}
# Preço genérico por provedor, usado só quando o modelo configurado não
# está na tabela acima (fallback de segurança — sempre prefira colocar
# o modelo certo na tabela em vez de confiar nesse valor "no chute").
PRECO_GENERICO_USD_POR_1K = {
    "openai": (float(os.getenv("OPENAI_PRECO_ENTRADA_POR_1K_USD", "0.00020")),
               float(os.getenv("OPENAI_PRECO_SAIDA_POR_1K_USD", "0.00120"))),
    "gemini": (float(os.getenv("GEMINI_PRECO_ENTRADA_POR_1K_USD", "0.00030")),
               float(os.getenv("GEMINI_PRECO_SAIDA_POR_1K_USD", "0.00250"))),
    "claude": (float(os.getenv("CLAUDE_PRECO_ENTRADA_POR_1K_USD", "0.00300")),
               float(os.getenv("CLAUDE_PRECO_SAIDA_POR_1K_USD", "0.01500"))),
}

# Cotação do dólar em reais — ATUALIZE periodicamente (não precisa ser
# em tempo real, mas revise de tempos em tempos pra não ficar muito
# desatualizado). Conferido em 03/09/2026: ~R$ 5,16.
USD_PARA_BRL = float(os.getenv("USD_PARA_BRL", "5.16"))

# Margem cobrada em cima do custo real (5.0 = cobra 5x o que a IA custou
# de verdade). É aqui que fica a sua margem de lucro do serviço de IA.
MARGEM_PADRAO = float(os.getenv("IA_MARGEM_PADRAO", "5.0"))

# Valor do crédito de boas-vindas (primeiro acesso), em R$ -- exclusivo
# pra IA desde a divisão de carteiras (08/09/2026); antes ia pro saldo
# geral (R$ 5,00), agora é R$ 10,00 de saldo_ia especificamente.
VALOR_CREDITO_BOAS_VINDAS = float(os.getenv("IA_CREDITO_BOAS_VINDAS", "10.00"))

# Quantos dias de trial cada módulo ganha a partir do primeiro uso.
DIAS_TRIAL_MODULO = int(os.getenv("IA_DIAS_TRIAL_MODULO", "30"))

# Tetos de uso grátis "pra sempre" (uma vez só por médico), por ação.
TETOS_GRATIS_UNICOS = {
    "prontuario_analise": 3,
    "secretaria_envio_paciente": 10,
}

# Algumas ações não chamam IA de verdade (ex: enviar a confirmação pro
# paciente é um TEXTO FIXO, sem tokens) mas ainda assim são o que o
# Paulo quer cobrar — o valor do envio de WhatsApp/e-mail em si, não o
# custo de IA. Por isso têm preço FIXO configurável em vez de calculado
# por token. Mesma regra de teto/trial se aplica por cima.
PRECOS_FIXOS_ACOES = {
    "secretaria_envio_paciente": float(os.getenv("IA_PRECO_ENVIO_PACIENTE", "1.50")),
    "financeiro_emitir_recibo": float(os.getenv("IA_PRECO_EMISSAO_RECIBO", "2.00")),
}

MODULOS_VALIDOS = ("secretaria", "prontuario", "prontuario_voz", "financeiro")

# Rótulos amigáveis pra tela "Painel de IA" (checkbox de cada módulo)
ROTULOS_MODULOS = {
    "secretaria": "Uso de secretária virtual pelo WhatsApp",
    "prontuario": "Análise de prontuário",
    "prontuario_voz": "Análise de voz para preenchimento automático de prontuário pela IA durante a consulta",
    "financeiro": "Assistente contábil",
}


class AcessoIABloqueadoError(Exception):
    """
    Levantada quando o médico não tem mais direito a uso grátis de IA
    naquele módulo (trial de 30 dias encerrado e nenhum teto grátis
    disponível) E o saldo da carteira está zerado ou negativo.
    """
    def __init__(self, modulo_slug: str, mensagem: str | None = None):
        self.modulo_slug = modulo_slug
        self.mensagem = mensagem or (
            f"O período de teste grátis do módulo '{modulo_slug}' acabou e o saldo "
            f"está insuficiente. Adicione créditos para continuar usando a IA nesse módulo."
        )
        super().__init__(self.mensagem)


# ---------- Configuração de preço/margem editável (Dashboard Admin) ----------
# O painel "IA — Consumo de tokens e faturamento" deixa o admin editar o
# percentual de aumento (ganho da empresa) e o preço por 1.000 tokens da
# OpenAI direto pela tela, sem precisar mexer em variável de ambiente
# nem redeployar. Guardado na mesma tabela `precos` de sempre (ver
# sql/migration_ia_precos.sql). Enquanto a migração não roda (ou numa
# instalação nova que ainda não salvou nada), cai nos valores de sempre
# (env var / tabela de preço do gpt-5.6-luna) -- nada muda pra quem já
# está rodando.

def obter_config_precificacao_ia() -> dict:
    """Config atual de preço/margem da IA paga -- o que o admin vê e edita
    no Dashboard. Nunca falha mesmo sem a migração rodada ainda."""
    precos = creditos_service.obter_precos()
    preco_luna_entrada, preco_luna_saida = PRECOS_USD_POR_1K["gpt-5.6-luna"]
    return {
        "percentual_aumento": precos.get("ia_percentual_aumento") if precos.get("ia_percentual_aumento") is not None else round((MARGEM_PADRAO - 1) * 100, 2),
        "preco_entrada_usd_1k": precos.get("ia_preco_entrada_usd_1k") or preco_luna_entrada,
        "preco_saida_usd_1k": precos.get("ia_preco_saida_usd_1k") or preco_luna_saida,
        "usd_para_brl": precos.get("ia_usd_para_brl") or USD_PARA_BRL,
    }


def atualizar_config_precificacao_ia(percentual_aumento: float, preco_entrada_usd_1k: float,
                                      preco_saida_usd_1k: float, usd_para_brl: float) -> dict:
    """Salva o que o admin editou na tela. Validações simples pra não
    deixar salvar um valor absurdo (negativo, cotação zerada) que
    bagunçaria toda cobrança de IA dali pra frente."""
    if percentual_aumento < 0:
        raise ValueError("O percentual de aumento não pode ser negativo.")
    if preco_entrada_usd_1k < 0 or preco_saida_usd_1k < 0:
        raise ValueError("Os preços por 1.000 tokens não podem ser negativos.")
    if usd_para_brl <= 0:
        raise ValueError("A cotação do dólar precisa ser maior que zero.")

    client = get_client()
    atual = client.table("precos").select("id").limit(1).execute().data
    payload = {
        "ia_percentual_aumento": percentual_aumento,
        "ia_preco_entrada_usd_1k": preco_entrada_usd_1k,
        "ia_preco_saida_usd_1k": preco_saida_usd_1k,
        "ia_usd_para_brl": usd_para_brl,
    }
    if atual:
        resp = client.table("precos").update(payload).eq("id", atual[0]["id"]).execute()
    else:
        resp = client.table("precos").insert(payload).execute()
    return resp.data[0]


# ---------- Cálculo de custo (o "calculador" em si) ----------

def calcular_custo_real(provedor: str, modelo: str | None, tokens_entrada: int, tokens_saida: int) -> float:
    """Quanto essa chamada custou DE VERDADE no provedor de IA, já em R$ (estimativa).
    Pra OpenAI (o provedor pago padrão desde 03/09/2026), usa sempre o preço configurado
    pelo admin no Dashboard (editável na tela, ver obter_config_precificacao_ia) -- é
    o valor que manda, mesmo que a tabela PRECOS_USD_POR_1K abaixo tenha outro número
    pro modelo específico. Gemini/Claude (não usados por padrão hoje) continuam pelo
    preço específico do modelo, com o preço genérico do provedor como reserva."""
    if provedor not in ("openai", "gemini", "claude"):
        raise ValueError(f"Provedor de IA desconhecido: {provedor}")

    if provedor == "openai":
        config = obter_config_precificacao_ia()
        preco_entrada_usd = config["preco_entrada_usd_1k"]
        preco_saida_usd = config["preco_saida_usd_1k"]
        usd_para_brl = config["usd_para_brl"]
    else:
        preco_entrada_usd, preco_saida_usd = PRECOS_USD_POR_1K.get(
            modelo or "", PRECO_GENERICO_USD_POR_1K[provedor]
        )
        usd_para_brl = USD_PARA_BRL

    custo_usd = (tokens_entrada / 1000) * preco_entrada_usd + (tokens_saida / 1000) * preco_saida_usd
    return round(custo_usd * usd_para_brl, 4)


def calcular_valor_cobranca(custo_real: float, margem: float | None = None) -> float:
    """Quanto cobrar do médico em cima do custo real — nunca menos que 1 centavo
    se houve consumo de verdade, pra não gerar cobrança de R$ 0,00 estranha no extrato.
    Sem `margem` explícita, usa o percentual de aumento configurado pelo admin no
    Dashboard (1 + percentual/100 -- ex: 400% = cobra 5x o custo real)."""
    if margem is None:
        margem = 1 + (obter_config_precificacao_ia()["percentual_aumento"] / 100)
    valor = round(custo_real * margem, 2)
    if custo_real > 0 and valor == 0:
        valor = 0.01
    return valor


# ---------- Crédito de boas-vindas ----------

def garantir_credito_boas_vindas(medico_id: str) -> bool:
    """
    Concede o crédito único de teste no primeiro acesso do médico à IA.
    Idempotente — não concede de novo se já foi concedido. Retorna True
    se concedeu agora (útil pra avisar o médico), False se já tinha.
    """
    client = get_client()
    medico = client.table("medicos").select("ia_trial_creditado").eq("id", medico_id).execute().data
    if not medico or medico[0].get("ia_trial_creditado"):
        return False

    creditos_service.registrar_transacao(
        medico_id, tipo="ajuste", valor=VALOR_CREDITO_BOAS_VINDAS,
        descricao="Crédito de boas-vindas — teste do assistente de IA",
        categoria="ia", carteira="ia",
    )
    client.table("medicos").update({"ia_trial_creditado": True}).eq("id", medico_id).execute()
    return True


# ---------- Estado do módulo (trial de 30 dias) ----------

def _obter_ou_ativar_modulo(medico_id: str, modulo_slug: str) -> dict:
    """Busca o estado do módulo pra esse médico; se for a primeira vez, ativa agora
    (é o que marca o início da contagem dos 30 dias grátis daquele módulo)."""
    if modulo_slug not in MODULOS_VALIDOS:
        raise ValueError(f"Módulo de IA desconhecido: {modulo_slug}")

    client = get_client()
    existente = (
        client.table("medico_modulos_ia").select("*")
        .eq("medico_id", medico_id).eq("modulo_slug", modulo_slug).execute().data
    )
    if existente:
        return existente[0]

    agora = datetime.now(timezone.utc)
    trial_fim = agora + timedelta(days=DIAS_TRIAL_MODULO)
    resp = client.table("medico_modulos_ia").insert({
        "medico_id": medico_id,
        "modulo_slug": modulo_slug,
        "ativado_em": agora.isoformat(),
        "trial_fim": trial_fim.isoformat(),
    }).execute()
    return resp.data[0]


def _modulo_em_trial(estado_modulo: dict) -> bool:
    trial_fim = estado_modulo["trial_fim"]
    if isinstance(trial_fim, str):
        trial_fim = datetime.fromisoformat(trial_fim.replace("Z", "+00:00"))
    if trial_fim.tzinfo is None:
        trial_fim = trial_fim.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < trial_fim


def dias_restantes_trial(estado_modulo: dict) -> int:
    trial_fim = estado_modulo["trial_fim"]
    if isinstance(trial_fim, str):
        trial_fim = datetime.fromisoformat(trial_fim.replace("Z", "+00:00"))
    if trial_fim.tzinfo is None:
        trial_fim = trial_fim.replace(tzinfo=timezone.utc)
    restante = trial_fim - datetime.now(timezone.utc)
    return max(0, restante.days)


# ---------- Teto de uso grátis (pra sempre, uma vez só) ----------

def _teto_disponivel(medico_id: str, acao: str) -> bool:
    limite = TETOS_GRATIS_UNICOS.get(acao)
    if limite is None:
        return False
    client = get_client()
    resp = (
        client.table("medico_ia_contadores").select("usados")
        .eq("medico_id", medico_id).eq("acao", acao).execute().data
    )
    usados = resp[0]["usados"] if resp else 0
    return usados < limite


def _consumir_teto_gratis(medico_id: str, acao: str):
    client = get_client()
    existente = (
        client.table("medico_ia_contadores").select("*")
        .eq("medico_id", medico_id).eq("acao", acao).execute().data
    )
    if existente:
        client.table("medico_ia_contadores").update(
            {"usados": existente[0]["usados"] + 1}
        ).eq("id", existente[0]["id"]).execute()
    else:
        client.table("medico_ia_contadores").insert(
            {"medico_id": medico_id, "acao": acao, "usados": 1}
        ).execute()


def contadores_gratis_medico(medico_id: str) -> dict:
    """Pra mostrar no painel: quanto ainda sobra de cada teto grátis."""
    client = get_client()
    resp = client.table("medico_ia_contadores").select("*").eq("medico_id", medico_id).execute().data
    usados_por_acao = {r["acao"]: r["usados"] for r in resp}
    return {
        acao: {"usados": usados_por_acao.get(acao, 0), "limite": limite,
               "restantes": max(0, limite - usados_por_acao.get(acao, 0))}
        for acao, limite in TETOS_GRATIS_UNICOS.items()
    }


# ---------- Toggle explícito do médico (Painel de IA) ----------
# Diferente de medico_modulos_ia (que só marca quando o médico USOU
# pela primeira vez, pra contar os 30 dias de trial) -- esse é o
# médico dizendo "quero usar isso" antes de gastar saldo de verdade.
# Sem marcar, só o crédito de teste grátis funciona.

def obter_modulos_ativados(medico_id: str) -> dict:
    """Devolve {modulo_slug: True/False} pros 4 módulos -- os que o
    médico nunca mexeu vêm como False (ativação é opt-in). Se a tabela
    ia_modulos_ativados ainda não existir (migração pendente), devolve
    tudo False em vez de quebrar a tela."""
    try:
        resp = (
            get_client().table("ia_modulos_ativados").select("modulo_slug, ativado")
            .eq("medico_id", medico_id).execute()
        )
        ativados = {r["modulo_slug"]: r["ativado"] for r in resp.data}
    except Exception as e:
        print(f"[ia_uso_service] ia_modulos_ativados indisponível (rode a migração?): {e}")
        ativados = {}
    return {slug: ativados.get(slug, False) for slug in MODULOS_VALIDOS}


def definir_modulo_ativado(medico_id: str, modulo_slug: str, ativado: bool) -> dict:
    if modulo_slug not in MODULOS_VALIDOS:
        raise ValueError(f"Módulo de IA desconhecido: {modulo_slug}")
    client = get_client()
    existente = (
        client.table("ia_modulos_ativados").select("id")
        .eq("medico_id", medico_id).eq("modulo_slug", modulo_slug).execute().data
    )
    payload = {"ativado": ativado, "atualizado_em": datetime.now(timezone.utc).isoformat()}
    if ativado:
        payload["ativado_em"] = datetime.now(timezone.utc).isoformat()
    if existente:
        resp = client.table("ia_modulos_ativados").update(payload).eq("id", existente[0]["id"]).execute()
    else:
        resp = client.table("ia_modulos_ativados").insert({
            "medico_id": medico_id, "modulo_slug": modulo_slug, **payload,
        }).execute()
    return resp.data[0]


def _modulo_ativado_pelo_medico(medico_id: str, modulo_slug: str) -> bool:
    resp = (
        get_client().table("ia_modulos_ativados").select("ativado")
        .eq("medico_id", medico_id).eq("modulo_slug", modulo_slug).execute().data
    )
    return bool(resp and resp[0]["ativado"])


# ---------- Pré-checagem (chamar ANTES de gastar dinheiro com IA de verdade) ----------

def verificar_acesso(medico_id: str, modulo_slug: str, acao: str | None = None):
    """
    Confere se o médico pode usar IA nesse módulo AGORA, antes de gastar
    com o provedor de IA de verdade. Levanta AcessoIABloqueadoError se:
    o módulo não foi ativado pelo médico em "Painel de IA" E não sobrou
    crédito de teste grátis nem teto grátis pra essa ação específica.

    Não gasta nada — só ativa o módulo (primeira vez) e checa o estado.
    """
    garantir_credito_boas_vindas(medico_id)
    estado_modulo = _obter_ou_ativar_modulo(medico_id, modulo_slug)

    if acao and _teto_disponivel(medico_id, acao):
        return  # ação específica ainda tem uso grátis garantido, libera sempre

    if _modulo_em_trial(estado_modulo):
        return  # dentro dos 30 dias grátis do módulo

    if not _modulo_ativado_pelo_medico(medico_id, modulo_slug):
        raise AcessoIABloqueadoError(
            modulo_slug,
            f"Pra usar IA no módulo '{ROTULOS_MODULOS.get(modulo_slug, modulo_slug)}' além do "
            f"crédito de teste grátis, ative essa opção em Painel de IA.",
        )

    saldo = creditos_service.obter_saldo_ia(medico_id)
    if saldo <= 0:
        raise AcessoIABloqueadoError(modulo_slug)
    # saldo positivo: libera (o valor exato só é conhecido depois da chamada,
    # em registrar_uso_ia — ver observação no topo do arquivo)


# ---------- Registro pós-chamada (mede, decide se cobra, debita) ----------

def _decidir_gratuidade(medico_id: str, modulo_slug: str, acao: str) -> tuple[bool, str | None]:
    """Mesma regra usada tanto pra uso medido por token quanto por ação de preço
    fixo: teto único disponível > trial de 30 dias do módulo > senão, cobra."""
    estado_modulo = _obter_ou_ativar_modulo(medico_id, modulo_slug)

    if acao in TETOS_GRATIS_UNICOS and _teto_disponivel(medico_id, acao):
        _consumir_teto_gratis(medico_id, acao)
        return True, "teto_uso_gratis"
    if _modulo_em_trial(estado_modulo):
        return True, "trial_30_dias"
    return False, None


def _debitar_e_logar(medico_id: str, modulo_slug: str, acao: str, provedor: str, modelo: str | None,
                      tokens_entrada: int, tokens_saida: int, custo_real: float,
                      gratuito: bool, motivo: str | None, descricao: str) -> dict:
    custo_cobrado = 0.0
    saldo_apos = None
    if not gratuito:
        custo_cobrado = calcular_valor_cobranca(custo_real) if tokens_entrada or tokens_saida else custo_real
        if custo_cobrado > 0:
            resultado = creditos_service.registrar_transacao(
                medico_id, tipo="consumo", valor=-custo_cobrado,
                descricao=descricao or f"Uso de IA — {modulo_slug}/{acao}",
                categoria="ia", carteira="ia",
            )
            saldo_apos = resultado["saldo_novo"]
            try:
                medico = get_client().table("medicos").select("*").eq("id", medico_id).execute().data
                if medico:
                    from app.services import notificacao_saldo
                    notificacao_saldo.verificar_e_notificar_saldo_baixo_fixo(medico[0], saldo_apos, carteira="ia")
            except Exception as e:
                print(f"[ia_uso_service] Erro ao verificar alerta de saldo de IA baixo: {e}")

    get_client().table("ia_uso_log").insert({
        "medico_id": medico_id,
        "modulo_slug": modulo_slug,
        "acao": acao,
        "provedor": provedor,
        "modelo": modelo,
        "tokens_entrada": tokens_entrada,
        "tokens_saida": tokens_saida,
        "custo_real": custo_real,
        "custo_cobrado": custo_cobrado,
        "gratuito": gratuito,
        "motivo_gratuito": motivo,
        "descricao": descricao,
    }).execute()

    return {
        "gratuito": gratuito,
        "motivo_gratuito": motivo,
        "custo_real": custo_real,
        "custo_cobrado": custo_cobrado,
        "saldo_apos": saldo_apos,
        "teto_restante": (
            TETOS_GRATIS_UNICOS[acao] - _contador_atual(medico_id, acao)
            if acao in TETOS_GRATIS_UNICOS else None
        ),
    }


def registrar_uso_ia(medico_id: str, modulo_slug: str, acao: str, provedor: str,
                      modelo: str | None, tokens_entrada: int, tokens_saida: int,
                      descricao: str = "") -> dict:
    """
    Chamar DEPOIS de uma chamada de IA bem-sucedida, já com os tokens
    reais consumidos (ex: uma mensagem de secretaria, uma análise de
    prontuário, uma sugestão de classificação de despesa). Decide se
    esse uso é grátis (teto único > trial de 30 dias) ou se deve debitar
    da carteira (custo real x margem), grava o extrato completo em
    ia_uso_log, e retorna um resumo pro chamador poder avisar o médico
    se quiser (ex: "essa foi sua última análise grátis").
    """
    custo_real = calcular_custo_real(provedor, modelo, tokens_entrada, tokens_saida)
    gratuito, motivo = _decidir_gratuidade(medico_id, modulo_slug, acao)
    return _debitar_e_logar(medico_id, modulo_slug, acao, provedor, modelo,
                             tokens_entrada, tokens_saida, custo_real, gratuito, motivo, descricao)


def registrar_uso_acao_fixa(medico_id: str, modulo_slug: str, acao: str, descricao: str = "") -> dict:
    """
    Igual a registrar_uso_ia, mas pra ações que NÃO chamam um provedor de
    IA (ex: enviar a confirmação de consulta pro paciente é um texto
    fixo/template — sem tokens) e por isso têm preço fixo configurado em
    PRECOS_FIXOS_ACOES, em vez de calculado por token. A mesma regra de
    teto/trial grátis se aplica por cima.
    """
    custo_real = PRECOS_FIXOS_ACOES.get(acao, 0.0)
    gratuito, motivo = _decidir_gratuidade(medico_id, modulo_slug, acao)
    return _debitar_e_logar(medico_id, modulo_slug, acao, provedor="lifemax", modelo=None,
                             tokens_entrada=0, tokens_saida=0, custo_real=custo_real,
                             gratuito=gratuito, motivo=motivo, descricao=descricao)


def _contador_atual(medico_id: str, acao: str) -> int:
    resp = (
        get_client().table("medico_ia_contadores").select("usados")
        .eq("medico_id", medico_id).eq("acao", acao).execute().data
    )
    return resp[0]["usados"] if resp else 0


# ---------- Visão geral pro painel do médico ----------

def status_ia_medico(medico_id: str) -> dict:
    """Tudo que o painel do médico precisa mostrar: saldo de IA, status
    de cada módulo (ativado pelo médico? em trial/teste? pago?) e
    quanto sobra de cada teto grátis."""
    client = get_client()
    modulos_ativados_trial = {
        m["modulo_slug"]: m
        for m in client.table("medico_modulos_ia").select("*").eq("medico_id", medico_id).execute().data
    }
    modulos_ativados_pelo_medico = obter_modulos_ativados(medico_id)

    status_modulos = {}
    for slug in MODULOS_VALIDOS:
        estado = modulos_ativados_trial.get(slug)
        if not estado:
            status_modulos[slug] = {"em_trial": None, "dias_restantes": None}
        else:
            status_modulos[slug] = {
                "em_trial": _modulo_em_trial(estado),
                "dias_restantes": dias_restantes_trial(estado),
            }
        status_modulos[slug]["rotulo"] = ROTULOS_MODULOS[slug]
        status_modulos[slug]["ativado_pelo_medico"] = modulos_ativados_pelo_medico[slug]

    return {
        "saldo": creditos_service.obter_saldo_ia(medico_id),
        "modulos": status_modulos,
        "tetos_gratis": contadores_gratis_medico(medico_id),
    }


def extrato_uso_ia(medico_id: str, limite: int = 30) -> list[dict]:
    resp = (
        get_client().table("ia_uso_log").select("*")
        .eq("medico_id", medico_id).order("criado_em", desc=True).limit(limite).execute()
    )
    return resp.data


# ---------- Visão geral pro admin: tokens gastos x quanto a empresa ganha ----------

def _filtrar_por_mes_ano(registros: list[dict], mes: int | None, ano: int | None) -> list[dict]:
    """Mesmo critério usado em creditos_service._filtrar_por_mes_ano -- olha
    só os 4 primeiros dígitos (ano) e os 2 seguintes (mês) da string
    'criado_em' (formato ISO), sem precisar converter pra datetime."""
    if mes is None and ano is None:
        return registros
    filtrados = []
    for r in registros:
        data_str = r.get("criado_em") or ""
        if not data_str:
            continue
        ano_r, mes_r = int(data_str[0:4]), int(data_str[5:7])
        if (mes is None or mes_r == mes) and (ano is None or ano_r == ano):
            filtrados.append(r)
    return filtrados


def estatisticas_uso_ia(mes: int | None = None, ano: int | None = None) -> dict:
    """Pro Dashboard Admin: quantos tokens foram consumidos e quanto a
    empresa ganhou de verdade num período (mês/ano, igual ao filtro que já
    existe no resto do Dashboard -- ou tudo, se nenhum dos dois for
    informado). 'Ganha' aqui é LUCRO: o que foi cobrado dos médicos menos
    o que a chamada custou de verdade nos provedores de IA -- não é só a
    receita bruta, é a margem que sobra de verdade."""
    registros = (
        get_client().table("ia_uso_log")
        .select("tokens_entrada, tokens_saida, custo_real, custo_cobrado, gratuito, criado_em")
        .execute()
        .data
    )
    filtrados = _filtrar_por_mes_ano(registros, mes, ano)

    tokens_entrada = sum(int(r.get("tokens_entrada") or 0) for r in filtrados)
    tokens_saida = sum(int(r.get("tokens_saida") or 0) for r in filtrados)
    custo_real = sum(float(r.get("custo_real") or 0) for r in filtrados)
    valor_cobrado = sum(float(r.get("custo_cobrado") or 0) for r in filtrados)
    total_chamadas = len(filtrados)
    chamadas_gratuitas = sum(1 for r in filtrados if r.get("gratuito"))

    return {
        "tokens_entrada": tokens_entrada,
        "tokens_saida": tokens_saida,
        "tokens_total": tokens_entrada + tokens_saida,
        "custo_real": round(custo_real, 2),
        "valor_cobrado": round(valor_cobrado, 2),
        "lucro": round(valor_cobrado - custo_real, 2),
        "total_chamadas": total_chamadas,
        "chamadas_gratuitas": chamadas_gratuitas,
        "chamadas_pagas": total_chamadas - chamadas_gratuitas,
    }


def estatisticas_uso_ia_diario(dias: int = 30) -> list[dict]:
    """Quebra dia a dia dos últimos `dias` dias (mais antigo primeiro) --
    tokens consumidos, custo real, valor cobrado e lucro por dia. Usado
    na tabela diária do painel de faturamento de IA do admin, ao lado do
    filtro por mês/ano de estatisticas_uso_ia()."""
    limite = (datetime.now(timezone.utc) - timedelta(days=dias)).date().isoformat()
    registros = (
        get_client().table("ia_uso_log")
        .select("tokens_entrada, tokens_saida, custo_real, custo_cobrado, criado_em")
        .execute()
        .data
    )

    por_dia: dict[str, dict] = {}
    for r in registros:
        data_str = (r.get("criado_em") or "")[:10]
        if not data_str or data_str < limite:
            continue
        dia = por_dia.setdefault(data_str, {"tokens_total": 0, "custo_real": 0.0, "valor_cobrado": 0.0})
        dia["tokens_total"] += int(r.get("tokens_entrada") or 0) + int(r.get("tokens_saida") or 0)
        dia["custo_real"] += float(r.get("custo_real") or 0)
        dia["valor_cobrado"] += float(r.get("custo_cobrado") or 0)

    return [
        {
            "data": data_str,
            "tokens_total": por_dia[data_str]["tokens_total"],
            "custo_real": round(por_dia[data_str]["custo_real"], 2),
            "valor_cobrado": round(por_dia[data_str]["valor_cobrado"], 2),
            "lucro": round(por_dia[data_str]["valor_cobrado"] - por_dia[data_str]["custo_real"], 2),
        }
        for data_str in sorted(por_dia.keys())
    ]


def estatisticas_uso_ia_por_medico(mes: int | None = None, ano: int | None = None) -> list[dict]:
    """Pra tela admin "Controle de IA" (pedido do Paulo em 21/09/2026):
    quanto CADA médico gastou de IA (tokens e R$) num período, junto com
    o saldo de IA atual dele -- diferente de estatisticas_uso_ia(), que
    só devolve o total agregado de todo mundo junto. Ordenado do médico
    que mais gastou (valor_cobrado) pro que menos gastou; médico sem
    nenhum uso no período não aparece na lista."""
    registros = (
        get_client().table("ia_uso_log")
        .select("medico_id, tokens_entrada, tokens_saida, custo_real, custo_cobrado, gratuito, criado_em")
        .execute()
        .data
    )
    filtrados = _filtrar_por_mes_ano(registros, mes, ano)

    por_medico: dict[str, dict] = {}
    for r in filtrados:
        medico_id = r.get("medico_id")
        if not medico_id:
            continue
        acumulado = por_medico.setdefault(medico_id, {
            "tokens_entrada": 0, "tokens_saida": 0, "custo_real": 0.0,
            "valor_cobrado": 0.0, "total_chamadas": 0, "chamadas_gratuitas": 0,
        })
        acumulado["tokens_entrada"] += int(r.get("tokens_entrada") or 0)
        acumulado["tokens_saida"] += int(r.get("tokens_saida") or 0)
        acumulado["custo_real"] += float(r.get("custo_real") or 0)
        acumulado["valor_cobrado"] += float(r.get("custo_cobrado") or 0)
        acumulado["total_chamadas"] += 1
        if r.get("gratuito"):
            acumulado["chamadas_gratuitas"] += 1

    if not por_medico:
        return []

    medicos = (
        get_client().table("medicos").select("id, nome")
        .in_("id", list(por_medico.keys())).execute().data
    )
    nomes = {m["id"]: m["nome"] for m in medicos}
    saldos_ia = {medico_id: creditos_service.obter_saldo_ia(medico_id) for medico_id in por_medico}

    linhas = [
        {
            "medico_id": medico_id,
            "medico_nome": nomes.get(medico_id, "(médico removido)"),
            "tokens_total": dados["tokens_entrada"] + dados["tokens_saida"],
            "custo_real": round(dados["custo_real"], 2),
            "valor_cobrado": round(dados["valor_cobrado"], 2),
            "lucro": round(dados["valor_cobrado"] - dados["custo_real"], 2),
            "total_chamadas": dados["total_chamadas"],
            "chamadas_gratuitas": dados["chamadas_gratuitas"],
            "saldo_ia_atual": saldos_ia.get(medico_id, 0),
        }
        for medico_id, dados in por_medico.items()
    ]
    linhas.sort(key=lambda linha: linha["valor_cobrado"], reverse=True)
    return linhas
