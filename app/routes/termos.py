"""
Tela do Termo de Uso — faltava essa peça no pacote (10/09/2026): o banco
já tinha as colunas certas (termo_aceito/termo_aceito_em/termo_aceito_ip,
ver migration_termo_uso.sql) e o gate @requer_termo_aceito
(app/services/termo_service.py) já existia e era aplicado de verdade em
3 rotas do painel do médico -- só que não existia NENHUMA página/rota
"termos.tela_termo" pra esse gate redirecionar. Resultado: TODO médico
recém-cadastrado (termo_aceito começa False por padrão, ver
supabase_client.criar_medico) caía com erro 500 (BuildError do Flask)
na primeira vez que tentava abrir o painel dele -- travava o fluxo
inteiro logo depois do primeiro acesso. Esse arquivo completa a peça que
faltava.

Atualizado em 10/09/2026 (à tarde): o texto placeholder foi substituído
pelo Contrato Digital de Utilização de Consultórios real da LifeMax
(texto centralizado em app/services/contrato_service.py, conferido
palavra por palavra contra o .docx original enviado pelo Paulo). Também
ganhou a rota /contrato/baixar, que gera esse mesmo contrato em PDF a
qualquer momento pelo painel do médico (botão no fim do dashboard),
preenchido com os dados reais do aceite de cada um.
"""
from flask import Blueprint, render_template, redirect, url_for, request, send_file
from app.services.auth_service import requer_login_medico, medico_logado_id
from app.services import supabase_client as db
from app.services import contrato_service

termos_bp = Blueprint("termos", __name__)


def _proximo_destino_seguro(next_path: str | None) -> str:
    """Só aceita um caminho relativo dentro do próprio site (começando com
    '/' e não com '//') -- evita que alguém manipule o parâmetro 'next'
    pra redirecionar o médico pra um site externo depois do aceite
    (open redirect)."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return url_for("medico_painel.painel")


@termos_bp.route("/termos", methods=["GET", "POST"])
@requer_login_medico
def tela_termo():
    medico_id = medico_logado_id()
    destino = _proximo_destino_seguro(request.values.get("next"))

    medico = db.get_medico_by_id(medico_id)
    if medico and medico.get("termo_aceito"):
        # já aceitou antes (ex: voltou nessa página sem precisar) -- não
        # trava, só manda direto pra onde ia.
        return redirect(destino)

    if request.method == "POST":
        if request.form.get("aceito") == "sim":
            db.registrar_aceite_termo(medico_id, request.remote_addr, versao=contrato_service.CONTRATO_VERSAO)
            return redirect(destino)
        erro = "Marque que leu e concorda com o Termo de Uso para continuar."
        return render_template(
            "termo_uso.html", erro=erro, next=destino,
            titulo=contrato_service.CONTRATO_TITULO, preambulo=contrato_service.CONTRATO_PREAMBULO,
            secoes=contrato_service.CONTRATO_SECOES, declaracoes=contrato_service.CONTRATO_DECLARACOES,
        )

    return render_template(
        "termo_uso.html", erro=None, next=destino,
        titulo=contrato_service.CONTRATO_TITULO, preambulo=contrato_service.CONTRATO_PREAMBULO,
        secoes=contrato_service.CONTRATO_SECOES, declaracoes=contrato_service.CONTRATO_DECLARACOES,
    )


@termos_bp.route("/contrato/baixar")
@requer_login_medico
def baixar_contrato():
    """Botão "baixar o contrato" do painel do médico (pedido do Paulo em
    10/09/2026) -- gera o PDF na hora, preenchendo o bloco de aceite com
    os dados reais do médico logado (data/hora, IP, versão), em vez de um
    PDF genérico igual pra todo mundo."""
    from app.services import pdf_service

    medico = db.get_medico_by_id(medico_logado_id())
    if not medico:
        return redirect(url_for("auth.login"))

    pdf_bytes = pdf_service.gerar_pdf_contrato(medico)
    nome_arquivo = f"Contrato_LifeMax_{(medico.get('nome') or 'medico').split()[0]}.pdf"
    return send_file(
        pdf_bytes, mimetype="application/pdf", as_attachment=True, download_name=nome_arquivo,
    )
