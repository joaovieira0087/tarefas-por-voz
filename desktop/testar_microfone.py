"""
Teste de microfone do Tarefas por Voz.
Mostra os microfones, grava 5 segundos mostrando o volume ao vivo,
e diz o que o Google entendeu. Se der certo, salva o microfone no config.json.
"""
import json
import os
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_CONFIG = os.path.join(PASTA, "config.json")
TAXA = 16000


def listar():
    import sounddevice as sd
    padrao = sd.default.device[0]
    print("\nMicrofones encontrados:")
    entradas = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            api = sd.query_hostapis(d["hostapi"])["name"]
            if api != "MME":  # mostra só um de cada (o Windows lista repetido)
                continue
            marca = "  <-- PADRÃO" if i == padrao else ""
            print(f"  [{i}] {d['name']}{marca}")
            entradas.append(i)
    return entradas, padrao


def gravar_e_entender(dispositivo, segundos=5):
    import numpy as np
    import sounddevice as sd
    import speech_recognition as sr

    nome = sd.query_devices(dispositivo)["name"] if dispositivo is not None else "padrão"
    input(f"\nVou gravar {segundos}s no microfone [{dispositivo}] {nome}.\n"
          "Aperte Enter e fale: 'comprar pão amanhã'...")
    n = int(TAXA * 0.1)
    blocos, niveis = [], []
    with sd.InputStream(samplerate=TAXA, channels=1, dtype="int16", blocksize=n, device=dispositivo) as mic:
        for _ in range(segundos * 10):
            b = mic.read(n)[0].copy()
            blocos.append(b)
            nivel = float(np.sqrt(np.mean(b.astype(np.float32) ** 2)))
            niveis.append(nivel)
            barra = "█" * min(50, int(nivel / 40))
            print(f"\r  volume {nivel:6.0f} {barra:<50}", end="", flush=True)
    print()
    silencio = sorted(niveis)[len(niveis) // 5]
    pico = max(niveis)
    print(f"\n  Barulho de fundo: {silencio:.0f}   |   Volume máximo da sua voz: {pico:.0f}")
    if pico < 15:
        print("  ❌ Volume zero: esse microfone não está captando nada (mudo ou errado).")
        return False
    if pico < silencio * 2:
        print("  ⚠️ Sua voz quase não aparece acima do barulho. Aumente o volume do microfone no Windows.")

    print("  Mandando para o Google entender...")
    audio = sr.AudioData(b"".join(b.tobytes() for b in blocos), TAXA, 2)
    try:
        texto = sr.Recognizer().recognize_google(audio, language="pt-BR")
        print(f"  ✅ Entendi: \"{texto}\"")
        return True
    except sr.UnknownValueError:
        print("  ❌ O Google não entendeu nenhuma palavra.")
    except sr.RequestError as e:
        print(f"  ❌ Erro ao falar com o Google: {e}")
    return False


def salvar(dispositivo):
    import sounddevice as sd
    cfg = {}
    if os.path.exists(ARQ_CONFIG):
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    cfg["microfone"] = sd.query_devices(dispositivo)["name"] if dispositivo is not None else None
    with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"\nSalvo no config.json: microfone = {cfg['microfone']}")
    print("Agora abra o programa de novo: pyw tarefas_voz.py (a versão nova fecha a antiga sozinha)")


def main():
    entradas, padrao = listar()
    dispositivo = padrao if padrao in entradas else None
    while True:
        ok = gravar_e_entender(dispositivo)
        if ok:
            if input("\nUsar esse microfone? (S/n): ").strip().lower() != "n":
                salvar(dispositivo)
            return
        esc = input("\nDigite o NÚMERO de outro microfone da lista para testar (ou Enter para sair): ").strip()
        if not esc.isdigit():
            return
        dispositivo = int(esc)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nErro: {e}")
    input("\nAperte Enter para fechar.")
