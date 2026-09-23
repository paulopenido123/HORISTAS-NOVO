"""
Texto integral do "Contrato de Prestação de Serviços de Coworking e Cessão
de Infraestrutura" da Lifemax -- substituiu o texto anterior ("Contrato
Digital de Utilização de Consultórios por Horas...") em 23/09/2026, a
pedido do Paulo (item 10), pelo modelo oficial enviado em .docx
(CONTRATO_DE_PRESTA__O_DE_SERVI_OS_DE_COWORKING_E_CESS_O_DE_INFRAESTRUTURA
-_HORAS_MODELO-BIOMAX.docx).

Fica centralizado aqui (em vez de espalhado direto nos templates) porque
DUAS coisas precisam mostrar exatamente o mesmo texto: a tela de aceite no
primeiro acesso (app/templates/termo_uso.html) e o PDF que o médico pode
baixar a qualquer momento depois (rota /contrato/baixar, ver
app/routes/termos.py) -- ter uma cópia só evita que as duas divirjam com o
tempo.

O texto do modelo original tem campos do CONTRATANTE pra preencher à mão
(CPF, endereço, e-mail, telefone, CRM) e uma cláusula 3.1 com quantidade/
valor de um pacote fechado comprado no ato -- como aqui é um contrato
digital, aceito ANTES de qualquer compra (ver reserva_service, item 1: o
médico aceita o contrato antes de comprar horas), esses dois pontos foram
adaptados: a identificação do profissional fica genérica no corpo do
contrato (os dados de fato ficam registrados à parte, no bloco "Dados do
aceite" do PDF -- ver pdf_service.gerar_pdf_contrato, que lista nome,
CPF, CRM, endereço, telefone, e-mail, especialidade e data de nascimento
do médico que aceitou) e a cláusula 3.1 descreve o sistema real de compra
de pacotes avulsos a qualquer momento pela plataforma, em vez de uma
quantidade fixa preenchida no papel. Todo o resto do texto é fiel ao
modelo original.

Se o texto do contrato mudar no futuro, atualize CONTRATO_VERSAO junto
(cada aceite grava a versão vigente no momento -- ver
supabase_client.registrar_aceite_termo / medicos.termo_versao) para manter
rastreável qual versão cada médico aceitou de fato.
"""

CONTRATO_VERSAO = "2.0 (23/09/2026)"

CONTRATO_TITULO = "CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE COWORKING E CESSÃO DE INFRAESTRUTURA"

CONTRATO_PREAMBULO = [
    "LIFEMAX COWORKING EIRELI",
    "CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE COWORKING E CESSÃO DE INFRAESTRUTURA",
    "CONTRATADO: LIFEMAX COWORKING EIRELI, pessoa jurídica de direito privado, inscrita no CNPJ sob o "
    "nº 29.478.011/0001-63, com sede na Rua Gonçalves Dias, nº 82, 4º andar, Funcionários, Belo "
    "Horizonte/MG, CEP 30.140-090, neste ato representada por seu administrador.",
    "CONTRATANTE: o profissional de saúde devidamente identificado no cadastro da plataforma "
    "LifeMax (nome, CPF, registro profissional, endereço, e-mail e telefone, conforme dados "
    "informados e mantidos atualizados pelo próprio profissional no sistema), doravante "
    "denominado CONTRATANTE.",
    "As partes acima identificadas têm, entre si, justo e acertado o presente Contrato de "
    "Prestação de Serviços, que se regerá pelas cláusulas seguintes e pelas disposições do "
    "Código Civil Brasileiro, excluindo-se expressamente a aplicação da Lei nº 8.245/91 (Lei do "
    "Inquilinato).",
]

# Cada seção: (título, [itens]) -- um item é um parágrafo (string) ou uma
# lista com marcadores ({"bullets": [...]})
CONTRATO_SECOES = [
    ("CLÁUSULA 1ª – DO OBJETO", [
        "1.1. O objeto deste contrato é a prestação de serviços de escritório e apoio "
        "administrativo, mediante a cessão temporária de uso de infraestrutura física "
        "(consultórios mobiliados e equipados) para atendimento na área da saúde.",
        "1.2. A cessão de uso não recai sobre sala ou imóvel determinado, mas sim sobre a "
        "disponibilidade de estações de trabalho/consultórios no momento da reserva sistêmica "
        "feita pelo CONTRATANTE.",
    ]),
    ("CLÁUSULA 2ª – DO PRAZO E VIGÊNCIA", [
        "2.1. O contrato terá vigência de 24 (vinte e quatro) meses a contar da data de sua "
        "assinatura (aceite eletrônico).",
        "2.2. Por se tratar de prestação de serviços de natureza rotativa e compartilhada, não "
        "há direito a renovação compulsória ou ponto comercial.",
    ]),
    ("CLÁUSULA 3ª – DOS VALORES E FORMA DE PAGAMENTO", [
        "3.1. O CONTRATANTE poderá adquirir, a qualquer momento através da plataforma, pacotes "
        "de horas avulsas para utilização dos consultórios, conforme as quantidades, valores e "
        "condições comerciais vigentes no momento de cada compra.",
        "3.2. Sistema de Conta Corrente: As horas adquiridas serão geridas em sistema digital. A "
        "cada reserva, o tempo correspondente será deduzido do saldo. Novas reservas ficam "
        "condicionadas à aquisição de novos créditos.",
        "3.3. Horários: O uso está restrito ao período de 2ª a 6ª feira (08h às 20h30) e sábados "
        "(08h às 12h), mediante disponibilidade.",
        "3.4. Tolerância: Frações de hora superiores a 15 (quinze) minutos serão computadas como "
        "01 (uma) hora integral de crédito.",
        "3.5. Validade: Créditos não utilizados em até 24 meses perderão a validade, sem direito "
        "a reembolso, face à reserva de disponibilidade mantida pelo CONTRATADO.",
    ]),
    ("CLÁUSULA 4ª – DOS SERVIÇOS INCLUSOS E ENCARGOS", [
        "4.1. Estão inclusos na remuneração: IPTU, condomínio, energia, água, limpeza, recepção "
        "para triagem, internet de alta velocidade e manutenção de mobiliário.",
        "4.2. Suporte Tecnológico: O CONTRATADO disponibiliza o uso de computador e impressora "
        "(tinta preta) exclusivamente para suporte ao atendimento local.",
        "4.3. Responsabilidade do Contratante: Materiais técnicos específicos, medicamentos, "
        "descartáveis de uso médico e equipamentos de uso pessoal da especialidade são de "
        "inteira responsabilidade e custo do CONTRATANTE.",
    ]),
    ("CLÁUSULA 5ª – DA CONSERVAÇÃO E ZELO PATRIMONIAL", [
        "5.1. O CONTRATANTE obriga-se a zelar pelos equipamentos (computadores, monitores, "
        "periféricos) e mobiliário.",
        "5.2. Danos: Qualquer dano causado por negligência, imperícia ou mau uso (ex: líquidos "
        "nos equipamentos, instalação de softwares maliciosos) será reparado pelo CONTRATANTE ou "
        "este indenizará o valor de um item novo de mercado em até 48 horas.",
        "5.3. É terminantemente proibida qualquer alteração estrutural, furos em paredes, "
        "mudança de layout ou instalação de equipamentos elétricos adicionais sem autorização "
        "prévia por escrito.",
    ]),
    ("CLÁUSULA 6ª – DA RESPONSABILIDADE TÉCNICA E ÉTICA", [
        "6.1. O CONTRATANTE é o único responsável técnico, civil e criminal pelos atos "
        "praticados em seus pacientes. O CONTRATADO não possui qualquer ingerência sobre "
        "condutas clínicas.",
        "6.2. O CONTRATANTE declara estar em dia com seu Conselho de Classe. A suspensão do "
        "registro profissional rescinde este contrato de pleno direito.",
        "6.3. Todos os fatos conflituosos (erros técnicos, atrasos, faltas de cordialidade, "
        "orientações equivocadas) são de responsabilidade exclusiva do CONTRATANTE, que deverá "
        "manter o CONTRATADO indene de qualquer pleito judicial.",
    ]),
    ("CLÁUSULA 7ª – DA PROTEÇÃO DE DADOS (LGPD)", [
        "7.1. O CONTRATANTE é o Controlador de Dados de seus pacientes sob a égide da Lei "
        "13.709/2018.",
        "7.2. É dever do CONTRATANTE garantir que nenhum dado sensível (prontuários, exames, "
        "receitas) seja deixado nos computadores ou dependências físicas do coworking após o "
        "uso. O CONTRATADO não armazena nem trata dados dos pacientes do CONTRATANTE.",
    ]),
    ("CLÁUSULA 8ª – DA RESCISÃO", [
        "8.1. O contrato poderá ser rescindido por infração de qualquer cláusula, sem ônus de "
        "multa para ambas as partes, visto tratar-se de serviço por consumo de créditos.",
        "8.2. O CONTRATADO poderá rescindir imediatamente o acesso em caso de comportamento "
        "inadequado que fira a ética profissional ou coloque em risco a imagem do espaço.",
    ]),
    ("CLÁUSULA 9ª – DO FORO", [
        "9.1. As partes elegem o Foro da Comarca de Belo Horizonte/MG para dirimir quaisquer "
        "controvérsias.",
    ]),
]

# Declarações do bloco final "ACEITE" do contrato -- viram checkboxes
# marcados (✓) tanto na tela de aceite quanto no PDF baixado depois, já
# que quem chegou a ver essas duas telas necessariamente já concordou com
# todas elas.
CONTRATO_DECLARACOES = [
    "Li e concordo integralmente com o Contrato de Prestação de Serviços de Coworking e Cessão "
    "de Infraestrutura da Lifemax.",
    "Estou ciente de que este contrato é regido pelo Código Civil Brasileiro, com exclusão "
    "expressa da Lei do Inquilinato (Lei nº 8.245/91), e tem vigência de 24 (vinte e quatro) "
    "meses.",
    "Estou ciente de que as horas adquiridas são geridas em sistema de conta corrente, deduzidas "
    "a cada reserva, e que novas reservas dependem da aquisição de novos créditos.",
    "Estou ciente de que a utilização dos consultórios está restrita a 2ª a 6ª feira (08h às "
    "20h30) e sábados (08h às 12h), mediante disponibilidade.",
    "Estou ciente de que frações de hora superiores a 15 minutos são computadas como 1 (uma) "
    "hora integral de crédito.",
    "Estou ciente de que créditos não utilizados em até 24 (vinte e quatro) meses perdem a "
    "validade, sem direito a reembolso.",
    "Estou ciente de que sou o único responsável técnico, civil e criminal pelos atos "
    "praticados em meus pacientes, sem qualquer ingerência da Lifemax sobre minhas condutas "
    "clínicas, e de que devo manter meu registro profissional em dia.",
    "Estou ciente de que sou o Controlador de Dados dos meus pacientes nos termos da LGPD (Lei "
    "13.709/2018) e que não devo deixar dados sensíveis (prontuários, exames, receitas) nos "
    "equipamentos ou dependências do coworking após o uso.",
    "Estou ciente de que devo zelar pelos equipamentos e mobiliário, respondendo por danos "
    "causados por negligência, imperícia ou mau uso.",
    "Estou ciente de que este contrato poderá ser rescindido por infração de qualquer cláusula, "
    "sem multa para ambas as partes, e que a Lifemax poderá rescindir imediatamente o acesso em "
    "caso de comportamento inadequado.",
    "Estou ciente de que este contrato elege o Foro da Comarca de Belo Horizonte/MG para "
    "dirimir quaisquer controvérsias.",
]
