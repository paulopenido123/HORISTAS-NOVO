"""
Painel de Controle — Lifemax Reserva por Hora

Interface gráfica com todos os botões para configurar, instalar e rodar
o sistema, sem precisar digitar comandos no terminal — mesmo padrão do
painel.py do sistema maior da Lifemax (Assistente de WhatsApp).

Para abrir: dê dois cliques neste arquivo (se o Python estiver associado
a arquivos .py) ou rode `python painel.py` uma única vez pra abrir a
janela — depois disso, tudo é clique de botão.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import sys
import os
import threading
import queue
import webbrowser
import platform
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
README_PATHS = [BASE_DIR / "README_PRODUCAO.md", BASE_DIR / "INSTALAR.md", BASE_DIR / "INFORME.md"]

# Campos do .env, organizados por grupo, com rótulo amigável e se é
# sensível (mostrado como ••• na tela). Só os grupos que este pacote
# (Reserva por Hora) realmente usa -- ver INFORME.md para o que não
# está incluído aqui.
CAMPOS_ENV = [
    ("Banco de dados — Neon (obrigatório)", [
        ("DATABASE_URL", "Connection string do Neon (Neon Console > seu projeto > Connect)", True),
    ]),
    ("Fotos dos consultórios — Neon Object Storage (opcional, mas recomendado)", [
        ("NEON_S3_ENDPOINT_URL", "S3 endpoint (Neon Console > Object Storage)", False),
        ("NEON_S3_REGION", "Região do projeto (ex: us-east-2)", False),
        ("NEON_S3_ACCESS_KEY_ID", "Access Key ID (Object Storage > Credentials)", True),
        ("NEON_S3_SECRET_ACCESS_KEY", "Secret Access Key (Object Storage > Credentials)", True),
        ("NEON_S3_BUCKET", "Nome do bucket (o que você criou, ex: lifemax-reserva-horas)", False),
    ]),
    ("Painel administrativo e sessão (obrigatório)", [
        ("ADMIN_PASSWORD", "Senha do painel /admin (você escolhe)", True),
        ("FLASK_SECRET_KEY", "Chave de sessão (você escolhe, bem aleatória)", True),
        ("ADMIN_PHONE", "Seu telefone, para alertas (opcional)", False),
    ]),
    ("Asaas (PIX/cartão) — para os médicos comprarem créditos", [
        ("ASAAS_API_KEY", "Chave de API do Asaas", True),
        ("ASAAS_ENV", "Ambiente: 'sandbox' (teste) ou 'production'", False),
        ("ASAAS_WEBHOOK_TOKEN", "Token do webhook (você escolhe)", True),
    ]),
    ("E-mail (SMTP) — avisa a recepção quando um médico reserva", [
        ("SMTP_HOST", "Servidor SMTP", False),
        ("SMTP_PORT", "Porta", False),
        ("SMTP_USER", "Usuário / e-mail", False),
        ("SMTP_PASSWORD", "Senha (ou senha de app)", True),
        ("EMAIL_FROM", "E-mail remetente", False),
    ]),
    ("Login com Google (opcional)", [
        ("GOOGLE_CLIENT_ID", "Client ID (Google Cloud Console)", False),
        ("GOOGLE_CLIENT_SECRET", "Client Secret", True),
        ("GOOGLE_LOGIN_REDIRECT_URI", "URL de redirecionamento do login (ex: https://SEU-DOMINIO/login/google/callback)", False),
    ]),
    ("Segurança do servidor", [
        ("FORCE_HTTPS_COOKIES", "'true' quando estiver no ar com HTTPS de verdade; 'false' enquanto testa local", False),
    ]),
]

DEFAULTS = {
    "ASAAS_ENV": "sandbox",
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "FORCE_HTTPS_COOKIES": "false",
    "NEON_S3_REGION": "us-east-2",
    "NEON_S3_BUCKET": "lifemax-reserva-horas",
}


def ler_env_existente() -> dict:
    valores = {}
    if ENV_PATH.exists():
        for linha in ENV_PATH.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip()
    return valores


def abrir_no_sistema(caminho_ou_url: str):
    sistema = platform.system()
    try:
        if str(caminho_ou_url).startswith("http"):
            webbrowser.open(caminho_ou_url)
        elif sistema == "Windows":
            os.startfile(caminho_ou_url)  # noqa
        elif sistema == "Darwin":
            subprocess.Popen(["open", caminho_ou_url])
        else:
            subprocess.Popen(["xdg-open", caminho_ou_url])
    except Exception as e:
        messagebox.showerror("Erro ao abrir", str(e))


class JanelaConfiguracao(tk.Toplevel):
    """Formulário para preencher o .env sem editar arquivo na mão."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Configurar credenciais (.env)")
        self.geometry("560x600")
        self.entradas = {}

        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        frame_scroll = ttk.Frame(canvas)
        frame_scroll.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame_scroll, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        valores_atuais = ler_env_existente()

        for grupo, campos in CAMPOS_ENV:
            titulo = ttk.Label(frame_scroll, text=grupo, font=("Segoe UI", 11, "bold"))
            titulo.pack(anchor="w", pady=(14, 4))

            for chave, rotulo, sensivel in campos:
                ttk.Label(frame_scroll, text=rotulo, font=("Segoe UI", 9)).pack(anchor="w")
                entrada = ttk.Entry(frame_scroll, width=60, show="•" if sensivel else "")
                valor_inicial = valores_atuais.get(chave, DEFAULTS.get(chave, ""))
                entrada.insert(0, valor_inicial)
                entrada.pack(anchor="w", pady=(0, 8))
                self.entradas[chave] = entrada

        rodape = ttk.Frame(self, padding=(16, 8))
        rodape.pack(fill="x")
        ttk.Button(rodape, text="Salvar", command=self.salvar).pack(side="right", padx=4)
        ttk.Button(rodape, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Label(
            rodape,
            text="Banco de dados (Neon) e Admin são obrigatórios para o sistema subir.",
            font=("Segoe UI", 8), foreground="#666",
        ).pack(side="left")

    def salvar(self):
        linhas = ["# Gerado pelo Painel de Controle — Lifemax Reserva por Hora\n"]
        for grupo, campos in CAMPOS_ENV:
            linhas.append(f"\n# --- {grupo} ---")
            for chave, _, _ in campos:
                valor = self.entradas[chave].get().strip()
                linhas.append(f"{chave}={valor}")
        ENV_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        messagebox.showinfo("Salvo", "Credenciais salvas em .env com sucesso.")
        self.destroy()


class PainelApp:
    def __init__(self, root):
        self.root = root
        root.title("Painel de Controle — Lifemax Reserva por Hora")
        root.geometry("620x640")

        self.processo_servidor = None
        self.fila_log = queue.Queue()
        self.todos_botoes = []
        self.operacao_em_andamento = False

        self._montar_interface()
        self.root.after(200, self._checar_fila_log)
        self.root.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # ---------- Interface ----------

    def _montar_interface(self):
        titulo = ttk.Label(self.root, text="Lifemax — Reserva por Hora",
                            font=("Segoe UI", 15, "bold"))
        titulo.pack(pady=(14, 0))
        subtitulo = ttk.Label(self.root, text="Reserva de consultório por hora/turno · Créditos via PIX/cartão · Painel Admin",
                               font=("Segoe UI", 9), foreground="#666")
        subtitulo.pack(pady=(0, 10))

        self._secao("1. Configuração", [
            ("⚙️  Configurar credenciais (.env)", self.abrir_configuracao),
            ("📦  Instalar dependências", self.instalar_dependencias),
        ])

        self._secao("2. Servidor", [
            ("▶️  Iniciar servidor", self.iniciar_servidor),
            ("⏹  Parar servidor", self.parar_servidor),
            ("🏠  Abrir página inicial", lambda: self.abrir_pagina("/")),
            ("🔑  Abrir Login do médico", lambda: self.abrir_pagina("/login")),
            ("🆕  Abrir Primeiro acesso", lambda: self.abrir_pagina("/primeiro-acesso")),
            ("🏢  Abrir Vitrine pública de consultórios", lambda: self.abrir_pagina("/consultorios")),
        ])

        self._secao("3. Painel administrativo", [
            ("🔐  Abrir login do Admin", lambda: self.abrir_pagina("/admin/login")),
            ("📊  Abrir Dashboard Admin", lambda: self.abrir_pagina("/admin")),
            ("🏥  Gerenciar Consultórios", lambda: self.abrir_pagina("/admin/consultorios")),
            ("🗓️  Abrir Matriz de Agendamento", lambda: self.abrir_pagina("/admin/matriz")),
        ])

        self._secao("Ajuda", [
            ("📖  Abrir instruções (README_PRODUCAO)", lambda: abrir_no_sistema(str(BASE_DIR / "README_PRODUCAO.md"))),
            ("🛠️  Abrir guia de instalação (INSTALAR)", lambda: abrir_no_sistema(str(BASE_DIR / "INSTALAR.md"))),
            ("📁  Abrir pasta do projeto", lambda: abrir_no_sistema(str(BASE_DIR))),
        ])

        self.status_var = tk.StringVar(value="Nenhum servidor rodando.")
        ttk.Label(self.root, textvariable=self.status_var, font=("Segoe UI", 9, "italic"),
                  foreground="#0a6").pack(pady=(6, 0))

        self.aviso_ocupado_var = tk.StringVar(value="")
        self.label_aviso_ocupado = tk.Label(
            self.root, textvariable=self.aviso_ocupado_var, font=("Segoe UI", 10, "bold"),
            bg="#fff4e0", fg="#7a4c00", pady=6,
        )

        self.label_log_titulo = ttk.Label(self.root, text="Log de atividade:", font=("Segoe UI", 9, "bold"))
        self.label_log_titulo.pack(anchor="w", padx=16, pady=(12, 2))
        self.log = scrolledtext.ScrolledText(self.root, height=10, state="disabled",
                                              font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True, padx=16, pady=(0, 14))

    def _secao(self, titulo, botoes):
        frame = ttk.LabelFrame(self.root, text=titulo, padding=10)
        frame.pack(fill="x", padx=16, pady=6)
        for i, (texto, comando) in enumerate(botoes):
            botao = ttk.Button(frame, text=texto, command=comando)
            botao.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=3)
            self.todos_botoes.append(botao)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _log_msg(self, texto):
        self.fila_log.put(texto)

    def _checar_fila_log(self):
        try:
            while True:
                linha = self.fila_log.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", linha + "\n")
                self.log.configure(state="disabled")
                self.log.see("end")
        except queue.Empty:
            pass
        self.root.after(200, self._checar_fila_log)

    # ---------- Travar/destravar botões durante operações demoradas ----------

    def _travar_interface(self, mensagem_aviso):
        self.operacao_em_andamento = True
        for botao in self.todos_botoes:
            botao.configure(state="disabled")
        self.aviso_ocupado_var.set(f"⏳ {mensagem_aviso} — aguarde, os botões voltam a funcionar sozinhos quando terminar.")
        self.label_aviso_ocupado.pack(fill="x", padx=16, pady=(4, 0), before=self.label_log_titulo)

    def _destravar_interface(self):
        self.operacao_em_andamento = False
        for botao in self.todos_botoes:
            botao.configure(state="normal")
        self.label_aviso_ocupado.pack_forget()
        self.aviso_ocupado_var.set("")

    def _executar_em_segundo_plano(self, mensagem_aviso, funcao_trabalho, ao_terminar=None):
        if self.operacao_em_andamento:
            messagebox.showinfo("Aguarde", "Já tem uma operação em andamento. Espere terminar antes de iniciar outra.")
            return

        self._travar_interface(mensagem_aviso)

        def rodar():
            sucesso = False
            try:
                sucesso = funcao_trabalho()
            except Exception as e:
                self._log_msg(f"❌ Erro inesperado: {e}")
            finally:
                self.root.after(0, self._destravar_interface)
                if ao_terminar:
                    self.root.after(0, lambda: ao_terminar(sucesso))

        threading.Thread(target=rodar, daemon=True).start()

    # ---------- Ações ----------

    def abrir_configuracao(self):
        JanelaConfiguracao(self.root)

    def _garantir_pip(self) -> bool:
        """
        Alguns Pythons no Windows (principalmente instalados pela Microsoft
        Store, ou versões muito novas como a 3.14 logo depois do
        lançamento) vêm SEM o módulo pip -- `python -m pip install ...`
        falha com "No module named pip" antes mesmo de tentar baixar
        qualquer pacote. Em vez de pedir pra pessoa digitar um comando no
        terminal pra resolver isso, o painel tenta consertar sozinho aqui:
        primeiro com `python -m ensurepip` (vem embutido no próprio
        Python), e se isso também não existir, baixando o instalador
        oficial do pip (get-pip.py) e rodando ele.
        """
        checagem = subprocess.run(
            [sys.executable, "-m", "pip", "--version"], capture_output=True,
            text=True, encoding="utf-8", errors="replace"
        )
        if checagem.returncode == 0:
            return True  # pip já funciona, nada a fazer

        self._log_msg("O Python instalado nesse computador não tem o pip -- tentando instalar "
                       "ele automaticamente (isso é normal em instalações novas do Windows)...")

        tentativa = subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True,
            text=True, encoding="utf-8", errors="replace"
        )
        self._log_msg((tentativa.stdout + tentativa.stderr)[-1500:])
        if tentativa.returncode == 0:
            self._log_msg("✅ pip instalado via ensurepip.")
            return True

        self._log_msg("ensurepip não funcionou -- baixando o instalador oficial do pip "
                       "(bootstrap.pypa.io)...")
        try:
            import urllib.request
            get_pip_path = BASE_DIR / "_get-pip.py"
            urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip_path)
            tentativa2 = subprocess.run(
                [sys.executable, str(get_pip_path)], capture_output=True,
                text=True, encoding="utf-8", errors="replace"
            )
            self._log_msg((tentativa2.stdout + tentativa2.stderr)[-1500:])
            get_pip_path.unlink(missing_ok=True)
            if tentativa2.returncode == 0:
                self._log_msg("✅ pip instalado via get-pip.py.")
                return True
        except Exception as e:
            self._log_msg(f"Não consegui baixar/instalar o pip automaticamente: {e}")

        self._log_msg(
            "❌ Não foi possível instalar o pip automaticamente. Abra o Prompt de Comando "
            f"e rode manualmente: \"{sys.executable}\" -m ensurepip --upgrade"
        )
        return False

    def instalar_dependencias(self):
        self._log_msg("Instalando dependências (isso pode levar um minuto)...")

        def rodar():
            if not self._garantir_pip():
                return False

            comando = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
            resultado = subprocess.run(comando, cwd=BASE_DIR, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace")
            saida = resultado.stdout + resultado.stderr

            if resultado.returncode != 0 and "externally-managed-environment" in saida:
                self._log_msg("Tentando novamente com --break-system-packages...")
                comando.append("--break-system-packages")
                resultado = subprocess.run(comando, cwd=BASE_DIR, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace")
                saida = resultado.stdout + resultado.stderr

            self._log_msg(saida[-2000:])
            if resultado.returncode == 0:
                self._log_msg("✅ Dependências instaladas com sucesso.")
                return True
            else:
                self._log_msg("❌ Erro ao instalar dependências — veja o log acima.")
                return False

        def ao_terminar(sucesso):
            if sucesso:
                messagebox.showinfo("Concluído", "✅ Dependências instaladas com sucesso!\n\nOs botões já estão liberados de novo.")
            else:
                messagebox.showerror("Erro", "❌ Algo deu errado ao instalar as dependências.\n\nConfira o Log de atividade para ver o motivo exato.")

        self._executar_em_segundo_plano("Instalando dependências", rodar, ao_terminar)

    def iniciar_servidor(self):
        if not ENV_PATH.exists():
            messagebox.showwarning(
                "Configuração necessária",
                "Configure as credenciais primeiro (botão 'Configurar credenciais').\n\n"
                "No mínimo, a Connection string do Neon, Senha do Admin e Chave de sessão "
                "precisam estar preenchidos — sem isso o servidor recusa iniciar (de propósito, "
                "por segurança)."
            )
            return
        if self.processo_servidor:
            messagebox.showinfo("Já rodando", "Já existe um servidor rodando. Pare-o antes de iniciar outro.")
            return

        comando = [sys.executable, "run.py"]
        self._log_msg("Iniciando servidor...")
        try:
            self.processo_servidor = subprocess.Popen(
                comando, cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except Exception as e:
            self._log_msg(f"❌ Erro ao iniciar: {e}")
            self.processo_servidor = None
            return

        self.status_var.set("Servidor rodando — http://localhost:5000")

        def ler_saida():
            for linha in self.processo_servidor.stdout:
                self._log_msg(linha.rstrip())
            # se o processo morreu sozinho (ex: RuntimeError do Config.validate()
            # por falta de variável obrigatória), destrava a tela pra tentar de novo
            if self.processo_servidor is not None:
                self.root.after(0, self._servidor_caiu)

        threading.Thread(target=ler_saida, daemon=True).start()
        threading.Timer(2.5, lambda: abrir_no_sistema("http://localhost:5000/")).start()

    def _servidor_caiu(self):
        if self.processo_servidor is not None:
            self.processo_servidor = None
            self.status_var.set("Servidor parou (veja o Log de atividade — provavelmente falta configurar alguma variável no .env).")

    def parar_servidor(self):
        if not self.processo_servidor:
            messagebox.showinfo("Nada rodando", "Nenhum servidor está rodando no momento.")
            return
        self.processo_servidor.terminate()
        self._log_msg("Servidor parado.")
        self.processo_servidor = None
        self.status_var.set("Nenhum servidor rodando.")

    def abrir_pagina(self, caminho):
        if not self.processo_servidor:
            resposta = messagebox.askyesno(
                "Servidor não iniciado",
                "Nenhum servidor está rodando ainda. Iniciar o servidor agora?"
            )
            if resposta:
                self.iniciar_servidor()
                threading.Timer(2.5, lambda: abrir_no_sistema(f"http://localhost:5000{caminho}")).start()
            return
        abrir_no_sistema(f"http://localhost:5000{caminho}")

    def _ao_fechar(self):
        if self.processo_servidor:
            self.processo_servidor.terminate()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = PainelApp(root)
    root.mainloop()
