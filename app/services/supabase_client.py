"""
Camada de acesso ao banco de dados.

⚠️ Nome do arquivo (10/09/2026): o sistema foi migrado do Supabase para o
Neon (Postgres serverless) a pedido do Paulo, pra poder usar o Object
Storage do próprio Neon e simplificar o banco pra um Postgres "normal".
Esse arquivo ficou com o nome antigo (`supabase_client.py`) de propósito
-- ele é importado em mais de quinze arquivos do projeto (`from
app.services import supabase_client as db` / `from
app.services.supabase_client import get_client`), e renomear o arquivo
significaria editar cada um desses imports à toa, sem ganhar nada em
troca. Por baixo, `get_client()` agora devolve um `PgClient`
(app/services/pg_query.py) que fala Postgres de verdade via psycopg2, mas
imita o mesmo jeito de escrever consulta do cliente Python do Supabase
(`.table(x).select(y).eq(...).execute().data`) -- por isso NENHUMA das
funções abaixo precisou mudar.

Assume o seguinte schema (ajuste os nomes de tabela/coluna para bater
com o que você já tem no financeiro.html, se já existir algo parecido):

medicos
  id (uuid, pk)
  nome (text)
  telefone (text, unique)        -- formato E.164, ex: 5531999999999
  especialidade (text)
  ativo (bool)

consultorios
  id (uuid, pk)
  nome (text)                    -- ex: "Sala 12"
  descricao (text)
  preco_periodo (numeric)        -- preço por período (manhã/tarde)
  fotos (text[])                 -- urls públicas no Supabase Storage

reservas
  id (uuid, pk)
  consultorio_id (uuid, fk)
  medico_id (uuid, fk)
  data (date)
  periodo (text)                 -- 'manha' | 'tarde' | 'noite'
  status (text)                  -- 'pendente' | 'confirmada' | 'cancelada'
  criado_em (timestamptz)

Se seus nomes reais forem diferentes, é só ajustar as strings de
tabela/coluna abaixo — a lógica do resto do sistema não muda.
"""
import re
from datetime import datetime, timezone
from app.services.pg_query import PgClient

_client: PgClient | None = None


def get_client() -> PgClient:
    global _client
    if _client is None:
        _client = PgClient()
    return _client


def _chave_ordenacao_natural(texto: str) -> list:
    """Chave de ordenação 'natural' (numérica onde tem número, alfabética
    no resto) -- pedido do Paulo em 21/09/2026 (2ª vez: primeiro foi o
    consultório 402 aparecendo por último, depois o 403 fora de ordem).

    O `.order("nome")` do banco ordena a string INTEIRA caractere por
    caractere -- então "403" vem DEPOIS de "40" e de qualquer nome que
    comece com dígito maior, mas também qualquer nome com espaço a mais
    no início/fim, ou com quantidade diferente de dígitos ("4" vs "40"
    vs "403"), sai fora da ordem esperada por um humano. Aqui a gente
    quebra o nome em pedaços de dígitos e não-dígitos e compara os
    pedaços numéricos como NÚMERO (não como texto), então "402" < "403"
    < "404" sempre, esteja o nome sozinho ("403") ou com texto junto
    ("Sala 403", "Consultório 4")."""
    texto_normalizado = (texto or "").strip()
    pedacos = re.split(r"(\d+)", texto_normalizado)
    return [int(p) if p.isdigit() else p.lower() for p in pedacos]


def ordenar_consultorios(consultorios: list[dict]) -> list[dict]:
    """Reordena uma lista de consultórios (já buscada do banco) em ordem
    natural crescente pelo campo 'nome' -- ver _chave_ordenacao_natural.
    Usado em TODA lista de consultórios voltada pra grade/matriz (Grade
    de Turnos do médico, Agenda Horistas do admin, Matriz de
    Agendamento, tela de Consultórios do admin), pra manter a mesma
    ordem visual nas quatro telas."""
    return sorted(consultorios, key=lambda c: _chave_ordenacao_natural(c.get("nome")))


def agora_iso() -> str:
    """Timestamp de agora, no formato que o Postgres aceita de verdade
    numa coluna timestamptz via update/insert do PostgREST.

    ⚠️ BUG CORRIGIDO (03/09/2026): várias partes do sistema usavam a
    STRING "now()" (entre aspas) pra marcar "agora" num campo de data --
    algo como atualizado_em = "now()". Isso funciona em SQL puro
    (dentro de uma migração, `default now()` é uma FUNÇÃO do banco), mas
    pelo PostgREST/Supabase isso vira um valor comum, e o Postgres tenta
    entender a palavra "now()" (com parênteses) como uma DATA -- e não
    consegue, porque o valor especial reconhecido é só "now" (SEM
    parênteses). O resultado: um erro do banco, sem aviso nenhum na tela
    além de "Ocorreu um erro interno no servidor" -- silencioso e fácil
    de não perceber até acontecer de verdade (mock de teste não pega
    isso, só o banco real recusando o valor). Use sempre essa função em
    vez de escrever "now()" à mão.
    """
    return datetime.now(timezone.utc).isoformat()


def get_medico_by_telefone(telefone: str) -> dict | None:
    """Busca o médico pelo número de telefone (identifica quem está falando)."""
    resp = get_client().table("medicos").select("*").eq("telefone", telefone).execute()
    data = resp.data
    return data[0] if data else None


def listar_consultorios_disponiveis(data: str, periodo: str) -> list[dict]:
    """
    Retorna consultórios livres em uma data/período.
    data: 'YYYY-MM-DD', periodo: 'manha' | 'tarde' | 'noite'
    """
    client = get_client()

    # Todos os consultórios
    todos = client.table("consultorios").select("*").execute().data

    # Reservas já existentes nesse slot (que não estão canceladas)
    ocupados_resp = (
        client.table("reservas")
        .select("consultorio_id")
        .eq("data", data)
        .eq("periodo", periodo)
        .neq("status", "cancelada")
        .execute()
    )
    ocupados_ids = {r["consultorio_id"] for r in ocupados_resp.data}

    disponiveis = [c for c in todos if c["id"] not in ocupados_ids]
    return disponiveis


def criar_reserva(consultorio_id: str, medico_id: str, data: str, periodo: str) -> dict:
    """Cria a reserva com status pendente (confirma depois do pagamento)."""
    resp = (
        get_client()
        .table("reservas")
        .insert({
            "consultorio_id": consultorio_id,
            "medico_id": medico_id,
            "data": data,
            "periodo": periodo,
            "status": "pendente",
            "tipo_reserva": "turno",
        })
        .execute()
    )
    return resp.data[0]


# Faixas de horário de cada turno — usadas para checar conflito com
# reservas avulsas por hora. Ajuste aqui se os horários reais do
# coworking forem diferentes.
# "noite" começa às 17h30 (não 17h) -- pedido do Paulo em 21/09/2026:
# pausa para limpeza das 17h às 17h30, mesma faixa que a agenda dos
# médicos fixos já usava (agenda_fixos_service.TURNOS_HORARIOS).
PERIODOS_HORARIOS = {
    "manha": ("08:00", "12:00"),
    "tarde": ("13:00", "17:00"),
    "noite": ("17:30", "20:30"),
}


def _minutos(horario) -> int:
    """Converte 'HH:MM' ou 'HH:MM:SS' (string) em minutos desde meia-noite."""
    partes = str(horario).split(":")
    return int(partes[0]) * 60 + int(partes[1])


def _somar_horas(hora_str: str, quantidade_horas: int) -> str:
    total_min = _minutos(hora_str) + quantidade_horas * 60
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def somar_horas(hora_str: str, quantidade_horas: int) -> str:
    """Versão pública de _somar_horas, para uso por outros módulos (ex: Google Agenda)."""
    return _somar_horas(hora_str, quantidade_horas)


def minutos_do_dia(hora_str: str) -> int:
    """Versão pública de _minutos, para uso por outros módulos (ex: validação de horário de consulta)."""
    return _minutos(hora_str)


def _existe_conflito_horario(consultorio_id: str, data: str, hora_inicio: str, hora_fim: str) -> bool:
    reservas = (
        get_client()
        .table("reservas")
        .select("periodo, tipo_reserva, hora_inicio, hora_fim")
        .eq("consultorio_id", consultorio_id)
        .eq("data", data)
        .neq("status", "cancelada")
        .execute()
        .data
    )
    novo_ini, novo_fim = _minutos(hora_inicio), _minutos(hora_fim)

    for r in reservas:
        if r["tipo_reserva"] == "turno":
            ini_str, fim_str = PERIODOS_HORARIOS[r["periodo"]]
        else:
            if not r.get("hora_inicio") or not r.get("hora_fim"):
                continue
            ini_str, fim_str = r["hora_inicio"], r["hora_fim"]

        ini, fim = _minutos(ini_str), _minutos(fim_str)
        if novo_ini < fim and ini < novo_fim:  # sobreposição de intervalos
            return True
    return False


def criar_reserva_por_hora(consultorio_id: str, medico_id: str, data: str,
                            hora_inicio: str, quantidade_horas: int,
                            criado_por_admin: bool = False) -> dict:
    """
    Cria uma reserva avulsa por hora. Levanta ValueError se o horário
    conflitar com outra reserva (turno ou hora) já existente — seja
    porque a checagem em Python encontrou o conflito, seja porque o
    banco de dados rejeitou por causa da trava de sobreposição (a
    proteção final contra dois médicos reservando no mesmo instante).

    `criado_por_admin` -- pedido do Paulo em 21/09/2026, botão "Agendar
    para:" na Agenda Horistas: marca que foi o ADMINISTRADOR quem criou
    essa reserva em nome do médico (não o próprio médico), pra Grade de
    Turnos / Minha Agenda / extrato avisarem isso claramente.
    """
    hora_fim = _somar_horas(hora_inicio, quantidade_horas)

    if _existe_conflito_horario(consultorio_id, data, hora_inicio, hora_fim):
        raise ValueError("Esse horário conflita com outra reserva já existente nesse consultório.")

    try:
        resp = (
            get_client()
            .table("reservas")
            .insert({
                "consultorio_id": consultorio_id,
                "medico_id": medico_id,
                "data": data,
                "periodo": None,
                "tipo_reserva": "hora",
                "hora_inicio": hora_inicio,
                "hora_fim": hora_fim,
                "quantidade_horas": quantidade_horas,
                "status": "pendente",
                "criado_por_admin": criado_por_admin,
            })
            .execute()
        )
    except Exception:
        # a checagem em Python acima não achou conflito, mas o banco
        # rejeitou mesmo assim — significa que outra reserva foi criada
        # bem no meio do processo (condição de corrida). É exatamente
        # para isso que a trava do banco existe.
        raise ValueError("Esse horário acabou de ser reservado por outra pessoa. Tente outro horário.")

    return resp.data[0]


def confirmar_reserva(reserva_id: str) -> dict:
    resp = (
        get_client()
        .table("reservas")
        .update({"status": "confirmada"})
        .eq("id", reserva_id)
        .execute()
    )
    return resp.data[0]


def get_reserva_by_id(reserva_id: str) -> dict | None:
    """Busca uma reserva por id -- usada pelo cancelamento (reserva_service.
    cancelar_reserva), pra conferir de quem é a reserva e calcular o
    horário de início antes de decidir se ainda dá reembolso."""
    resp = get_client().table("reservas").select("*").eq("id", reserva_id).execute()
    return resp.data[0] if resp.data else None


def definir_paciente_reserva(reserva_id: str, paciente_id: str | None) -> dict:
    """Grava (ou limpa, se `paciente_id` vier None) qual paciente está
    marcado pra ocupar esse horário -- botão "Incluir/alterar paciente"
    na tela "Minha agenda" do médico (ver reserva_service.associar_paciente,
    que confere antes que a reserva e o paciente são realmente do mesmo
    médico)."""
    resp = (
        get_client()
        .table("reservas")
        .update({"paciente_id": paciente_id})
        .eq("id", reserva_id)
        .execute()
    )
    return resp.data[0]


def definir_hora_confirmada_reserva(reserva_id: str, hora_confirmada: str | None) -> dict:
    """Campo "confirmação da hora" (ver reserva_service.definir_hora_confirmada)
    -- pedido do Paulo em 11/09/2026."""
    resp = (
        get_client().table("reservas").update({"hora_confirmada": hora_confirmada}).eq("id", reserva_id).execute()
    )
    return resp.data[0]


def listar_pacientes_agendados_por_reservas(reserva_ids: list[str]) -> dict:
    """Pra cada reserva, a lista de pacientes marcados pra receber o
    e-mail de confirmação de agendamento (tabela `reserva_pacientes`,
    ver sql/migration_notificacoes_email.sql) -- busca todo mundo de UMA
    vez (uma query só, com `in_`) em vez de uma consulta por reserva,
    mesmo cuidado do N+1 corrigido em admin.clientes() em 11/09/2026.
    Devolve um dict {reserva_id: [linha, ...]}, cada linha já com
    `pacientes.nome_completo`/`pacientes.email` embutidos."""
    if not reserva_ids:
        return {}
    resp = (
        get_client().table("reserva_pacientes")
        .select("*, pacientes(nome_completo, email)")
        .in_("reserva_id", reserva_ids)
        .execute()
    )
    agrupado: dict[str, list[dict]] = {}
    for linha in resp.data:
        agrupado.setdefault(linha["reserva_id"], []).append(linha)
    return agrupado


def adicionar_paciente_reserva(reserva_id: str, paciente_id: str) -> dict | None:
    """Insere (ou ignora, se já existir) uma linha em `reserva_pacientes`
    -- usada tanto pelo botão legado "Incluir/alterar paciente" (mantém
    os dois mecanismos sincronizados, ver reserva_service.associar_paciente)
    quanto pelo novo "+ Adicionar paciente" da seção de e-mail de
    agendamento (reserva_service.adicionar_paciente_agendamento)."""
    client = get_client()
    existente = (
        client.table("reserva_pacientes").select("id")
        .eq("reserva_id", reserva_id).eq("paciente_id", paciente_id).execute().data
    )
    if existente:
        return existente[0]
    resp = client.table("reserva_pacientes").insert({
        "reserva_id": reserva_id, "paciente_id": paciente_id,
    }).execute()
    return resp.data[0] if resp.data else None


def remover_paciente_da_reserva(reserva_id: str, paciente_id: str):
    (
        get_client().table("reserva_pacientes")
        .delete().eq("reserva_id", reserva_id).eq("paciente_id", paciente_id).execute()
    )


def marcar_email_agendamento_enviado(reserva_id: str, paciente_id: str):
    (
        get_client().table("reserva_pacientes")
        .update({"email_enviado_em": agora_iso()})
        .eq("reserva_id", reserva_id).eq("paciente_id", paciente_id)
        .execute()
    )


def marcar_reserva_cancelada(reserva_id: str, cancelado_por_admin: bool = False) -> dict:
    """Muda o status pra 'cancelada' e grava `cancelado_em` (ver
    migration_cancelado_em.sql) -- o reembolso (ou não, se dentro de 12h)
    é decidido e lançado à parte por reserva_service.cancelar_reserva.
    `cancelado_em` é o que permite o relatório de Agendamentos (admin)
    mostrar a ocorrência do cancelamento na linha do tempo certa, e não
    só a data da reserva em si.

    `cancelado_por_admin` -- pedido do Paulo em 21/09/2026, botão
    "Cancelar agendamento" na Agenda Horistas: marca que foi o
    ADMINISTRADOR quem cancelou (não o próprio médico)."""
    resp = (
        get_client()
        .table("reservas")
        .update({"status": "cancelada", "cancelado_em": agora_iso(), "cancelado_por_admin": cancelado_por_admin})
        .eq("id", reserva_id)
        .execute()
    )
    return resp.data[0]


def obter_transacao_consumo_da_reserva(reserva_id: str) -> dict | None:
    """Acha a transação tipo='consumo' que debitou essa reserva -- pra
    reembolsar EXATAMENTE o valor cobrado na hora, mesmo que o preço da
    hora avulsa tenha mudado depois (pedido do Paulo em 10/09/2026,
    cancelamento com reembolso de horas)."""
    resp = (
        get_client().table("creditos_transacoes").select("*")
        .eq("reserva_id", reserva_id).eq("tipo", "consumo")
        .order("criado_em", desc=True).limit(1).execute()
    )
    return resp.data[0] if resp.data else None


def listar_reservas_medico(medico_id: str) -> list[dict]:
    """Todas as reservas (turno ou hora avulsa, qualquer status) desse
    médico, com o nome do consultório já embutido -- usada na tela "Minha
    Agenda" (pedido do Paulo em 10/09/2026). Ordenadas por data/horário
    crescente (mais próxima primeiro), calculado em Python porque turno
    guarda só `periodo` (sem hora_inicio) e hora avulsa guarda hora_inicio
    -- os dois precisam de uma chave de ordenação comum."""
    resp = (
        get_client()
        .table("reservas")
        .select("*, consultorios(nome), pacientes(nome_completo)")
        .eq("medico_id", medico_id)
        .execute()
    )
    reservas = resp.data

    def _chave_ordenacao(r):
        if r.get("tipo_reserva") == "hora" and r.get("hora_inicio"):
            hora = r["hora_inicio"]
        else:
            hora = PERIODOS_HORARIOS.get(r.get("periodo"), ("00:00",))[0]
        return (r.get("data") or "", hora)

    reservas.sort(key=_chave_ordenacao)
    return reservas


def criar_cliente_medico(medico_id: str, nome: str, endereco: str = "",
                          email: str = "", telefone: str = "") -> dict:
    """Cadastro rápido de contato do cliente do médico (Nome, endereço,
    e-mail, telefone/WhatsApp) -- pedido do Paulo em 10/09/2026, botão
    "Incluir dados cliente" na página do médico. Sem vínculo com
    consulta/prontuário (esse pacote não inclui Agenda de Pacientes)."""
    resp = (
        get_client()
        .table("clientes_medico")
        .insert({
            "medico_id": medico_id,
            "nome": nome,
            "endereco": endereco or None,
            "email": email or None,
            "telefone": telefone or None,
        })
        .execute()
    )
    return resp.data[0]


def listar_clientes_medico(medico_id: str) -> list[dict]:
    resp = (
        get_client()
        .table("clientes_medico")
        .select("*")
        .eq("medico_id", medico_id)
        .order("nome")
        .execute()
    )
    return resp.data


def listar_todos_consultorios() -> list[dict]:
    """Todos os consultórios ativos, para a página pública/admin."""
    resp = get_client().table("consultorios").select("*").eq("ativo", True).order("nome").execute()
    return ordenar_consultorios(resp.data)


def andar_a_partir_do_nome(nome: str) -> str | None:
    """Deriva o andar automaticamente a partir do número/nome do
    consultório -- pedido do Paulo em 10/09/2026: não é mais um campo
    digitado à mão no formulário, é sempre calculado a partir do começo
    do número da sala. Regra: pega os dígitos do início do nome; até 3
    dígitos, o andar é só o 1º dígito (ex: "402" -> andar "4"); com 4
    dígitos ou mais, o andar são os 2 primeiros dígitos (ex: "1101" ->
    andar "11"). Se o nome não começar com dígito, não dá pra inferir
    (devolve None)."""
    m = re.match(r"^\s*(\d+)", nome or "")
    if not m:
        return None
    digitos = m.group(1)
    return digitos[:2] if len(digitos) > 3 else digitos[:1]


def criar_consultorio(nome: str, descricao: str, preco_periodo: float, andar: str = "") -> dict:
    # `andar` deixou de ser digitado no formulário -- agora é sempre
    # derivado do nome (ver andar_a_partir_do_nome). O parâmetro
    # continua aceito (e tem prioridade se vier preenchido) só pra não
    # quebrar o import de agenda fixa em agenda_fixos_service.py, que
    # ainda passa um andar explícito vindo da planilha.
    andar_final = andar.strip() if (andar or "").strip() else andar_a_partir_do_nome(nome)
    resp = (
        get_client()
        .table("consultorios")
        .insert({"nome": nome, "descricao": descricao, "preco_periodo": preco_periodo,
                 "fotos": [], "ativo": True, "andar": andar_final})
        .execute()
    )
    return resp.data[0]


def atualizar_andar_consultorio(consultorio_id: str, andar: str) -> dict:
    """Só o andar -- usado na aba "Configurações locais" (Agenda Fixos),
    pra mudar de qual telão/painel um consultório recebe o aviso de
    chamada quando o médico dele chama um paciente."""
    resp = (
        get_client().table("consultorios").update({"andar": (andar or "").strip() or None})
        .eq("id", consultorio_id).execute()
    )
    return resp.data[0]


def excluir_consultorio(consultorio_id: str) -> str:
    """
    Tenta apagar de vez. Se o consultório já tiver reservas associadas
    (o banco vai reclamar por causa da referência), desativa em vez de
    apagar — assim o histórico financeiro não se perde.
    Retorna 'apagado' ou 'desativado'.
    """
    client = get_client()
    try:
        client.table("consultorios").delete().eq("id", consultorio_id).execute()
        return "apagado"
    except Exception:
        client.table("consultorios").update({"ativo": False}).eq("id", consultorio_id).execute()
        return "desativado"


def adicionar_fotos_consultorio(consultorio_id: str, novas_urls: list[str]) -> dict:
    """Anexa novas fotos à lista existente do consultório (não substitui)."""
    client = get_client()
    atual = client.table("consultorios").select("fotos").eq("id", consultorio_id).execute().data
    fotos_existentes = atual[0]["fotos"] if atual and atual[0]["fotos"] else []
    fotos_atualizadas = fotos_existentes + novas_urls

    resp = (
        client.table("consultorios")
        .update({"fotos": fotos_atualizadas})
        .eq("id", consultorio_id)
        .execute()
    )
    return resp.data[0]


def remover_foto_consultorio(consultorio_id: str, url_foto: str) -> dict:
    client = get_client()
    atual = client.table("consultorios").select("fotos").eq("id", consultorio_id).execute().data
    fotos_existentes = atual[0]["fotos"] if atual and atual[0]["fotos"] else []
    fotos_atualizadas = [f for f in fotos_existentes if f != url_foto]

    resp = (
        client.table("consultorios")
        .update({"fotos": fotos_atualizadas})
        .eq("id", consultorio_id)
        .execute()
    )
    return resp.data[0]


def listar_medicos_ativos() -> list[dict]:
    resp = get_client().table("medicos").select("*").eq("ativo", True).order("nome").execute()
    return resp.data


def definir_autorizacao_medico(medico_id: str, autorizado: bool) -> dict:
    """Liga/desliga o toggle "Usuário autorizado no sistema" -- pedido do
    Paulo em 10/09/2026. Só mexe em `autorizado` (nada de saldo, nada de
    `ativo`, que é um campo diferente e já existia antes pra
    ativar/desativar cadastro)."""
    resp = (
        get_client().table("medicos").update({"autorizado": autorizado}).eq("id", medico_id).execute()
    )
    return resp.data[0] if resp.data else None


def definir_email_confirmado(medico_id: str, confirmado: bool) -> dict | None:
    """Liga (quando o médico clica no link de confirmação -- ver
    recuperacao_senha_service.confirmar_email) ou desliga (quando o
    admin cadastra/troca o e-mail dele -- ver app/routes/admin.py,
    novo_cliente/editar_cliente) a ⭐ que aparece do lado do e-mail na
    lista de Clientes do admin -- pedido do Paulo em 11/09/2026."""
    resp = (
        get_client().table("medicos").update({"email_confirmado": confirmado}).eq("id", medico_id).execute()
    )
    return resp.data[0] if resp.data else None


def criar_medico(nome: str, telefone: str, especialidade: str = "", tipo_vinculo: str = "avulso",
                  empresa_id: str | None = None, email: str = "", crm: str = "", cpf_cnpj: str = "",
                  endereco_cep: str = "", endereco_rua: str = "", endereco_numero: str = "",
                  endereco_complemento: str = "", endereco_bairro: str = "", endereco_cidade: str = "",
                  endereco_estado: str = "", convenios: list[str] | None = None,
                  autorizado: bool = True) -> dict:
    """`autorizado=True` por padrão -- preserva o comportamento de sempre
    pra quem já chamava essa função (ex: importação de agenda fixa em
    agenda_fixos_service.py, onde é o PRÓPRIO admin que está cadastrando
    médicos a partir de uma planilha já conferida por ele, não faz
    sentido travar esses). Quem precisa nascer com `autorizado=False`
    (auto-cadastro público, sem ninguém do lado do admin conferindo antes
    -- ver rota /primeiro-acesso em app/routes/auth.py, pedido do Paulo em
    10/09/2026) passa `autorizado=False` explicitamente na chamada."""
    resp = (
        get_client()
        .table("medicos")
        .insert({
            "nome": nome,
            "telefone": telefone,
            "especialidade": especialidade,
            "saldo_creditos": 0,
            "ativo": True,
            "autorizado": autorizado,
            "assistente_ativo": False,
            "termo_aceito": False,
            "is_beta_tester": False,
            "tipo_vinculo": tipo_vinculo,
            "empresa_id": empresa_id,
            "email": email,
            "crm": crm,
            "cpf_cnpj": cpf_cnpj,
            "endereco_cep": endereco_cep,
            "endereco_rua": endereco_rua,
            "endereco_numero": endereco_numero,
            "endereco_complemento": endereco_complemento,
            "endereco_bairro": endereco_bairro,
            "endereco_cidade": endereco_cidade,
            "endereco_estado": endereco_estado,
            "convenios": convenios or [],
        })
        .execute()
    )
    return resp.data[0]


def atualizar_medico(medico_id: str, nome: str, telefone: str, especialidade: str, cpf_cnpj: str = "",
                      email: str | None = None, crm: str | None = None, empresa_id: str | None = None,
                      endereco_cep: str | None = None, endereco_rua: str | None = None,
                      endereco_numero: str | None = None, endereco_complemento: str | None = None,
                      endereco_bairro: str | None = None, endereco_cidade: str | None = None,
                      endereco_estado: str | None = None, convenios: list[str] | None = None,
                      tipo_vinculo: str | None = None) -> dict:
    dados = {"nome": nome, "telefone": telefone, "especialidade": especialidade, "cpf_cnpj": cpf_cnpj}
    # email/crm/empresa_id/endereço/convênios/tipo_vinculo são opcionais e só
    # entram no update se informados (None = "não mexe nesse campo") -- assim
    # quem não manda esses campos continua funcionando exatamente igual.
    # tipo_vinculo acrescentado em 11/09/2026 pra tela "Editar dados" do
    # cliente no admin (app/routes/admin.py, editar_cliente).
    if email is not None:
        dados["email"] = email
    if crm is not None:
        dados["crm"] = crm
    if empresa_id is not None:
        dados["empresa_id"] = empresa_id
    if tipo_vinculo is not None:
        dados["tipo_vinculo"] = tipo_vinculo
    if endereco_cep is not None:
        dados["endereco_cep"] = endereco_cep
    if endereco_rua is not None:
        dados["endereco_rua"] = endereco_rua
    if endereco_numero is not None:
        dados["endereco_numero"] = endereco_numero
    if endereco_complemento is not None:
        dados["endereco_complemento"] = endereco_complemento
    if endereco_bairro is not None:
        dados["endereco_bairro"] = endereco_bairro
    if endereco_cidade is not None:
        dados["endereco_cidade"] = endereco_cidade
    if endereco_estado is not None:
        dados["endereco_estado"] = endereco_estado
    if convenios is not None:
        dados["convenios"] = convenios
    resp = get_client().table("medicos").update(dados).eq("id", medico_id).execute()
    return resp.data[0]


def listar_funcionarios_ativos() -> list[dict]:
    resp = get_client().table("funcionarios").select("*").eq("ativo", True).execute()
    return resp.data


def get_medico_by_id(medico_id: str) -> dict | None:
    resp = get_client().table("medicos").select("*").eq("id", medico_id).execute()
    return resp.data[0] if resp.data else None


def registrar_aceite_termo(medico_id: str, ip: str | None, versao: str | None = None):
    """`versao`: qual versão do contrato (contrato_service.CONTRATO_VERSAO)
    estava vigente no momento do aceite -- grava junto pra manter
    rastreável qual texto exato o médico concordou, caso o contrato mude
    no futuro (ver migration_termo_versao.sql)."""
    get_client().table("medicos").update({
        "termo_aceito": True,
        "termo_aceito_em": agora_iso(),
        "termo_aceito_ip": ip,
        "termo_versao": versao,
    }).eq("id", medico_id).execute()


def get_consultorio_by_id(consultorio_id: str) -> dict | None:
    resp = get_client().table("consultorios").select("*").eq("id", consultorio_id).execute()
    return resp.data[0] if resp.data else None


def grade_de_turnos(data_inicio: str, data_fim: str) -> dict:
    """
    Monta a grade completa: para cada consultório, para cada dia no
    intervalo, para cada período (manha/tarde/noite), diz se está livre
    ou ocupado (e por quem, se ocupado).
    Retorna: {"consultorios": [...], "reservas": [...]}
    já prontos para o frontend montar a grade.
    """
    client = get_client()
    consultorios = ordenar_consultorios(
        client.table("consultorios").select("*").eq("ativo", True).order("nome").execute().data
    )

    reservas = (
        client.table("reservas")
        .select("*, medicos(nome)")
        .gte("data", data_inicio)
        .lte("data", data_fim)
        .neq("status", "cancelada")
        .execute()
        .data
    )

    return {"consultorios": consultorios, "reservas": reservas}


def resumo_financeiro_medico(medico_id: str, mes: int, ano: int) -> dict:
    """
    Placeholder: aqui você deve integrar com sua tabela/view financeira
    real (a mesma que alimenta o financeiro.html). Por ora, soma as
    reservas confirmadas do mês como proxy de faturamento com o coworking.
    """
    client = get_client()
    resp = (
        client.table("reservas")
        .select("*, consultorios(preco_periodo)")
        .eq("medico_id", medico_id)
        .eq("status", "confirmada")
        .execute()
    )
    total = 0
    count = 0
    for r in resp.data:
        data_reserva = r["data"]
        ano_r, mes_r, _ = data_reserva.split("-")
        if int(mes_r) == mes and int(ano_r) == ano:
            total += r["consultorios"]["preco_periodo"]
            count += 1
    return {"total_gasto_consultorio": total, "numero_reservas": count, "mes": mes, "ano": ano}
