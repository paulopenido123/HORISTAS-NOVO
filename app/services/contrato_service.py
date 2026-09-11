"""
Texto integral do "Contrato Digital de Utilização de Consultórios por
Horas, Serviços e Regras de Reserva" da LifeMax -- substituiu o texto
placeholder de termo_uso.html em 10/09/2026 (o arquivo .docx original foi
enviado pelo Paulo).

Fica centralizado aqui (em vez de espalhado direto nos templates) porque
DUAS coisas precisam mostrar exatamente o mesmo texto: a tela de aceite no
primeiro acesso (app/templates/termo_uso.html) e o PDF que o médico pode
baixar a qualquer momento depois (rota /contrato/baixar, ver
app/routes/termos.py) -- ter uma cópia só evita que as duas divirjam com o
tempo.

Se o texto do contrato mudar no futuro, atualize CONTRATO_VERSAO junto
(cada aceite grava a versão vigente no momento -- ver
supabase_client.registrar_aceite_termo / medicos.termo_versao) para manter
rastreável qual versão cada médico aceitou de fato.
"""

CONTRATO_VERSAO = "1.0 (10/09/2026)"

CONTRATO_TITULO = "CONTRATO DIGITAL DE UTILIZAÇÃO DE CONSULTÓRIOS POR HORAS, SERVIÇOS E REGRAS DE RESERVA"

CONTRATO_PREAMBULO = [
    "LIFEMAX CONSULTÓRIOS",
    "TERMO DE ADESÃO E UTILIZAÇÃO DE ESPAÇOS PROFISSIONAIS DE SAÚDE",
    "Pelo presente instrumento, de um lado, LIFEMAX CONSULTÓRIOS, doravante denominada "
    "simplesmente LIFEMAX, e, de outro lado, o profissional de saúde devidamente cadastrado na "
    "plataforma, doravante denominado USUÁRIO ou PROFISSIONAL, estabelecem o presente Contrato "
    "Digital de Utilização de Consultórios por Horas e Serviços, mediante aceite eletrônico "
    "realizado na plataforma LifeMax.",
    "O presente contrato regulamenta a utilização dos consultórios, salas e demais espaços "
    "disponibilizados pela LifeMax, bem como as regras de compra de horas, reservas, "
    "cancelamentos, utilização dos ambientes e contratação de serviços adicionais.",
]

# Cada seção: (título, [itens]) -- um item é um parágrafo (string) ou uma
# lista com marcadores ({"bullets": [...]})
CONTRATO_SECOES = [
    ("1. ACEITE DIGITAL", [
        "1.1. O presente contrato será apresentado ao profissional em formato digital na "
        "primeira ocasião em que este realizar login na plataforma LifeMax.",
        "1.2. Para prosseguir com a utilização da plataforma e dos serviços, o profissional "
        "deverá declarar seu aceite mediante mecanismo eletrônico disponibilizado no sistema.",
        "1.3. O aceite eletrônico possui validade para todos os fins de direito e representa a "
        "concordância do profissional com as condições estabelecidas neste instrumento.",
        "1.4. Após o aceite, este contrato permanecerá disponível na área do usuário na "
        "plataforma, podendo ser consultado e baixado pelo profissional a qualquer momento.",
        "1.5. O profissional declara que possui capacidade e autorização para exercer sua "
        "atividade profissional e que utilizará os espaços exclusivamente para atividades "
        "compatíveis com sua habilitação profissional e com a legislação aplicável.",
    ]),
    ("2. OBJETO", [
        "2.1. A LifeMax disponibiliza aos profissionais da área da saúde espaços físicos "
        "equipados para a realização de consultas, atendimentos, avaliações, reuniões "
        "profissionais e demais atividades compatíveis com a estrutura disponibilizada, "
        "mediante aquisição prévia de horas e realização de reservas através da plataforma.",
        "2.2. A contratação é realizada de forma digital, não havendo necessidade de assinatura "
        "física deste instrumento.",
        "2.3. A utilização dos espaços está condicionada à disponibilidade de horários, às "
        "regras da plataforma, ao saldo existente na conta do profissional e às demais "
        "condições estabelecidas neste contrato.",
    ]),
    ("3. COMPRA DE HORAS", [
        "3.1. A utilização dos consultórios será realizada mediante aquisição de créditos de "
        "horas disponibilizados pela LifeMax.",
        "3.2. A compra de créditos será realizada em pacotes de, no mínimo, 6 (seis) horas.",
        "3.3. O profissional poderá adquirir quantidade superior ao mínimo estabelecido, "
        "conforme os pacotes e condições comerciais disponibilizados na plataforma.",
        "3.4. As horas adquiridas serão disponibilizadas como saldo na conta do profissional e "
        "poderão ser utilizadas mediante realização de reservas.",
        "3.5. A LifeMax poderá estabelecer diferentes modalidades, valores, pacotes, condições "
        "comerciais, prazos de utilização e demais características dos créditos, "
        "disponibilizando essas informações na plataforma.",
    ]),
    ("4. RESERVAS", [
        "4.1. Todas as reservas deverão obrigatoriamente ser realizadas através do "
        "site/plataforma LifeMax, mediante login e autenticação do profissional.",
        "4.2. Não serão consideradas válidas reservas realizadas informalmente por WhatsApp, "
        "telefone, e-mail, mensagens ou diretamente com funcionários, salvo se a LifeMax "
        "expressamente autorizar procedimento diverso.",
        "4.3. Cada reserva deverá respeitar o período mínimo de 1 (uma) hora.",
        "4.4. A utilização de período inferior a 1 (uma) hora não dará direito ao profissional "
        "a crédito, desconto ou devolução proporcional da hora reservada. Exemplo: caso o "
        "profissional reserve 1 (uma) hora e utilize o consultório durante apenas 30 minutos, "
        "será contabilizada 1 (uma) hora.",
        "4.5. Da mesma forma, caso o profissional reserve determinado período e não compareça "
        "ao consultório, a reserva permanecerá sujeita às regras de cancelamento previstas "
        "neste contrato.",
    ]),
    ("5. SALDO NEGATIVO", [
        "5.1. O sistema LifeMax controlará automaticamente o saldo de horas/créditos "
        "disponível para cada profissional.",
        "5.2. Não será possível realizar novas reservas enquanto o saldo do profissional "
        "estiver negativo.",
        "5.3. O profissional deverá regularizar eventual saldo negativo antes de realizar "
        "novas reservas.",
        "5.4. A LifeMax poderá bloquear temporariamente novas reservas ou outras "
        "funcionalidades da plataforma enquanto houver saldo negativo ou qualquer obrigação "
        "financeira pendente.",
    ]),
    ("6. CANCELAMENTO DE RESERVAS", [
        "6.1. O profissional poderá cancelar uma reserva diretamente através da plataforma.",
        "6.2. O cancelamento deverá ser realizado no prazo máximo de 12 (doze) horas, "
        "observadas as regras e horários indicados no sistema.",
        "6.3. Caso a reserva não seja cancelada dentro do prazo de 12 (doze) horas, ela será "
        "contabilizada normalmente, ainda que o profissional não compareça ou não utilize o "
        "consultório durante o período reservado.",
        "6.4. A ausência do profissional, de seu paciente ou de qualquer pessoa vinculada ao "
        "atendimento não será considerada, por si só, motivo para cancelamento ou restituição "
        "da hora reservada.",
        "6.5. Em situações excepcionais, a LifeMax poderá, a seu exclusivo critério, analisar "
        "pedidos de cancelamento fora do prazo, sem que isso constitua obrigação ou gere "
        "precedente para situações futuras.",
    ]),
    ("7. UTILIZAÇÃO DOS CONSULTÓRIOS", [
        "7.1. Os espaços deverão ser utilizados exclusivamente para atividades profissionais "
        "compatíveis com a finalidade dos consultórios e com a estrutura disponibilizada pela "
        "LifeMax.",
        "7.2. É expressamente proibida a utilização dos consultórios para:",
        {"bullets": [
            "realização de cirurgias de qualquer natureza;",
            "realização de procedimentos invasivos ou de maior complexidade que exijam "
            "estrutura hospitalar, centro cirúrgico ou equipamentos específicos não "
            "disponibilizados pela LifeMax;",
            "procedimentos que ofereçam risco incompatível com a estrutura física do "
            "consultório;",
            "utilização de medicamentos, equipamentos ou materiais que exijam condições "
            "especiais de armazenamento ou suporte não disponíveis no local;",
            "qualquer atividade proibida pela legislação, pelas normas sanitárias ou pelas "
            "normas dos respectivos Conselhos Profissionais;",
            "qualquer atividade que possa colocar em risco pacientes, profissionais, "
            "funcionários, visitantes ou o patrimônio da LifeMax.",
        ]},
        "7.3. O profissional é integralmente responsável por verificar se o procedimento que "
        "pretende realizar é compatível com a estrutura disponibilizada e com as normas legais "
        "e profissionais aplicáveis.",
        "7.4. A LifeMax poderá impedir imediatamente a realização de qualquer procedimento que "
        "considere incompatível com a estrutura do local, com as normas de segurança ou com a "
        "finalidade do espaço.",
    ]),
    ("8. RESPONSABILIDADE PROFISSIONAL", [
        "8.1. A LifeMax disponibiliza infraestrutura física e serviços de apoio, não sendo "
        "responsável pela atuação técnica, clínica ou profissional realizada pelo usuário.",
        "8.2. O profissional será exclusivamente responsável por seus atendimentos, "
        "diagnósticos, prescrições, procedimentos, orientações, documentos emitidos e demais "
        "atos praticados no exercício de sua profissão.",
        "8.3. O profissional deverá manter válidos seus registros profissionais, licenças, "
        "autorizações e demais documentos necessários ao exercício de sua atividade.",
        "8.4. A LifeMax não estabelece, interfere ou se responsabiliza pela relação "
        "médico-paciente ou pela relação entre o profissional e seus clientes/pacientes.",
    ]),
    ("9. CONSERVAÇÃO, ORGANIZAÇÃO E USO DOS ESPAÇOS", [
        "9.1. O profissional deverá utilizar os consultórios com zelo, cuidado e "
        "responsabilidade.",
        "9.2. O ambiente deverá ser deixado em condições adequadas de organização e "
        "conservação após sua utilização.",
        "9.3. O profissional será responsável por danos causados por ele, seus pacientes, "
        "acompanhantes, funcionários, prestadores ou quaisquer pessoas que estejam no local "
        "sob sua responsabilidade.",
        "9.4. Eventuais danos ao mobiliário, equipamentos, instalações ou demais bens da "
        "LifeMax poderão ser cobrados do responsável.",
    ]),
    ("10. RELACIONAMENTO E CONVIVÊNCIA", [
        "10.1. A LifeMax busca proporcionar um ambiente profissional, respeitoso e cordial "
        "entre profissionais, pacientes, funcionários, secretárias, recepcionistas e demais "
        "usuários.",
        "10.2. O profissional deverá manter comportamento respeitoso e adequado com todos os "
        "colaboradores e prestadores da LifeMax.",
        "10.3. Não serão tolerados:",
        {"bullets": [
            "agressões verbais ou físicas;",
            "ameaças, intimidações ou constrangimentos;",
            "tratamento desrespeitoso ou ofensivo;",
            "atitudes discriminatórias;",
            "discussões ou conflitos que prejudiquem o funcionamento do ambiente;",
            "assédio de qualquer natureza;",
            "utilização de linguagem ou comportamento incompatível com um ambiente "
            "profissional.",
        ]},
        "10.4. Eventuais divergências deverão ser tratadas de forma respeitosa e encaminhadas "
        "à administração da LifeMax para avaliação e solução.",
        "10.5. As secretárias, recepcionistas e demais colaboradores da LifeMax deverão ser "
        "tratados com cordialidade e respeito, não sendo permitido exigir, de forma abusiva, "
        "tarefas ou serviços que não estejam incluídos na contratação realizada pelo "
        "profissional.",
        "10.6. A LifeMax poderá adotar medidas administrativas em caso de comportamento "
        "inadequado, inclusive suspensão ou encerramento do acesso à plataforma, observadas as "
        "circunstâncias do caso.",
    ]),
    ("11. SERVIÇOS ADICIONAIS", [
        "11.1. A LifeMax poderá disponibilizar ao profissional serviços adicionais, "
        "contratados separadamente dos créditos de utilização dos consultórios.",
        "11.2. Entre os serviços adicionais poderão estar disponíveis, conforme oferta "
        "vigente:",
        {"bullets": [
            "Agenda profissional;",
            "Prontuário eletrônico;",
            "Prontuário eletrônico com recursos de Inteligência Artificial (IA);",
            "Agenda integrada com prontuário;",
            "Assistente de Inteligência Artificial através do WhatsApp;",
            "outros serviços tecnológicos, administrativos ou de suporte que venham a ser "
            "disponibilizados pela LifeMax.",
        ]},
        "11.3. A contratação desses serviços será opcional e poderá possuir cobrança, "
        "condições, limites e regras próprias, apresentadas ao profissional antes da "
        "contratação.",
        "11.4. A contratação ou não contratação dos serviços adicionais não altera as regras "
        "de utilização dos consultórios por horas.",
    ]),
    ("12. SISTEMA E PLATAFORMA DIGITAL", [
        "12.1. O profissional é responsável pela guarda de suas credenciais de acesso à "
        "plataforma.",
        "12.2. O login e a senha são pessoais e não deverão ser compartilhados com terceiros.",
        "12.3. O profissional será responsável pelas operações realizadas mediante sua conta, "
        "ressalvadas situações comprovadas de acesso indevido decorrente de falha da "
        "plataforma.",
        "12.4. A LifeMax poderá realizar atualizações, manutenções e modificações na "
        "plataforma visando melhorar sua segurança, funcionamento e funcionalidades.",
    ]),
    ("13. ALTERAÇÃO DAS REGRAS DE RESERVA", [
        "13.1. A LifeMax poderá alterar, atualizar, complementar ou modificar as regras de "
        "utilização e reserva dos consultórios, sempre que entender necessário para melhorar a "
        "operação, disponibilidade dos espaços, segurança, organização ou experiência dos "
        "usuários.",
        "13.2. As novas regras serão disponibilizadas na plataforma e passarão a reger as "
        "reservas realizadas após sua entrada em vigor, respeitados os direitos já "
        "constituídos e as disposições legais aplicáveis.",
        "13.3. Sempre que houver alteração relevante das condições de utilização, a LifeMax "
        "poderá disponibilizar aviso ao usuário através da plataforma ou dos canais de "
        "comunicação cadastrados.",
    ]),
    ("14. SUSPENSÃO OU ENCERRAMENTO DO ACESSO", [
        "14.1. A LifeMax poderá suspender temporariamente o acesso do profissional à "
        "plataforma ou aos consultórios em situações que envolvam, entre outras:",
        {"bullets": [
            "saldo negativo ou débitos pendentes;",
            "descumprimento deste contrato;",
            "utilização inadequada das instalações;",
            "realização de procedimento não autorizado;",
            "comportamento inadequado ou desrespeitoso;",
            "utilização da plataforma para finalidade ilícita;",
            "risco à segurança de pacientes, profissionais, funcionários ou terceiros.",
        ]},
        "14.2. Em situações graves, a LifeMax poderá encerrar a relação contratual, observadas "
        "as disposições legais aplicáveis.",
    ]),
    ("15. RESPONSABILIDADE PELOS PACIENTES E ACOMPANHANTES", [
        "15.1. O profissional será responsável pela orientação de seus pacientes e "
        "acompanhantes quanto às regras de utilização do espaço.",
        "15.2. O profissional deverá zelar para que seus pacientes e acompanhantes mantenham "
        "comportamento adequado e respeitoso nas dependências da LifeMax.",
        "15.3. Danos causados por pacientes ou acompanhantes poderão ser atribuídos ao "
        "profissional responsável pelo atendimento, sem prejuízo do direito de a LifeMax "
        "buscar diretamente o responsável pelo dano.",
    ]),
    ("16. COMUNICAÇÕES", [
        "16.1. As comunicações relacionadas à utilização da plataforma, reservas, saldo, "
        "pagamentos, alterações de regras e demais assuntos operacionais poderão ser "
        "realizadas através do próprio sistema, e-mail, WhatsApp ou outros canais "
        "disponibilizados pela LifeMax.",
        "16.2. O profissional deverá manter seus dados de contato atualizados na plataforma.",
    ]),
    ("17. ACEITE E VIGÊNCIA", [
        "17.1. O presente contrato entra em vigor a partir do aceite eletrônico realizado pelo "
        "profissional.",
        "17.2. O aceite será registrado eletronicamente pela plataforma, juntamente com os "
        "dados necessários para comprovação da manifestação de vontade do usuário.",
        "17.3. O presente contrato permanecerá vigente enquanto o profissional utilizar os "
        "serviços da LifeMax, sem prejuízo das obrigações que, por sua natureza, permaneçam "
        "aplicáveis após o encerramento da utilização.",
    ]),
    ("18. DISPOSIÇÕES GERAIS", [
        "18.1. O profissional declara ter lido integralmente este contrato antes de realizar o "
        "aceite eletrônico.",
        "18.2. A utilização da plataforma e a realização de reservas representam concordância "
        "com as regras vigentes na data da utilização.",
        "18.3. Caso alguma disposição deste contrato seja considerada inválida ou inexigível, "
        "as demais disposições permanecerão válidas, na medida permitida pela legislação "
        "aplicável.",
        "18.4. Este contrato deverá ser interpretado em conjunto com as informações, condições "
        "comerciais e regras disponibilizadas na plataforma LifeMax.",
        "18.5. O profissional declara estar ciente de que a LifeMax fornece infraestrutura e "
        "serviços de apoio, não substituindo as obrigações, responsabilidades técnicas e "
        "legais inerentes ao exercício de sua profissão.",
    ]),
]

# Declarações do bloco final "ACEITE DIGITAL" do contrato -- viram
# checkboxes marcados (✓) tanto na tela de aceite quanto no PDF baixado
# depois, já que quem chegou a ver essas duas telas necessariamente já
# concordou com todas elas.
CONTRATO_DECLARACOES = [
    "Li e concordo integralmente com o Contrato Digital de Utilização de Consultórios por "
    "Horas, Serviços e Regras de Reserva da LifeMax.",
    "Estou ciente de que a compra mínima de créditos é de 6 (seis) horas.",
    "Estou ciente de que cada reserva possui duração mínima de 1 (uma) hora e que a hora "
    "reservada será contabilizada integralmente, ainda que não seja utilizada em sua "
    "totalidade.",
    "Estou ciente de que as reservas devem ser realizadas através da plataforma LifeMax, "
    "mediante login.",
    "Estou ciente de que não poderei realizar novas reservas enquanto meu saldo estiver "
    "negativo.",
    "Estou ciente do prazo de 12 (doze) horas para cancelamento de reservas e de que, após "
    "esse prazo, a reserva será contabilizada.",
    "Estou ciente de que os consultórios não podem ser utilizados para cirurgias ou "
    "procedimentos incompatíveis com a estrutura disponibilizada.",
    "Estou ciente das normas de convivência, respeito e relacionamento profissional "
    "estabelecidas neste contrato.",
    "Estou ciente de que serviços como agenda, prontuário, recursos de IA e assistente de IA "
    "via WhatsApp poderão ser contratados separadamente.",
    "Estou ciente de que a LifeMax poderá alterar suas regras de reserva e utilização, nos "
    "termos deste contrato e da legislação aplicável.",
]
