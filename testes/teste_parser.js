// Testa o entendimento das frases e datas do servidor.  Rode: node testes/teste_parser.js
const fs = require('fs');
const vm = require('vm');
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../servidor/Code.gs', 'utf8'), ctx);

const HOJE = '2026-11-05'; // quinta
const casos = [
  ['Assistente, adicione para mim uma tarefa chamada comprar pão até sábado', 'Comprar pão', '2026-11-07'],
  ['adicione para mim uma tarefa na minha agenda, né, comprar pão até sábado', 'Comprar pão', '2026-11-07'],
  ['comando assistente adiciona comprar pão dia 7', 'Comprar pão', '2026-11-07'],
  ['Jarvis, comprar pão amanhã', 'Comprar pão', '2026-11-06'],
  ['adiciona na minha agenda revisar o relatório da Ana amanhã', 'Revisar o relatório da Ana', '2026-11-06'],
  ['me lembra de pagar a fatura dia 10', 'Pagar a fatura', '2026-11-10'],
  ['me lembra de pagar a fatura dia 3', 'Pagar a fatura', '2026-12-03'],
  ['criar tarefa estudar inglês para 20 de novembro', 'Estudar inglês', '2026-11-20'],
  ['tarefa reunião com o time sexta às 15h', 'Reunião com o time', '2026-11-06', '15:00'],
  ['nova tarefa entregar relatório 12/11', 'Entregar relatório', '2026-11-12'],
  ['adicionar tarefa comprar café', 'Comprar café', null],
  ['coloca na lista ligar pro médico daqui a 3 dias', 'Ligar pro médico', '2026-11-08'],
  ['adiciona regar as plantas quinta', 'Regar as plantas', '2026-11-12'],
  ['adiciona regar as plantas segunda da semana que vem', 'Regar as plantas', '2026-11-09'],
  ['adiciona regar as plantas sábado da semana que vem', 'Regar as plantas', '2026-11-14'],
  ['adiciona a tarefa comprar pão até o dia sete', 'Comprar pão', '2026-11-07'],
  ['adiciona comprar pão pra depois de amanhã', 'Comprar pão', '2026-11-07'],
  ['preciso entregar o trabalho no dia 2 de janeiro', 'Entregar o trabalho', '2027-01-02'],
  ['adiciona pagar o aluguel no fim do mês', 'Pagar o aluguel', '2026-11-30'],
  ['quero adicionar uma tarefa com o nome de lavar o carro hoje', 'Lavar o carro', '2026-11-05'],
  ['adiciona dentista às 3 da tarde amanhã', 'Dentista', '2026-11-06', '15:00'],
  ['adiciona as 3 tarefas do curso amanhã', 'As 3 tarefas do curso', '2026-11-06'],
];
ctx.PALAVRAS_ATIVACAO = ['assistente', 'Jarvis'];  // como se NOMES_ATIVACAO = "Jarvis"
let falhas = 0;
for (const [frase, tit, data, hora] of casos) {
  const r = ctx.interpretar(frase, HOJE);
  const ok = r.titulo === tit && r.data === data && (hora === undefined || r.hora === hora);
  if (!ok) falhas++;
  console.log((ok ? 'OK  ' : 'FALHA') + ' | ' + frase + '\n      -> ' + JSON.stringify(r));
}
console.log('\nPergunta exemplo: ' + ctx.montarPergunta(ctx.interpretar(casos[0][0], HOJE)));

const quando = [['amanhã', '2026-11-06'], ['sexta às 19h', '2026-11-06'], ['dia 20', '2026-11-20'], ['vinte', '2026-11-20'],
                ['15/12', '2026-12-15'], ['sem data', 'sem'], ['', 'sem'], ['não', 'sem'], ['cancela', 'cancelar'], ['blablabla', 'nao_entendi']];
for (const [resp, esperado] of quando) {
  const q = ctx.interpretarQuando(resp, HOJE);
  const ok = (q.data || q.tipo) === esperado; if (!ok) falhas++;
  console.log((ok ? 'OK  ' : 'FALHA') + ' | quando "' + resp + '" -> ' + JSON.stringify(q));
}

const respostas = [
  ['não', 'nao'], ['Não, obrigado', 'nao'], ['pode salvar', 'nao'], ['N', 'nao'], ['', 'nao'],
  ['cancela', 'cancelar'], ['sim', 'sim'], ['quero', 'sim'],
  ['levantar os requisitos com o cliente', 'descricao'],
  ['A descrição é levantar requisitos do módulo de agenda', 'descricao'],
  ['não esquecer de levar o crachá', 'descricao'],
];
for (const [resp, tipo] of respostas) {
  const r = ctx.interpretarResposta(resp);
  const ok = r.tipo === tipo; if (!ok) falhas++;
  console.log((ok ? 'OK  ' : 'FALHA') + ' | "' + resp + '" -> ' + JSON.stringify(r));
}
console.log(falhas ? `\n${falhas} FALHA(S)` : '\nTUDO OK');
process.exit(falhas ? 1 : 0);
