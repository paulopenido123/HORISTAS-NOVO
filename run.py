import sys

# Corrigido em 10/09/2026: no Windows, o print() às vezes usa uma
# codificação limitada (cp1252) em vez de UTF-8 -- principalmente quando o
# processo é capturado por outro programa, como o painel.py faz ao rodar
# esse arquivo. Qualquer emoji ou caractere fora do alfabeto ocidental
# básico (ex: 👋, usado num aviso de "novo médico cadastrado") faz o
# print() explodir com UnicodeEncodeError -- e como isso acontecia DENTRO
# do tratamento de uma requisição, a requisição inteira quebrava com erro
# 500 (aconteceu de verdade testando o /primeiro-acesso em produção).
# Forçar UTF-8 aqui, bem no início, antes de qualquer print() rodar,
# resolve de vez -- não só esse caso, qualquer print() futuro com emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import os
from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    # Em produção (Render, etc), a porta vem de uma variável de ambiente
    # chamada PORT — o serviço de hospedagem decide qual porta usar, a
    # gente só precisa "escutar" a que ele mandar. Localmente, sem essa
    # variável configurada, continua usando 5000 como sempre.
    porta = int(os.environ.get("PORT", 5000))

    # DEBUG=true só localmente (no seu computador) — em produção, deixa
    # sempre "false" (ou simplesmente não configura essa variável lá).
    modo_debug = os.environ.get("DEBUG", "false").lower() == "true"

    # socketio.run() no lugar de app.run() — este pacote não tem
    # videoconferência (isso ficou no sistema maior), mas Flask-SocketIO
    # já está registrado no app factory (app/extensions.py) e é usado por
    # agenda_fixos_service.py, então precisa do socketio.run() para o
    # WebSocket funcionar corretamente.
    socketio.run(app, host="0.0.0.0", port=porta, debug=modo_debug, allow_unsafe_werkzeug=True)
