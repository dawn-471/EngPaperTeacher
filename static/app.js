/* EngPaperTeacher frontend */
'use strict';

const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => [...(el || document).querySelectorAll(s)];

const state = {
  docs: [],
  doc: null,
  chunks: null,
  view: 'read',
  units: null,
  selUnit: null,
  theme: localStorage.getItem('ept-theme') || 'auto',
  selWord: null,
  batchJob: null,
  vocabRows: [],
};

const TAG_CN = { zk: '中考', gk: '高考', cet4: '四级', cet6: '六级', ky: '考研', toefl: '托福', ielts: '雅思', gre: 'GRE' };
const EXCH_CN = { p: '过去式', d: '过去分词', i: '现在分词', '3': '三单', s: '复数', r: '比较级', t: '最高级' };

function elt(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

async function jget(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 3200);
}

/* ---------- boot ---------- */
window.addEventListener('DOMContentLoaded', init);

async function init() {
  applyTheme(state.theme);
  bindUI();
  try {
    const h = await jget('/api/health');
    const dot = $('#dictStatus');
    dot.classList.toggle('off', !h.dict_installed);
    dot.title = h.dict_installed ? '离线词典已安装（ECDICT）' : '离线词典未安装';
    const { docs } = await jget('/api/docs');
    state.docs = docs || [];
    renderDocSelect();
    if (state.docs.length) {
      const saved = localStorage.getItem('ept-doc');
      const pick = state.docs.find(d => d.doc_id === saved) ? saved : state.docs[0].doc_id;
      await loadDoc(pick);
    } else {
      showEmpty(true);
      syncDocActions();
    }
  } catch (e) {
    toast('无法连接后端服务：' + e.message);
  }
}

function bindUI() {
  $$('#themeSeg .seg').forEach(b => b.addEventListener('click', () => applyTheme(b.dataset.themeOpt)));
  const fi = $('#fileInput');
  $('#uploadBtn').addEventListener('click', () => fi.click());
  $('#emptyUpload').addEventListener('click', () => fi.click());
  fi.addEventListener('change', () => { if (fi.files[0]) uploadFile(fi.files[0]); fi.value = ''; });
  $('#docSelect').addEventListener('change', e => loadDoc(e.target.value));
  $('#showRefs').addEventListener('change', e => document.body.classList.toggle('show-refs', e.target.checked));
  let posTimer = null;
  $('#reader').addEventListener('scroll', () => {
    if (!state.doc) return;
    clearTimeout(posTimer);
    posTimer = setTimeout(() => {
      localStorage.setItem('ept-pos-' + state.doc.doc_id, String($('#reader').scrollTop));
    }, 300);
  });
  $('#renameDocBtn').addEventListener('click', renameCurrentDoc);
  $('#reparseBtn').addEventListener('click', reparseCurrentDoc);
  $('#deleteDocBtn').addEventListener('click', deleteCurrentDoc);
  $('#chunkAllBtn').addEventListener('click', runChunkAll);
  $('#chunkMode').addEventListener('change', e => {
    if (e.target.checked) {
      if (state.chunks) applyGlobalChunks();
      else runChunkAll();
    } else {
      clearAllChunks();
    }
  });
  bindSettings();
  bindCourse();
  bindVocab();
  bindTTS();
  document.addEventListener('click', e => {
    if (!e.target.closest('#popup') && !e.target.closest('.word')) hidePopup();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hidePopup(); });
}

function applyTheme(t) {
  if (t === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('ept-theme', t);
  state.theme = t;
  $$('#themeSeg .seg').forEach(b => b.classList.toggle('on', b.dataset.themeOpt === t));
}

/* ---------- docs ---------- */
function renderDocSelect() {
  const sel = $('#docSelect');
  sel.innerHTML = '';
  if (!state.docs.length) {
    sel.append(elt('option', null, '（无文档）'));
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  for (const d of state.docs) {
    const o = elt('option', null, d.title || d.doc_id);
    o.value = d.doc_id;
    sel.append(o);
  }
  if (state.doc) sel.value = state.doc.doc_id;
}

function showEmpty(show) {
  $('#emptyState').hidden = !show;
  $('#article').style.display = show ? 'none' : '';
}

function syncDocActions() {
  const has = !!state.doc;
  $('#renameDocBtn').disabled = !has;
  $('#reparseBtn').disabled = !has;
  $('#deleteDocBtn').disabled = !has;
}

async function renameCurrentDoc() {
  if (!state.doc) return;
  const value = prompt('修改文档标题', state.doc.title || state.doc.doc_id);
  if (value === null) return;
  const title = value.trim();
  if (!title) { toast('标题不能为空'); return; }
  try {
    const r = await fetch('/api/doc/' + encodeURIComponent(state.doc.doc_id), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    state.doc.title = j.title;
    const { docs } = await jget('/api/docs');
    state.docs = docs || [];
    renderDocSelect();
    toast('标题已更新');
  } catch (e) {
    toast('重命名失败：' + e.message);
  }
}

async function loadDoc(docId) {
  try {
    const doc = await jget('/api/doc/' + encodeURIComponent(docId));
    state.doc = doc;
    state.chunks = null;
    state.units = null;
    state.selUnit = null;
    localStorage.setItem('ept-doc', doc.doc_id);
    const cm = $('#chunkMode');
    if (cm) cm.checked = false;
    if (state.view === 'course') refreshUnits();
    renderDoc(doc);
    renderDocSelect();
    showEmpty(false);
    syncDocActions();
    hidePopup();
    const savedPos = parseInt(localStorage.getItem('ept-pos-' + doc.doc_id) || '0', 10);
    if (savedPos > 0) {
      requestAnimationFrame(() => {
        const reader = $('#reader');
        if (reader) reader.scrollTop = savedPos;
      });
    }
  } catch (e) {
    toast('加载文档失败：' + e.message);
  }
}

async function deleteCurrentDoc() {
  if (!state.doc) return;
  const doc = state.doc;
  if (state.batchJob && state.batchJob.doc_id === doc.doc_id) {
    toast('请先取消批量生成，再删除文档');
    return;
  }
  if (!confirm('删除「' + (doc.title || doc.doc_id) + '」及其课程/语块数据？此操作不可撤销。')) return;
  try {
    const r = await fetch('/api/doc/' + encodeURIComponent(doc.doc_id), { method: 'DELETE' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    if (localStorage.getItem('ept-doc') === doc.doc_id) localStorage.removeItem('ept-doc');
    state.doc = null;
    state.units = null;
    state.selUnit = null;
    const { docs } = await jget('/api/docs');
    state.docs = docs || [];
    renderDocSelect();
    if (state.docs.length) await loadDoc(state.docs[0].doc_id);
    else {
      showEmpty(true);
      syncDocActions();
      renderUnitList();
      refreshVocabCount();
    }
    toast('已删除文档');
  } catch (e) {
    toast('删除失败：' + e.message);
  }
}

async function reparseCurrentDoc() {
  if (!state.doc) return;
  const doc = state.doc;
  if (state.batchJob && state.batchJob.doc_id === doc.doc_id) {
    toast('请先取消批量生成，再重新解析');
    return;
  }
  if (!confirm('重新解析「' + (doc.title || doc.doc_id) + '」？标题/段落会更新，已生成的课程学案保留但可能需要重新生成单元划分。')) return;
  const btn = $('#reparseBtn');
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = '解析中…';
  try {
    const r = await fetch('/api/doc/' + encodeURIComponent(doc.doc_id) + '/reparse', { method: 'POST' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    await loadDoc(doc.doc_id);
    toast('已重新解析：' + (j.title || doc.doc_id));
  } catch (e) {
    toast('重新解析失败：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
    syncDocActions();
  }
}

async function uploadFile(file) {
  const btn = $('#uploadBtn');
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '解析中…';
  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/upload', { method: 'POST', body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    const { docs } = await jget('/api/docs');
    state.docs = docs || [];
    await loadDoc(j.doc_id);
    toast('已解析：' + (j.title || j.doc_id) + '（' + j.blocks + ' 块）');
  } catch (e) {
    toast('上传失败：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

/* ---------- render ---------- */
function renderDoc(doc) {
  const art = $('#article');
  art.innerHTML = '';
  const frag = document.createDocumentFragment();
  let lastPage = null;

  for (const b of doc.blocks) {
    if (b.page !== lastPage) {
      const div = elt('div', 'page-divider');
      div.append(elt('span', null, 'Page ' + b.page));
      frag.append(div);
      lastPage = b.page;
    }
    let el;
    if (b.kind === 'title') el = elt('h1', 'blk-title', b.text);
    else if (b.kind === 'meta') el = elt('div', 'blk-meta', b.text);
    else if (b.kind === 'heading') el = elt('h2', 'blk-heading', b.text);
    else if (b.kind === 'ref') el = elt('div', 'blk-ref', b.text);
    else el = renderPara(b);
    el.id = 'blk-' + b.i;
    frag.append(el);
  }
  art.append(frag);
  renderOutline(doc);
}

function renderPara(b) {
  const p = elt('p', 'blk-para');
  const pr = elt('span', 'para-read', '▷');
  pr.title = '整段朗读';
  pr.addEventListener('click', ev => { ev.stopPropagation(); speakParagraph(p); });
  p.append(pr);
  const sents = b.sentences && b.sentences.length ? b.sentences : [b.text];
  sents.forEach((sent, idx) => {
    if (idx) p.append(document.createTextNode(' '));
    const s = elt('span', 'sentence');
    s.dataset.text = sent;
    fillPlain(s, sent);
    p.append(s);
  });
  return p;
}

function fillPlain(s, text) {
  s.innerHTML = '';
  for (const tok of tokenize(text)) {
    if (tok.w) s.append(elt('span', 'word', tok.t));
    else s.append(document.createTextNode(tok.t));
  }
  appendChips(s);
}

function appendChips(s) {
  const chips = elt('span', 'sx-chips');
  for (const pair of [['读', '整句朗读'], ['译', '整句翻译'], ['块', '语块划分'], ['精', 'LLM 精修（需先配置设置）']]) {
    const c = elt('span', 'sx-chip', pair[0]);
    c.title = pair[1];
    chips.append(c);
  }
  s.append(chips);
}

function tokenize(text) {
  const out = [];
  const re = /[A-Za-z][A-Za-z'’-]*/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ t: text.slice(last, m.index), w: false });
    out.push({ t: m[0], w: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ t: text.slice(last), w: false });
  return out;
}

let outlineObs = null;
function renderOutline(doc) {
  const nav = $('#outline');
  nav.innerHTML = '';
  if (outlineObs) { outlineObs.disconnect(); outlineObs = null; }
  const map = new Map();
  outlineObs = new IntersectionObserver(entries => {
    for (const en of entries) {
      if (en.isIntersecting) {
        $$('#outline .outline-item').forEach(b => b.classList.remove('active'));
        const btn = map.get(en.target.id);
        if (btn) btn.classList.add('active');
      }
    }
  }, { rootMargin: '-8% 0px -75% 0px' });

  const sections = doc.sections || [];
  for (const s of sections) {
    const btn = elt('button', 'outline-item', s.title);
    btn.addEventListener('click', () => {
      const t = document.getElementById('blk-' + s.block_index);
      if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    nav.append(btn);
    const blk = document.getElementById('blk-' + s.block_index);
    if (blk) { map.set(blk.id, btn); outlineObs.observe(blk); }
  }
  if (!sections.length) nav.append(elt('div', 'outline-empty', '（未识别到章节标题）'));
}

/* ---------- interactions ---------- */
document.addEventListener('click', e => {
  const sel = window.getSelection().toString().length;
  const w = e.target.closest('.word');
  if (w) {
    if (sel) return;
    onWordClick(w);
    return;
  }
  const s = e.target.closest('.sentence');
  if (!s || sel) return;
  const chip = e.target.closest('.sx-chip');
  if (chip) {
    const t = chip.textContent;
    if (t === '读') { speakSentenceToggle(s); return; }
    if (t === '块') { toggleChunks(s); return; }
    if (t === '精') { refineSentence(s); return; }
    onSentenceClick(s);
    return;
  }
  if (e.target.closest('.chunk')) return;
  onSentenceClick(s);
});

async function onWordClick(wordEl) {
  if (state.selWord) state.selWord.classList.remove('sel');
  state.selWord = wordEl;
  wordEl.classList.add('sel');
  const q = wordEl.textContent;
  const rect = wordEl.getBoundingClientRect();
  showPopupLoading(rect);
  try {
    const res = await jget('/api/word?q=' + encodeURIComponent(q));
    renderWordPopup(res, rect);
  } catch (e) {
    renderWordPopup({ ok: false, word: q }, rect);
  }
}

function showPopupLoading(rect) {
  const el = $('#popup');
  el.innerHTML = '';
  el.append(elt('div', 'pp-loading', '查询中…'));
  positionPopup(el, rect);
  el.hidden = false;
}

function renderWordPopup(res, rect) {
  const el = $('#popup');
  el.innerHTML = '';
  const head = elt('div', 'pp-head');
  head.append(elt('span', 'pp-word', (res.entry && res.entry.word) || res.word || ''));
  if (res.entry && res.entry.phonetic) head.append(elt('span', 'pp-phon', '/' + res.entry.phonetic + '/'));
  const spk = elt('button', 'btn sm pp-speak', '🔊');
  spk.title = '朗读';
  spk.addEventListener('click', ev => {
    ev.stopPropagation();
    ttsSpeakText((res.entry && res.entry.word) || res.word || '');
  });
  head.append(spk);
  el.append(head);

  if (res.entry && res.entry.tags && res.entry.tags.length) {
    const row = elt('div', 'pp-tags');
    for (const t of res.entry.tags) row.append(elt('span', 'tag tag-' + t, TAG_CN[t] || t.toUpperCase()));
    el.append(row);
  }

  const body = elt('div', 'pp-body');
  if (res.entry && res.entry.translation && res.entry.translation.length) {
    for (const line of res.entry.translation) body.append(elt('div', 'pp-line', line));
  } else if (res.translation) {
    body.append(elt('div', 'pp-line', res.translation));
  } else if (!res.ok) {
    body.append(elt('div', 'pp-line pp-miss', '未找到释义（离线词典与在线翻译均未命中）'));
  }
  if (res.entry && res.entry.exchange) {
    const f = fmtExchange(res.entry.exchange);
    if (f) body.append(elt('div', 'pp-exch', '变形：' + f));
  }
  el.append(body);

  if (res.source) {
    const src = res.source === 'ecdict' ? 'ECDICT 本地词典'
      : res.source === 'google' ? 'Google 翻译'
      : res.source === 'mymemory' ? 'MyMemory 翻译' : res.source;
    el.append(elt('div', 'pp-src', src));
  }
  positionPopup(el, rect);
}

function fmtExchange(s) {
  const parts = [];
  for (const seg of s.split('/')) {
    const i = seg.indexOf(':');
    if (i < 0) continue;
    const k = seg.slice(0, i), v = seg.slice(i + 1);
    if (EXCH_CN[k] && v) parts.push(EXCH_CN[k] + ' ' + v);
  }
  return parts.join('；');
}

function positionPopup(el, rect) {
  el.style.left = '0px';
  el.style.top = '0px';
  const bw = el.offsetWidth, bh = el.offsetHeight;
  const left = Math.min(Math.max(12, rect.left - 20), window.innerWidth - bw - 12);
  let top = rect.bottom + 8;
  if (top + bh > window.innerHeight - 12) top = Math.max(12, rect.top - bh - 8);
  el.style.left = left + 'px';
  el.style.top = top + 'px';
}

function hidePopup() {
  const el = $('#popup');
  if (el.hidden) return;
  el.hidden = true;
  el.innerHTML = '';
  if (state.selWord) {
    state.selWord.classList.remove('sel');
    state.selWord = null;
  }
}

async function onSentenceClick(s) {
  const sib = s.nextElementSibling && s.nextElementSibling.classList.contains('cn-tr')
    ? s.nextElementSibling : null;
  if (sib) { sib.hidden = !sib.hidden; return; }
  const tr = elt('span', 'cn-tr', '翻译中…');
  s.after(tr);
  try {
    const r = await fetch('/api/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: s.dataset.text, llm: getLLM() }),
    });
    const res = await r.json().catch(() => ({}));
    if (r.ok && res.ok) {
      tr.textContent = res.text;
    } else {
      const hint = res.errors && res.errors.length ? '（' + res.errors[0] + '）' : '';
      tr.textContent = '翻译失败' + hint + '；可在「设置」配置 LLM 作为兜底';
      tr.classList.add('fail');
    }
  } catch (e) {
    tr.textContent = '翻译失败：' + e.message;
    tr.classList.add('fail');
  }
}

/* ---------- chunks ---------- */
const LABEL_KEY = {
  '主语': 'subject', '谓语': 'verb', '宾语': 'object', '表语': 'complement',
  '状语': 'adverbial', '定语': 'attributive', '介词短语': 'prep', '从句': 'clause',
  '分句': 'sentence_piece', '连接': 'glue', '其他': 'other',
};

function labelKey(c) {
  return c.key || LABEL_KEY[c.label] || 'other';
}

function setSentenceChunks(s, chunks) {
  s.innerHTML = '';
  chunks.forEach((c, idx) => {
    if (idx) s.append(document.createTextNode(' '));
    const sp = elt('span', 'chunk ck-' + labelKey(c));
    sp.title = c.label + (c.note ? '：' + c.note : '');
    for (const tok of tokenize(c.text)) {
      if (tok.w) sp.append(elt('span', 'word', tok.t));
      else sp.append(document.createTextNode(tok.t));
    }
    s.append(sp);
  });
  appendChips(s);
  s.classList.add('chunked');
}

function clearSentenceChunks(s) {
  if (!s.classList.contains('chunked')) return;
  fillPlain(s, s.dataset.text);
  s.classList.remove('chunked');
}

async function toggleChunks(s) {
  if (s.classList.contains('chunked')) { clearSentenceChunks(s); return; }
  let chunks = s.__chunks || (state.chunks && state.chunks[s.dataset.text]);
  if (!chunks) {
    try {
      const res = await jget('/api/chunk?text=' + encodeURIComponent(s.dataset.text));
      chunks = res.chunks;
    } catch (e) { toast('语块划分失败：' + e.message); return; }
  }
  s.__chunks = chunks;
  setSentenceChunks(s, chunks);
}

async function runChunkAll() {
  if (!state.doc) return;
  const btn = $('#chunkAllBtn');
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '划分中…';
  try {
    try {
      state.chunks = await jget('/api/doc/' + state.doc.doc_id + '/chunks');
    } catch (e) {
      const r = await fetch('/api/doc/' + state.doc.doc_id + '/chunk_all', { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || r.status);
      state.chunks = await jget('/api/doc/' + state.doc.doc_id + '/chunks');
      toast('已划分 ' + j.sentences + ' 句 / ' + j.chunks + ' 块');
    }
    if ($('#chunkMode').checked) applyGlobalChunks();
    else toast('语块数据已就绪，勾选「语块模式」查看');
  } catch (e) {
    toast('划分失败：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function applyGlobalChunks() {
  if (!state.chunks) return;
  $$('#article .sentence').forEach(s => {
    const cs = state.chunks[s.dataset.text];
    if (cs) { s.__chunks = cs; setSentenceChunks(s, cs); }
  });
}

function clearAllChunks() {
  $$('#article .sentence.chunked').forEach(clearSentenceChunks);
}

async function refineSentence(s) {
  const llm = getLLM();
  if (!llm.base_url || !llm.model) {
    openSettings();
    toast('请先在「设置」中配置 LLM');
    return;
  }
  const sib = s.nextElementSibling && s.nextElementSibling.classList.contains('chunk-refine')
    ? s.nextElementSibling : null;
  if (sib) { sib.hidden = !sib.hidden; return; }
  const box = elt('span', 'chunk-refine', '精修中…');
  s.after(box);
  try {
    const r = await fetch('/api/chunk/refine', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: s.dataset.text, llm }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    box.innerHTML = '';
    if (j.summary) box.append(elt('div', 'cr-summary', j.summary));
    const list = elt('div', 'cr-list');
    for (const c of j.chunks || []) {
      const row = elt('div', 'cr-row');
      row.append(elt('span', 'cr-text', c.text));
      if (c.label) row.append(elt('span', 'cr-label', c.label));
      if (c.note) row.append(elt('span', 'cr-note', c.note));
      list.append(row);
    }
    box.append(list);
    if (!(j.chunks || []).length) box.textContent = '精修返回为空';
  } catch (e) {
    box.textContent = '精修失败：' + e.message;
    box.classList.add('fail');
  }
}

/* ---------- settings ---------- */
function getLLM() {
  try { return JSON.parse(localStorage.getItem('ept-llm') || '{}'); } catch (e) { return {}; }
}

function openSettings() {
  const llm = getLLM();
  $('#llmBase').value = llm.base_url || '';
  $('#llmKey').value = llm.api_key || '';
  $('#llmModel').value = llm.model || '';
  $('#llmEffort').value = llm.effort || 'off';
  const mtSel = $('#llmMaxTokens');
  mtSel.value = String(llm.max_tokens || 0);
  if (!mtSel.value) mtSel.value = '0';
  $('#llmMsg').textContent = '';
  if ($('#ttsVoice').options.length <= 1) loadTTSVoices();
  $('#settingsModal').hidden = false;
}

function bindSettings() {
  $('#settingsBtn').addEventListener('click', openSettings);
  $('#llmCancel').addEventListener('click', () => { $('#settingsModal').hidden = true; });
  $('#settingsModal').addEventListener('click', e => {
    if (e.target.id === 'settingsModal') e.target.hidden = true;
  });
  $('#llmSave').addEventListener('click', () => {
    localStorage.setItem('ept-llm', JSON.stringify({
      base_url: $('#llmBase').value.trim(),
      api_key: $('#llmKey').value.trim(),
      model: $('#llmModel').value.trim(),
      effort: $('#llmEffort').value || 'off',
      max_tokens: parseInt($('#llmMaxTokens').value, 10) || 0,
    }));
    $('#settingsModal').hidden = true;
    toast('已保存（仅存本机浏览器）');
  });
  $('#llmFetch').addEventListener('click', async () => {
    const base = $('#llmBase').value.trim();
    const key = $('#llmKey').value.trim();
    if (!base) { $('#llmMsg').textContent = '先填 Base URL'; return; }
    $('#llmMsg').textContent = '拉取中…';
    try {
      const res = await fetch('/api/llm/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm: { base_url: base, api_key: key } }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || ('HTTP ' + res.status));
      const dl = $('#modelList');
      dl.innerHTML = '';
      for (const m of j.models || []) {
        const o = document.createElement('option');
        o.value = m;
        dl.append(o);
      }
      $('#llmMsg').textContent = '共 ' + (j.models || []).length + ' 个模型（点 Model 输入框选择）';
      const cur = $('#llmModel').value.trim();
      if (cur && !(j.models || []).includes(cur)) {
        $('#llmMsg').textContent = '共 ' + (j.models || []).length + ' 个模型｜注意：当前填写的「' + cur + '」不在该服务列表中，请从下拉选择';
      }
    } catch (e) {
      $('#llmMsg').textContent = '拉取失败：' + e.message;
    }
  });
  $('#llmTest').addEventListener('click', async () => {
    const llm = {
      base_url: $('#llmBase').value.trim(),
      api_key: $('#llmKey').value.trim(),
      model: $('#llmModel').value.trim(),
      effort: $('#llmEffort').value || 'off',
      max_tokens: parseInt($('#llmMaxTokens').value, 10) || 0,
    };
    if (!llm.base_url || !llm.model) { $('#llmMsg').textContent = '先填 Base URL 和 Model'; return; }
    $('#llmMsg').textContent = '测试中…';
    try {
      const res = await fetch('/api/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || ('HTTP ' + res.status));
      $('#llmMsg').textContent = '✅ 连接成功（模型回复：' + (j.reply || '') + '）';
    } catch (e) {
      $('#llmMsg').textContent = '❌ ' + e.message;
    }
  });
}

/* ---------- TTS (read-aloud) ---------- */
const tts = {
  audio: null,
  queue: [],
  idx: -1,
  playing: false,
  currentEl: null,
  token: 0,
  browserActive: false,
};

function getTTSSettings() {
  try { return JSON.parse(localStorage.getItem('ept-tts') || '{}'); } catch (e) { return {}; }
}

function saveTTSSettings(patch) {
  const s = Object.assign(getTTSSettings(), patch);
  localStorage.setItem('ept-tts', JSON.stringify(s));
  return s;
}

function bindTTS() {
  $('#readAllBtn').addEventListener('click', readAllStart);
  $('#ttsPrev').addEventListener('click', () => ttsSkip(-1));
  $('#ttsNext').addEventListener('click', () => ttsSkip(1));
  $('#ttsPlay').addEventListener('click', ttsTogglePlay);
  $('#ttsStop').addEventListener('click', () => ttsStop(true));
  $('#ttsVoice').addEventListener('change', e => {
    saveTTSSettings({ voice: e.target.value });
    if (tts.playing) ttsRestart();
  });
  $('#ttsRate').addEventListener('change', e => {
    saveTTSSettings({ rate: e.target.value });
    if (tts.playing) ttsRestart();
  });
  $('#ttsFollow').addEventListener('change', e => saveTTSSettings({ follow: e.target.checked }));
  $('#ttsPreview').addEventListener('click', () => {
    ttsSpeakText('The community garden supplies fresh vegetables throughout the summer.');
  });
  const s = getTTSSettings();
  if (s.follow === false) $('#ttsFollow').checked = false;
  if (s.rate) $('#ttsRate').value = s.rate;
  loadTTSVoices();
  window.__ttsState = () => JSON.stringify({
    playing: tts.playing,
    idx: tts.idx,
    len: tts.queue.length,
    t: tts.audio ? Math.round(tts.audio.currentTime * 100) / 100 : 0,
    paused: tts.audio ? tts.audio.paused : null,
    err: tts.audio && tts.audio.error ? tts.audio.error.code : null,
    ba: tts.browserActive,
  });
}

async function loadTTSVoices() {
  const sel = $('#ttsVoice');
  if (tts._voicesLoading) return;
  tts._voicesLoading = true;
  if (!sel.options.length || sel.options[0].value === '') {
    sel.innerHTML = '';
    const ph = elt('option', null, '（加载中…）');
    ph.value = '';
    sel.append(ph);
  }
  try {
    const res = await jget('/api/tts/voices');
    sel.innerHTML = '';
    for (const v of res.voices || []) {
      const o = elt('option', null, v.label);
      o.value = v.id;
      sel.append(o);
    }
    const saved = getTTSSettings().voice;
    if (saved) sel.value = saved;
    if (!sel.value) {
      const pref = ['en-US-AndrewMultilingualNeural', 'en-US-AvaMultilingualNeural', 'en-US-AriaNeural'];
      for (const p of pref) {
        if ([...sel.options].some(o => o.value === p)) { sel.value = p; break; }
      }
    }
    if (!sel.value && sel.options.length) sel.value = sel.options[0].value;
  } catch (e) {
    if (!sel.options.length || sel.options[0].value === '') {
      sel.innerHTML = '';
      const ph = elt('option', null, '（加载失败，重开设置重试）');
      ph.value = '';
      sel.append(ph);
    }
  } finally {
    tts._voicesLoading = false;
  }
}

function ttsSpeakText(text) {
  ttsStartQueue([{ el: null, text }], 0);
}

function speakSentenceToggle(s) {
  if (s.classList.contains('speaking')) { ttsStop(true); return; }
  ttsStartQueue([{ el: s, text: s.dataset.text }], 0);
}

function speakParagraph(pEl) {
  const items = [...pEl.querySelectorAll('.sentence')].map(s => ({ el: s, text: s.dataset.text }));
  if (!items.length) return;
  const active = tts.queue.some(it => it.el && pEl.contains(it.el));
  if (tts.playing && active) { ttsStop(true); return; }
  ttsStartQueue(items, 0);
}

function readAllStart() {
  const items = [...$$('#article .sentence')].map(s => ({ el: s, text: s.dataset.text }));
  if (!items.length) return;
  if (tts.playing && tts.queue.length === items.length) { ttsStop(true); return; }
  let start = 0;
  for (let i = 0; i < items.length; i++) {
    const r = items[i].el.getBoundingClientRect();
    if (r.top >= 60) { start = i; break; }
  }
  ttsStartQueue(items, start);
}

function ttsStartQueue(items, startIdx) {
  ttsStop(true);
  tts.queue = items;
  ttsPlayIndex(startIdx || 0);
}

function ttsStop(clear) {
  tts.token++;
  tts.playing = false;
  tts.browserActive = false;
  if (tts.audio) {
    try { tts.audio.pause(); } catch (e) { /* ignore */ }
    try { tts.audio.removeAttribute('src'); } catch (e) { /* ignore */ }
    try { tts.audio.load(); } catch (e) { /* ignore */ }
    tts.audio = null;
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (tts.currentEl) {
    tts.currentEl.classList.remove('speaking');
    tts.currentEl = null;
  }
  $('#ttsPlay').textContent = '▶';
  if (clear) {
    tts.queue = [];
    tts.idx = -1;
    $('#ttsBar').hidden = true;
    $('#ttsNow').textContent = '';
  }
}

function ttsSkip(delta) {
  if (!tts.queue.length) return;
  const next = Math.max(0, Math.min(tts.queue.length - 1, tts.idx + delta));
  ttsPlayIndex(next);
}

function ttsRestart() {
  if (tts.idx >= 0) ttsPlayIndex(tts.idx);
}

function ttsTogglePlay() {
  if (!tts.queue.length) return;
  if (tts.playing) {
    if (tts.audio && !tts.audio.paused) { try { tts.audio.pause(); } catch (e) { /* ignore */ } }
    if (tts.browserActive && window.speechSynthesis) window.speechSynthesis.cancel();
    tts.browserActive = false;
    tts.playing = false;
    $('#ttsPlay').textContent = '▶';
  } else {
    tts.playing = true;
    $('#ttsPlay').textContent = '⏸';
    const audio = tts.audio;
    if (audio && audio.src && audio.paused && !audio.ended && audio.currentTime > 0) {
      const token = tts.token;
      audio.play().catch(err => {
        if (token === tts.token && !(err && err.name === 'AbortError')) ttsPlayIndex(tts.idx);
      });
    } else {
      ttsPlayIndex(Math.max(0, tts.idx));
    }
  }
}

function ttsPlayIndex(i) {
  if (i < 0 || i >= tts.queue.length) { ttsStop(true); return; }
  const token = ++tts.token;   // supersedes every older playback callback
  tts.browserActive = false;
  if (tts.audio) {             // hard-stop the previous clip
    try { tts.audio.pause(); } catch (e) { /* ignore */ }
    tts.audio = null;
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  tts.idx = i;
  const item = tts.queue[i];
  if (tts.currentEl) tts.currentEl.classList.remove('speaking');
  tts.currentEl = item.el || null;
  if (item.el) item.el.classList.add('speaking');
  $('#ttsBar').hidden = false;
  $('#ttsPlay').textContent = '⏸';
  tts.playing = true;
  const s = getTTSSettings();
  const voice = $('#ttsVoice').value || s.voice || 'en-US-AriaNeural';
  const rate = $('#ttsRate').value || s.rate || '-10%';
  $('#ttsNow').textContent = (i + 1) + '/' + tts.queue.length + ' · ' + (item.text || '').slice(0, 60);
  if (s.follow !== false && item.el) item.el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  const nxt = tts.queue[i + 1];
  if (nxt) {
    fetch('/api/tts?text=' + encodeURIComponent(nxt.text)
      + '&voice=' + encodeURIComponent(voice) + '&rate=' + encodeURIComponent(rate)).catch(() => {});
  }
  const url = '/api/tts?text=' + encodeURIComponent(item.text)
    + '&voice=' + encodeURIComponent(voice) + '&rate=' + encodeURIComponent(rate);
  const audio = new Audio(url);
  tts.audio = audio;
  audio.addEventListener('ended', () => {
    if (token === tts.token && tts.playing) ttsPlayIndex(tts.idx + 1);
  });
  audio.addEventListener('error', () => {
    if (token === tts.token && tts.playing && audio === tts.audio) ttsBrowserSpeak(item, token);
  });
  audio.play().catch(err => {
    if (token !== tts.token) return;                 // superseded by a newer action
    if (err && err.name === 'AbortError') return;    // interrupted on purpose (switch/stop)
    if (audio === tts.audio && tts.playing) ttsBrowserSpeak(item, token);
  });
}

function ttsBrowserSpeak(item, token) {
  if (token !== tts.token) return;
  if (!('speechSynthesis' in window) || !window.SpeechSynthesisUtterance) {
    toast('朗读失败：在线语音与浏览器语音均不可用');
    ttsStop(true);
    return;
  }
  tts.browserActive = true;
  if (tts.audio) { try { tts.audio.pause(); } catch (e) { /* ignore */ } }
  const u = new SpeechSynthesisUtterance(item.text);
  u.lang = 'en-US';
  u.rate = 0.95;
  const adv = () => { if (token === tts.token && tts.playing) ttsPlayIndex(tts.idx + 1); };
  u.onend = adv;
  u.onerror = adv;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

/* ---------- course mode ---------- */
const CARD_TITLES = ['① 通读预判', '② 长难句拆解', '③ 词汇卡', '④ 语法点', '⑤ 同义替换', '⑥ 练习', '⑦ 输出'];
const EX_TYPES = { tfng: '判断', cloze: '填空', translate: '翻译' };

function bindCourse() {
  $$('#viewSeg .seg').forEach(b => b.addEventListener('click', () => switchView(b.dataset.view)));
  $('#buildUnitsBtn').addEventListener('click', buildUnits);
  $('#genLessonBtn').addEventListener('click', generateLesson);
  $('#genAllBtn').addEventListener('click', generateAllLessons);
  $('#vocabExportBtn').addEventListener('click', () => window.open('/api/vocab/export', '_blank'));
}

function switchView(view) {
  state.view = view;
  $$('#viewSeg .seg').forEach(b => b.classList.toggle('on', b.dataset.view === view));
  const course = view === 'course';
  $('#course').hidden = !course;
  $('.sidebar').hidden = course;
  $('.reader').hidden = course;
  if (course) {
    refreshUnits();
    refreshVocabCount();
  }
}

async function refreshUnits() {
  if (!state.doc) return;
  try {
    const res = await jget('/api/doc/' + state.doc.doc_id + '/course/units');
    state.units = res.units || [];
  } catch (e) {
    state.units = [];
  }
  renderUnitList();
}

function renderUnitList() {
  const nav = $('#unitList');
  nav.innerHTML = '';
  if (!state.units || !state.units.length) {
    nav.append(elt('div', 'outline-empty', '（还没有单元划分）'));
    return;
  }
  for (const u of state.units) {
    const b = elt('button', 'unit-item' + (state.selUnit === u.id ? ' sel' : ''));
    b.append(document.createTextNode(u.title));
    b.append(elt('span', 'u-meta', u.words + '词'));
    if (u.has_lesson) b.append(elt('span', 'u-done', '已生成'));
    b.addEventListener('click', () => selectUnit(u.id));
    nav.append(b);
  }
}

async function buildUnits() {
  if (!state.doc) return;
  const btn = $('#buildUnitsBtn');
  btn.disabled = true;
  btn.textContent = '划分中…';
  try {
    const r = await fetch('/api/doc/' + state.doc.doc_id + '/course/units', { method: 'POST' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || r.status);
    state.units = j.units || [];
    renderUnitList();
    toast('已生成 ' + state.units.length + ' 个单元');
  } catch (e) {
    toast('生成失败：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '生成单元划分';
  }
}

async function selectUnit(uid) {
  state.selUnit = uid;
  renderUnitList();
  try {
    const res = await jget('/api/doc/' + state.doc.doc_id + '/course/lesson/' + uid);
    renderLesson(res.lesson);
  } catch (e) {
    const m = $('#courseMain');
    m.innerHTML = '';
    const d = elt('div', 'empty');
    d.append(elt('div', 'empty-title', '该单元尚未生成学案'));
    d.append(elt('div', 'empty-sub', '点击左栏「生成当前单元学案」（需配置 LLM）'));
    m.append(d);
  }
}

async function generateLesson() {
  if (!state.doc || state.selUnit == null) { toast('先在左栏选择一个单元'); return; }
  const llm = getLLM();
  if (!llm.base_url || !llm.model) { openSettings(); toast('请先配置 LLM'); return; }
  const btn = $('#genLessonBtn');
  btn.disabled = true;
  btn.textContent = '生成中…（约 30-90 秒）';
  try {
    const r = await fetch('/api/doc/' + state.doc.doc_id + '/course/lesson/' + state.selUnit, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    renderLesson(j.lesson);
    toast('学案已生成' + (j.vocab_added ? '，新增 ' + j.vocab_added + ' 个生词入词库' : ''));
    refreshUnits();
    refreshVocabCount();
  } catch (e) {
    toast('生成失败：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '生成当前单元学案';
  }
}

async function refreshVocabCount() {
  try {
    const res = await jget('/api/vocab');
    $('#vocabCount').textContent = '词库：' + (res.rows || []).length + ' 词';
  } catch (e) { /* ignore */ }
}

function updateBatchUI() {
  const btn = $('#genAllBtn');
  const msg = $('#batchMsg');
  const job = state.batchJob;
  if (!job) {
    btn.disabled = false;
    btn.textContent = '补齐全部学案';
    msg.textContent = '';
    return;
  }
  if (job.state === 'running') {
    btn.disabled = false;
    btn.textContent = '取消批量生成 (' + job.done + '/' + job.total + ')';
    msg.textContent = (job.current ? '正在生成：' + job.current : '等待中…')
      + (job.errors && job.errors.length ? '；失败 ' + job.errors.length : '');
  } else {
    btn.disabled = false;
    btn.textContent = '补齐全部学案';
    msg.textContent = job.state === 'cancelled'
      ? '已取消（完成 ' + job.done + '/' + job.total + '）'
      : '完成 ' + job.done + '/' + job.total
        + (job.errors && job.errors.length ? '，失败 ' + job.errors.length : '');
  }
}

async function generateAllLessons() {
  if (!state.doc) { toast('先选择一个文档'); return; }
  if (state.batchJob) { await cancelBatch(); return; }
  const llm = getLLM();
  if (!llm.base_url || !llm.model) { openSettings(); toast('请先配置 LLM'); return; }
  if (!state.units) await refreshUnits();
  if (!state.units || !state.units.length) {
    toast('请先在课程模式生成单元划分');
    return;
  }
  const missing = state.units.filter(u => !u.has_lesson);
  if (!missing.length) { toast('所有单元均已有学案'); return; }
  if (!confirm('将依次生成 ' + missing.length + ' 个学案（需要 LLM，可能耗时较长）。继续？')) return;
  const btn = $('#genAllBtn');
  btn.disabled = true;
  btn.textContent = '启动中…';
  try {
    const r = await fetch('/api/doc/' + state.doc.doc_id + '/course/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm, only_missing: true }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    if (!j.job) {
      btn.disabled = false;
      updateBatchUI();
      toast('没有需要生成的单元');
      return;
    }
    state.batchJob = Object.assign({ doc_id: state.doc.doc_id }, j.job);
    updateBatchUI();
    pollBatch();
  } catch (e) {
    btn.disabled = false;
    updateBatchUI();
    toast('启动批量生成失败：' + e.message);
  }
}

async function cancelBatch() {
  const job = state.batchJob;
  if (!job) return;
  const btn = $('#genAllBtn');
  btn.disabled = true;
  btn.textContent = '正在取消…';
  try {
    await fetch('/api/doc/' + job.doc_id + '/course/batch/' + job.id + '/cancel',
      { method: 'POST' });
  } catch (e) {
    toast('取消失败：' + e.message);
  } finally {
    btn.disabled = false;
    updateBatchUI();
  }
}

async function pollBatch() {
  const job = state.batchJob;
  if (!job) return;
  try {
    const res = await jget('/api/doc/' + job.doc_id + '/course/batch/' + job.id);
    state.batchJob = Object.assign({ doc_id: job.doc_id }, res.job);
    updateBatchUI();
    if (res.job.state === 'running') {
      setTimeout(pollBatch, 1500);
      return;
    }
    const doneJob = res.job;
    state.batchJob = null;
    updateBatchUI();
    if (state.doc && state.doc.doc_id === job.doc_id) {
      await refreshUnits();
      refreshVocabCount();
      if (state.selUnit != null) await selectUnit(state.selUnit);
      if (doneJob.errors && doneJob.errors.length) {
        toast('批量完成：' + doneJob.done + '/' + doneJob.total
          + '，失败 ' + doneJob.errors.length + '（详见 batch 状态）');
      } else {
        toast('批量完成：' + doneJob.done + '/' + doneJob.total + ' 个学案');
      }
    }
  } catch (e) {
    state.batchJob = null;
    updateBatchUI();
    toast('批量状态获取失败：' + e.message);
  }
}

/* ---------- vocab manager ---------- */
let vocabTimer = null;

function bindVocab() {
  $('#vocabManageBtn').addEventListener('click', openVocab);
  $('#vocabClose').addEventListener('click', closeVocab);
  $('#vocabModal').addEventListener('click', e => {
    if (e.target.id === 'vocabModal') closeVocab();
  });
  $('#vocabRefresh').addEventListener('click', loadVocab);
  $('#vocabSearch').addEventListener('input', () => {
    clearTimeout(vocabTimer);
    vocabTimer = setTimeout(loadVocab, 250);
  });
  $('#vocabExportBtn2').addEventListener('click', () => window.open('/api/vocab/export', '_blank'));
  $('#vocabAddBtn').addEventListener('click', addVocab);
  $('#vocabNewWord').addEventListener('keydown', e => { if (e.key === 'Enter') addVocab(); });
}

function openVocab() {
  $('#vocabModal').hidden = false;
  $('#vocabMsg').textContent = '';
  loadVocab();
}

function closeVocab() {
  $('#vocabModal').hidden = true;
}

async function loadVocab() {
  const q = $('#vocabSearch').value.trim();
  try {
    const res = await jget('/api/vocab' + (q ? '?q=' + encodeURIComponent(q) : ''));
    state.vocabRows = res.rows || [];
    renderVocab();
    $('#vocabMsg').textContent = '共 ' + state.vocabRows.length + ' 词';
  } catch (e) {
    $('#vocabMsg').textContent = '加载失败：' + e.message;
  }
}

function renderVocab() {
  const box = $('#vocabList');
  box.innerHTML = '';
  if (!state.vocabRows.length) {
    box.append(elt('div', 'vocab-empty', '没有匹配的单词'));
    return;
  }
  const t = document.createElement('table');
  const head = document.createElement('tr');
  for (const h of ['单词', '音标', '词性', '释义', '来源', '笔记', '操作']) {
    head.append(elt('th', null, h));
  }
  t.append(head);
  for (const r of state.vocabRows) {
    const tr = document.createElement('tr');
    const wd = elt('td');
    wd.append(elt('strong', null, r.word || ''));
    tr.append(wd);
    tr.append(elt('td', null, r.phonetic || ''));
    tr.append(elt('td', null, r.pos || ''));
    tr.append(elt('td', null, r.meaning_cn || ''));
    tr.append(elt('td', null, r.source || ''));
    tr.append(elt('td', null, r.note || ''));
    const op = elt('td');
    const ed = elt('button', 'btn vrow-del', '改释义');
    ed.title = '修改中文释义';
    ed.addEventListener('click', () => editVocabMeaning(r));
    const del = elt('button', 'btn vrow-del', '删除');
    del.addEventListener('click', () => deleteVocab(r.word));
    op.append(ed, del);
    tr.append(op);
    t.append(tr);
  }
  box.append(t);
}

async function addVocab() {
  const word = $('#vocabNewWord').value.trim();
  if (!word) return;
  const meaning = $('#vocabNewMeaning').value.trim();
  const btn = $('#vocabAddBtn');
  btn.disabled = true;
  try {
    const r = await fetch('/api/vocab/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word, meaning_cn: meaning, source: 'manual' }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    if (!j.added) {
      $('#vocabMsg').textContent = '「' + word + '」已在词库中';
    } else {
      $('#vocabMsg').textContent = '已添加「' + word + '」';
      $('#vocabNewWord').value = '';
      $('#vocabNewMeaning').value = '';
    }
    await loadVocab();
    refreshVocabCount();
  } catch (e) {
    $('#vocabMsg').textContent = '添加失败：' + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function editVocabMeaning(row) {
  const value = prompt('修改「' + row.word + '」的释义', row.meaning_cn || '');
  if (value === null) return;
  try {
    const r = await fetch('/api/vocab/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word: row.word, patch: { meaning_cn: value.trim() } }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    await loadVocab();
  } catch (e) {
    $('#vocabMsg').textContent = '更新失败：' + e.message;
  }
}

async function deleteVocab(word) {
  if (!confirm('从词库删除「' + word + '」？')) return;
  try {
    const r = await fetch('/api/vocab/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
    $('#vocabMsg').textContent = '已删除「' + word + '」';
    await loadVocab();
    refreshVocabCount();
  } catch (e) {
    $('#vocabMsg').textContent = '删除失败：' + e.message;
  }
}

function lessonCard(title) {
  const c = elt('div', 'ls-card');
  c.append(elt('div', 'ls-card-title', title));
  return c;
}

function renderLesson(lesson) {
  const m = $('#courseMain');
  m.innerHTML = '';
  const wrap = elt('div', 'lesson');
  wrap.append(elt('h1', 'lesson-title', lesson.title || '学案'));
  const ov = lesson.overview || {};
  if ((ov.questions || []).length) {
    const c = lessonCard(CARD_TITLES[0]);
    const ul = elt('ul', 'q-list');
    for (const q of ov.questions) ul.append(elt('li', null, q));
    c.append(ul);
    wrap.append(c);
  }
  if ((lesson.sentences || []).length) {
    const c = lessonCard(CARD_TITLES[1]);
    for (const s of lesson.sentences) {
      const b = elt('div', 'ls-block');
      b.append(elt('div', 'ls-sent', s.text || ''));
      if (s.structure) b.append(elt('div', 'ls-struct', '结构：' + s.structure));
      if (s.translation) b.append(elt('div', 'ls-trans', '译文：' + s.translation));
      c.append(b);
    }
    wrap.append(c);
  }
  if ((lesson.vocab || []).length) {
    const c = lessonCard(CARD_TITLES[2]);
    const t = document.createElement('table');
    t.className = 'vocab-table';
    const head = document.createElement('tr');
    for (const h of ['词', '音标', '词性', '释义', '搭配', '例句']) head.append(elt('th', null, h));
    t.append(head);
    for (const v of lesson.vocab) {
      const tr = document.createElement('tr');
      const wd = elt('td');
      wd.append(elt('strong', null, v.word || ''));
      for (const tg of (v.tags || [])) wd.append(elt('span', 'tag tag-' + tg, TAG_CN[tg] || tg.toUpperCase()));
      tr.append(wd);
      tr.append(elt('td', null, v.phonetic || ''));
      tr.append(elt('td', null, v.pos || ''));
      tr.append(elt('td', null, v.meaning_cn || ''));
      tr.append(elt('td', null, v.collocations || ''));
      tr.append(elt('td', null, v.example || ''));
      t.append(tr);
    }
    c.append(t);
    wrap.append(c);
  }
  if ((lesson.grammar || []).length) {
    const c = lessonCard(CARD_TITLES[3]);
    for (const g of lesson.grammar) {
      const b = elt('div', 'ls-block');
      b.append(elt('div', 'ls-sent', g.point || ''));
      if (g.explain) b.append(elt('div', 'ls-struct', g.explain));
      if (g.example) b.append(elt('div', 'ls-trans', '例：' + g.example));
      c.append(b);
    }
    wrap.append(c);
  }
  if ((lesson.paraphrase || []).length) {
    const c = lessonCard(CARD_TITLES[4]);
    const t = document.createElement('table');
    t.className = 'vocab-table';
    const head = document.createElement('tr');
    for (const h of ['原文', '替换表达', '说明']) head.append(elt('th', null, h));
    t.append(head);
    for (const p of lesson.paraphrase) {
      const tr = document.createElement('tr');
      tr.append(elt('td', null, p.original || ''));
      tr.append(elt('td', null, p.alternative || ''));
      tr.append(elt('td', null, p.note || ''));
      t.append(tr);
    }
    c.append(t);
    wrap.append(c);
  }
  if ((lesson.exercises || []).length) {
    const c = lessonCard(CARD_TITLES[5]);
    for (const ex of lesson.exercises) c.append(renderExercise(ex));
    wrap.append(c);
  }
  if ((lesson.output || []).length) {
    const c = lessonCard(CARD_TITLES[6]);
    const ul = elt('ul', 'q-list');
    for (const o of lesson.output) ul.append(elt('li', null, o.task || ''));
    c.append(ul);
    wrap.append(c);
  }
  if (lesson.generated_at) wrap.append(elt('div', 'lesson-foot', '生成于 ' + lesson.generated_at));
  m.append(wrap);
}

function normAnswer(value) {
  return String(value || '').toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, ' ')
    .replace(/\b(?:a|an|the)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function answerCandidates(answer) {
  const parts = String(answer || '').split(/[;；|/]+/).map(s => s.trim()).filter(Boolean);
  return parts.length ? parts : [String(answer || '').trim()];
}

function answerMatches(typed, answer) {
  const got = normAnswer(typed);
  if (!got) return false;
  return answerCandidates(answer).some(c => normAnswer(c) === got);
}

function tfngKey(value) {
  const v = String(value || '').trim().toUpperCase().replace(/\s+/g, ' ');
  if (v === 'T' || v === 'TRUE' || v === 'YES' || v === 'Y') return 'T';
  if (v === 'F' || v === 'FALSE' || v === 'NO' || v === 'N') return 'F';
  if (v === 'NG' || v === 'NOT GIVEN' || v === 'NOTGIVEN') return 'NG';
  return v;
}

function renderExercise(ex) {
  const b = elt('div', 'ex-block');
  b.append(elt('span', 'ex-type', EX_TYPES[ex.type] || ex.type || '练习'));
  b.append(elt('span', 'ex-q', ex.question || ''));
  const ans = elt('div', 'ex-ans');
  ans.hidden = true;
  ans.append(elt('div', null, '答案：' + (ex.answer || '')));
  if (ex.explain) ans.append(elt('div', 'ex-explain', ex.explain));
  if (ex.type === 'tfng') {
    const row = elt('div', 'ex-btns');
    const expected = tfngKey(ex.answer);
    for (const opt of ['T', 'F', 'NG']) {
      const ob = elt('button', 'btn ex-opt', opt);
      ob.addEventListener('click', () => {
        for (const other of row.querySelectorAll('.ex-opt')) {
          other.classList.remove('ok', 'bad');
        }
        ob.classList.add(opt === expected ? 'ok' : 'bad');
        ans.hidden = false;
      });
      row.append(ob);
    }
    b.append(row);
  } else {
    const row = elt('div', 'ex-actions');
    const inp = elt('input', 'ex-input');
    inp.placeholder = '你的答案…（多个答案可用 / 或 ; 分隔）';
    const ck = elt('button', 'btn', '核对');
    ck.addEventListener('click', () => {
      const ok = answerMatches(inp.value, ex.answer);
      inp.classList.remove('ok', 'bad');
      inp.classList.add(ok ? 'ok' : 'bad');
      ans.hidden = false;
    });
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') ck.click(); });
    row.append(inp, ck);
    b.append(row);
  }
  const show = elt('button', 'btn link', '查看答案');
  show.addEventListener('click', () => { ans.hidden = !ans.hidden; });
  b.append(show);
  b.append(ans);
  return b;
}
