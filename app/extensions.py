"""
Instâncias das extensões do Flask, isoladas aqui (em vez de dentro de
app/__init__.py) para evitar import circular: as rotas precisam
importar `limiter` para usar o decorator @limiter.limit(...), e
app/__init__.py precisa importar as rotas — se `limiter` também
morasse em app/__init__.py, isso criaria um ciclo de import.
"""
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect

socketio = SocketIO(async_mode="threading", cors_allowed_origins="*")
limiter = Limiter(key_func=get_remote_address, default_limits=[])
csrf = CSRFProtect()
