#!/usr/bin/env node
// Смоук-тест интерфейса админки: каждый раздел — отдельная HTML-страница на своём URL,
// поэтому проверяем переходы по ссылкам, живучесть фильтров после перезагрузки
// и отсутствие JS-ошибок/4xx на каждой странице.
//
//   node tests/ui_smoke.mjs [http://127.0.0.1:8012] [user] [pass]
//
// Ожидания адаптивные (poll до TIMEOUT): сервер на 1 CPU через SSH-туннель отвечает
// медленно, фиксированные паузы давали бы ложные падения.
//
// Только read-only взаимодействия (навигация, фильтры, поиск, пагинация, раскрытие
// лога). Исключение — dry-run задача постинга, если журнал пуст: в VK ничего не уходит.
import { Browser, sleep } from '/Users/eryashevs/.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const BASE = (process.argv[2] || 'http://127.0.0.1:8012').replace(/\/$/, '');
const USER = process.argv[3] || '';
const PASS = process.argv[4] || '';
// имя раздела -> путь; порядок = обход тестом
const ROUTES = [['dash', '/'], ['ads', '/ads'], ['sources', '/sources'], ['vk', '/vk'],
  ['jobs', '/jobs'], ['logs', '/logs'], ['settings', '/settings']];
const SHOTS = 'data/screens';
const TIMEOUT = Number(process.env.UI_SMOKE_TIMEOUT || 30000);

let fails = 0;
const check = (name, ok, detail = '') => {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) fails++;
};

// Опрос страницы до истечения TIMEOUT; возвращает последнее измеренное значение.
async function untilVal(page, fn, arg, pred) {
  const t0 = Date.now();
  let v;
  for (;;) {
    v = await page.eval(fn, arg);
    if (pred(v)) return v;
    if (Date.now() - t0 > TIMEOUT) return v;
    await sleep(300);
  }
}

// Готов ли раздел: страница в DOM, скелетоны заменены данными, ошибки загрузки нет.
const MEASURE = (want) => {
  const T = (sel) => {
    const e = document.querySelector(sel);
    return e ? e.textContent.replace(/\s+/g, ' ').trim() : null;
  };
  const N = (sel) => document.querySelectorAll(sel).length;
  const page = document.body.dataset.page;
  const main = document.querySelector('.page');
  const out = {
    want,
    page,
    chars: main ? main.textContent.replace(/\s+/g, ' ').trim().length : 0,
    skeleton: N('.skel'),
    errline: N('.errline'),
    navCurrent: (document.querySelector('.nitem[aria-current=page]') || {}).dataset?.page ||
      (document.querySelector('.nitem[aria-current=page]') || {}).dataset?.nav || null,
    href: location.pathname + location.search,
    dupIds: (() => {
      const seen = new Map();
      document.querySelectorAll('[id]').forEach(e => seen.set(e.id, (seen.get(e.id) || 0) + 1));
      return [...seen].filter(([, n]) => n > 1).map(([i, n]) => `${i}×${n}`);
    })(),
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
  out.ready = out.page === want && out.skeleton === 0 && out.chars > 60 && out.errline === 0;
  if (want === 'dash') {
    out.kpi = N('#kpis .kpi');
    out.kpiValues = [...document.querySelectorAll('#kpis .kpi')].map(e => e.textContent.replace(/\s+/g, ' ').trim());
    out.stages = N('#pipe .stage');
    out.risks = N('#risks .risk');
    out.recent = N('#dashRecent .adcard');
    out.posts = N('#dashPosts .lrow');
    out.jobs = N('#dashJobs .lrow');
    out.sched = N('#schedCard .kv');
    out.vkcard = N('#dashVkCard .kv');
    out.ready = out.ready && out.kpi === 4 && out.recent > 0;
  }
  if (want === 'ads') {
    out.chips = [...document.querySelectorAll('#adCounts button[data-f]')].map(e => e.textContent.replace(/\s+/g, ' ').trim());
    out.rows = N('#adsBody tr[data-id]');
    out.count = T('#adsCount');
    out.pager = T('#adsPage');
    out.sel = (document.querySelector('#adCounts button.sel') || {}).dataset?.f || null;
    out.exportHref = (document.getElementById('adsExport') || {}).href || null;
    out.vkLinks = N('#adsBody a[href*="vk.com"]');
    out.thumbs = N('#adsBody .thumb');
    out.ready = out.ready && out.rows > 0 && out.chips.length === 4;
  }
  if (want === 'sources') {
    out.rows = N('#srcBody tr[data-url]');
    out.add = !!document.getElementById('srcUrl');
    out.pills = [...document.querySelectorAll('#srcBody .pill')].map(e => e.textContent.trim());
    out.ready = out.ready && out.rows > 0 && out.add;
  }
  if (want === 'vk') {
    out.kpi = N('#vkKpis .kpi');
    out.kv = N('#vkCard .kv');
    out.card = (T('#vkCard') || '').slice(0, 90);
    out.preview = (T('#pvCard') || '').length;
    out.history = N('#vkHistBody tr');
    out.oauth = (document.getElementById('vkOauthLink') || {}).href || null;
    out.ready = out.ready && out.kv > 0 && out.preview > 0;
  }
  if (want === 'jobs') {
    out.rows = N('#jobsBody tr[data-job]');
    out.logRows = N('#jobsBody tr.logtr');
    out.empty = N('#jobsBody .empty');
    out.pills = [...document.querySelectorAll('#jobsBody .pill')].map(e => e.textContent.trim());
    // журнал живёт в памяти процесса: пустой список с подписью — тоже отрисованное состояние
    out.ready = out.ready && (out.rows > 0 || out.empty > 0);
  }
  if (want === 'logs') {
    out.tail = (T('#logbox') || '').length;
    out.auto = !!document.getElementById('logAuto');
    out.download = !!document.querySelector('a[href="/api/logs?download=1"]');
    out.ready = out.ready && out.tail > 20 && out.auto;
  }
  if (want === 'settings') {
    const num = ['s_frl', 's_pages', 's_batch', 's_publish'];
    out.filled = num.filter(id => { const e = document.getElementById(id); return e && e.value !== ''; }).length;
    out.toggles = ['s_details', 's_photos', 's_paused', 's_reqphotos'].filter(id => !!document.getElementById(id)).length;
    out.proxy = (T('#proxyCard') || '').slice(0, 90);
    const tk = document.getElementById('s_vktoken');
    const mask = T('#s_vktoken_state') || '';
    out.tokenEmpty = !!tk && tk.value === '';
    out.tokenMasked = /симв|маск|ключ/i.test(mask) && !/vk1\.a\.[A-Za-z0-9]{20}/.test(mask + (tk ? tk.value : ''));
    out.advanced = !!document.getElementById('advRow')?.hidden;
    out.ready = out.ready && out.filled === 4 && out.toggles === 4;
  }
  return out;
};

const browser = await Browser.launch({ width: 1440, height: 900 });
const page = await browser.newPage({ width: 1440, height: 900 });
await page.send('Page.enable');
await page.send('Network.enable');

const badResponses = [];
browser.on(page.sessionId, 'Network.responseReceived', (p) => {
  const { url, status } = p.response;
  // 404 на /photo — штатное поведение (снимок мог быть удалён из data/photos), не считаем ошибкой
  if (status >= 400 && /\/api\/|export\.csv|\/job\/|\/login|\/logs|\/settings/.test(url)) {
    badResponses.push(`${status} ${url}`);
  }
});

await page.goto(BASE, { settleMs: 800 });

if (USER && PASS) {
  const code = await page.eval(async (o) => {
    const r = await fetch(o.base + '/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: o.u, password: o.p }),
    });
    return r.status;
  }, { base: BASE, u: USER, p: PASS });
  if (code !== 200) { console.log(`FAIL вход: HTTP ${code} для ${USER}`); await browser.close(); process.exit(1); }
  await page.goto(BASE, { settleMs: 800 });
  console.log('вход выполнен:', USER, '→', BASE);
}

const shell = await untilVal(page, () => ({
  nav: [...document.querySelectorAll('.nitem')].map(a => a.getAttribute('href')),
  sidebar: !!document.getElementById('side'),
  topbar: !!document.getElementById('stamp') && !!document.getElementById('vkDot'),
  crumb: (document.getElementById('crumb') || {}).textContent || '',
  chromeGlobal: (() => {
    const st = document.getElementById('status'), jl = document.getElementById('joblog');
    return !!(st && jl) && !st.closest('.page') && !jl.closest('.page');
  })(),
  theme: document.documentElement.dataset.theme,
}), null, (v) => v.nav.length > 0);
console.log('\nКАРКАС');
check('пункты навигации = разделы', shell.nav.length === ROUTES.length, `${shell.nav.length}/${ROUTES.length}`);
check('ссылки ведут на URL разделов', shell.nav.join(' ') === ['/', '/ads', '/sources', '/vk', '/jobs', '/logs', '/settings'].join(' '), shell.nav.join(' '));
check('топбар с состоянием VK', shell.topbar);
check('хлебные крошки', shell.crumb.length > 0, shell.crumb);
check('статус и живой лог — вне содержимого раздела', shell.chromeGlobal);
check('тема задана до отрисовки', ['light', 'dark'].includes(shell.theme), shell.theme);

const R = {};
for (const [name, path] of ROUTES) {
  const before = page.consoleErrors.length;
  await page.goto(BASE + path, { settleMs: 400 });
  R[name] = await untilVal(page, MEASURE, name, (v) => v.ready || v.errline > 0);
  console.log(`\nСТРАНИЦА ${path} (${R[name].chars} симв.)`);
  check('отрисован нужный раздел', R[name].page === name, `${R[name].page} (ожидался ${name})`);
  check('навигация подсвечивает активный', R[name].navCurrent === name, String(R[name].navCurrent));
  check('нет ошибки загрузки', R[name].errline === 0);
  check('данные отрисованы', R[name].ready, `скелетонов ${R[name].skeleton}, ${R[name].chars} симв.`);
  check('нет дублей id', R[name].dupIds.length === 0, R[name].dupIds.join(', '));
  check('нет горизонтального скролла', !R[name].overflowX);
  if (page.consoleErrors.length > before) {
    check('JS при переходе', false, page.consoleErrors.slice(before).join(' | '));
  }
}

console.log('\nДАННЫЕ');
const d = R.dash;
check('KPI-полоса', d.kpi === 4, d.kpiValues.join(' · '));
check('конвейер из 4 стадий', d.stages === 4, `${d.stages}`);
check('строка рисков', d.risks > 0, `${d.risks}`);
check('последние объявления', d.recent > 0, `${d.recent} карточек`);
check('виджет постов', d.posts >= 0, `${d.posts} строк`);
check('виджет задач', d.jobs >= 0, `${d.jobs} строк`);
check('расписание крона', d.sched >= 3, `${d.sched} строк`);
check('VK-сводка на дашборде', d.vkcard >= 4, `${d.vkcard} строк`);
const a = R.ads;
check('счётчики-фильтры', a.chips.length === 4, a.chips.join(' / '));
check('таблица объявлений', a.rows > 0, `${a.rows} строк`);
check('миниатюры фото', a.thumbs > 0, `${a.thumbs}`);
check('счётчик записей', /показано .* из /.test(a.count || ''), a.count);
check('пагинатор «страница / всего»', /^\d+ \/ \d+$/.test(a.pager || ''), a.pager);
check('CSV-ссылка с текущим фильтром', /export\.csv\?filter=all/.test(a.exportHref || ''), a.exportHref);
const so = R.sources;
check('источники отрисованы', so.rows > 0, `${so.rows} строк · ${so.pills.slice(0, 3).join(', ')}`);
const v = R.vk;
check('карточка канала', /ключ|сообщество|стена/i.test(v.card), v.card);
check('KPI канала', v.kpi === 4, `${v.kpi}`);
check('предпросмотр поста', v.preview > 20, `${v.preview} симв.`);
check('OAuth-ссылка на user-ключ', /client_id=\d+/.test(v.oauth || ''), v.oauth || 'нет');
const lg = R.logs;
check('хвост лога', lg.tail > 20, `${lg.tail} симв.`);
check('скачивание лога доступно', lg.download);
const s = R.settings;
check('числовые настройки из БД', s.filled === 4, `${s.filled}/4`);
check('переключатели настроек', s.toggles === 4, `${s.toggles}/4`);
check('статус прокси виден', /прокси|proxy|socks|карант|прям|адресов|пул|здоров/i.test(s.proxy), s.proxy);
check('ключ VK не светится в форме', s.tokenEmpty && s.tokenMasked, `поле пустое: ${s.tokenEmpty}`);

// опубликованные посты: проверяем историю только если они реально есть в базе
const posted = await page.eval(async () => {
  const r = await fetch('/api/state');
  const j = await r.json();
  return (j.db || {}).posted || 0;
});
await page.goto(BASE + '/vk', { settleMs: 400 });
const vkHist = await untilVal(page, MEASURE, 'vk', (x) => x.ready || x.errline > 0);
check('история публикаций соответствует базе',
  posted > 0 ? vkHist.history > 0 : true,
  `${vkHist.history} строк при ${posted} опубликованных`);

console.log('\nИНТЕРАКТИВ');
await page.goto(BASE + '/ads', { settleMs: 400 });
await untilVal(page, () => document.querySelectorAll('#adCounts button[data-f]').length === 4, null, Boolean);
const chipClicked = await page.eval(() => {
  const b = [...document.querySelectorAll('#adCounts button[data-f]')].find(x => x.dataset.f === 'posted');
  if (!b) return false;
  b.click();
  return true;
});
const filtered = await untilVal(page, () => ({
  sel: (document.querySelector('#adCounts button.sel') || {}).dataset?.f || null,
  search: location.search,
  pills: [...document.querySelectorAll('#adsBody tr[data-id] .pill')].map(e => e.textContent.trim()),
  links: [...document.querySelectorAll('#adsBody a[href*="vk.com"]')].length,
  rows: document.querySelectorAll('#adsBody tr[data-id]').length,
}), null, (x) => x.sel === 'posted' && x.rows > 0);
check('фильтр «Опубликованные» переключился', chipClicked && filtered.sel === 'posted', `sel=${filtered.sel}`);
check('фильтр попал в URL', /filter=posted/.test(filtered.search), filtered.search);
check('в выборке только опубликованные', filtered.pills.length > 0 && filtered.pills.every(p => /опубл/.test(p)),
  [...new Set(filtered.pills)].join(', ') || 'нет строк');
check('ссылки на посты VK', filtered.links > 0, `${filtered.links}`);

// ключевое отличие от hash-навигации: состояние переживает перезагрузку страницы
await page.send('Page.reload');
await sleep(600);
const kept = await untilVal(page, () => ({
  sel: (document.querySelector('#adCounts button.sel') || {}).dataset?.f || null,
  rows: document.querySelectorAll('#adsBody tr[data-id]').length,
  pills: [...document.querySelectorAll('#adsBody tr[data-id] .pill')].map(e => e.textContent.trim()),
}), null, (x) => x.sel === 'posted' && x.rows > 0);
check('фильтр живёт в URL и после перезагрузки', kept.sel === 'posted' && kept.rows > 0,
  `sel=${kept.sel}, ${kept.rows} строк`);

// поиск берём термин из реальных данных, а не наугад
const term = await page.eval(() => {
  const t = (document.querySelector('#adsBody tr .t1') || {}).textContent || '';
  return (t.split(/[^\p{L}]+/u).filter(x => x.length >= 5).sort((x, y) => y.length - x.length)[0] || '').toLowerCase() || null;
});
if (term) {
  const searched = await untilVal(page, (w) => {
    const i = document.getElementById('adSearch');
    if (i.value !== w) { i.value = w; document.getElementById('btnSearch').click(); }
    return {
      search: location.search,
      rows: document.querySelectorAll('#adsBody tr[data-id]').length,
      titles: [...document.querySelectorAll('#adsBody tr .t1')].map(e => e.textContent.trim()),
    };
  }, term, (x) => x.rows > 0 && x.titles.length > 0 && x.titles.every(t => t.toLowerCase().includes(term)));
  check(`поиск «${term}» сужает выдачу`, searched.titles.length > 0 &&
    searched.titles.every(t => t.toLowerCase().includes(term)), `${searched.rows} строк · ${(searched.titles[0] || '').slice(0, 44)}`);
  check('поиск попал в URL', /q=/.test(searched.search), searched.search);
} else {
  check('поиск по тексту', false, 'не удалось взять термин из таблицы');
}

// пагинация вперёд (после поиска сбрасываем фильтры переходом на чистый URL)
await page.goto(BASE + '/ads', { settleMs: 400 });
const pagerBefore = await untilVal(page, () => (document.getElementById('adsPage') || {}).textContent.replace(/\s+/g, ' ').trim() || '',
  null, Boolean);
const nextDisabled = await page.eval(() => !!document.getElementById('adsNext').disabled);
if (!nextDisabled) {
  await page.eval(() => document.getElementById('adsNext').click());
  const paged = await untilVal(page, () => ({
    pager: (document.getElementById('adsPage') || {}).textContent.replace(/\s+/g, ' ').trim(),
    search: location.search,
    rows: document.querySelectorAll('#adsBody tr[data-id]').length,
  }), null, (x) => x.pager && x.pager !== pagerBefore);
  check('пагинация листается и пишет страницу в URL', /^\d+ \/ \d+$/.test(paged.pager) && /page=2/.test(paged.search),
    `${pagerBefore} → ${paged.pager} · ${paged.rows} строк · ${paged.search}`);
} else {
  check('пагинация листается', false, 'кнопка «Вперёд» неактивна: записей меньше одной страницы');
}

// журнал задач: deep-link /jobs?job=<id> раскрывает лог без лишних кликов
await page.goto(BASE + '/jobs', { settleMs: 400 });
let hasJob = await untilVal(page, () => ({
  rows: document.querySelectorAll('#jobsBody tr[data-job]').length,
  ids: [...document.querySelectorAll('#jobsBody tr[data-job]')].map(e => e.dataset.job),
}), null, (x) => x.rows > 0);
if (!hasJob.rows) {
  // журнал живёт в памяти процесса: на свежем запуске создаём dry-run задачу (в VK ничего не уходит)
  await page.eval(async () => {
    await fetch('/vk/publish', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dry_run: true, limit: 2 }),
    });
  });
  hasJob = await untilVal(page, () => ({
    rows: document.querySelectorAll('#jobsBody tr[data-job]').length,
    ids: [...document.querySelectorAll('#jobsBody tr[data-job]')].map(e => e.dataset.job),
  }), null, (x) => x.rows > 0);
}
check('журнал задач непустой', hasJob.rows > 0, `${hasJob.rows} задач`);
if (hasJob.rows) {
  await page.goto(`${BASE}/jobs?job=${encodeURIComponent(hasJob.ids[0])}`, { settleMs: 500 });
  const jobOpen = await untilVal(page, () => {
    const row = document.querySelector('#jobsBody tr.logtr');
    const txt = row ? ((row.querySelector('.joblog') || {}).textContent || '').trim() : '';
    return { len: txt.length, head: txt.slice(0, 40), search: location.search };
  }, null, (x) => x.len > 1);
  check('лог задачи раскрывается по ссылке', jobOpen.len > 1, `${jobOpen.len} симв.: ${jobOpen.head}`);
  const toggled = await page.eval(() => {
    const b = document.querySelector('#jobsBody [data-toggle]');
    if (!b) return null;
    b.click();
    return b.textContent.trim();
  });
  const closed = await untilVal(page, () => ({
    logs: document.querySelectorAll('#jobsBody tr.logtr').length,
    label: (document.querySelector('#jobsBody [data-toggle]') || {}).textContent?.trim() || '',
  }), null, (x) => x.logs === 0 || x.label === 'показать');
  check('раскрытие лога переключается кнопкой', closed.logs === 0 || toggled === 'скрыть',
    `метка: ${toggled} → ${closed.label}`);
}

// тема: переключение живёт в localStorage и не ломает вёрстку
const themeFlip = await untilVal(page, () => {
  const before = document.documentElement.dataset.theme;
  document.getElementById('themeBtn').click();
  return { before, after: document.documentElement.dataset.theme, stored: localStorage.getItem('avito-theme') };
}, null, (x) => x.before !== x.after);
check('переключатель темы меняет data-theme', themeFlip.before !== themeFlip.after,
  `${themeFlip.before} → ${themeFlip.after}`);
check('тема запоминается', themeFlip.stored === themeFlip.after, String(themeFlip.stored));
await page.eval(() => { localStorage.removeItem('avito-theme'); });

console.log('\nАДАПТИВ');
for (const [label, vp] of [['планшет 768', { width: 768, height: 1024 }],
                           ['телефон 390', { width: 390, height: 844, dsf: 2, mobile: true }]]) {
  await page.setViewport(vp);
  await page.goto(BASE + '/ads', { settleMs: 500 });
  const mob = await untilVal(page, () => ({
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
    burger: getComputedStyle(document.getElementById('burger')).display !== 'none',
    rows: document.querySelectorAll('#adsBody tr[data-id]').length,
    labels: [...document.querySelectorAll('#adsBody td[data-label]')].length,
  }), null, (x) => x.rows > 0 && (x.burger || label === 'планшет 768'));
  check(`${label}: нет бокового скролла`, !mob.overflowX);
  check(`${label}: таблица остаётся читаемой`, mob.rows > 0 && (label === 'планшет 768' || mob.labels > 0),
    `${mob.rows} строк · подписей ${mob.labels}`);
  if (mob.burger) {
    const opened = await page.eval(() => {
      document.getElementById('burger').click();
      const side = document.getElementById('side');
      return { open: side.classList.contains('open'), expanded: document.getElementById('burger').getAttribute('aria-expanded') };
    });
    check(`${label}: бургер открывает меню`, opened.open && opened.expanded === 'true', JSON.stringify(opened));
    await page.eval(() => document.getElementById('scrim').click());
    const closed = await page.eval(() => document.getElementById('side').classList.contains('open'));
    check(`${label}: затемнение закрывает меню`, !closed);
  } else {
    check(`${label}: боковая колонка видна без бургера`,
      await page.eval(() => getComputedStyle(document.getElementById('side')).display !== 'none'));
  }
}
await page.setViewport({ width: 1440, height: 900 });

console.log('\nОШИБКИ');
check('нет JS-исключений', page.consoleErrors.length === 0, page.consoleErrors.slice(0, 3).join(' | '));
check('нет 4xx/5xx на запросах', badResponses.length === 0, badResponses.slice(0, 3).join(' | '));

console.log('\nСКРИНШОТЫ');
for (const [name, path] of ROUTES) {
  await page.goto(BASE + path, { settleMs: 400 });
  await untilVal(page, MEASURE, name, (x) => x.ready || x.errline > 0);
  await page.screenshot({ path: `${SHOTS}/admin-${name}.jpg`, format: 'jpeg', quality: 72, fullPage: true });
}
await page.setViewport({ width: 768, height: 1024 });
await page.goto(BASE + '/', { settleMs: 600 });
await untilVal(page, MEASURE, 'dash', (x) => x.ready || x.errline > 0);
await page.screenshot({ path: `${SHOTS}/admin-tablet.jpg`, format: 'jpeg', quality: 72, fullPage: true });
await page.setViewport({ width: 390, height: 844, dsf: 2, mobile: true });
await page.goto(BASE + '/', { settleMs: 600 });
await untilVal(page, MEASURE, 'dash', (x) => x.ready || x.errline > 0);
await page.screenshot({ path: `${SHOTS}/admin-mobile.jpg`, format: 'jpeg', quality: 72, fullPage: true });
console.log(`скриншоты: ${SHOTS}/admin-*.jpg`);

console.log(fails ? `\nRESULT: ${fails} FAIL` : '\nRESULT: 0 FAIL');
await browser.close();
process.exit(fails ? 1 : 0);
