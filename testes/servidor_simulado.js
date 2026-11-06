// Simula o Google Apps Script localmente (inclusive o redirecionamento 302 do Google),
// para testar o app do computador sem mexer na sua conta.
//   node testes/servidor_simulado.js
//   config.json: {"url": "http://127.0.0.1:8765/exec", "chave": "abc123"}
//   Veja o que seria salvo/enviado em http://127.0.0.1:8765/log
const fs = require('fs'), vm = require('vm'), http = require('http');
const salvas = [], emails = [];
const props = { CHAVE: 'abc123', PROVEDOR: process.env.PROVEDOR || 'google', TODOIST_TOKEN: 'tk' };
const ctx = {
  console,
  PropertiesService: { getScriptProperties: () => ({ getProperty: k => props[k] || null, setProperty: (k, v) => props[k] = v }) },
  Tasks: { Tasks: { insert: (t, l) => { salvas.push({ t, l }); return { id: '1', webViewLink: 'https://tasks.google.com/task/1' }; } },
           Tasklists: { list: () => ({}) } },
  MailApp: { sendEmail: o => emails.push(o), getRemainingDailyQuota: () => 100 },
  Session: { getEffectiveUser: () => ({ getEmail: () => 'voce@exemplo.com' }) },
  Utilities: {
    formatDate: () => '2026-11-05',
    getUuid: () => 'x',
    parseDate: (s) => new Date(s.replace(' ', 'T') + ':00-03:00'),
  },
  UrlFetchApp: { fetch: (url, o) => { salvas.push({ todoist: JSON.parse(o.payload) });
    return { getResponseCode: () => 200, getContentText: () => '{"id":"999"}' }; } },
  ContentService: { MimeType: { TEXT: 'text/plain', JSON: 'application/json' },
    createTextOutput: s => ({ s, setMimeType(m) { this.m = m; return this; } }) },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../servidor/Code.gs', 'utf8'), ctx);

let ultimo = null;
http.createServer((req, res) => {
  let body = '';
  req.on('data', c => body += c);
  req.on('end', () => {
    if (req.url.startsWith('/exec')) {
      ultimo = req.method === 'POST' ? ctx.doPost({ postData: { contents: body }, parameter: {} })
                                     : ctx.doGet({ parameter: Object.fromEntries(new URL(req.url, 'http://x').searchParams) });
      res.writeHead(302, { Location: '/echo' }); return res.end();
    }
    if (req.url === '/echo') { res.writeHead(200, { 'Content-Type': ultimo.m }); return res.end(ultimo.s); }
    if (req.url === '/log') { res.writeHead(200); return res.end(JSON.stringify({ salvas, emails }, null, 1)); }
    res.writeHead(404); res.end();
  });
}).listen(8765, () => console.log('ok na 8765'));
