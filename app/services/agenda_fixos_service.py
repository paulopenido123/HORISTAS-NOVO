"""
Agenda dos médicos fixos (Módulo 2): médicos com sala e turno fixos no
coworking (diferente da Grade de Turnos, onde o médico avulso aluga
consultório por hora). Aqui a sala já é reservada pra ele em cada
dia/turno da semana, e o que se agenda são OS PACIENTES dentro desses
turnos, em blocos de 20 minutos.

A tela mostra a agenda de 1 médico por vez, no formato semana (linhas de
horário x colunas de dia), com 7 status possíveis pra cada consulta:
Agendado, Confirmado, Chegou, Em atendimento, Finalizado, Cancelado, Faltou.

Import (planilha real de ocupação dos consultórios + dados dos médicos),
cadastro de empresas, grade semanal (médico x dia x turno x sala),
agendamento de consulta, check-in, confirmação, chamada do telão da
recepção e finalização moram todos aqui -- é o mesmo tipo de organização
que reserva_service.py já usa pra Grade de Turnos.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from app.services import supabase_client as db

# ---------------------------------------------------------------------------
# "Hoje" no fuso de Brasília -- o servidor roda em UTC (Render), então
# date.today() puro "vira o dia" 3 horas mais cedo que o horário real de
# Brasília (ex: 22h de terça no relógio da recepção já era quarta pro
# servidor, o que podia fazer a agenda mostrar/gravar no dia errado bem no
# fim do expediente). O Brasil não tem mais horário de verão desde 2019,
# então o fuso de Brasília é sempre UTC-3 -- por isso o fallback manual
# abaixo é seguro mesmo se o pacote de fusos horários (tzdata) não estiver
# instalado no servidor.
try:
    from zoneinfo import ZoneInfo
    _FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")
except Exception:
    _FUSO_BRASIL = None


def hoje_brasil() -> date:
    agora_utc = datetime.now(timezone.utc)
    if _FUSO_BRASIL is not None:
        try:
            return agora_utc.astimezone(_FUSO_BRASIL).date()
        except Exception:
            pass
    return (agora_utc - timedelta(hours=3)).date()

# ---------------------------------------------------------------------------
# Turnos: horário de cada um, e quais dias da semana têm cada turno.
# Sábado só tem manhã -- os outros dias têm os 3.
# ---------------------------------------------------------------------------
TURNOS_HORARIOS = {
    "manha": ("08:00", "12:00"),
    "tarde": ("13:00", "17:00"),
    "noite": ("17:30", "20:30"),
}
# tamanho de cada bloco de consulta do médico fixo -- era de 15 em 15 min,
# passou a ser de 20 em 20 (os 3 turnos acima são todos múltiplos exatos
# de 20 min, então não sobra pedaço nenhum: manhã e tarde viram 12 blocos,
# noite vira 9 blocos).
DURACAO_PADRAO_MIN = 20
DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado"]
TURNOS_POR_DIA = {
    "segunda": ["manha", "tarde", "noite"], "terca": ["manha", "tarde", "noite"],
    "quarta": ["manha", "tarde", "noite"], "quinta": ["manha", "tarde", "noite"],
    "sexta": ["manha", "tarde", "noite"], "sabado": ["manha"],
}
_ROTULO_DIA = {"segunda": "Segunda", "terca": "Terça", "quarta": "Quarta", "quinta": "Quinta",
               "sexta": "Sexta", "sabado": "Sábado"}
_ROTULO_TURNO = {"manha": "Manhã", "tarde": "Tarde", "noite": "Noite"}

_WEEKDAY_PARA_DIA = {0: "segunda", 1: "terca", 2: "quarta", 3: "quinta", 4: "sexta", 5: "sabado", 6: None}
# weekday() do Python: 0=segunda ... 6=domingo
_ROTULO_DIA_CURTO = {0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui", 4: "Sex", 5: "Sáb", 6: "Dom"}
_WEEKDAY_PARA_DIA_CURTO_CHAVE = {0: "segunda", 1: "terca", 2: "quarta", 3: "quinta", 4: "sexta", 5: "sabado", 6: "domingo"}

# Legenda de status da consulta -- os mesmos 7 itens que aparecem embaixo do
# calendário na tela (cor é só sugestão, dá pra trocar sem afetar nada).
STATUS_CONSULTA = ["agendado", "confirmado", "chegou", "em_atendimento", "finalizado", "cancelado", "faltou"]
ROTULO_STATUS = {
    "agendado": "Agendado", "confirmado": "Confirmado", "chegou": "Chegou",
    "em_atendimento": "Em atendimento", "finalizado": "Finalizado",
    "cancelado": "Cancelado", "faltou": "Faltou",
}
COR_STATUS = {
    "agendado": "#2f6fb0", "confirmado": "#7a4fc9", "chegou": "#b98900",
    "em_atendimento": "#1f8f5c", "finalizado": "#5b6b76",
    "cancelado": "#8a94a0", "faltou": "#c0472e",
}


class ConflitoAgendaError(Exception):
    pass


class ForaDoTurnoError(Exception):
    pass


class HorarioBloqueadoError(Exception):
    """Data/turno cai dentro de um bloqueio de agenda (feriado, viagem do
    médico) -- diferente de ForaDoTurnoError, esse nunca pode ser
    ignorado/forçado pelo encaixe."""
    pass


def dia_semana_da_data(data_str: str) -> str | None:
    """'YYYY-MM-DD' -> 'segunda'..'sabado', ou None se for domingo (não atende)."""
    d = datetime.strptime(data_str, "%Y-%m-%d").date()
    return _WEEKDAY_PARA_DIA[d.weekday()]


def gerar_horarios_turno(turno: str) -> list[str]:
    """Lista de horários de 20 em 20 min dentro do turno (ex: manhã -> 08:00, 08:20, ..., 11:40)."""
    inicio, fim = TURNOS_HORARIOS[turno]
    h_ini, m_ini = map(int, inicio.split(":"))
    h_fim, m_fim = map(int, fim.split(":"))
    atual = h_ini * 60 + m_ini
    limite = h_fim * 60 + m_fim
    horarios = []
    while atual + DURACAO_PADRAO_MIN <= limite:
        horarios.append(f"{atual // 60:02d}:{atual % 60:02d}")
        atual += DURACAO_PADRAO_MIN
    return horarios


def turno_do_horario(horario: str) -> str | None:
    """Descobre em qual turno um horário 'HH:MM' cai."""
    h, m = map(int, horario.split(":")[:2])
    minutos = h * 60 + m
    for turno, (ini, fim) in TURNOS_HORARIOS.items():
        h_ini, m_ini = map(int, ini.split(":"))
        h_fim, m_fim = map(int, fim.split(":"))
        if h_ini * 60 + m_ini <= minutos < h_fim * 60 + m_fim:
            return turno
    return None


# ---------------------------------------------------------------------------
# Normalização de texto vindo da planilha (acentos, maiúsculas, espaços)
# ---------------------------------------------------------------------------
def _normalizar_texto(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(texto.split())


def _chave_nome(nome: str) -> str:
    """Chave de comparação pra casar o mesmo médico entre a aba 'Agenda' e a
    aba 'Dados dos Médicos' -- só pelo nome (um médico pode ocupar mais de
    uma sala, mas só tem um cadastro de contato)."""
    return _normalizar_texto(nome)


def normalizar_dia(valor) -> str | None:
    texto = _normalizar_texto(valor)
    mapa = {"segunda": "segunda", "segunda-feira": "segunda", "seg": "segunda",
            "terca": "terca", "terca-feira": "terca", "ter": "terca",
            "quarta": "quarta", "quarta-feira": "quarta", "qua": "quarta",
            "quinta": "quinta", "quinta-feira": "quinta", "qui": "quinta",
            "sexta": "sexta", "sexta-feira": "sexta", "sex": "sexta",
            "sabado": "sabado", "sab": "sabado"}
    return mapa.get(texto)


def normalizar_turno(valor) -> str | None:
    texto = _normalizar_texto(valor)
    mapa = {"manha": "manha", "m": "manha", "tarde": "tarde", "t": "tarde", "noite": "noite", "n": "noite"}
    return mapa.get(texto)


def normalizar_telefone(valor) -> str | None:
    """Extrai só os dígitos e garante o DDI 55 na frente (padrão E.164 sem '+' usado no resto do sistema)."""
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", str(valor))
    if not digitos:
        return None
    if not digitos.startswith("55") and len(digitos) in (10, 11):
        digitos = "55" + digitos
    return digitos


def telefone_sem_ddi(valor) -> str:
    """O contrário de normalizar_telefone -- pra MOSTRAR pro médico/paciente
    (login, "Dados Pessoais", listas no admin etc.): tira o "55" da
    frente, deixando só DDD + número. Nunca usar isso pra guardar no
    banco nem pra mandar mensagem pelo WhatsApp -- lá o "55" continua
    obrigatório (é assim que a Meta identifica o número)."""
    if not valor:
        return ""
    digitos = re.sub(r"\D", "", str(valor))
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos[2:]
    return digitos


def normalizar_cpf(valor) -> str:
    if valor is None:
        return ""
    return re.sub(r"\D", "", str(valor))


# ---------------------------------------------------------------------------
# Empresas: Lifemax roda várias empresas diferentes, atendendo clientes
# diferentes -- cada médico fixo é vinculado a uma delas.
# ---------------------------------------------------------------------------
def listar_empresas() -> list[dict]:
    resp = db.get_client().table("empresas").select("*").order("nome").execute()
    return resp.data


def obter_ou_criar_empresa(nome: str, cache: dict | None = None) -> str | None:
    nome = (nome or "").strip()
    if not nome:
        return None
    cache = cache if cache is not None else {}
    chave = _normalizar_texto(nome)
    if chave in cache:
        return cache[chave]
    if not cache:
        for e in listar_empresas():
            cache[_normalizar_texto(e["nome"])] = e["id"]
        if chave in cache:
            return cache[chave]
    nova = db.get_client().table("empresas").insert({"nome": nome}).execute().data[0]
    cache[chave] = nova["id"]
    return nova["id"]


# ---------------------------------------------------------------------------
# Separar o(s) nome(s) reais de uma célula da planilha "Agenda". Nas
# planilhas reais do Paulo, às vezes vem uma nota administrativa colada no
# nome (ex: "Fulano De Tal /cond.", "Fulano De Tal.cond.", "Fulano/iptu") --
# isso é só uma anotação de quem paga condomínio/IPTU da sala, não é um
# segundo médico. Já quando os DOIS lados de um "/" são nomes completos de
# verdade, não dá pra saber sozinho qual é o médico daquele horário -- nesse
# caso a célula é reportada como ambígua e IGNORADA (nunca inventamos qual
# dos dois é o certo).
# ---------------------------------------------------------------------------
_PALAVRAS_RUIDO = ("cond", "condominio", "iptu")
_SUFIXO_RUIDO_RE = re.compile(
    r"[\s/.\-]*\b(?:" + "|".join(_PALAVRAS_RUIDO) + r")\.?\s*$", re.IGNORECASE
)


def _remover_sufixo_ruido(texto: str) -> str:
    anterior = None
    atual = texto.strip()
    while anterior != atual:
        anterior = atual
        atual = _SUFIXO_RUIDO_RE.sub("", atual).strip()
    return atual


def _separar_ocupantes(valor) -> tuple[list[str], bool]:
    """Devolve (lista_de_nomes_reais, ambiguo). Lista vazia = célula sem
    nome reconhecível (só ruído, ou vazia). ambiguo=True = mais de um nome
    completo na mesma célula -- não decide sozinho, quem importa reporta."""
    bruto = (str(valor) if valor is not None else "").strip()
    if not bruto:
        return [], False

    limpo = _remover_sufixo_ruido(bruto)
    if not limpo:
        return [], False

    if "/" not in limpo:
        return ([limpo] if len(limpo.split()) >= 2 else []), False

    partes = [_remover_sufixo_ruido(p.strip(" ./")) for p in limpo.split("/")]
    candidatos = [p for p in partes if p and len(p.split()) >= 2]
    if len(candidatos) <= 1:
        return candidatos, False
    return candidatos, True


# ---------------------------------------------------------------------------
# Import da planilha real de ocupação dos consultórios (2 abas):
#   "Agenda"            -> Andar, Consultório, e 16 colunas de turno
#                           (Seg-M, Seg-T, Seg-N, ..., Sáb-M) com o nome de
#                           quem ocupa aquele consultório naquele dia/turno.
#   "Dados dos Médicos" -> Andar, Consultório, Empresa, Nome, E-mail,
#                           Telefone, Endereço, CEP, Especialidade, CRM, CPF.
#
# A conta de médico fixo só é criada pra quem REALMENTE ocupa um horário na
# aba "Agenda" (casando pelo nome, não por sala+nome, porque um médico pode
# ocupar mais de uma sala) -- a aba "Dados dos Médicos" só enriquece o
# contato. Isso evita criar login pra linhas administrativas (ex: o próprio
# dono do coworking aparecendo como "contato" de uma sala que ele não
# atende) e pra qualquer nome que não tenha telefone (telefone é obrigatório
# e único no cadastro de médico) -- nesses casos a linha é reportada, nunca
# adivinhada.
# ---------------------------------------------------------------------------
_COLUNAS_TURNO_AGENDA = [
    ("Seg-M", "segunda", "manha"), ("Seg-T", "segunda", "tarde"), ("Seg-N", "segunda", "noite"),
    ("Ter-M", "terca", "manha"), ("Ter-T", "terca", "tarde"), ("Ter-N", "terca", "noite"),
    ("Qua-M", "quarta", "manha"), ("Qua-T", "quarta", "tarde"), ("Qua-N", "quarta", "noite"),
    ("Qui-M", "quinta", "manha"), ("Qui-T", "quinta", "tarde"), ("Qui-N", "quinta", "noite"),
    ("Sex-M", "sexta", "manha"), ("Sex-T", "sexta", "tarde"), ("Sex-N", "sexta", "noite"),
    ("Sáb-M", "sabado", "manha"),
]


def importar_planilha_consultorios(conteudo_bytes: bytes) -> dict:
    import openpyxl
    from io import BytesIO

    resultado = {
        "consultorios_criados": 0, "medicos_criados": 0, "medicos_atualizados": 0,
        "grade_gravada": 0,
        "medicos_sem_telefone": [],       # ocupam sala mas não têm telefone na planilha -> sem login possível
        "ocupantes_sem_contato": [],      # nome ocupa sala na Agenda mas não achei na aba de contatos
        "celulas_ambiguas": [],           # célula com 2+ nomes completos -- não decidi sozinho
        "conflitos_cpf": [],              # mesmo CPF em nomes diferentes -- provável erro de digitação
        "erros": [],
    }

    try:
        wb = openpyxl.load_workbook(BytesIO(conteudo_bytes), data_only=True)
    except Exception as e:
        resultado["erros"].append(f"Não consegui abrir o arquivo — confira se é o .xlsx exportado ({e}).")
        return resultado

    nome_aba_agenda = next((n for n in wb.sheetnames if _normalizar_texto(n) == "agenda"), None)
    nome_aba_medicos = next((n for n in wb.sheetnames if "medic" in _normalizar_texto(n)), None)
    if nome_aba_agenda is None or nome_aba_medicos is None:
        resultado["erros"].append('Preciso de duas abas nessa planilha: "Agenda" e "Dados dos Médicos".')
        return resultado

    ws_agenda = wb[nome_aba_agenda]
    ws_medicos = wb[nome_aba_medicos]

    # ---- 1. lê a aba "Dados dos Médicos", indexa por nome normalizado ----
    contatos_por_nome: dict[str, dict] = {}
    cpf_por_chave: dict[str, str] = {}
    for linha in ws_medicos.iter_rows(min_row=2, values_only=True):
        if not linha or not any(linha):
            continue
        valores = (list(linha) + [None] * 11)[:11]
        _andar, _consultorio, empresa, nome, email, telefone, endereco, cep, especialidade, crm, cpf = valores
        nome = str(nome).strip() if nome else ""
        if not nome:
            continue
        chave = _chave_nome(nome)
        cpf_limpo = normalizar_cpf(cpf)
        contatos_por_nome[chave] = {
            "nome": nome,
            "empresa": str(empresa).strip() if empresa else "",
            "email": str(email).strip() if email else "",
            "telefone": normalizar_telefone(telefone),
            "especialidade": str(especialidade).strip() if especialidade else "",
            "crm": str(crm).strip() if crm else "",
            "cpf": cpf_limpo,
            # A planilha traz o endereço como um texto único (não separado em rua/número/bairro/etc.),
            # então guardamos o texto inteiro no campo "rua" mesmo — o médico (ou o Paulo) pode
            # depois abrir o cadastro e separar em campos se quiser. Antes essas 2 colunas eram
            # simplesmente ignoradas na importação.
            "endereco_rua": str(endereco).strip() if endereco else "",
            "endereco_cep": str(cep).strip() if cep else "",
        }
        if cpf_limpo:
            if cpf_limpo in cpf_por_chave and cpf_por_chave[cpf_limpo] != chave:
                outro_nome = contatos_por_nome.get(cpf_por_chave[cpf_limpo], {}).get("nome", cpf_por_chave[cpf_limpo])
                resultado["conflitos_cpf"].append(
                    f'O CPF {cpf} aparece tanto em "{outro_nome}" quanto em "{nome}" na aba "Dados dos Médicos" — '
                    f"confira, provavelmente é erro de digitação (não mexi em nenhum dos dois)."
                )
            else:
                cpf_por_chave[cpf_limpo] = chave

    # ---- 2. lê a aba "Agenda": cria/atualiza salas e monta a ocupação por nome ----
    consultorios_cache = {c["nome"].strip().lower(): c for c in db.listar_todos_consultorios()}
    ocupacao_por_nome: dict[str, dict] = {}  # chave -> {"nome": ..., "slots": [...]}

    for linha in ws_agenda.iter_rows(min_row=2, values_only=True):
        if not linha or not any(linha):
            continue
        valores = (list(linha) + [None] * 18)[:18]
        andar, consultorio_nome = valores[0], valores[1]
        consultorio_nome = str(consultorio_nome).strip() if consultorio_nome else ""
        if not consultorio_nome:
            continue
        andar_str = str(andar).strip() if andar else ""

        chave_sala = consultorio_nome.lower()
        if chave_sala in consultorios_cache:
            consultorio_id = consultorios_cache[chave_sala]["id"]
            if andar_str and not consultorios_cache[chave_sala].get("andar"):
                db.get_client().table("consultorios").update({"andar": andar_str}).eq("id", consultorio_id).execute()
                consultorios_cache[chave_sala]["andar"] = andar_str
        else:
            novo_consultorio = db.criar_consultorio(consultorio_nome, "", 0, andar=andar_str)
            consultorio_id = novo_consultorio["id"]
            consultorios_cache[chave_sala] = novo_consultorio
            resultado["consultorios_criados"] += 1

        for idx, (_rotulo_col, dia, turno) in enumerate(_COLUNAS_TURNO_AGENDA):
            texto_celula = valores[2 + idx]
            if texto_celula is None or not str(texto_celula).strip():
                continue

            nomes, ambiguo = _separar_ocupantes(texto_celula)
            if ambiguo:
                resultado["celulas_ambiguas"].append(
                    f'{consultorio_nome}, {_ROTULO_DIA[dia]} de {_ROTULO_TURNO[turno]}: "{texto_celula}" — '
                    f"tem mais de um nome completo, não dá pra saber sozinho qual é o médico certo. "
                    f"Ajuste essa célula na planilha (deixe só 1 nome) e importe de novo."
                )
                continue
            if not nomes:
                continue  # célula só tinha ruído administrativo (ex: uma nota solta), nada pra importar

            nome_ocupante = nomes[0]
            chave = _chave_nome(nome_ocupante)
            info = ocupacao_por_nome.setdefault(chave, {"nome": nome_ocupante, "slots": []})
            info["slots"].append({
                "dia": dia, "turno": turno, "consultorio_id": consultorio_id, "sala_nome": consultorio_nome,
            })

    # ---- 3. pra cada ocupante real, casa com o contato e grava médico + grade ----
    cache_empresas: dict[str, str] = {}
    for chave, info in ocupacao_por_nome.items():
        contato = contatos_por_nome.get(chave)
        if not contato:
            resultado["ocupantes_sem_contato"].append(info["nome"])
            continue
        if not contato["telefone"]:
            resultado["medicos_sem_telefone"].append(contato["nome"])
            continue

        empresa_id = obter_ou_criar_empresa(contato["empresa"], cache_empresas) if contato["empresa"] else None

        medico = db.get_medico_by_telefone(contato["telefone"])
        if medico is None:
            medico = db.criar_medico(
                contato["nome"], contato["telefone"], contato["especialidade"], tipo_vinculo="fixo",
                empresa_id=empresa_id, email=contato["email"], crm=contato["crm"], cpf_cnpj=contato["cpf"],
                endereco_rua=contato["endereco_rua"], endereco_cep=contato["endereco_cep"],
            )
            resultado["medicos_criados"] += 1
        else:
            db.get_client().table("medicos").update({
                "tipo_vinculo": "fixo",
                "empresa_id": empresa_id if empresa_id is not None else medico.get("empresa_id"),
                "especialidade": contato["especialidade"] or medico.get("especialidade"),
                "email": contato["email"] or medico.get("email"),
                "crm": contato["crm"] or medico.get("crm"),
                "cpf_cnpj": contato["cpf"] or medico.get("cpf_cnpj"),
                "endereco_rua": contato["endereco_rua"] or medico.get("endereco_rua"),
                "endereco_cep": contato["endereco_cep"] or medico.get("endereco_cep"),
            }).eq("id", medico["id"]).execute()
            resultado["medicos_atualizados"] += 1

        for slot in info["slots"]:
            try:
                db.get_client().table("grade_medico_fixo").upsert({
                    "medico_id": medico["id"], "dia_semana": slot["dia"], "turno": slot["turno"],
                    "consultorio_id": slot["consultorio_id"], "ativo": True,
                }, on_conflict="medico_id,dia_semana,turno").execute()
                resultado["grade_gravada"] += 1
            except Exception:
                resultado["erros"].append(
                    f'{slot["sala_nome"]} ({_ROTULO_DIA[slot["dia"]]} de {_ROTULO_TURNO[slot["turno"]]}) já está com '
                    f'outro médico fixo — ajuste a sala ou o horário na planilha e importe de novo.'
                )

    return resultado


# ---------------------------------------------------------------------------
# Visualização de disponibilidade dos consultórios (por andar, 16 turnos por
# semana -- Seg-M, Seg-T, Seg-N ... Sáb-M) -- verde = ocupado por médico
# fixo (mensalista), em branco = vago (é exatamente o que sobra livre pros
# horistas usarem -- ver restringir_horista_a_vagos() logo abaixo).
# ---------------------------------------------------------------------------
def _chave_ordenacao_andar(andar: str) -> int:
    numeros = re.findall(r"\d+", andar or "")
    return int(numeros[0]) if numeros else 9999


def _chave_ordenacao_consultorio(nome: str) -> tuple:
    numeros = re.findall(r"\d+", nome or "")
    return (int(numeros[0]) if numeros else 9999, nome or "")


def mapa_disponibilidade_consultorios() -> list[dict]:
    """Agrupa todos os consultórios ativos por andar e monta, pra cada um,
    a ocupação dos 16 turnos da semana com base na grade fixa
    (grade_medico_fixo) -- não olha agendamento avulso (Grade de Turnos)
    nem horista, só quem tem sala fixa reservada todo dia da semana."""
    consultorios = db.get_client().table("consultorios").select("*").eq("ativo", True).execute().data
    grade = (
        db.get_client().table("grade_medico_fixo")
        .select("*, medicos(nome)").eq("ativo", True).execute().data
    )
    ocupacao_por_consultorio: dict[str, dict] = {}
    for g in grade:
        chave_turno = next(
            (rotulo for rotulo, dia, turno in _COLUNAS_TURNO_AGENDA if dia == g["dia_semana"] and turno == g["turno"]),
            None,
        )
        if chave_turno is None:
            continue
        medico_nome = (g.get("medicos") or {}).get("nome", "")
        ocupacao_por_consultorio.setdefault(g["consultorio_id"], {})[chave_turno] = medico_nome

    por_andar: dict[str, list] = {}
    for c in consultorios:
        andar = (c.get("andar") or "").strip() or "Sem andar"
        ocupacao = ocupacao_por_consultorio.get(c["id"], {})
        turnos = [
            {"chave": rotulo, "ocupado": rotulo in ocupacao, "medico_nome": ocupacao.get(rotulo, "")}
            for rotulo, _dia, _turno in _COLUNAS_TURNO_AGENDA
        ]
        por_andar.setdefault(andar, []).append({"id": c["id"], "nome": c["nome"], "turnos": turnos})

    resultado = []
    for andar in sorted(por_andar.keys(), key=_chave_ordenacao_andar):
        salas = sorted(por_andar[andar], key=lambda s: _chave_ordenacao_consultorio(s["nome"]))
        resultado.append({"andar": andar, "consultorios": salas})
    return resultado


def consultorios_vagos_no_turno(dia_semana: str, turno: str) -> list[dict]:
    """Consultórios que NENHUM médico fixo ocupa nesse dia+turno -- é o
    conjunto que pode ser liberado pra horista usar (ver Gerar Matriz)."""
    todos = db.get_client().table("consultorios").select("*").eq("ativo", True).execute().data
    ocupados_resp = (
        db.get_client().table("grade_medico_fixo").select("consultorio_id")
        .eq("dia_semana", dia_semana).eq("turno", turno).eq("ativo", True).execute()
    )
    ocupados_ids = {g["consultorio_id"] for g in ocupados_resp.data}
    return [c for c in todos if c["id"] not in ocupados_ids]


# ---------------------------------------------------------------------------
# Grade semanal (consulta)
# ---------------------------------------------------------------------------
def listar_medicos_fixos() -> list[dict]:
    resp = (
        db.get_client().table("medicos").select("*, empresas(id, nome)")
        .eq("tipo_vinculo", "fixo").eq("ativo", True).order("nome").execute()
    )
    return resp.data


def obter_grade_dia(dia_semana: str) -> list[dict]:
    """Quem atende nesse dia da semana, em qual turno e sala (join com medicos/consultorios)."""
    resp = (
        db.get_client()
        .table("grade_medico_fixo")
        .select("*, medicos(id, nome, especialidade), consultorios(id, nome)")
        .eq("dia_semana", dia_semana)
        .eq("ativo", True)
        .execute()
    )
    linhas = resp.data
    linhas.sort(key=lambda l: (l["medicos"]["nome"] if l.get("medicos") else "", l["turno"]))
    return linhas


def obter_grade_medico(medico_id: str) -> list[dict]:
    resp = (
        db.get_client()
        .table("grade_medico_fixo")
        .select("*, consultorios(id, nome)")
        .eq("medico_id", medico_id)
        .eq("ativo", True)
        .execute()
    )
    return resp.data


def definir_grade_medico(medico_id: str, slots: list[dict]) -> dict:
    """Substitui a grade inteira desse médico fixo pelos slots informados --
    usado no cadastro/edição manual de médico (diferente da importação em
    massa da planilha, que só soma). `slots` é uma lista de
    {"dia_semana": ..., "turno": ..., "consultorio_id": ...}.

    Desativa (ativo=False) as combinações dia+turno que esse médico tinha
    e não estão mais na lista nova, e upserta (cria ou reativa) as
    informadas. Se uma sala já estiver ocupada por OUTRO médico fixo
    nesse mesmo dia+turno, essa combinação fica de fora e some no
    'erros' -- as demais são salvas normalmente."""
    existentes = obter_grade_medico(medico_id)
    chaves_novas = {(s["dia_semana"], s["turno"]) for s in slots}
    for g in existentes:
        if (g["dia_semana"], g["turno"]) not in chaves_novas:
            db.get_client().table("grade_medico_fixo").update({"ativo": False}).eq("id", g["id"]).execute()

    erros = []
    gravados = 0
    for s in slots:
        try:
            db.get_client().table("grade_medico_fixo").upsert({
                "medico_id": medico_id, "dia_semana": s["dia_semana"], "turno": s["turno"],
                "consultorio_id": s["consultorio_id"], "ativo": True,
            }, on_conflict="medico_id,dia_semana,turno").execute()
            gravados += 1
        except Exception:
            erros.append(
                f'{_ROTULO_DIA.get(s["dia_semana"], s["dia_semana"])} de '
                f'{_ROTULO_TURNO.get(s["turno"], s["turno"])} já está ocupado por outro médico fixo nessa sala.'
            )
    return {"gravados": gravados, "erros": erros}


# ---------------------------------------------------------------------------
# Horários vagos / ocupados de um médico num dia
# ---------------------------------------------------------------------------
def horarios_do_dia(medico_id: str, data_str: str) -> list[dict]:
    """
    Pra cada turno em que esse médico atende nesse dia da semana, devolve os
    horários de 20 em 20 min com o que já está ocupado (se estiver).
    """
    dia = dia_semana_da_data(data_str)
    if dia is None:
        return []

    grade = {g["turno"]: g for g in obter_grade_medico(medico_id) if g["dia_semana"] == dia}
    if not grade:
        return []

    ocupados_resp = (
        db.get_client().table("agenda_consultas").select("*")
        .eq("medico_id", medico_id).eq("data", data_str).neq("status", "cancelado")
        .execute()
    )
    # dict de LISTAS -- normalmente 1 consulta por horário, mas um "+
    # Encaixe" (2º paciente de propósito no mesmo horário) pode empilhar
    # mais de uma aqui (ver migration_agenda_encaixe.sql)
    ocupados_por_horario: dict[str, list] = {}
    for c in ocupados_resp.data:
        ocupados_por_horario.setdefault(c["horario"][:5], []).append(c)
    bloqueios = listar_bloqueios_medico(medico_id)

    turnos = []
    for turno in TURNOS_POR_DIA[dia]:
        info_turno = grade.get(turno)
        if not info_turno:
            continue
        bloqueio = _bloqueio_do_turno(bloqueios, data_str, turno)
        horarios = []
        for h in gerar_horarios_turno(turno):
            consultas = ocupados_por_horario.get(h) or []
            horarios.append({
                "horario": h, "ocupado": bool(consultas),
                "consulta": consultas[0] if consultas else None,
                "consultas": consultas, "bloqueado": bloqueio is not None,
            })
        turnos.append({
            "turno": turno, "rotulo_turno": _ROTULO_TURNO[turno],
            "consultorio_id": info_turno["consultorios"]["id"] if info_turno.get("consultorios") else info_turno["consultorio_id"],
            "consultorio_nome": info_turno["consultorios"]["nome"] if info_turno.get("consultorios") else "",
            "horarios": horarios,
            "bloqueado": bloqueio is not None,
            "bloqueio_id": (bloqueio or {}).get("id"),
            "bloqueio_motivo": (bloqueio or {}).get("motivo") or "",
        })
    return turnos


def obter_semana_medico(medico_id: str, data_ref_str: str) -> dict:
    """Monta a semana inteira (domingo a sábado, igual à tela de referência)
    pra 1 médico só -- cada dia com os turnos/horários dele (via
    horarios_do_dia), pra desenhar a grade de horário x dia na tela."""
    d = datetime.strptime(data_ref_str, "%Y-%m-%d").date()
    dias_desde_domingo = (d.weekday() + 1) % 7  # weekday(): 0=segunda..6=domingo
    domingo = d - timedelta(days=dias_desde_domingo)

    dias = []
    for i in range(7):
        data_dia = domingo + timedelta(days=i)
        data_str = data_dia.isoformat()
        turnos = horarios_do_dia(medico_id, data_str)
        dias.append({
            "data": data_str,
            "dia_semana": _WEEKDAY_PARA_DIA_CURTO_CHAVE[data_dia.weekday()],
            "rotulo_curto": _ROTULO_DIA_CURTO[data_dia.weekday()],
            "dia_num": data_dia.day,
            "atende": bool(turnos),
            "turnos": turnos,
        })

    return {
        "semana_inicio": domingo.isoformat(),
        "semana_fim": (domingo + timedelta(days=6)).isoformat(),
        "dias": dias,
    }


# ---------------------------------------------------------------------------
# Agendar / confirmar / chegada / chamar / finalizar / faltou / cancelar
# ---------------------------------------------------------------------------
def obter_semana_consultorio(consultorio_id: str, data_ref_str: str) -> dict:
    """Igual a obter_semana_medico, só que olhando pra 1 CONSULTÓRIO (sala)
    em vez de 1 médico -- pra tela "Ver por: Consultório" da Agenda Fixos.
    Cada turno da semana pode ter um médico fixo diferente ocupando a
    sala (ou nenhum, se a sala está vaga naquele dia/turno), então cada
    "turno" no retorno já vem com o médico daquele turno junto (medico_id,
    medico_nome, medico_especialidade) -- diferente da versão por médico,
    que já sabe de antemão quem é o médico.
    """
    d = datetime.strptime(data_ref_str, "%Y-%m-%d").date()
    dias_desde_domingo = (d.weekday() + 1) % 7  # weekday(): 0=segunda..6=domingo
    domingo = d - timedelta(days=dias_desde_domingo)

    grade_resp = (
        db.get_client()
        .table("grade_medico_fixo")
        .select("*, medicos(id, nome, especialidade)")
        .eq("consultorio_id", consultorio_id)
        .eq("ativo", True)
        .execute()
    )
    grade_por_dia_turno = {(g["dia_semana"], g["turno"]): g for g in grade_resp.data if g.get("medicos")}
    bloqueios_por_medico: dict[str, list] = {}

    dias_da_semana = [(domingo + timedelta(days=i)).isoformat() for i in range(7)]

    # Antes: 1 consulta ao banco POR TURNO OCUPADO da semana (até 21
    # numa semana cheia) -- agora é 1 consulta só pra semana inteira
    # desse consultório, agrupada aqui em Python (mesmo motivo do
    # Dashboard Admin ter ficado lento, corrigido em 08/09/2026).
    consultas_da_semana = (
        db.get_client().table("agenda_consultas").select("*")
        .eq("consultorio_id", consultorio_id)
        .gte("data", dias_da_semana[0]).lte("data", dias_da_semana[-1])
        .neq("status", "cancelado")
        .execute()
    ).data
    consultas_por_data_horario: dict[tuple, list] = {}
    for c in consultas_da_semana:
        consultas_por_data_horario.setdefault((c["data"], c["horario"][:5], c["medico_id"]), []).append(c)

    dias = []
    for i in range(7):
        data_dia = domingo + timedelta(days=i)
        data_str = data_dia.isoformat()
        dia_chave = _WEEKDAY_PARA_DIA_CURTO_CHAVE[data_dia.weekday()]

        turnos = []
        for turno in TURNOS_POR_DIA.get(dia_chave, []):
            g = grade_por_dia_turno.get((dia_chave, turno))
            if not g:
                continue
            medico = g["medicos"]
            if medico["id"] not in bloqueios_por_medico:
                bloqueios_por_medico[medico["id"]] = listar_bloqueios_medico(medico["id"])
            bloqueio = _bloqueio_do_turno(bloqueios_por_medico[medico["id"]], data_str, turno)
            horarios = []
            for h in gerar_horarios_turno(turno):
                consultas = consultas_por_data_horario.get((data_str, h, medico["id"])) or []
                horarios.append({
                    "horario": h, "ocupado": bool(consultas),
                    "consulta": consultas[0] if consultas else None,
                    "consultas": consultas, "bloqueado": bloqueio is not None,
                })
            turnos.append({
                "turno": turno, "rotulo_turno": _ROTULO_TURNO[turno],
                "consultorio_id": consultorio_id,
                "medico_id": medico["id"], "medico_nome": medico["nome"],
                "medico_especialidade": medico.get("especialidade") or "",
                "horarios": horarios,
                "bloqueado": bloqueio is not None,
                "bloqueio_id": (bloqueio or {}).get("id"),
                "bloqueio_motivo": (bloqueio or {}).get("motivo") or "",
            })

        dias.append({
            "data": data_str,
            "dia_semana": dia_chave,
            "rotulo_curto": _ROTULO_DIA_CURTO[data_dia.weekday()],
            "dia_num": data_dia.day,
            "atende": bool(turnos),
            "turnos": turnos,
        })

    return {
        "semana_inicio": domingo.isoformat(),
        "semana_fim": (domingo + timedelta(days=6)).isoformat(),
        "dias": dias,
    }


def _limites_do_mes(data_ref_str: str) -> tuple[date, date]:
    d = datetime.strptime(data_ref_str, "%Y-%m-%d").date()
    primeiro_dia = d.replace(day=1)
    if d.month == 12:
        ultimo_dia = d.replace(year=d.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        ultimo_dia = d.replace(month=d.month + 1, day=1) - timedelta(days=1)
    return primeiro_dia, ultimo_dia


def _contagem_por_status(consultas: list[dict]) -> dict:
    contagem: dict[str, int] = {}
    for c in consultas:
        contagem[c["status"]] = contagem.get(c["status"], 0) + 1
    return contagem


def obter_mes_medico(medico_id: str, data_ref_str: str) -> dict:
    """Visão "Mês" -- 1 célula por dia do mês, com bolinhas coloridas por
    status (pra secretária ver de longe onde tem mais movimento) em vez
    dos horários um por um (isso fica pras abas Semana/Dia). Clicar num
    dia leva pra aba Dia daquele dia."""
    primeiro_dia, ultimo_dia = _limites_do_mes(data_ref_str)

    dias_com_grade = {g["dia_semana"] for g in obter_grade_medico(medico_id)}

    consultas_resp = (
        db.get_client().table("agenda_consultas").select("*")
        .eq("medico_id", medico_id)
        .gte("data", primeiro_dia.isoformat()).lte("data", ultimo_dia.isoformat())
        .execute()
    )
    por_dia: dict[str, list] = {}
    for c in consultas_resp.data:
        por_dia.setdefault(c["data"], []).append(c)

    dias = []
    d = primeiro_dia
    while d <= ultimo_dia:
        data_str = d.isoformat()
        dia_chave = _WEEKDAY_PARA_DIA_CURTO_CHAVE[d.weekday()]
        consultas_do_dia = por_dia.get(data_str, [])
        dias.append({
            "data": data_str, "dia_num": d.day, "dia_semana": dia_chave,
            "atende": dia_chave in dias_com_grade,
            "contagem_status": _contagem_por_status(consultas_do_dia),
            "total": len(consultas_do_dia),
        })
        d += timedelta(days=1)

    return {"ano": primeiro_dia.year, "mes": primeiro_dia.month, "dias": dias}


def obter_mes_consultorio(consultorio_id: str, data_ref_str: str) -> dict:
    """Igual a obter_mes_medico, só que pra 1 consultório (pode ter médico
    diferente em dias diferentes, igual à visão semana por consultório)."""
    primeiro_dia, ultimo_dia = _limites_do_mes(data_ref_str)

    grade_resp = (
        db.get_client().table("grade_medico_fixo").select("*")
        .eq("consultorio_id", consultorio_id).eq("ativo", True).execute()
    )
    dias_com_grade = {g["dia_semana"] for g in grade_resp.data}

    consultas_resp = (
        db.get_client().table("agenda_consultas").select("*")
        .eq("consultorio_id", consultorio_id)
        .gte("data", primeiro_dia.isoformat()).lte("data", ultimo_dia.isoformat())
        .execute()
    )
    por_dia: dict[str, list] = {}
    for c in consultas_resp.data:
        por_dia.setdefault(c["data"], []).append(c)

    dias = []
    d = primeiro_dia
    while d <= ultimo_dia:
        data_str = d.isoformat()
        dia_chave = _WEEKDAY_PARA_DIA_CURTO_CHAVE[d.weekday()]
        consultas_do_dia = por_dia.get(data_str, [])
        dias.append({
            "data": data_str, "dia_num": d.day, "dia_semana": dia_chave,
            "atende": dia_chave in dias_com_grade,
            "contagem_status": _contagem_por_status(consultas_do_dia),
            "total": len(consultas_do_dia),
        })
        d += timedelta(days=1)

    return {"ano": primeiro_dia.year, "mes": primeiro_dia.month, "dias": dias}


def listar_bloqueios_medico(medico_id: str) -> list[dict]:
    resp = (
        db.get_client().table("agenda_bloqueios").select("*")
        .eq("medico_id", medico_id).order("data_inicio").execute()
    )
    return resp.data


def _bloqueio_do_turno(bloqueios: list[dict], data_str: str, turno: str) -> dict | None:
    """Acha, entre os bloqueios já buscados desse médico, o que cobre essa
    data+turno -- bloqueio sem 'turno' definido cobre o dia inteiro."""
    for b in bloqueios:
        if b["data_inicio"] <= data_str <= b["data_fim"] and (not b.get("turno") or b["turno"] == turno):
            return b
    return None


def criar_bloqueio(medico_id: str, data_inicio: str, data_fim: str,
                    turno: str | None = None, motivo: str = "",
                    hora_inicio: str | None = None, hora_fim: str | None = None,
                    autor: dict | None = None) -> dict:
    if data_fim < data_inicio:
        raise ValueError("A data final não pode ser antes da data inicial.")
    if hora_inicio and hora_fim and hora_fim <= hora_inicio:
        raise ValueError("A hora final precisa ser depois da hora inicial.")
    autor = autor or {"tipo": "sistema", "id": None, "nome": "Sistema"}
    dados = {
        "medico_id": medico_id, "data_inicio": data_inicio, "data_fim": data_fim,
        "turno": turno or None, "motivo": (motivo or "").strip() or None,
        "hora_inicio": hora_inicio or None, "hora_fim": hora_fim or None,
        "criado_por_tipo": autor.get("tipo", "sistema"), "criado_por_id": autor.get("id"),
        "criado_por_nome": autor.get("nome") or "Sistema",
    }
    resp = db.get_client().table("agenda_bloqueios").insert(dados).execute()
    return resp.data[0]


def remover_bloqueio(bloqueio_id: str) -> None:
    db.get_client().table("agenda_bloqueios").delete().eq("id", bloqueio_id).execute()


def agendar_consulta(medico_id: str, data_str: str, horario: str, paciente_nome: str,
                      paciente_telefone: str = "", paciente_data_nascimento: str | None = None,
                      paciente_cpf: str = "", convenio: str = "", valor_consulta: float | None = None,
                      forma_pagamento: str = "", observacoes: str = "", origem: str = "secretaria",
                      paciente_id: str | None = None, consultorio_id: str | None = None,
                      ignorar_turno: bool = False, encaixe: bool = False, autor: dict | None = None) -> dict:
    """`ignorar_turno=True` é o "encaixe fora do horário": deixa agendar
    mesmo num dia/turno que não está na grade fixa desse médico (aí
    `consultorio_id` é obrigatório, já que não tem como descobrir a sala
    sozinho). `encaixe=True` é o "encaixe em cima de outro": deixa
    agendar um paciente EXTRA num horário que esse mesmo médico já tem
    ocupado (dois pacientes no mesmo horário) -- normalmente o banco
    recusaria isso (ConflitoAgendaError), mas marcado como encaixe fica
    de fora dessa trava. As duas coisas são independentes e podem
    acontecer juntas. Nenhuma das duas ignora um bloqueio de agenda
    (feriado/viagem) -- esse continua travando o agendamento de
    qualquer jeito. Também nenhuma ignora domingo nem os turnos que a
    clínica não abre (ex: sábado à noite) -- isso é regra da clínica,
    não da grade pessoal do médico.
    """
    dia = dia_semana_da_data(data_str)
    if dia is None:
        raise ForaDoTurnoError("Não atendemos aos domingos.")

    turno = turno_do_horario(horario)
    if turno is None or turno not in TURNOS_POR_DIA[dia]:
        raise ForaDoTurnoError(f"{horario} está fora dos turnos de atendimento em {_ROTULO_DIA.get(dia, dia)}.")

    if horario not in gerar_horarios_turno(turno):
        raise ForaDoTurnoError("Os horários são de 20 em 20 minutos, a partir do início do turno.")

    bloqueio = _bloqueio_do_turno(listar_bloqueios_medico(medico_id), data_str, turno)
    if bloqueio:
        motivo = f" ({bloqueio['motivo']})" if bloqueio.get("motivo") else ""
        raise HorarioBloqueadoError(f"Essa agenda está bloqueada nesse dia/turno{motivo}.")

    # ⚠️ Bug corrigido: esse dicionário era indexado só por `turno`
    # ("manha"/"tarde"/"noite"), sem o dia da semana -- se o médico
    # atende o mesmo turno em mais de um dia (ex: manhã na segunda E na
    # terça), cada dia sobrescrevia o anterior aqui, e só o último
    # "vencia". Resultado: agendar num horário que o médico realmente
    # atende podia cair no aviso "esse médico não tem esse turno na
    # grade fixa desse dia" errado, dependendo da ordem que o banco
    # devolvia as linhas -- mesmo a tela mostrando aquele horário como
    # livre corretamente (a tela já filtrava por dia certo). Agora a
    # chave inclui o dia da semana, então cada dia guarda o seu próprio
    # consultório sem se sobrepor.
    grade = {(g["dia_semana"], g["turno"]): g for g in obter_grade_medico(medico_id)}
    info_turno = grade.get((dia, turno))
    if not info_turno:
        if not ignorar_turno:
            raise ForaDoTurnoError("Esse médico não tem esse turno na grade fixa desse dia.")
        if not consultorio_id:
            raise ForaDoTurnoError("Escolha o consultório pra fazer o encaixe fora do horário.")
        consultorio_id_final = consultorio_id
    else:
        consultorio_id_final = info_turno["consultorios"]["id"] if info_turno.get("consultorios") else info_turno["consultorio_id"]

    dados = {
        "medico_id": medico_id, "consultorio_id": consultorio_id_final,
        "paciente_nome": paciente_nome, "paciente_telefone": paciente_telefone,
        "paciente_data_nascimento": paciente_data_nascimento, "paciente_cpf": paciente_cpf,
        "convenio": convenio, "valor_consulta": valor_consulta, "forma_pagamento": forma_pagamento,
        "observacoes": observacoes, "data": data_str, "turno": turno, "horario": horario,
        "status": "agendado", "origem": origem, "paciente_id": paciente_id,
        "duracao_min": DURACAO_PADRAO_MIN, "encaixe": encaixe,
    }
    try:
        resp = db.get_client().table("agenda_consultas").insert(dados).execute()
    except Exception:
        raise ConflitoAgendaError("Esse horário acabou de ser ocupado por outro paciente. Escolha outro.")
    consulta = resp.data[0]
    registrar_historico(consulta["id"], "agendou", autor,
                         detalhe=f"{paciente_nome} — {data_str} {horario}" + (" (encaixe)" if encaixe else ""))
    _avisar_medico_agenda_mudou(medico_id, consulta)
    return consulta


ANDAR_PADRAO = "Térreo"  # usado quando o consultório não tem andar preenchido, pra nunca perder o aviso


def listar_andares() -> list[str]:
    """Lista os andares distintos já cadastrados nos consultórios (usado
    tanto pra secretária escolher em que andar está atendendo, quanto
    pra listar os telões disponíveis em /recepcao/telao)."""
    consultorios = db.get_client().table("consultorios").select("andar").eq("ativo", True).execute().data
    andares = sorted({(c.get("andar") or "").strip() or ANDAR_PADRAO for c in consultorios})
    return andares


def _avisar_medico_agenda_mudou(medico_id: str | None, consulta: dict | None = None) -> None:
    """Avisa em tempo real a tela do médico (painel_agenda_fixa.html) que
    algo mudou na agenda dele -- pedido do Paulo: tudo que a secretária
    registrar (agendar, confirmar, cancelar, marcar falta/finalizado
    etc.) o médico vê na hora, sem precisar dar F5. A tela reage
    recarregando a lista do dia -- simples, e nunca fica desatualizada
    mesmo pra um campo que a gente não trata individualmente."""
    if not medico_id:
        return
    try:
        from app.extensions import socketio
        socketio.emit("agenda-mudou", {"consulta_id": (consulta or {}).get("id")}, room=f"medico-{medico_id}")
    except Exception as e:
        print(f"[agenda_fixos_service] Não consegui avisar o médico (agenda-mudou): {e}")


def registrar_historico(consulta_id: str, acao: str, autor: dict | None, detalhe: str | None = None) -> None:
    """Grava uma linha no histórico da consulta -- quem fez o quê e
    quando (pedido do Paulo: "histórico de agendamento" no menu de
    botão direito). `autor` é {"tipo": "secretaria"|"admin"|"medico"|
    "sistema", "id": str|None, "nome": str} -- None vira "sistema"
    (mudança automática, sem humano por trás)."""
    autor = autor or {"tipo": "sistema", "id": None, "nome": "Sistema"}
    try:
        db.get_client().table("agenda_consultas_historico").insert({
            "agenda_consulta_id": consulta_id,
            "autor_tipo": autor.get("tipo", "sistema"),
            "autor_id": autor.get("id"),
            "autor_nome": autor.get("nome") or "Sistema",
            "acao": acao,
            "detalhe": detalhe,
        }).execute()
    except Exception as e:
        print(f"[agenda_fixos_service] Não consegui registrar histórico ({acao}): {e}")


def obter_historico(consulta_id: str) -> list[dict]:
    resp = (
        db.get_client().table("agenda_consultas_historico").select("*")
        .eq("agenda_consulta_id", consulta_id).order("criado_em").execute()
    )
    return resp.data


def _mudar_status(consulta_id: str, status: str, campo_data_extra: str | None = None,
                   autor: dict | None = None) -> dict | None:
    dados = {"status": status, "atualizado_em": db.agora_iso()}
    if campo_data_extra:
        dados[campo_data_extra] = db.agora_iso()
    resp = db.get_client().table("agenda_consultas").update(dados).eq("id", consulta_id).execute()
    consulta = resp.data[0] if resp.data else None
    if consulta:
        registrar_historico(consulta_id, f"status_{status}", autor)
    # "chegou" já tem seu próprio aviso em tempo real mais rico (mais
    # abaixo, em marcar_chegada) -- evita mandar os dois avisos juntos
    # pra mesma mudança, que causaria dois efeitos brigando na tela
    if consulta and campo_data_extra != "chegou_em":
        _avisar_medico_agenda_mudou(consulta.get("medico_id"), consulta)
    return consulta


def definir_observacao_alerta(consulta_id: str, texto: str, autor: dict | None = None) -> dict | None:
    """"Aviso de observação" (pedido do Paulo): diferente do campo
    "observações" comum -- esse aparece como um "*" vermelho na célula
    da consulta na grade, visível sem precisar clicar. Texto vazio
    remove o aviso (o "*" some da grade)."""
    texto = (texto or "").strip()
    resp = db.get_client().table("agenda_consultas").update(
        {"observacao_alerta": texto or None}
    ).eq("id", consulta_id).execute()
    consulta = resp.data[0] if resp.data else None
    if consulta:
        registrar_historico(consulta_id, "editou_observacao_alerta" if texto else "removeu_observacao_alerta",
                             autor, detalhe=texto or None)
    return consulta


def definir_lista_espera(consulta_id: str, ativo: bool, observacao: str = "", autor: dict | None = None) -> dict | None:
    """"Lista de espera" (pedido do Paulo): marca/desmarca o paciente
    como aguardando na lista de espera -- aparece como um "E" vermelho
    no final da célula da consulta na grade."""
    resp = db.get_client().table("agenda_consultas").update(
        {"lista_espera": ativo, "lista_espera_observacao": (observacao or "").strip() or None}
    ).eq("id", consulta_id).execute()
    consulta = resp.data[0] if resp.data else None
    if consulta:
        registrar_historico(consulta_id, "marcou_lista_espera" if ativo else "desmarcou_lista_espera",
                             autor, detalhe=(observacao or "").strip() or None)
    return consulta



def marcar_confirmado(consulta_id: str, autor: dict | None = None) -> dict | None:
    return _mudar_status(consulta_id, "confirmado", "confirmado_em", autor)


def marcar_chegada(consulta_id: str, autor: dict | None = None) -> dict | None:
    """Marca a consulta como 'chegou' (a secretária/atendente apertou o
    botão 'Chegou' na recepção) e avisa o médico dono da consulta em
    tempo real, na tela dele (painel_agenda_fixa.html) -- mesmo padrão de
    chamar_paciente(), mas indo só pra sala daquele médico (medico-<id>),
    não pra recepção inteira."""
    consulta = _mudar_status(consulta_id, "chegou", "chegou_em", autor)
    if consulta is None:
        return None

    try:
        from app.extensions import socketio
        socketio.emit("paciente-chegou", {
            "consulta_id": consulta["id"],
            "paciente_nome": consulta.get("paciente_nome"),
            "horario": consulta.get("horario"),
        }, room=f"medico-{consulta['medico_id']}")
    except Exception as e:
        print(f"[agenda_fixos_service] Não consegui avisar o médico em tempo real: {e}")

    return consulta


def marcar_finalizado(consulta_id: str, autor: dict | None = None) -> dict | None:
    return _mudar_status(consulta_id, "finalizado", "finalizado_em", autor)


def marcar_faltou(consulta_id: str, autor: dict | None = None) -> dict | None:
    return _mudar_status(consulta_id, "faltou", None, autor)


def cancelar_consulta(consulta_id: str, autor: dict | None = None) -> dict | None:
    return _mudar_status(consulta_id, "cancelado", None, autor)


def marcar_agendado_manual(consulta_id: str, autor: dict | None = None) -> dict | None:
    """Volta o status pra 'agendado' -- pra desfazer uma marcação errada
    (ex: clicou no status errado sem querer). Normalmente 'agendado' só
    acontece sozinho, ao criar a consulta; isso é só pra corrigir."""
    return _mudar_status(consulta_id, "agendado", None, autor)


def marcar_atendimento_manual(consulta_id: str, autor: dict | None = None) -> dict | None:
    """Força o status 'em_atendimento' na mão (secretária/admin), pro caso
    de o médico não ter chamado o paciente pela tela dele -- reaproveita
    chamar_paciente() de propósito, pra também avisar o telão da
    recepção em tempo real, exatamente como se o médico tivesse chamado."""
    return chamar_paciente(consulta_id, autor)


def chamar_paciente(consulta_id: str, autor: dict | None = None) -> dict | None:
    """Marca a consulta como 'em_atendimento' (o médico chamou o paciente pra
    sala), registra no log do telão daquele ANDAR, e avisa em tempo real
    (Socket.IO) quem estiver com o telão daquele andar aberto -- e também
    a secretária que estiver atendendo naquele andar (aviso vermelho ao
    lado de "Agenda dos Médicos Fixos")."""
    consulta_resp = db.get_client().table("agenda_consultas").select("*, medicos(nome), consultorios(nome, andar)").eq("id", consulta_id).execute()
    if not consulta_resp.data:
        return None
    consulta = consulta_resp.data[0]

    db.get_client().table("agenda_consultas").update(
        {"status": "em_atendimento", "chamado_em": db.agora_iso(), "atualizado_em": db.agora_iso()}
    ).eq("id", consulta_id).execute()
    registrar_historico(consulta_id, "chamou_paciente", autor)

    medico_nome = consulta["medicos"]["nome"] if consulta.get("medicos") else "Médico"
    sala_nome = consulta["consultorios"]["nome"] if consulta.get("consultorios") else "—"
    andar = ((consulta.get("consultorios") or {}).get("andar") or "").strip() or ANDAR_PADRAO

    chamada_resp = db.get_client().table("chamados_recepcao").insert({
        "agenda_consulta_id": consulta_id, "medico_id": consulta["medico_id"],
        "medico_nome": medico_nome, "sala_nome": sala_nome, "paciente_nome": consulta["paciente_nome"],
        "andar": andar,
    }).execute()
    chamada = chamada_resp.data[0]
    # 'chamado_em' vem do 'default now()' do banco -- não confia que a
    # resposta do insert sempre traz esse campo (ex: um select parcial no
    # futuro), pra nunca deixar de avisar o telão por causa disso
    chamada.setdefault("chamado_em", datetime.utcnow().isoformat())

    try:
        from app.extensions import socketio
        payload = {
            "paciente_nome": chamada["paciente_nome"], "medico_nome": medico_nome,
            "sala_nome": sala_nome, "andar": andar, "chamado_em": chamada["chamado_em"],
        }
        # o telão daquele andar (TV da sala de espera)
        socketio.emit("chamada-paciente", payload, room=f"telao-{andar}")
        # e a tela da(s) secretária(s) que estiver(em) atendendo esse
        # mesmo andar agora -- aviso vermelho ao lado do título
        socketio.emit("chamada-paciente-secretaria", payload, room=f"telao-{andar}")
    except Exception as e:
        print(f"[agenda_fixos_service] Não consegui avisar o telão em tempo real: {e}")

    return chamada


def listar_chamados_recentes(andar: str | None = None, limite: int = 10) -> list[dict]:
    query = db.get_client().table("chamados_recepcao").select("*")
    if andar:
        query = query.eq("andar", andar)
    resp = query.order("chamado_em", desc=True).limit(limite).execute()
    return resp.data


def listar_agenda_dia_medico(medico_id: str, data_str: str) -> list[dict]:
    resp = (
        db.get_client().table("agenda_consultas").select("*, consultorios(nome)")
        .eq("medico_id", medico_id).eq("data", data_str)
        .neq("status", "cancelado").order("horario").execute()
    )
    return resp.data


# ---------------------------------------------------------------------------
# Pesquisa de compromissos ("🔍 Pesquisar") -- busca livre na agenda inteira
# (não só do médico selecionado na tela), pelos campos que a secretária
# mais usa pra achar um agendamento específico: nome do paciente,
# profissional, consultório, status e período (De/Até).
# ---------------------------------------------------------------------------
def pesquisar_consultas(paciente_nome: str = "", medico_id: str = "", consultorio_id: str = "",
                         status: str = "", data_de: str = "", data_ate: str = "",
                         paciente_cpf: str = "", limite: int = 200) -> list[dict]:
    query = db.get_client().table("agenda_consultas").select("*, medicos(nome), consultorios(nome)")
    paciente_nome = (paciente_nome or "").strip()
    if paciente_nome:
        query = query.ilike("paciente_nome", f"%{paciente_nome}%")
    paciente_cpf = re.sub(r"\D", "", paciente_cpf or "")
    if paciente_cpf:
        # busca por CPF (pedido do Paulo, além da busca por nome que já
        # existia) -- ignora pontuação tanto do que foi digitado quanto
        # do que está salvo, pra achar mesmo se um dos dois tiver o CPF
        # formatado diferente (com ou sem ponto/traço)
        candidatos = (
            db.get_client().table("agenda_consultas").select("id")
            .not_.is_("paciente_cpf", "null").execute().data
        )
        ids_com_cpf_batendo = [
            c["id"] for c in candidatos
            if paciente_cpf in re.sub(r"\D", "", c.get("paciente_cpf") or "")
        ]
        if not ids_com_cpf_batendo:
            return []
        query = query.in_("id", ids_com_cpf_batendo)
    if medico_id:
        query = query.eq("medico_id", medico_id)
    if consultorio_id:
        query = query.eq("consultorio_id", consultorio_id)
    if status:
        query = query.eq("status", status)
    if data_de:
        query = query.gte("data", data_de)
    if data_ate:
        query = query.lte("data", data_ate)
    resp = query.order("data", desc=True).order("horario", desc=True).limit(limite).execute()
    return resp.data
