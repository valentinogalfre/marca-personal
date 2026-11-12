// node arnes.js <comun.js> <pagina.js> <rutas.json> <pathname> <search>
const fs = require('fs'); const vm = require('vm');
const [comunF, paginaF, rutasF, pathname, search] = process.argv.slice(2);
const rutas = JSON.parse(fs.readFileSync(rutasF, 'utf8'));
const errores = [];
class Node_ {
  constructor(tag, text) { this.tagName = tag; this.childNodes = []; this.attrs = {}; this._text = text; this.parentNode = null;
    this.dataset = {}; this.style = { setProperty(){}, removeProperty(){} }; this.listeners = {};
    const self = this; this.classList = { add(...c){ self.attrs.class = ((self.attrs.class||'')+' '+c.join(' ')).trim(); }, remove(){}, toggle(){}, contains(c){ return (self.attrs.class||'').split(' ').includes(c);} }; }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length-1] || null; }
  get children() { return this.childNodes.filter(c => c.tagName !== '#text'); }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  append(...cs) { for (const c of cs) this.appendChild(typeof c === 'string' ? new Node_('#text', c) : c); }
  prepend(...cs) { for (const c of cs.reverse()) this.insertBefore(typeof c === 'string' ? new Node_('#text', c) : c, this.firstChild); }
  insertBefore(c, ref) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; const i = ref ? this.childNodes.indexOf(ref) : -1; if (i < 0) this.childNodes.push(c); else this.childNodes.splice(i, 0, c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  replaceChild(n, o) { this.insertBefore(n, o); this.removeChild(o); return o; }
  replaceChildren(...cs) { this.childNodes = []; this.append(...cs); }
  replaceWith(n) { if (this.parentNode) this.parentNode.replaceChild(n, this); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k] ?? null; } removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; } toggleAttribute(k, f) { if (f) this.attrs[k] = ''; else delete this.attrs[k]; }
  addEventListener(e, f) { (this.listeners[e] = this.listeners[e] || []).push(f); } removeEventListener() {}
  get textContent() { if (this.tagName === '#text') return this._text; return this.childNodes.map(c => c.textContent).join(''); }
  set textContent(v) { this.childNodes = []; if (v !== '' && v != null) this.appendChild(new Node_('#text', String(v))); }
  get innerText() { return this.textContent; }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) { const out = []; const walk = (n) => { for (const c of n.childNodes) { if (c.tagName !== '#text' && coincide(c, sel)) out.push(c); walk(c); } }; walk(this); return out; }
  closest() { return null; } focus() {} blur() {} scrollIntoView() {} getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0, height: 0, width: 0 }; }
  matches(sel) { return coincide(this, sel); } click() {} select() {} showModal() {} close() {}
  cloneNode() { return new Node_(this.tagName); }
}
function coincide(n, sel) { sel = sel.trim(); if (sel.startsWith('#')) return n.attrs.id === sel.slice(1) || n.id === sel.slice(1);
  if (sel.startsWith('.')) return (n.attrs.class || '').split(' ').includes(sel.slice(1)) || (n.className||'').split(' ').includes(sel.slice(1));
  const m = sel.match(/^\[([\w-]+)(?:="?([^"\]]*)"?)?\]$/); if (m) { const a = m[1]; if (a.startsWith('data-')) { const k = a.slice(5).replace(/-(\w)/g,(x,y)=>y.toUpperCase()); if (k in n.dataset) return m[2]===undefined || n.dataset[k]===m[2]; } return a in n.attrs && (m[2]===undefined || n.attrs[a]===m[2]); }
  return n.tagName === sel.toUpperCase(); }
const body = new Node_('BODY'); const html = new Node_('HTML'); html.appendChild(body);
const app = new Node_('DIV'); app.attrs.id = 'app'; app.attrs.class = process.env.APPCLASS || ''; body.appendChild(app);
const document = { body, documentElement: html, title: '', visibilityState: 'visible', activeElement: body,
  createElement: (t) => new Node_(String(t).toUpperCase()), createElementNS: (ns, t) => new Node_(t), createTextNode: (t) => new Node_('#text', t),
  querySelector: (s) => html.querySelector(s), querySelectorAll: (s) => html.querySelectorAll(s), getElementById: (id) => html.querySelector('#'+id),
  addEventListener() {}, removeEventListener() {}, contains: (n) => html.contains(n), createRange: () => ({ selectNodeContents() {} }), hasFocus: () => true };
const pendiente = () => new Promise(() => {});
let llamadas = [];
function fetch(ruta, op) { llamadas.push((op && op.method || 'GET') + ' ' + ruta);
  const p = String(ruta).split('?')[0];
  if (p === '/api/cambios') return pendiente();
  if (p in rutas) { const [st, cuerpo] = rutas[p]; return Promise.resolve({ ok: st >= 200 && st < 300, status: st, json: async () => JSON.parse(cuerpo) }); }
  return Promise.resolve({ ok: false, status: 404, json: async () => ({ codigo: 'no_encontrado', error: 'x' }) }); }
const ctx = { window: null, document, Node: Node_, navigator: { vibrate() {} , clipboard: { writeText: async () => {} } }, console, fetch,
  setTimeout: (f, ms) => (ms > 5000 ? 0 : setTimeout(f, ms)), clearTimeout, setInterval: () => 0, clearInterval() {},
  location: { pathname, search: search || '', href: 'http://x' + pathname + (search||''), hash: '', origin: 'http://x' },
  history: { replaceState() {}, pushState() {} }, localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} }, performance: { now: () => Date.now() },
  Intl, Date, Math, JSON, Number, String, AbortController, URLSearchParams, URL, requestAnimationFrame: (f) => setTimeout(f, 0), cancelAnimationFrame() {},
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }), getComputedStyle: () => ({ getPropertyValue: () => '' }),
  scrollTo() {}, scrollBy() {}, innerHeight: 800, innerWidth: 400, scrollY: 0, isSecureContext: false, addEventListener() {}, removeEventListener() {},
  getSelection: () => ({ removeAllRanges() {}, addRange() {} }), print() {}, Promise, Map, Set, Array, Object, Error, encodeURIComponent, decodeURIComponent, isFinite, parseFloat, parseInt };
ctx.window = ctx; ctx.globalThis = ctx; ctx.self = ctx;
process.on('unhandledRejection', (e) => errores.push('rechazo: ' + (e && e.stack || e)));
process.on('uncaughtException', (e) => errores.push('excepcion: ' + (e && e.stack || e)));
vm.createContext(ctx);
try { vm.runInContext(fs.readFileSync(comunF, 'utf8'), ctx, { filename: 'comun.js' }); vm.runInContext(fs.readFileSync(paginaF, 'utf8'), ctx, { filename: paginaF.split('/').pop() }); }
catch (e) { errores.push('carga: ' + e.stack); }
setTimeout(() => {
  const textos = []; const walk = (n) => { for (const c of n.childNodes) { if (c.tagName === '#text') textos.push(c._text); else if (!c.hidden && !('hidden' in c.attrs)) { for (const a of ['title','aria-label','href','placeholder']) if (c.attrs[a]) textos.push('['+a+'='+c.attrs[a]+']'); if (c.href) textos.push('[href='+c.href+']'); walk(c); } } };
  walk(html);
  console.log(JSON.stringify({ errores, titulo: document.title, llamadas, texto: textos.join(' | ') }));
  process.exit(0);
}, 400);
