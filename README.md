<img width="1875" height="866" alt="image" src="https://github.com/user-attachments/assets/27752863-eba4-4cd5-88bc-1f9b76945061" />




# 🎙️ Tarefas por Voz

Crie tarefas **falando**, pelo computador (atalho de teclado) ou pelo celular (Siri). Ele entende a frase em português, descobre a data sozinho ("amanhã", "sexta", "dia 20"…), salva no **Google Tasks** (ou no **Todoist**) e te manda um **e-mail de confirmação**.

**100% grátis**: usa só Google Apps Script, Google Tasks, Gmail, Python e Atalhos do iPhone. Nada de servidor pago, nada de chave de API paga.

```
Você: "Comprar pão amanhã"
App:  📝 Tarefa: Comprar pão   📅 Data: amanhã, sexta, 06/11
      Quer adicionar uma descrição?
Você: "Não"
App:  ✅ Pronto! "Comprar pão" salva para amanhã. Te mandei um e-mail.
```

## ✨ O que ele faz

- **Entende frases naturais:** "me lembra de pagar a conta de luz dia 10", "reunião com o time sexta às 15h", "coloca na lista lavar o carro daqui a 3 dias".
- **Pergunta só o que falta:** se você não disse a data, ele pergunta "Para quando?". Se disse, pula direto para a descrição.
- **Texto ao vivo:** as palavras aparecem enquanto você fala (Vosk, offline). A versão final é feita pelo reconhecimento do Google, que é mais preciso.
- **Espera você pensar:** só segue depois de 4,5 s de silêncio (dá para mudar).
- **Voltar e cancelar** a qualquer momento, falando ou com botão.
- **Fala as respostas** em voz alta, com as vozes do próprio Windows.
- **E-mail de confirmação** para você mesmo, com o link da tarefa.

## 🧩 Como funciona

```
Celular (Siri) ─────┐
                    ├──►  Servidor grátis na sua conta Google  ──►  Google Tasks (ou Todoist)
Computador          │     (Apps Script: entende frase e data)  └──►  E-mail para você
(Ctrl+Alt+J + voz) ─┘
```

| Pasta | O que é |
|---|---|
| `servidor/` | O "cérebro": código do Google Apps Script (`Code.gs` + `appsscript.json`) |
| `desktop/` | App para Windows: atalho de teclado, microfone, texto ao vivo e janela |
| `testes/` | Testes do entendimento de frases e um servidor simulado para testar sem a sua conta |

---

## 🚀 Instalação

São 3 partes. Faça na ordem: **Google → Computador → Celular**. Leva uns 20 minutos.

### 1) Servidor no Google (10 min)

1. Abra https://script.google.com → **Novo projeto**. Dê o nome **Tarefas por Voz**.
2. Apague o conteúdo de `Código.gs` e cole o de [`servidor/Code.gs`](servidor/Code.gs). Salve.
3. ⚙️ **Configurações do projeto** → marque **"Mostrar arquivo de manifesto appsscript.json"**. Abra o `appsscript.json` e cole o conteúdo de [`servidor/appsscript.json`](servidor/appsscript.json). *(Isso liga o Google Tasks e acerta o fuso para São Paulo.)*
4. No menu de funções, escolha **`configurar`** → **▶ Executar** → autorize. Quando aparecer "O Google não verificou este app": **Avançado → Acessar (não seguro)**. O app é seu, na sua conta, então pode autorizar.
5. No **Registro de execução** aparece `SUA CHAVE: xxxxxxxx`. **Guarde essa chave**: ela funciona como uma senha.
6. **Implantar → Nova implantação → App da Web**
   - Executar como: **Eu** · Quem pode acessar: **Qualquer pessoa**
   - Copie a **URL** (termina em `/exec`).
7. Teste no navegador, trocando pelos seus dados (não cria tarefa):
   ```
   SUA_URL?chave=SUA_CHAVE&acao=entender&texto=comprar pão amanhã
   ```

> 🔁 **Mudou o código do servidor?** Implantar → **Gerenciar implantações** → ✏️ → Versão: **Nova versão**. Sem isso, a URL continua rodando a versão antiga.

### 2) Computador com Windows (5 min)

1. Instale o [Python](https://www.python.org/downloads/). Recomendado: 3.12 ou 3.13. No instalador, marque **"Add python.exe to PATH"**.
2. Baixe este repositório (**Code → Download ZIP**) e descompacte numa pasta fixa (ex.: `C:\TarefasPorVoz`).
3. Dê dois cliques em **`desktop\instalar.bat`**. Ele instala as bibliotecas, pede a **URL** e a **CHAVE**, testa a conexão e pergunta se você quer que ele abra junto com o Windows.
4. Aperte **Ctrl+Alt+J** em qualquer tela e fale.

> **O microfone não capta?** Rode `desktop\testar_microfone.bat`. Ele mostra o volume ao vivo e salva o microfone certo. Isso é comum quando há microfones virtuais (OBS, Virtual Audio Cable) definidos como padrão.
>
> **Texto ao vivo:** na primeira vez, ele baixa sozinho o modelo de português do Vosk (~30 MB). O rodapé da janela mostra o progresso.

### 3) iPhone com Siri (5 min, opcional)

No app **Atalhos** → **+**, adicione estas ações, nesta ordem:

| # | Ação | Configuração |
|---|---|---|
| 1 | **Pedir Entrada** | Texto · Pergunta: `Qual é a tarefa? Ex.: comprar pão amanhã` |
| 2 | **Definir Variável** | Nome `comando` · Entrada: **Entrada Fornecida** |
| 3 | **Obter Conteúdo do URL** | Sua URL · Método **POST** · Corpo **JSON** com os campos de texto: `chave` = sua chave · `acao` = `entender` · `texto` = **comando** · `formato` = `texto` |
| 4 | **Pedir Entrada** | Texto · Pergunta: **Conteúdo do URL** |
| 5 | **Obter Conteúdo do URL** | Mesma URL · **POST** · **JSON**: `chave` · `acao` = `salvar` · `texto` = **comando** · `descricao` = **Entrada Fornecida** · `formato` = `texto` |
| 6 | **Mostrar Resultado** | **Conteúdo do URL** |

Dê um nome ao atalho, por exemplo **"Anotar tarefa"**, e diga: **"E aí Siri, anotar tarefa"**.
Também dá para colocar o atalho no **Botão de Ação** ou em **Ajustes → Acessibilidade → Toque → Tocar Atrás**.

> No celular o fluxo é mais curto: tarefa → descrição. A data você fala junto com a tarefa.

---

## 🗣️ Como usar

| Você fala | Ele entende |
|---|---|
| "Comprar pão amanhã" | **Comprar pão** · amanhã |
| "Adiciona pagar a conta de luz dia 10" | **Pagar a conta de luz** · dia 10 (se já passou, o do mês que vem) |
| "Me lembra de ligar para o dentista" | **Ligar para o dentista** · pergunta a data |
| "Reunião com o time sexta às 15h" | **Reunião com o time** · sexta · 15:00 |
| "Criar tarefa entregar o relatório 20 de novembro" | **Entregar o relatório** · 20/11 |
| "Coloca na lista lavar o carro daqui a 3 dias" | **Lavar o carro** · daqui a 3 dias |
| "Estudar inglês sábado da semana que vem" | **Estudar inglês** · sábado da próxima semana |
| "Pagar o aluguel no fim do mês" | **Pagar o aluguel** · último dia do mês |

**Datas que ele entende:** hoje, amanhã, depois de amanhã, dias da semana, "da semana que vem", "dia 7", "7 de dezembro", "12/11", "daqui a 3 dias", "semana que vem", "fim de semana", "fim do mês", e horários como "às 15h" ou "às 3 da tarde".

**Durante a conversa (no computador):**

| Quero… | Faça |
|---|---|
| Pular a pergunta (sem data / sem descrição) | **Enter** com a caixa vazia, ou diga **"não"** / **"sem data"** |
| Voltar para a pergunta anterior | Diga **"voltar"**, ou clique em **← Voltar** |
| Desistir (nada é salvo) | Diga **"cancelar"** |
| Digitar em vez de falar | Comece a digitar: ele para de ouvir na hora |
| Fechar a janela (continua rodando) | **Esc** ou **Sair** |
| Desligar o programa | **⏹ Parar execução** |
| Atualizar o programa | Troque o arquivo e rode `pyw tarefas_voz.py`: a versão nova fecha a antiga sozinha |

## ⚙️ Configuração

**Computador:** `desktop/config.json` (copie de [`config.example.json`](desktop/config.example.json) ou rode o instalador).

| Campo | Padrão | Para quê |
|---|---|---|
| `url`, `chave` | — | Da parte 1 |
| `atalho` | `<ctrl>+<alt>+j` | Atalho de teclado global |
| `voz_ligada` | `true` | Falar as respostas em voz alta |
| `ouvir_ligado` | `true` | Abrir já ouvindo o microfone |
| `microfone` | `null` | Nome do microfone (o `testar_microfone` preenche) |
| `sensibilidade` | `1.0` | Aumente (ex.: `2.0`) se ele não perceber sua voz |
| `pausa_fim_segundos` | `4.5` | Silêncio que conta como "terminei de falar" |
| `texto_ao_vivo` | `true` | Mostrar as palavras enquanto você fala |

**Servidor:** Apps Script → ⚙️ Configurações do projeto → **Propriedades do script**.

| Propriedade | Para quê |
|---|---|
| `CHAVE` | Criada pela função `configurar` |
| `PROVEDOR` | `google` (padrão) ou `todoist` |
| `TODOIST_TOKEN` | Token da API do Todoist (Configurações → Integrações → Desenvolvedor) |
| `LISTA_ID` | Outra lista do Google Tasks (padrão: a principal) |
| `EMAIL` | Mandar o aviso para outro e-mail (padrão: o dono do script) |
| `NOMES_ATIVACAO` | Palavras que ele ignora no começo da frase, separadas por vírgula (ex.: `Jarvis, Sexta-feira`) |

## 🛠️ Problemas comuns

| Problema | Solução |
|---|---|
| "Chave inválida" | A chave do `config.json` ou do Atalho é diferente da que está em Propriedades do script → `CHAVE` |
| Aparece HTML / página de login | A implantação não está como **Qualquer pessoa**, ou a URL não termina em `/exec` |
| Mudei o código e nada mudou | Servidor: **Nova versão** na implantação. Computador: rode `pyw tarefas_voz.py` de novo |
| "Servidor desatualizado" | Cole o `Code.gs` novo e publique uma **Nova versão** |
| Microfone não capta | `desktop\testar_microfone.bat` |
| Texto ao vivo não aparece | O rodapé da janela diz o motivo. Normalmente é só rodar `py -m pip install vosk` |
| O atalho não abre nada | O programa não está rodando: `desktop\iniciar.bat`. Veja também `desktop\tarefas_voz.log` |
| Nome técnico entendido errado ("dev" → "deve") | Diga "voltar" e corrija digitando, ou digite direto |

**Limites grátis:** 100 e-mails por dia (Gmail comum). O reconhecimento final usa o serviço gratuito do Google e precisa de internet. O texto ao vivo funciona offline.

## 🧪 Desenvolvimento

```bash
# Testes do entendimento de frases e datas (Node 18+)
node testes/teste_parser.js

# Servidor simulado (não mexe na sua conta Google)
node testes/servidor_simulado.js
# no desktop/config.json use: {"url": "http://127.0.0.1:8765/exec", "chave": "abc123"}
python desktop/tarefas_voz.py --teste "comprar pão" "amanhã" "não"
```

## 📄 Licença

[MIT](LICENSE): use, modifique e compartilhe à vontade.
