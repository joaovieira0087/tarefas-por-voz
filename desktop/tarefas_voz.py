"""
Tarefas por Voz — app do computador (Windows)

Aperte Ctrl+Alt+J (ou o atalho do config.json), fale a tarefa (ou digite),
responda "para quando" e "descrição" se ele perguntar, e pronto:
a tarefa é criada e você recebe um e-mail.

Durante a conversa:  "voltar" = pergunta anterior  ·  "cancelar" = desiste

Teste sem microfone (cria a tarefa de verdade):
    python tarefas_voz.py --teste "comprar pão" "amanhã" "não"
"""
import unicodedata
import json
import logging
import math
import os
import queue
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_CONFIG = os.path.join(PASTA, "config.json")
ARQ_LOG = os.path.join(PASTA, "tarefas_voz.log")

logging.basicConfig(
    filename=ARQ_LOG, level=logging.INFO, encoding="utf-8",
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("tarefas_voz")

# Com "pyw" não existe terminal; algumas bibliotecas quebram ao tentar escrever nele.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# Modelo pequeno de português do Vosk (texto ao vivo), baixado na 1ª vez
VOSK_MODELO = "vosk-model-small-pt-0.3"
VOSK_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODELO}.zip"


# ----------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------
NOME_APP = "Tarefas por Voz"

PADRAO = {
    "url": "",
    "chave": "",
    "atalho": "<ctrl>+<alt>+j",
    "voz_ligada": True,       # fala as respostas em voz alta
    "ouvir_ligado": True,     # abre já ouvindo o microfone
    "idioma": "pt-BR",
    "microfone": None,        # None = padrão do Windows; ou o número/nome do testar_microfone
    "sensibilidade": 1.0,     # aumente (ex.: 2.0) se ele não perceber sua voz
    "pausa_fim_segundos": 4.5,  # quanto tempo calado ele espera antes de seguir
    "texto_ao_vivo": True,    # mostra as palavras enquanto você fala (Vosk, offline)
}


def carregar_config():
    cfg = dict(PADRAO)
    if os.path.exists(ARQ_CONFIG):
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def normalizar(texto):
    """minúsculas, sem acento e sem pontuação"""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in t).split())


PALAVRAS_VOLTAR = {"voltar", "volta", "volte", "anterior", "pergunta anterior", "voltar pergunta",
                   "voltar uma", "voltar etapa", "corrigir", "quero voltar"}
PALAVRAS_CANCELAR = {"cancelar", "cancela", "cancele", "cancelado", "esquece", "esqueca", "desistir",
                     "desisto", "deixa pra la", "nao quero mais", "aborta", "abortar", "cancelar tarefa"}


def comando_especial(texto):
    """Devolve 'voltar', 'cancelar' ou None."""
    n = normalizar(texto)
    if n in PALAVRAS_VOLTAR:
        return "voltar"
    if n in PALAVRAS_CANCELAR:
        return "cancelar"
    return None


# ----------------------------------------------------------------
# Conversa com o servidor (Google Apps Script)
# ----------------------------------------------------------------
def chamar_servidor(cfg, acao, texto, descricao=None, **extras):
    corpo = {"chave": cfg["chave"], "acao": acao, "texto": texto}
    if descricao is not None:
        corpo["descricao"] = descricao
    corpo.update(extras)
    req = urllib.request.Request(
        cfg["url"], data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        # O Google responde com um redirecionamento; o urllib segue sozinho.
        with urllib.request.urlopen(req, timeout=40) as r:
            bruto = r.read().decode("utf-8")
        return json.loads(bruto)
    except urllib.error.HTTPError as e:
        log.exception("HTTP %s", e.code)
        return {"ok": False, "status": "erro", "falar": f"O servidor respondeu com erro {e.code}."}
    except urllib.error.URLError:
        log.exception("Sem conexão")
        return {"ok": False, "status": "erro", "falar": "Não consegui falar com o servidor. Confira a internet e a URL."}
    except json.JSONDecodeError:
        log.error("Resposta não-JSON: %s", bruto[:300])
        return {"ok": False, "status": "erro",
                "falar": "O servidor não respondeu direito. Confira se a implantação está como 'Qualquer pessoa'."}


# ----------------------------------------------------------------
# Voz (falar em voz alta) — usa as vozes do próprio Windows
# ----------------------------------------------------------------
class Voz:
    def __init__(self, ligada=True):
        self.ligada = ligada
        self.fila = queue.Queue()
        if ligada:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        motor = None
        try:
            try:
                import comtypes  # necessário para usar a voz fora da thread principal
                comtypes.CoInitialize()
            except Exception:
                pass
            import pyttsx3
            motor = pyttsx3.init()
            for v in motor.getProperty("voices"):
                info = f"{v.name} {v.id}".lower()
                if "pt-br" in info or "portuguese" in info or "brazil" in info or "maria" in info:
                    motor.setProperty("voice", v.id)
                    break
            motor.setProperty("rate", 195)
        except Exception:
            log.exception("Voz indisponível")
            motor = None
        while True:
            texto, pronto = self.fila.get()
            try:
                if motor:
                    motor.say(texto)
                    motor.runAndWait()
            except Exception:
                log.exception("Erro ao falar")
            finally:
                pronto.set()

    def falar(self, texto, esperar=True):
        if not self.ligada or not texto:
            return
        pronto = threading.Event()
        self.fila.put((texto, pronto))
        if esperar:
            pronto.wait(timeout=30)


# ----------------------------------------------------------------
# Ouvido (microfone -> texto), grátis via reconhecimento do Google
# ----------------------------------------------------------------
def achar_microfone(escolha):
    """escolha: None (padrão do Windows), número do dispositivo, ou parte do nome."""
    if escolha in (None, "", "padrao"):
        return None
    import sounddevice as sd
    if isinstance(escolha, int) or str(escolha).isdigit():
        return int(escolha)
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and str(escolha).lower() in d["name"].lower():
            return i
    log.warning("Microfone '%s' não encontrado, usando o padrão", escolha)
    return None


class Ouvido:
    TAXA = 16000
    BLOCO = 0.1  # segundos

    def __init__(self, idioma="pt-BR", microfone=None, sensibilidade=1.0, pausa_fim=4.5):
        self.idioma = idioma
        self.microfone = microfone
        self.sensibilidade = max(0.2, float(sensibilidade or 1.0))
        self.pausa_fim = max(1.0, float(pausa_fim or 4.5))  # silêncio que conta como "terminei"
        self.modelo = None  # modelo Vosk (texto ao vivo); carregado em segundo plano

    def ouvir(self, cancelado, ao_status, ao_parcial=None, espera_max=8, fala_max=60, silencio_fim=None):
        """Grava até você parar de falar. Devolve o texto, ou None se não ouviu nada.
        ao_parcial(texto) é chamado enquanto você fala, com o texto ao vivo (Vosk)."""
        silencio_fim = silencio_fim or self.pausa_fim
        import numpy as np
        import sounddevice as sd
        import speech_recognition as sr

        n = int(self.TAXA * self.BLOCO)
        rms = lambda d: float(np.sqrt(np.mean(d.astype(np.float32) ** 2)))
        tudo, partes, antes = [], [], []
        falou, silencio, t, pico = False, 0.0, 0.0, 0.0
        dispositivo = achar_microfone(self.microfone)

        # Texto ao vivo (Vosk, offline). Se não tiver, segue sem ele.
        rec, confirmado, ultimo = None, [], [""]
        if self.modelo is not None and ao_parcial:
            try:
                from vosk import KaldiRecognizer
                rec = KaldiRecognizer(self.modelo, self.TAXA)
            except Exception:
                log.exception("Vosk indisponível")

        def alimentar(bloco):
            if rec is None:
                return
            if rec.AcceptWaveform(bloco.tobytes()):
                frase = json.loads(rec.Result()).get("text", "")
                if frase:
                    confirmado.append(frase)
                parcial = ""
            else:
                parcial = json.loads(rec.PartialResult()).get("partial", "")
            texto = " ".join(confirmado + ([parcial] if parcial else []))
            if texto != ultimo[0]:
                ultimo[0] = texto
                ao_parcial(texto)

        with sd.InputStream(samplerate=self.TAXA, channels=1, dtype="int16",
                            blocksize=n, device=dispositivo) as mic:
            ruido = [rms(mic.read(n)[0]) for _ in range(3)]  # mede o barulho do ambiente
            base = sum(ruido) / len(ruido)
            # limiar bem mais baixo que antes: microfone de notebook capta baixo
            limiar = max(60.0, base * 1.8, base + 80.0) / self.sensibilidade
            ao_status("🎤 Ouvindo... pode falar")
            while t < fala_max + espera_max:
                if cancelado():
                    return None
                bloco = mic.read(n)[0].copy()
                t += self.BLOCO
                nivel = rms(bloco)
                pico = max(pico, nivel)
                tudo.append(bloco)
                alimentar(bloco)
                if nivel > limiar:
                    if not falou:
                        partes.extend(antes)  # guarda o comecinho da fala
                    if silencio > 0.5:
                        ao_status("🎤 Ouvindo... pode falar")
                    falou, silencio = True, 0.0
                elif falou:
                    antes_seg = int(silencio)
                    silencio += self.BLOCO
                    # depois de 1s calado, mostra a contagem até finalizar
                    if silencio >= 1.0 and int(silencio) != antes_seg:
                        resta = max(1, math.ceil(silencio_fim - silencio))
                        ao_status(f"⏸️ Esperando você continuar... {resta}s")
                if falou:
                    partes.append(bloco)
                    if silencio >= silencio_fim or len(partes) * self.BLOCO >= fala_max:
                        break
                else:
                    antes = (antes + [bloco])[-4:]
                    if t >= espera_max:
                        break

        log.info("Microfone: dispositivo=%s ruido=%.0f limiar=%.0f pico=%.0f falou=%s",
                 dispositivo, base, limiar, pico, falou)
        if cancelado():
            return None
        if not falou:
            # Plano B: não detectou fala, mas manda a gravação inteira mesmo assim.
            if pico < 15:  # praticamente silêncio total = microfone errado/mudo
                raise RuntimeError("O microfone não está captando nada (volume zero). "
                                   "Rode o testar_microfone.bat para escolher o microfone certo.")
            partes = tudo
        texto_vosk = ""
        if rec is not None:
            fim = json.loads(rec.FinalResult()).get("text", "")
            texto_vosk = " ".join(confirmado + ([fim] if fim else [])).strip()
        ao_status("⏳ Entendendo...")
        audio = sr.AudioData(b"".join(p.tobytes() for p in partes), self.TAXA, 2)
        try:
            # versão final, mais precisa, pelo Google
            return sr.Recognizer().recognize_google(audio, language=self.idioma)
        except sr.UnknownValueError:
            return texto_vosk or None
        except sr.RequestError as e:
            if texto_vosk:  # sem internet: fica com o texto do Vosk
                return texto_vosk
            raise RuntimeError(f"Reconhecimento de voz indisponível ({e}).")


# ----------------------------------------------------------------
# Janela
# ----------------------------------------------------------------
class App:
    COR_FUNDO = "#1e1f24"
    COR_CARTAO = "#2a2b31"
    TITULOS = {
        "comando": "📝  Qual é a tarefa?",
        "data": "📅  Para quando?",
        "descricao": "📄  Alguma descrição?",
    }
    EXEMPLOS = {
        "comando": 'Exemplos:  "Comprar pão amanhã"   ·   "Pagar a conta de luz dia 10"   ·   "Reunião sexta às 15h"',
        "data": 'Exemplos:  "amanhã"  ·  "sexta"  ·  "dia 20"  ·  "15/12"        Enter vazio ou "sem data" = sem data',
        "descricao": 'Exemplo:  "levar a lista de compras"        Enter vazio ou "não" = salvar sem descrição',
    }
    AJUDA = {
        "comando": 'Dica: diga "cancelar" para desistir  ·  Esc fecha a janela  ·  nada é salvo até o final',
        "data": 'Dica: diga "voltar" para corrigir a tarefa  ·  "cancelar" para desistir (nada é salvo)',
        "descricao": 'Dica: diga "voltar" para a pergunta anterior  ·  "cancelar" para desistir (nada é salvo)',
    }

    def __init__(self, cfg):
        import tkinter as tk
        self.tk = tk
        self.cfg = cfg
        self.voz = Voz(cfg.get("voz_ligada", True))
        self.ouvido = Ouvido(cfg.get("idioma", "pt-BR"), cfg.get("microfone"),
                             cfg.get("sensibilidade", 1.0), cfg.get("pausa_fim_segundos", 4.5))
        self.eventos = queue.Queue()
        self.rodada = 0
        self.rodada_escuta = -1
        self.estado = "fechado"   # fechado | comando | data | descricao | aguardando | fim
        self.envio = {}           # o que já foi respondido: texto, quando, descricao
        self.campos_etapa = {}    # resumo mostrado em cada etapa (para o "voltar")

        F = self.COR_FUNDO
        self.root = tk.Tk()
        self.root.title(NOME_APP)
        self.root.configure(bg=F)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        w, h = 720, 390
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.lbl_status = tk.Label(self.root, text="", bg=F, fg="#8ab4f8",
                                   font=("Segoe UI", 15, "bold"), anchor="w")
        self.lbl_status.pack(fill="x", padx=18, pady=(14, 6))

        # Cartão com o resumo da tarefa (aparece a partir da 2ª etapa)
        self.cartao = tk.Frame(self.root, bg=self.COR_CARTAO)
        self.lbl_cartao = tk.Label(self.cartao, text="", bg=self.COR_CARTAO, fg="#e8eaed",
                                   font=("Segoe UI", 12), justify="left", anchor="w")
        self.lbl_cartao.pack(fill="x", padx=14, pady=8)

        self.lbl_info = tk.Label(self.root, text="", bg=F, fg="#e8eaed", font=("Segoe UI", 12),
                                 wraplength=680, justify="left", anchor="w")
        self.lbl_info.pack(fill="x", padx=18, pady=(6, 0))
        self.lbl_exemplo = tk.Label(self.root, text="", bg=F, fg="#9aa0a6", font=("Segoe UI", 10),
                                    wraplength=680, justify="left", anchor="w")
        self.lbl_exemplo.pack(fill="x", padx=18, pady=(2, 0))

        self.entrada = tk.Entry(self.root, font=("Segoe UI", 13), bg="#2b2c33", fg="#ffffff",
                                insertbackground="#ffffff", relief="flat")
        self.entrada.pack(fill="x", padx=18, pady=10, ipady=6)
        self.entrada.bind("<Return>", lambda e: self.enviar())
        self.entrada.bind("<Key>", self._ao_digitar)
        self.root.bind("<Escape>", lambda e: self.fechar())

        barra = tk.Frame(self.root, bg=F)
        barra.pack(fill="x", padx=18)
        estilo = dict(font=("Segoe UI", 11), relief="flat", padx=12, pady=4, cursor="hand2")
        tk.Button(barra, text="🎤 Falar", command=self.iniciar_escuta, bg="#3c4043", fg="white", **estilo).pack(side="left")
        tk.Button(barra, text="Enviar ↵", command=self.enviar, bg="#1a73e8", fg="white", **estilo).pack(side="left", padx=8)
        self.btn_voltar = tk.Button(barra, text="← Voltar", command=self.voltar, bg="#3c4043", fg="white", **estilo)
        self.btn_voltar.pack(side="left")
        # Parar execução = desliga o programa (Ctrl+Alt+J para de funcionar até abrir de novo)
        tk.Button(barra, text="⏹ Parar execução", command=self.parar, bg="#5c2b29", fg="#f6aea9",
                  font=("Segoe UI", 10), relief="flat", padx=10, pady=4, cursor="hand2").pack(side="right")
        # Sair do assistente = só fecha a janela; continua esperando o Ctrl+Alt+J
        tk.Button(barra, text="Sair do assistente (Esc)", command=self.fechar, bg="#3c4043", fg="white",
                  font=("Segoe UI", 10), relief="flat", padx=10, pady=4, cursor="hand2").pack(side="right", padx=8)

        # Rodapé: mostra se o texto ao vivo está funcionando
        self.lbl_rodape = tk.Label(self.root, text="", bg=F, fg="#80868b", font=("Segoe UI", 9), anchor="w")
        self.lbl_rodape.pack(side="bottom", fill="x", padx=18, pady=(0, 8))
        # Dica de como voltar / cancelar
        self.lbl_ajuda = tk.Label(self.root, text="", bg=F, fg="#9aa0a6", font=("Segoe UI", 9, "italic"), anchor="w")
        self.lbl_ajuda.pack(side="bottom", fill="x", padx=18, pady=(0, 2))

        self.root.withdraw()
        self.root.after(100, self._processar_eventos)
        self._registrar_atalho()
        if cfg.get("texto_ao_vivo", True):
            self.rodape("⏳ Preparando o texto ao vivo...")
            threading.Thread(target=self._carregar_vosk, daemon=True).start()
        else:
            self.rodape("⚪ Texto ao vivo desligado no config.json")

    # --- texto ao vivo (Vosk) ---
    def rodape(self, texto):
        self.lbl_rodape.config(text=texto)

    def _carregar_vosk(self):
        aviso = lambda t: self.depois(lambda: self.rodape(t))
        try:
            import vosk
        except ImportError:
            aviso("⚪ Texto ao vivo desligado: falta instalar. No terminal: py -m pip install vosk")
            return
        try:
            vosk.SetLogLevel(-1)
            pasta = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "vosk")
            destino = os.path.join(pasta, VOSK_MODELO)
            if not os.path.isdir(destino):
                os.makedirs(pasta, exist_ok=True)
                arq_zip = destino + ".zip"
                ultimo = [-1]

                def progresso(blocos, tam_bloco, total):
                    if total > 0:
                        pct = min(100, blocos * tam_bloco * 100 // total)
                        if pct // 5 != ultimo[0]:
                            ultimo[0] = pct // 5
                            aviso(f"⏳ Baixando o texto ao vivo (só na 1ª vez)... {pct}%")

                urllib.request.urlretrieve(VOSK_URL, arq_zip, reporthook=progresso)
                aviso("⏳ Descompactando o texto ao vivo...")
                import zipfile
                with zipfile.ZipFile(arq_zip) as z:
                    z.extractall(pasta)
                os.remove(arq_zip)
            aviso("⏳ Carregando o texto ao vivo...")
            self.ouvido.modelo = vosk.Model(destino)
            log.info("Vosk pronto (texto ao vivo ligado)")
            aviso("🟢 Texto ao vivo ligado")
        except Exception as e:
            log.exception("Texto ao vivo desligado (Vosk não carregou)")
            aviso(f"⚪ Texto ao vivo desligado: {e}")

    # --- utilidades de thread ---
    def depois(self, func):
        self.eventos.put(func)

    def _processar_eventos(self):
        try:
            while True:
                self.eventos.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            log.exception("Erro na janela")
        self.root.after(100, self._processar_eventos)

    def _registrar_atalho(self):
        from pynput import keyboard
        atalho = self.cfg.get("atalho", "<ctrl>+<alt>+j")
        self.ouvinte = keyboard.GlobalHotKeys({atalho: lambda: self.depois(self.abrir)})
        self.ouvinte.daemon = True
        self.ouvinte.start()
        log.info("Atalho registrado: %s", atalho)

    # --- aparência de cada etapa ---
    def status(self, texto, info=None):
        self.lbl_status.config(text=texto)
        if info is not None:
            self.lbl_info.config(text=info)

    def mostrar_etapa(self, etapa, pergunta="", campos=None):
        self.lbl_status.config(text=self.TITULOS.get(etapa, ""))
        self.lbl_info.config(text=pergunta)
        self.lbl_exemplo.config(text=self.EXEMPLOS.get(etapa, ""))
        self.lbl_ajuda.config(text=self.AJUDA.get(etapa, ""))
        self.btn_voltar.config(state=("disabled" if etapa == "comando" else "normal"))
        if etapa in ("data", "descricao"):
            self.campos_etapa[etapa] = campos
        self.mostrar_cartao(campos)

    def mostrar_cartao(self, c):
        if not c:
            self.cartao.pack_forget()
            return
        linhas = [f"📝  Tarefa:   {c.get('titulo', '')}",
                  f"📅  Data:     {c.get('dataTexto') or 'sem data'}"]
        if c.get("hora"):
            linhas.append(f"⏰  Horário:  {c['hora']}")
        if c.get("descricao"):
            linhas.append(f"📄  Descrição:  {c['descricao']}")
        self.lbl_cartao.config(text="\n".join(linhas))
        self.cartao.pack(fill="x", padx=18, pady=(0, 2), after=self.lbl_status)

    # --- fluxo ---
    def abrir(self):
        self.rodada += 1
        self.estado = "comando"
        self.envio = {}
        self.campos_etapa = {}
        self.entrada.delete(0, "end")
        self.mostrar_etapa("comando", "Fale ou digite o que você precisa fazer (e quando, se quiser).")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.entrada.focus_set()
        if self.cfg.get("ouvir_ligado", True):
            self.iniciar_escuta()

    def fechar(self):
        self.rodada += 1
        self.estado = "fechado"
        self.root.withdraw()

    def parar(self):
        from tkinter import messagebox
        self.rodada += 1  # para de ouvir enquanto pergunta
        if messagebox.askyesno(
                f"Parar o {NOME_APP}",
                "Parar a execução?\n\nO atalho de teclado só volta a funcionar quando você abrir "
                "o programa de novo (iniciar.bat ou: pyw tarefas_voz.py).",
                parent=self.root):
            log.info("Execução parada pelo usuário")
            try:
                self.ouvinte.stop()
            except Exception:
                pass
            self.root.destroy()
            os._exit(0)

    def voltar(self):
        """Volta para a pergunta anterior, sem salvar nada."""
        if self.estado not in ("data", "descricao"):
            return
        self.rodada += 1  # para de ouvir
        if self.estado == "descricao" and "quando" in self.envio:
            # tinha perguntado a data: volta para ela
            self.envio.pop("quando", None)
            self.envio.pop("descricao", None)
            self.estado = "data"
            self.entrada.delete(0, "end")
            self.mostrar_etapa("data", "Ok, voltando. Para quando é essa tarefa?", self.campos_etapa.get("data"))
            self._falar_e_ouvir("Ok. Para quando é essa tarefa?")
            return
        # volta para o começo, com o texto anterior na caixa para você corrigir
        anterior = self.envio.get("texto", "")
        self.envio = {}
        self.campos_etapa = {}
        self.estado = "comando"
        self.mostrar_etapa("comando", "Ok, voltando. Corrija o texto e aperte Enter, ou fale de novo.")
        self.entrada.delete(0, "end")
        self.entrada.insert(0, anterior)
        self.entrada.icursor("end")
        self._falar_e_ouvir("Ok. Qual é a tarefa?")

    def cancelar(self):
        """Desiste da tarefa atual (nada é salvo) e fecha a janela."""
        self.rodada += 1
        self.estado = "fim"
        self.envio = {}
        self.lbl_status.config(text="Cancelado")
        self.mostrar_cartao(None)
        self.lbl_info.config(text="Ok, cancelei. Nada foi salvo.")
        self.lbl_exemplo.config(text="")
        self.lbl_ajuda.config(text="")
        self.entrada.delete(0, "end")
        minha = self.rodada

        def fim():
            self.voz.falar("Ok, cancelei.")
            time.sleep(1.0 if self.voz.ligada else 2)
            self.depois(lambda: minha == self.rodada and self.fechar())

        threading.Thread(target=fim, daemon=True).start()

    def _ao_digitar(self, evento):
        # Começou a digitar enquanto ele ouvia: para de ouvir e deixa você escrever.
        if self.rodada_escuta == self.rodada and evento.char and evento.char.isprintable():
            self.rodada += 1
            self.entrada.config(fg="#ffffff")
            self.lbl_status.config(text="✍️  Digitando... (Enter para enviar)")

    def _mostrar_parcial(self, texto):
        self.entrada.config(fg="#9aa0a6")  # cinza = texto ao vivo (ainda não é o final)
        self.entrada.delete(0, "end")
        self.entrada.insert(0, texto)
        self.entrada.xview_moveto(1)

    def iniciar_escuta(self):
        if self.estado not in ("comando", "data", "descricao"):
            return
        self.rodada += 1
        minha = self.rodada
        self.rodada_escuta = minha
        cancelado = lambda: minha != self.rodada
        self.entrada.config(fg="#ffffff")

        def trabalho():
            texto, erro = None, None
            try:
                texto = self.ouvido.ouvir(
                    cancelado,
                    lambda s: self.depois(lambda: (not cancelado()) and self.lbl_status.config(text=s)),
                    lambda p: self.depois(lambda: (not cancelado()) and self._mostrar_parcial(p)))
            except Exception as e:
                log.exception("Erro no microfone")
                erro = str(e) or "Erro no microfone."
            self.depois(lambda: self._ao_ouvir(minha, texto, erro))

        threading.Thread(target=trabalho, daemon=True).start()

    def _ao_ouvir(self, minha, texto, erro):
        if minha != self.rodada or self.estado == "fechado":
            return
        self.rodada_escuta = -1
        self.entrada.config(fg="#ffffff")
        titulo = self.TITULOS.get(self.estado, "")
        if erro:
            self.status("⚠️  Microfone", erro + " Você pode digitar.")
            return
        if not texto:
            if self.estado == "comando":
                self.status(titulo, "Não entendi. Clique em 🎤 Falar e tente de novo, ou digite e aperte Enter.")
            else:
                # Ficou calado na data/descrição = pular essa pergunta
                self.enviar("")
            return
        self.entrada.delete(0, "end")
        self.entrada.insert(0, texto)
        self.enviar(texto)

    def enviar(self, texto=None):
        if self.estado not in ("comando", "data", "descricao"):
            return
        texto = (texto if texto is not None else self.entrada.get()).strip()
        if self.estado == "comando" and not texto:
            return
        palavra = comando_especial(texto)
        if palavra == "cancelar":
            return self.cancelar()
        if palavra == "voltar":
            if self.estado == "comando":
                self.entrada.delete(0, "end")
                self.lbl_info.config(text="Você já está na primeira pergunta. Fale ou digite a tarefa.")
                return
            return self.voltar()
        self.rodada += 1  # para de ouvir
        if self.estado == "comando":
            self.envio = {"texto": texto}
        elif self.estado == "data":
            self.envio["quando"] = texto
        else:
            self.envio["descricao"] = texto
        self.estado = "aguardando"
        self.lbl_status.config(text="⏳  Enviando...")
        envio = dict(self.envio)

        def trabalho():
            extras = {k: v for k, v in envio.items() if k != "texto"}
            r = chamar_servidor(self.cfg, "conversar", envio["texto"], **extras)
            self.depois(lambda: self._ao_responder(r))

        threading.Thread(target=trabalho, daemon=True).start()

    def _ao_responder(self, r):
        falar = r.get("falar", "")
        st = r.get("status")
        etapa = r.get("etapa")
        self.entrada.delete(0, "end")

        if st == "acao_invalida":
            self.estado = "comando"
            self.status("⚠️  Servidor desatualizado",
                        "Cole o Code.gs novo no Apps Script e faça Implantar → Gerenciar implantações → "
                        "✏️ → Nova versão.")
            return

        if etapa in ("data", "descricao"):
            # se ele não entendeu a resposta, apaga para perguntar de novo
            self.envio.pop("quando" if etapa == "data" else "descricao", None)
            self.estado = etapa
            self.mostrar_etapa(etapa, r.get("pergunta", falar), r.get("campos"))
            self._falar_e_ouvir(falar)
            return

        if st in ("salvo", "cancelado"):
            self.estado = "fim"
            if st == "salvo":
                self.lbl_status.config(text="✅  Tarefa salva!")
                self.mostrar_cartao(r.get("campos"))
                self.lbl_info.config(text="Te mandei um e-mail com os detalhes.")
            else:
                self.lbl_status.config(text="Cancelado")
                self.mostrar_cartao(None)
                self.lbl_info.config(text=falar)
            self.lbl_exemplo.config(text="")
            self.lbl_ajuda.config(text="")
            self.btn_voltar.config(state="disabled")
            minha = self.rodada

            def fim():
                self.voz.falar(falar)
                time.sleep(1.2 if self.voz.ligada else 3)  # dá tempo de ler
                self.depois(lambda: minha == self.rodada and self.fechar())

            threading.Thread(target=fim, daemon=True).start()
            return

        # erro (ex.: não entendeu o nome, sem internet): volta pro começo
        self.estado = "comando"
        self.envio = {}
        self.mostrar_etapa("comando", falar)
        self.lbl_status.config(text="⚠️  Ops")
        self._falar_e_ouvir(falar, ouvir=(st == "sem_titulo"))

    def _falar_e_ouvir(self, texto, ouvir=True):
        minha = self.rodada
        estado = self.estado

        def trabalho():
            self.voz.falar(texto)  # espera terminar de falar para o microfone não se ouvir
            if ouvir and self.cfg.get("ouvir_ligado", True):
                self.depois(lambda: (minha == self.rodada and self.estado == estado) and self.iniciar_escuta())

        threading.Thread(target=trabalho, daemon=True).start()

    def rodar(self):
        self.root.mainloop()


# ----------------------------------------------------------------
# Modo teste (sem janela, sem microfone)
# ----------------------------------------------------------------
def modo_teste(cfg, comando, *respostas):
    """Simula a conversa: comando e depois as respostas, na ordem em que ele perguntar."""
    print("Você:", comando)
    envio = {}
    r = chamar_servidor(cfg, "conversar", comando)
    respostas = list(respostas)
    while True:
        print(f"App [{r.get('etapa') or r.get('status')}]:", r.get("falar"))
        if r.get("etapa") not in ("data", "descricao"):
            return 0 if r.get("status") in ("salvo", "cancelado") else 1
        resp = respostas.pop(0) if respostas else ""
        print("Você:", resp or "(vazio)")
        envio["quando" if r["etapa"] == "data" else "descricao"] = resp
        r = chamar_servidor(cfg, "conversar", comando, **envio)


def main():
    cfg = carregar_config()
    if not cfg.get("url") or not cfg.get("chave"):
        msg = "Falta configurar a URL e a CHAVE. Rode o instalar.bat (ou copie config.example.json para config.json e preencha)."
        print(msg)
        log.error(msg)
        return 1

    if len(sys.argv) >= 2 and sys.argv[1] == "--teste":
        comando = sys.argv[2] if len(sys.argv) > 2 else "tarefa de teste amanhã"
        return modo_teste(cfg, comando, *sys.argv[3:])

    # Só pode ter um assistente rodando. Se já tiver um (ex.: versão antiga),
    # este avisa o antigo para fechar e assume o lugar.
    trava = assumir_lugar()
    if trava is None:
        msg = (f"Tem outro {NOME_APP} aberto que não quis fechar (versão antiga). "
               "Feche ele pelo botão 'Parar execução' e abra de novo.")
        print(msg)
        log.error(msg)
        return 1
    threading.Thread(target=esperar_pedido_de_saida, args=(trava,), daemon=True).start()

    log.info("Assistente iniciado")
    App(cfg).rodar()
    return 0


PORTA_TRAVA = 47653


def assumir_lugar():
    """Tenta ficar com a 'vaga' do assistente; se estiver ocupada, pede para o antigo sair."""
    for _ in range(25):  # tenta por ~7 segundos
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", PORTA_TRAVA))
            s.listen(1)
            return s
        except OSError:
            s.close()
            try:
                with socket.create_connection(("127.0.0.1", PORTA_TRAVA), timeout=1) as c:
                    c.sendall(b"sair")
                    log.info("Pedi para a versão antiga fechar")
            except OSError:
                pass
            time.sleep(0.3)
    return None


def esperar_pedido_de_saida(trava):
    """Fica ouvindo: se uma versão nova pedir, este assistente fecha."""
    while True:
        try:
            conexao, _ = trava.accept()
            with conexao:
                if conexao.recv(16) == b"sair":
                    log.info("Uma versão nova foi aberta: fechando esta")
                    trava.close()
                    os._exit(0)
        except OSError:
            return


if __name__ == "__main__":
    sys.exit(main())
