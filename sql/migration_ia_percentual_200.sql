-- Ajusta o percentual de aumento cobrado sobre o custo real da IA para
-- 200% (pedido do Paulo em 21/09/2026, junto com a recriação da compra
-- de créditos de IA): cobrar 200% em cima do que o GPT/Luna custou de
-- verdade, ou seja, 3x o custo real (1 + 200/100). O valor anterior era
-- o default de migration_ia_precos.sql (400 = 5x). A partir daqui isso
-- também fica editável na tela admin "Controle de IA" (ver
-- app/routes/admin.py / app/templates/admin_controle_ia.html), então
-- essa atualização aqui é só o ponto de partida -- o Paulo pode mudar
-- de novo a qualquer momento pela tela, sem precisar rodar SQL.
update precos set ia_percentual_aumento = 200;
