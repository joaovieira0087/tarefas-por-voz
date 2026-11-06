"""
Instalador do Tarefas por Voz (Windows).
1) instala as bibliotecas  2) salva sua URL e CHAVE  3) testa o servidor
4) faz o assistente abrir junto com o Windows  5) inicia o assistente
"""
import json
import os
import subprocess
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(PASTA, "tarefas_voz.py")
ARQ_CONFIG = os.path.join(PASTA, "config.json")


def passo(n, texto):
    print(f"\n[{n}/5] {texto}")


def main():
    print("=== Instalador do Tarefas por Voz ===")

    passo(1, "Instalando as bibliotecas (pode levar 1-2 minutos)...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "-r",
                        os.path.join(PASTA, "requirements.txt")])
    if r.returncode != 0:
        print("Não consegui instalar as bibliotecas. Veja a mensagem acima.")
        return 1

    passo(2, "Configuração")
    cfg = {}
    if os.path.exists(ARQ_CONFIG):
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    url = input(f"Cole a URL do App da Web (termina em /exec) [{cfg.get('url', '')}]: ").strip() or cfg.get("url", "")
    chave = input(f"Cole a sua CHAVE [{cfg.get('chave', '')}]: ").strip() or cfg.get("chave", "")
    cfg.update({"url": url, "chave": chave})
    cfg.setdefault("atalho", "<ctrl>+<alt>+j")
    cfg.setdefault("voz_ligada", True)
    cfg.setdefault("ouvir_ligado", True)
    cfg.setdefault("idioma", "pt-BR")
    with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("Salvo em config.json")

    passo(3, "Testando o servidor (não cria tarefa)...")
    sys.path.insert(0, PASTA)
    from tarefas_voz import chamar_servidor
    r = chamar_servidor(cfg, "entender", "tarefa de teste amanhã")
    print("Resposta:", r.get("falar"))
    if not r.get("ok"):
        print("O teste falhou. Confira a URL e a CHAVE e rode o instalador de novo.")
        return 1

    passo(4, "Abrir junto com o Windows")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    if os.name == "nt" and input("Quer que ele inicie sozinho com o Windows? (S/n): ").strip().lower() != "n":
        inicializar = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
        vbs = os.path.join(inicializar, "Tarefas por Voz.vbs")
        with open(vbs, "w", encoding="utf-8") as f:
            f.write(f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{SCRIPT}""", 0, False\n')
        print("Pronto: ele vai abrir sozinho quando você ligar o computador.")

    passo(5, "Iniciando...")
    subprocess.Popen([pythonw, SCRIPT], cwd=PASTA)
    atalho = cfg["atalho"].replace("<", "").replace(">", "").upper()
    print(f"\nTudo certo! Aperte {atalho} em qualquer lugar e fale o comando.")
    return 0


if __name__ == "__main__":
    code = main()
    input("\nAperte Enter para fechar.")
    sys.exit(code)
