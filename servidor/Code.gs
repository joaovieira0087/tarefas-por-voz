/**
 * ============================================================
 *  TAREFAS POR VOZ — servidor (Google Apps Script, grátis)
 * ============================================================
 *  Recebe a frase falada/digitada, entende o nome da tarefa e a
 *  data, cria a tarefa (Google Tasks ou Todoist) e te manda um
 *  e-mail de você para você mesmo.
 *
 *  Ações aceitas (GET ou POST com JSON):
 *    acao=conversar texto=... [quando=...] [descricao=...]
 *                   -> fluxo em etapas (notebook): pergunta a data só se
 *                      faltar, depois a descrição, depois salva
 *    acao=entender  texto=...            -> devolve a pergunta da descrição
 *    acao=salvar    texto=... descricao=... -> salva e manda e-mail
 *    formato=texto  (opcional)           -> resposta em texto puro (iPhone)
 *    chave=...      (obrigatório)        -> senha que só você conhece
 *
 *  Propriedades do script (Configurações do projeto):
 *    CHAVE            criada pela função configurar()
 *    PROVEDOR         google (padrão) ou todoist
 *    TODOIST_TOKEN    token da API do Todoist (se PROVEDOR=todoist)
 *    LISTA_ID         lista do Google Tasks (padrão: a principal)
 *    EMAIL            e-mail que recebe o aviso (padrão: o dono do script)
 *    NOMES_ATIVACAO   palavras que ele ignora no começo da frase,
 *                     separadas por vírgula (ex.: "Jarvis, Sexta-feira")
 * ============================================================
 */

var TZ = 'America/Sao_Paulo';
var NOME_APP = 'Tarefas por Voz';
var PALAVRAS_ATIVACAO = ['assistente']; // dá para adicionar mais em NOMES_ATIVACAO

// ------------------------------------------------------------
//  1) Entrada da web
// ------------------------------------------------------------
function doGet(e) {
  return responder_((e && e.parameter) ? e.parameter : {});
}

function doPost(e) {
  var dados = {};
  try {
    if (e && e.postData && e.postData.contents) dados = JSON.parse(e.postData.contents);
  } catch (err) { /* corpo não era JSON: segue com os parâmetros da URL */ }
  if (e && e.parameter) {
    for (var k in e.parameter) if (dados[k] === undefined) dados[k] = e.parameter[k];
  }
  return responder_(dados);
}

function responder_(d) {
  var r;
  try {
    r = processar_(d);
  } catch (err) {
    r = { ok: false, status: 'erro', falar: 'Deu um erro no servidor: ' + err.message };
  }
  if (String(d.formato || '').toLowerCase() === 'texto') {
    return ContentService.createTextOutput(r.falar).setMimeType(ContentService.MimeType.TEXT);
  }
  return ContentService.createTextOutput(JSON.stringify(r)).setMimeType(ContentService.MimeType.JSON);
}

function processar_(d) {
  var props = PropertiesService.getScriptProperties();
  var chave = props.getProperty('CHAVE');
  if (!chave || String(d.chave || '') !== chave) {
    return { ok: false, status: 'nao_autorizado', falar: 'Chave inválida. Confira a configuração.' };
  }

  var extras = String(props.getProperty('NOMES_ATIVACAO') || '').split(',')
    .map(function (x) { return x.trim(); }).filter(String);
  PALAVRAS_ATIVACAO = ['assistente'].concat(extras);

  var acao = normalizar(String(d.acao || 'entender')).trim();
  var texto = String(d.texto || '');
  var t = interpretar(texto, hojeISO_());

  if (!t.titulo) {
    return { ok: false, status: 'sem_titulo', falar: 'Não entendi o nome da tarefa. Pode falar de novo?' };
  }

  if (acao === 'conversar') return conversar_(d, t, texto);

  if (acao === 'entender') {
    return {
      ok: true, status: 'pergunta',
      titulo: t.titulo, data: t.data, dataTexto: t.dataTexto, hora: t.hora,
      falar: montarPergunta(t)
    };
  }

  if (acao === 'salvar') {
    var resp = interpretarResposta(String(d.descricao || ''));
    if (resp.tipo === 'cancelar') {
      return { ok: false, status: 'cancelado', falar: 'Ok, cancelei. Nada foi salvo.' };
    }
    if (resp.tipo === 'sim') {
      return { ok: false, status: 'precisa_descricao', falar: 'Beleza, pode falar a descrição.' };
    }
    return salvarEResponder_(t, resp.tipo === 'descricao' ? resp.descricao : '', texto);
  }

  return { ok: false, status: 'acao_invalida', falar: 'Ação desconhecida: ' + acao };
}

function salvarEResponder_(t, descricao, texto) {
  var salvo = salvarTarefa_(t, descricao, texto);
  return {
    ok: true, status: 'salvo', etapa: 'fim', campos: campos_(t, descricao), link: salvo.link,
    falar: 'Pronto! "' + t.titulo + '" salva' + (t.data ? ' para ' + t.dataTexto : ' sem data') +
           (t.hora ? ' às ' + t.hora : '') +
           (salvo.emailOk ? '. Te mandei um e-mail.' : '. (Não consegui mandar o e-mail.)')
  };
}

function campos_(t, descricao) {
  return { titulo: t.titulo, data: t.data, dataTexto: t.data ? t.dataTexto : 'sem data',
           hora: t.hora, descricao: descricao || '' };
}

/**
 * Fluxo em etapas. O app manda tudo o que já foi respondido a cada chamada:
 *   1) só texto            -> se faltar data: etapa "data"; senão etapa "descricao"
 *   2) texto + quando      -> etapa "descricao"   (quando vazio / "sem data" = sem data)
 *   3) + descricao         -> salva (descricao vazia / "não" = sem descrição)
 */
function conversar_(d, t, texto) {
  var hoje = hojeISO_();
  var temQuando = d.quando !== undefined && d.quando !== null;
  var temDescricao = d.descricao !== undefined && d.descricao !== null;

  if (!t.data && temQuando) {
    var q = interpretarQuando(String(d.quando), hoje);
    if (q.tipo === 'cancelar') return { ok: false, status: 'cancelado', etapa: 'fim', falar: 'Ok, cancelei. Nada foi salvo.' };
    if (q.tipo === 'nao_entendi') {
      return { ok: true, status: 'pergunta', etapa: 'data', campos: campos_(t),
               pergunta: 'Não entendi a data. Tente "amanhã", "sexta" ou "dia 20". Ou diga "sem data".',
               falar: 'Não entendi a data. Tente amanhã, sexta ou dia 20. Ou diga sem data.' };
    }
    if (q.tipo === 'data') {
      t.data = q.data; t.dataTexto = textoData(q.data, hoje);
      if (q.hora) t.hora = q.hora;
    }
  }

  if (!t.data && !temQuando) {
    return { ok: true, status: 'pergunta', etapa: 'data', campos: campos_(t),
             pergunta: 'Para quando é essa tarefa?',
             falar: 'Para quando é "' + t.titulo + '"? Diga a data, ou "sem data".' };
  }

  if (!temDescricao) {
    return { ok: true, status: 'pergunta', etapa: 'descricao', campos: campos_(t),
             pergunta: 'Quer adicionar uma descrição?',
             falar: '"' + t.titulo + '", ' + (t.data ? 'para ' + t.dataTexto : 'sem data') +
                    (t.hora ? ' às ' + t.hora : '') +
                    '. Quer adicionar uma descrição? Diga a descrição, ou "não" para salvar.' };
  }

  var resp = interpretarResposta(String(d.descricao));
  if (resp.tipo === 'cancelar') return { ok: false, status: 'cancelado', etapa: 'fim', falar: 'Ok, cancelei. Nada foi salvo.' };
  if (resp.tipo === 'sim') {
    return { ok: true, status: 'precisa_descricao', etapa: 'descricao', campos: campos_(t),
             pergunta: 'Beleza, qual é a descrição?', falar: 'Beleza, pode falar a descrição.' };
  }
  return salvarEResponder_(t, resp.tipo === 'descricao' ? resp.descricao : '', texto);
}

// ------------------------------------------------------------
//  2) Salvar a tarefa + e-mail
// ------------------------------------------------------------
function salvarTarefa_(t, descricao, textoOriginal) {
  var props = PropertiesService.getScriptProperties();
  var provedor = String(props.getProperty('PROVEDOR') || 'google').toLowerCase();

  var notas = [];
  if (descricao) notas.push(descricao);
  if (t.hora) notas.push('Horário: ' + t.hora);
  notas.push('(Criada por voz: "' + textoOriginal.trim() + '")');
  var textoNotas = notas.join('\n');

  var link = '';
  if (provedor === 'todoist') {
    link = criarNoTodoist_(t, textoNotas, props.getProperty('TODOIST_TOKEN'));
  } else {
    link = criarNoGoogleTasks_(t, textoNotas, props.getProperty('LISTA_ID') || '@default');
  }

  var emailOk = true;
  try {
    enviarEmail_(t, descricao, provedor, link, props.getProperty('EMAIL'));
  } catch (err) {
    emailOk = false;
    console.error('Falha no e-mail: ' + err.message);
  }
  return { link: link, emailOk: emailOk };
}

function criarNoGoogleTasks_(t, notas, listaId) {
  var tarefa = { title: t.titulo, notes: notas };
  if (t.data) tarefa.due = t.data + 'T00:00:00.000Z'; // Google Tasks guarda só a data
  var criada = Tasks.Tasks.insert(tarefa, listaId);
  return criada.webViewLink || 'https://tasks.google.com/';
}

function criarNoTodoist_(t, notas, token) {
  if (!token) throw new Error('Falta o TODOIST_TOKEN nas propriedades do script.');
  var corpo = { content: t.titulo, description: notas };
  if (t.data && t.hora) {
    corpo.due_datetime = Utilities.parseDate(t.data + ' ' + t.hora, TZ, 'yyyy-MM-dd HH:mm').toISOString();
  } else if (t.data) {
    corpo.due_date = t.data;
  }
  var res = UrlFetchApp.fetch('https://api.todoist.com/api/v1/tasks', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify(corpo),
    muteHttpExceptions: true
  });
  var code = res.getResponseCode();
  if (code < 200 || code >= 300) throw new Error('Todoist respondeu ' + code + ': ' + res.getContentText().slice(0, 200));
  var json = JSON.parse(res.getContentText());
  return 'https://app.todoist.com/app/task/' + json.id;
}

function enviarEmail_(t, descricao, provedor, link, emailConfigurado) {
  var para = emailConfigurado || Session.getEffectiveUser().getEmail();
  var nomeApp = provedor === 'todoist' ? 'Todoist' : 'Google Tasks';
  var assunto = '✅ Nova tarefa: ' + t.titulo + (t.data ? ' (' + t.dataTexto + ')' : '');
  var html =
    '<div style="font-family:Arial,sans-serif;font-size:15px;color:#222">' +
    '<h2 style="margin:0 0 12px">✅ Tarefa criada</h2>' +
    '<p><b>Tarefa:</b> ' + esc_(t.titulo) + '</p>' +
    '<p><b>Prazo:</b> ' + (t.data ? esc_(t.dataTexto) : 'sem data') + (t.hora ? ' às ' + esc_(t.hora) : '') + '</p>' +
    '<p><b>Descrição:</b> ' + (descricao ? esc_(descricao) : '<i>sem descrição</i>') + '</p>' +
    '<p><a href="' + link + '">Abrir no ' + nomeApp + '</a></p>' +
    '<p style="color:#888;font-size:12px">Enviado pelo ' + NOME_APP + '</p></div>';
  MailApp.sendEmail({ to: para, subject: assunto, htmlBody: html, name: NOME_APP });
}

function esc_(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function hojeISO_() {
  return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd');
}

// ------------------------------------------------------------
//  3) Rode UMA vez no editor: cria a chave e pede as permissões
// ------------------------------------------------------------
function configurar() {
  var props = PropertiesService.getScriptProperties();
  var chave = props.getProperty('CHAVE');
  if (!chave) {
    chave = Utilities.getUuid().replace(/-/g, '').slice(0, 16);
    props.setProperty('CHAVE', chave);
  }
  if (!props.getProperty('PROVEDOR')) props.setProperty('PROVEDOR', 'google');

  // Estas linhas só servem para o Google pedir as permissões agora.
  Tasks.Tasklists.list({ maxResults: 1 });
  MailApp.getRemainingDailyQuota();

  console.log('==============================================');
  console.log('SUA CHAVE: ' + chave);
  console.log('Copie essa chave. Você vai usar no celular e no computador.');
  console.log('Provedor atual: ' + props.getProperty('PROVEDOR'));
  console.log('==============================================');
}

// Rode no editor para ver como ele entende algumas frases (não salva nada).
function testar() {
  var frases = [
    'comprar pão amanhã',
    'adiciona pagar a conta de luz dia 10',
    'me lembra de ligar para o dentista',
    'tarefa reunião com o time sexta às 15h',
    'criar tarefa entregar o relatório 20 de novembro'
  ];
  frases.forEach(function (f) {
    var t = interpretar(f, hojeISO_());
    console.log(f + '\n   -> ' + JSON.stringify(t) + '\n   -> ' + montarPergunta(t));
  });
}

// ============================================================
//  4) ENTENDIMENTO DA FRASE (funções puras, sem Google)
// ============================================================
var DIAS_SEMANA = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];
var DIAS_SEMANA_N = ['domingo', 'segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado'];
var MESES_N = ['janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho', 'julho',
               'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

var NUM_PALAVRAS = (function () {
  var u = { um: 1, uma: 1, primeiro: 1, dois: 2, duas: 2, tres: 3, quatro: 4, cinco: 5, seis: 6,
            sete: 7, oito: 8, nove: 9 };
  var m = { dez: 10, onze: 11, doze: 12, treze: 13, quatorze: 14, catorze: 14, quinze: 15,
            dezesseis: 16, dezessete: 17, dezoito: 18, dezenove: 19, vinte: 20, trinta: 30 };
  for (var k in u) m[k] = u[k];
  for (var k2 in u) { if (k2 !== 'primeiro') m['vinte e ' + k2] = 20 + u[k2]; }
  m['trinta e um'] = 31; m['trinta e uma'] = 31;
  return m;
})();
var NUM_RE = '(\\d{1,2}|' + Object.keys(NUM_PALAVRAS).sort(function (a, b) { return b.length - a.length; }).join('|') + ')';

function numero_(s) {
  if (/^\d+$/.test(s)) return parseInt(s, 10);
  return NUM_PALAVRAS[s] || null;
}

/** minúsculas e sem acento, mantendo o MESMO tamanho do texto original */
function normalizar(s) {
  return Array.from(String(s).normalize('NFC')).map(function (c) {
    var n = c.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    return n.length === 1 ? n : c.toLowerCase().charAt(0);
  }).join('');
}

// --- datas como 'yyyy-mm-dd', calculadas em UTC para não sofrer com fuso ---
function isoParaDate_(iso) { var p = iso.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
function dateParaIso_(d) { return d.toISOString().slice(0, 10); }
function somarDias_(iso, n) { var d = isoParaDate_(iso); d.setUTCDate(d.getUTCDate() + n); return dateParaIso_(d); }
function diaSemana_(iso) { return isoParaDate_(iso).getUTCDay(); }
function montarData_(ano, mes, dia) {
  var d = new Date(Date.UTC(ano, mes - 1, dia));
  if (d.getUTCMonth() !== mes - 1) return null; // ex.: 31/02
  return dateParaIso_(d);
}

function textoData(iso, hoje) {
  if (!iso) return 'sem data';
  var p = iso.split('-');
  var curta = p[2] + '/' + p[1] + (p[0] !== hoje.slice(0, 4) ? '/' + p[0] : '');
  var nomeDia = DIAS_SEMANA[diaSemana_(iso)];
  if (iso === hoje) return 'hoje, ' + curta;
  if (iso === somarDias_(hoje, 1)) return 'amanhã, ' + nomeDia + ', ' + curta;
  return nomeDia + ', ' + curta;
}

/**
 * Lê a frase e devolve { titulo, data, dataTexto, hora }.
 * hoje = 'yyyy-mm-dd' (no fuso de São Paulo).
 */
function interpretar(texto, hoje) {
  var st = { o: String(texto || '').normalize('NFC') };
  st.n = normalizar(st.o);

  // Apaga um trecho (troca por espaços nos dois textos, mantendo as posições)
  function apagar(re) {
    var achou = null;
    var m = re.exec(st.n);
    if (m) {
      var ini = m.index, fim = m.index + m[0].length;
      var esp = new Array(fim - ini + 1).join(' ');
      st.o = st.o.slice(0, ini) + esp + st.o.slice(fim);
      st.n = st.n.slice(0, ini) + esp + st.n.slice(fim);
      achou = m;
    }
    return achou;
  }

  var FIM = '(?=$|[\\s,.!?;:])';
  var INI = '(?:^|\\s)';

  // 1) palavra de ativação no começo ("assistente, ...", "ok Jarvis, ..."), se houver
  var ATIVACAO = palavrasAtivacaoRe_();
  apagar(ATIVACAO);

  // 2) horário (opcional): "às 15h", "às 3 da tarde", "15:30"
  var hora = null;
  var mh = apagar(new RegExp(INI + '(?:as|a partir das|ate as)\\s+' + NUM_RE +
    '\\s*(?:(h|:|horas?)\\s*(\\d{2})?)?(?:\\s+e\\s+(meia|\\d{1,2}))?(?:\\s+da\\s+(manha|tarde|noite))?' + FIM));
  if (mh && (mh[2] || mh[5])) {
    var hh = numero_(mh[1]);
    var mm = mh[3] ? parseInt(mh[3], 10) : (mh[4] === 'meia' ? 30 : (mh[4] ? parseInt(mh[4], 10) : 0));
    if ((mh[5] === 'tarde' || mh[5] === 'noite') && hh < 12) hh += 12;
    if (hh !== null && hh < 24 && mm < 60) hora = ('0' + hh).slice(-2) + ':' + ('0' + mm).slice(-2);
  } else if (mh) {
    // não era horário de verdade: desfaz
    st = { o: String(texto || '').normalize('NFC') }; st.n = normalizar(st.o);
    apagar(ATIVACAO);
  }

  // 3) data
  var PRE = '(?:(?:ate|para|pra|pro|no|na|em|de|do|da|dia|prazo|com prazo|entrega|entregar|vence|vencimento)\\s+)*';
  var MESES_RE = '(' + MESES_N.join('|') + ')';
  var data = null;
  var regras = [
    { re: 'depois de amanha', f: function () { return somarDias_(hoje, 2); } },
    { re: 'amanha', f: function () { return somarDias_(hoje, 1); } },
    { re: 'hoje', f: function () { return hoje; } },
    { re: '(?:daqui a|daqui|em|dentro de)\\s+' + NUM_RE + '\\s+(dias?|semanas?)', f: function (m) {
        var n = numero_(m[1]); if (!n) return null;
        return somarDias_(hoje, /^semana/.test(m[2]) ? n * 7 : n); } },
    { re: '(?:(?:proxim[oa]|nest[ea]|ess[ea])\\s+)?(domingo|segunda|terca|quarta|quinta|sexta|sabado)(?:[\\s-]*feira)?' +
          '(?:\\s+(que vem|da semana que vem|da proxima semana))?', f: function (m) {
        var alvo = DIAS_SEMANA_N.indexOf(m[1]);
        var dif = (alvo - diaSemana_(hoje) + 7) % 7; if (dif === 0) dif = 7;
        var d = somarDias_(hoje, dif);
        if (m[2] && m[2] !== 'que vem') {
          // "da semana que vem": garante que cai na semana seguinte (seg-dom)
          var segundaAtual = somarDias_(hoje, -((diaSemana_(hoje) + 6) % 7));
          if (d < somarDias_(segundaAtual, 7)) d = somarDias_(d, 7);
        }
        return d; } },
    { re: '(\\d{1,2})\\s*/\\s*(\\d{1,2})(?:\\s*/\\s*(\\d{2,4}))?', f: function (m) {
        return dataDiaMes_(hoje, +m[1], +m[2], m[3]); } },
    { re: '(?:dia\\s+)?' + NUM_RE + '\\s+de\\s+' + MESES_RE + '(?:\\s+de\\s+(\\d{4}))?', f: function (m) {
        return dataDiaMes_(hoje, numero_(m[1]), MESES_N.indexOf(m[2]) + 1, m[3]); } },
    { re: 'dia\\s+' + NUM_RE, f: function (m) { return dataDia_(hoje, numero_(m[1])); } },
    { re: '(?:fim|final) de semana|(?:fim|final) da semana', f: function () {
        var ds = diaSemana_(hoje); if (ds === 6 || ds === 0) return hoje;
        return somarDias_(hoje, 6 - ds); } },
    { re: '(?:fim|final) do mes', f: function () {
        var d = isoParaDate_(hoje); return dateParaIso_(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0))); } },
    { re: 'semana que vem|proxima semana', f: function () {
        return somarDias_(hoje, 7 - ((diaSemana_(hoje) + 6) % 7)); } }
  ];
  for (var i = 0; i < regras.length && !data; i++) {
    var re = new RegExp(INI + PRE + '(?:' + regras[i].re + ')' + FIM);
    var m = re.exec(st.n);
    if (m) {
      // INI e PRE não têm grupos de captura, então m[1], m[2]... são os da regra
      var d = regras[i].f(m);
      if (d) { data = d; apagar(re); }
    }
  }

  // 4) limpa as palavras de comando, sobrando só o nome da tarefa
  var VERBOS = 'adiciona|adicione|adicionar|cria|crie|criar|coloca|coloque|colocar|bota|bote|botar|poe|ponha|' +
    'anota|anote|anotar|registra|registre|registrar|agenda|agende|agendar|inclui|inclua|incluir|salva|salve|salvar|' +
    'marca|marque|marcar|lembra|lembre|lembrar|cadastra|cadastre|cadastrar|insere|insira|inserir|nova|novo';
  var limpezas = [
    new RegExp('^\\s*(?:por favor\\s+)?(?:me\\s+)?(?:' + VERBOS + ')(?:\\s+(?:me|ai|pra mim|para mim))?(?:\\s+de)?' + FIM),
    /^\s*(?:eu\s+)?(?:quero|preciso|gostaria de|vou)\s+(?:que\s+)?(?:(?:adicionar|criar|colocar|anotar|registrar|agendar|incluir|salvar|marcar|cadastrar)\b)?/,
    new RegExp(INI + '(?:pra|para) mim' + FIM),
    new RegExp(INI + 'por favor' + FIM),
    new RegExp(INI + 'ne' + FIM),
    new RegExp('(?:^\\s*(?:(?:uma|um|a|o|essa|esta)\\s+)?|\\s(?:uma|um|a|o|essa|esta)\\s+)(?:nova\\s+|novo\\s+)?(?:tarefa|task|lembrete|atividade|compromisso|item|to-?do|pendencia)s?(?:\\s+nova|\\s+novo)?' + FIM),
    new RegExp(INI + '(?:na|no|nas|nos|em|pra|para|pro|a|ao)\\s+(?:(?:minha|meu|minhas|meus|a|o)\\s+)?(?:lista de tarefas|agenda|lista|tarefas|todoist|google tasks|calendario|inbox|caixa de entrada)' + FIM),
    new RegExp(INI + '(?:chamad[ao]|com o nome(?: de)?|com nome(?: de)?|de nome|nomead[ao]|que se chama|com (?:o )?titulo(?: de)?)' + FIM)
  ];
  for (var volta = 0; volta < 2; volta++) {
    limpezas.forEach(function (re) { while (apagar(re)) { /* repete */ } });
  }
  // pontuação e conectivos soltos nas pontas
  var pontas = [
    /^\s*[,.;:!?\-–"'“”]+/,
    /[,.;:!?\-–"'“”]+\s*$/,
    /^\s*(?:de|do|da|que|e|para|pra|pro|sobre|com|ate)(?=\s)/,
    /\s(?:de|do|da|para|pra|pro|ate|e|no|na|em|com|que|o|a)\s*$/
  ];
  for (var v2 = 0; v2 < 4; v2++) pontas.forEach(function (re) { while (apagar(re)) {} });

  var titulo = st.o.replace(/\s+/g, ' ').trim();
  titulo = titulo.replace(/\s+([,.;:!?])/g, '$1');
  if (titulo) titulo = titulo.charAt(0).toUpperCase() + titulo.slice(1);

  return { titulo: titulo, data: data, dataTexto: textoData(data, hoje), hora: hora };
}

function palavrasAtivacaoRe_() {
  var nomes = PALAVRAS_ATIVACAO.map(function (p) {
    return normalizar(p).trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
  }).filter(String);
  return new RegExp('^\\s*(?:(?:o|oi|ei|e ai|ok|ola|fala|alo)[\\s,]+)?(?:comando\\s+)?(?:' +
                    nomes.join('|') + ')\\b[\\s,.:!-]*');
}

function dataDiaMes_(hoje, dia, mes, anoTxt) {
  if (!dia || !mes || mes < 1 || mes > 12) return null;
  var anoHoje = +hoje.slice(0, 4);
  if (anoTxt) {
    var ano = +anoTxt; if (ano < 100) ano += 2000;
    return montarData_(ano, mes, dia);
  }
  var d = montarData_(anoHoje, mes, dia);
  if (d && d < hoje) d = montarData_(anoHoje + 1, mes, dia);
  return d;
}

function dataDia_(hoje, dia) {
  if (!dia || dia > 31) return null;
  var ano = +hoje.slice(0, 4), mes = +hoje.slice(5, 7);
  for (var k = 0; k < 13; k++) { // procura o próximo mês que tenha esse dia
    var d = montarData_(ano, mes, dia);
    if (d && d >= hoje) return d;
    mes++; if (mes > 12) { mes = 1; ano++; }
  }
  return null;
}

function montarPergunta(t) {
  return 'Tarefa: "' + t.titulo + '". Data: ' +
    (t.data ? t.dataTexto : 'sem data') +
    (t.hora ? ', às ' + t.hora : '') +
    '. Quer adicionar uma descrição? Diga a descrição, ou "não" para salvar.';
}

/** Entende a resposta da pergunta "Para quando?" */
function interpretarQuando(resposta, hoje) {
  var n = normalizar(resposta).replace(/[.,!?;:]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!n || /^(?:nao|n|sem|sem data|sem prazo|nenhuma|nada|nao tem|tanto faz|deixa sem|pula|pular|proximo|qualquer dia)(?:\s+(?:data|prazo|obrigado|precisa|tem|mesmo))*$/.test(n)) {
    return { tipo: 'sem' };
  }
  if (/^(?:cancela|cancelar|cancele|esquece|esqueca|deixa pra la|aborta)\b/.test(n)) return { tipo: 'cancelar' };
  var soDia = new RegExp('^(?:(?:ate|para|pra|no|na|o|a|dia)\\s+)*' + NUM_RE + '$').exec(n);
  if (soDia) {
    var d = dataDia_(hoje, numero_(soDia[1]));
    if (d) return { tipo: 'data', data: d, hora: null };
  }
  var r = interpretar('x ' + resposta, hoje);
  if (r.data) return { tipo: 'data', data: r.data, hora: r.hora };
  if (r.hora) return { tipo: 'data', data: hoje, hora: r.hora };
  return { tipo: 'nao_entendi' };
}

/** Entende a resposta da pergunta da descrição */
function interpretarResposta(resposta) {
  var o = String(resposta || '').normalize('NFC').trim();
  var n = normalizar(o).replace(/[.,!?;:]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!n) return { tipo: 'nao' };
  if (/^(?:cancela|cancelar|cancele|cancelado|esquece|esqueca|deixa pra la|nao salva|nao salvar|aborta|abortar)\b/.test(n)) {
    return { tipo: 'cancelar' };
  }
  var COMPL = '(?:\\s+(?:obrigado|obrigada|valeu|precisa|quero|pode salvar|pode|salva|salvar|so|mesmo|ta|bom|isso|e so isso|so isso|necessario|tem))*';
  if (new RegExp('^(?:nao|n|nem|sem descricao|nenhuma|nada|so salva|so salvar|pode salvar|salva|salvar|salve|ok|beleza|ta bom|negativo|dispensa|assim mesmo|pode ser assim|tudo certo)' + COMPL + '$').test(n)) {
    return { tipo: 'nao' };
  }
  if (/^(?:sim|s|quero|claro|pode|tem|preciso|yes|uhum|aham)(?:\s+(?:quero|sim|por favor|preciso|tem))*$/.test(n)) {
    return { tipo: 'sim' };
  }
  // tira prefixos tipo "sim, a descrição é ..."
  var m = /^(?:(?:sim|quero)\s+)?(?:(?:a\s+)?descricao(?:\s+e|\s+sera)?|coloca(?:r)?(?:\s+na descricao)?(?:\s+que)?|adiciona(?:r)?(?:\s+na descricao)?(?:\s+que)?|bota(?:\s+que)?)\s+/.exec(n + ' ');
  var desc = m ? o.slice(Math.min(m[0].length, o.length)) : o;
  desc = desc.replace(/^[\s,.:;\-]+/, '').trim();
  if (!desc) return { tipo: 'sim' };
  return { tipo: 'descricao', descricao: desc.charAt(0).toUpperCase() + desc.slice(1) };
}
