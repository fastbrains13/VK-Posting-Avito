#!/usr/bin/env node
// Смоук-тест интерфейса админки: прогоняем все разделы в headless Chrome,
// ловим JS-ошибки, сетевые 4xx/5xx и проверяем, что данные реально отрисованы.
//
//   node tests/ui_smoke.mjs [http://127.0.0.1:8012/] [user] [pass]
//
// Ожидания адаптивные (poll до TIMEOUT): сервер на 1 CPU через SSH-туннель отвечает
// медленно, и фиксированные паузы давали бы ложные падения.
//
// Только read-only взаимодействия (навигация, фильтры, поиск, пагинация):
// тест ходит в живую БД, поэтому удалять и публиковать ничего не будет.
// Исключение — dry-run задача постинга, если журнал пуст: она ничего не отправляет.
import { Browser, sleep } from '/Users/eryashevs/.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const BASE = process.argv[2] || 'http://127.0.0.1:8012/';
const USER = process.argv[3] || '';
const PASS = process.argv[4] || '';
const ROUTES = ['dash', 'ads', 'sources', 'vk', 'jobs', 'logs', 'settings'];
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

// общий помощник измерения: готов ли раздел (нет скелетонов, есть текст, нет ошибки)
const MEASURE = (r) => {
  const view = document.querySelector('.view.on');
  const T = (sel) => { const e = document.querySelector(sel); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; };
  const N = (sel) => document.querySelectorAll(sel).length;
  const NV = (sel) => (view ? view.querySelectorAll(sel).length : 0);
  const out = {
    route: r,
    active: view ? view.id : null,
    chars: view ? view.textContent.replace(/\s+/g, ' ').trim().length : 0,
    skeleton: NV('.skel'),
    errline: NV('.errline'),
  };
  out.ready = out.active === 'view-' + r && out.skeleton === 0 && out.chars > 60;
  if (r === 'dash') {
    out.kpi = N('#kpi .k');
    out.kpiValues = [...document.querySelectorAll('#kpi .k')].map(e => e.textContent.replace(/\s+/g, ' ').trim());
    out.pipe = N('#pipe .stage');
    out.recent = N('#dashRecent .adcard');
    out.posts = N('#dashPosts .lrow');
    out.sched = N('#schedCard .kv');
    out.ready = out.ready && out.recent > 0;
  }
  if (r === 'ads') {
    out.chips = [...document.querySelectorAll('#adCounts button[data-f]')].map(e => e.textContent.replace(/\s+/g, ' ').trim());
    out.rows = N('#adsBody tr');
    out.pager = T('#adsPager');
    out.sel = (document.querySelector('#adCounts button.sel') || {}).dataset?.f || null;
    out.exportHref = (document.getElementById('btnExport') || {}).href || null;
    out.ready = out.ready && out.rows > 0 && out.chips.length === 4;
  }
  if (r === 'sources') {
    out.rows = N('#srcBody tr');
    out.addForm = !!document.getElementById('newUrl');
    out.ready = out.ready && out.rows > 0;
  }
  if (r === 'vk') {
    out.card = (T('#vkCard') || '').slice(0, 90);
    out.preview = (T('#pvCard') || '').length;
    out.history = N('#vkHistBody tr');
    out.oauth = (document.getElementById('vkOauthLink') || {}).href || null;
    out.reqPhotos = !!document.getElementById('s_reqphotos');
    // loadVK дорабатывает раздел по частям: ждём самый последний шаг (ссылка OAuth + история)
    out.ready = out.ready && out.preview > 0 && /client_id=/.test(out.oauth || '') && out.history > 0;
  }
  if (r === 'jobs') { out.rows = N('#jobsBody tr'); }
  if (r === 'logs') {
    out.tail = (T('#logbox') || '').length;
    out.auto = !!document.getElementById('logAuto');
    out.ready = out.ready && out.tail > 20;
  }
  if (r === 'settings') {
    const num = ['s_frl', 's_pages', 's_batch', 's_publish'];
    out.filled = num.filter(id => { const e = document.getElementById(id); return e && e.value !== ''; }).length;
    out.toggles = ['s_details', 's_photos', 's_paused'].filter(id => !!document.getElementById(id)).length;
    out.proxy = (T('#proxyCard') || '').slice(0, 90);
    const tk = document.getElementById('s_vktoken');
    out.vkTokenMasked = !(tk && /vk1\.a\.[A-Za-z0-9]{20}/.test(tk.value));
    out.ready = out.ready && out.filled === 4;
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
  if (status >= 400 && /\/api\/|export\.csv|\/logs|\/vk\/|\/login/.test(url)) badResponses.push(`${status} ${url}`);
});

await page.goto(BASE, { settleMs: 800 });

if (USER && PASS) {
  const code = await page.eval(async (o) => {
    const r = await fetch(o.base.replace(/\/$/, '') + '/login', {
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
  navCount: document.querySelectorAll('.nitem').length,
  views: document.querySelectorAll('.view').length,
  topbar: !!document.getElementById('stamp') && !!document.getElementById('vkDot'),
  overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
  dupIds: (() => {
    const seen = new Map();
    document.querySelectorAll('[id]').forEach(e => seen.set(e.id, (seen.get(e.id) || 0) + 1));
    return [...seen].filter(([, n]) => n > 1).map(([i, n]) => `${i}×${n}`);
  })(),
  globalChrome: (() => {
    const st = document.getElementById('status'), jl = document.getElementById('joblog');
    return !!(st && jl) && !st.closest('.view') && !jl.closest('.view');
  })(),
}), null, (v) => v.navCount > 0);
console.log('\nSHELL');
check('пункты навигации', shell.navCount === ROUTES.length, `${shell.navCount}/${ROUTES.length}`);
check('топбар с состоянием VK', shell.topbar);
check('все разделы в DOM', shell.views === ROUTES.length, `${shell.views}`);
check('нет горизонтального скролла', !shell.overflowX);
check('нет дублей id', shell.dupIds.length === 0, shell.dupIds.join(', '));
check('статус и живой лог — глобальные', shell.globalChrome);

const R = {};
for (const route of ROUTES) {
  const before = page.consoleErrors.length;
  await page.eval((r) => { location.hash = '#' + r; }, route);
  R[route] = await untilVal(page, MEASURE, route, (v) => v.ready || v.errline > 0);
  console.log(`\nРАЗДЕЛ #${route} (${R[route].chars} симв.)`);
  check('раздел активен', R[route].active === 'view-' + route, R[route].active || 'null');
  check('нет ошибки загрузки', R[route].errline === 0);
  check('данные отрисованы', R[route].ready, `скелетонов ${R[route].skeleton}, ${R[route].chars} симв.`);
  if (page.consoleErrors.length > before) {
    check('JS при переходе', false, page.consoleErrors.slice(before).join(' | '));
  }
}

console.log('\nПРОВЕРКИ ПО ДАННЫМ');
const d = R.dash;
check('KPI-полоса', d.kpi === 5, d.kpiValues.join(' · '));
check('конвейер из 3 стадий', d.pipe === 3, `${d.pipe}`);
check('последние объявления', d.recent > 0, `${d.recent} карточек`);
check('последние посты', d.posts > 0, `${d.posts} строк`);
check('расписание крона', d.sched >= 3, `${d.sched} строк`);
const a = R.ads;
check('счётчики-фильтры', a.chips.length === 4, a.chips.join(' / '));
check('таблица объявлений', a.rows > 0, `${a.rows} строк`);
check('пагинация считает записи', /\d+\s*–\s*\d+\s*из/.test(a.pager || ''), a.pager);
check('CSV-ссылка с фильтром', /export\.csv\?filter=all/.test(a.exportHref || ''), a.exportHref);
const v = R.vk;
check('карточка канала', /Сообщество|токен|VK/i.test(v.card), v.card);
check('предпросмотр поста', v.preview > 20, `${v.preview} симв.`);
check('OAuth-ссылка на user-ключ', /client_id=54874130/.test(v.oauth || ''), v.oauth || 'нет');
check('история постов', v.history > 0, `${v.history} строк`);
const s = R.settings;
check('числовые настройки из БД', s.filled === 4, `${s.filled}/4`);
check('переключатели настроек', s.toggles === 3, `${s.toggles}/3`);
check('статус прокси виден', /прокси|proxy|socks|карант|бан|прям|адресов|пул/i.test(s.proxy), s.proxy);
check('токен VK не светится целиком', s.vkTokenMasked);
const lg = R.logs;
check('хвост лога', lg.tail > 20, `${lg.tail} симв.`);

console.log('\nИНТЕРАКТИВ (только чтение)');
await page.eval(() => { location.hash = '#ads'; });
await untilVal(page, () => document.querySelectorAll('#adCounts button[data-f]').length === 4, null, Boolean);
const chip = await page.eval(() => {
  const b = [...document.querySelectorAll('#adCounts button[data-f]')].find(x => x.dataset.f === 'posted');
  if (!b) return false;
  b.click();
  return true;
});
const filtered = await untilVal(page, () => ({
  sel: (document.querySelector('#adCounts button.sel') || {}).dataset?.f || null,
  sub: (document.getElementById('adsSub') || {}).textContent || '',
  pills: [...document.querySelectorAll('#adsBody tr td .pill')].map(e => e.textContent.trim()),
  links: [...document.querySelectorAll('#adsBody tr .pillink')].length,
}), null, (x) => x.sel === 'posted' && x.pills.length > 0);
check('фильтр «Опубликованные» переключился', chip && filtered.sel === 'posted', `sel=${filtered.sel}`);
check('подпись считает total', /Всего под фильтром/.test(filtered.sub), filtered.sub.trim());
check('в выборке только опубликованные', filtered.pills.length > 0 && filtered.pills.every(p => /опубликовано/.test(p)),
  [...new Set(filtered.pills)].join(', ') || 'нет строк');
check('ссылки на посты VK', filtered.links > 0, `${filtered.links}`);

// поиск берём термин из реальных данных, а не наугад
const term = await page.eval(() => {
  const t = (document.querySelector('#adsBody tr .t1') || {}).textContent || '';
  const w = t.split(/[^\p{L}]+/u).filter(x => x.length >= 5).sort((x, y) => y.length - x.length)[0];
  return w ? w.toLowerCase() : null;
});
if (term) {
  await page.eval((w) => {
    const i = document.getElementById('adSearch');
    i.value = w;
    i.dispatchEvent(new Event('input', { bubbles: true }));
  }, term);
  const searched = await untilVal(page, (w) => ({
    rows: document.querySelectorAll('#adsBody tr').length,
    titles: [...document.querySelectorAll('#adsBody tr .t1')].map(e => e.textContent.trim()),
    sub: (document.getElementById('adsSub') || {}).textContent || '',
  }), term, (x) => x.rows > 0 && x.titles.length > 0 && x.titles.every(t => t.toLowerCase().includes(term)));
  check(`поиск «${term}» сужает выдачу`, searched.rows > 0 && searched.titles.every(t => t.toLowerCase().includes(term)),
    `${searched.rows} строк · ${(searched.titles[0] || '').slice(0, 44)}`);
  await page.eval(() => {
    const i = document.getElementById('adSearch');
    i.value = '';
    i.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await untilVal(page, () => document.querySelectorAll('#adsBody tr').length > 5, null, Boolean);
} else {
  check('поиск по тексту', false, 'не удалось взять термин из таблицы');
}

// пагинация вперёд
const pagerBefore = await page.eval(() => (document.getElementById('adsPager') || {}).textContent.replace(/\s+/g, ' ').trim() || '');
await page.eval(() => { const b = document.getElementById('pgNext'); if (b && !b.disabled) b.click(); });
const paged = await untilVal(page, () => ({
  pager: (document.getElementById('adsPager') || {}).textContent.replace(/\s+/g, ' ').trim(),
  rows: document.querySelectorAll('#adsBody tr').length,
}), null, (x) => x.pager && x.pager !== pagerBefore);
check('пагинация листается', /^\d+–\d+/.test(paged.pager), `${pagerBefore} → ${paged.pager} · ${paged.rows} строк`);

// раскрытие задачи в журнале + проверка, что автообновление его не сбрасывает
await page.eval(() => { location.hash = '#jobs'; });
await sleep(700);
let hasJob = await page.eval(() => !!document.querySelector('#jobsBody tr[data-job]'));
if (!hasJob) {
  // журнал живёт в памяти процесса: на свежем запуске создаём dry-run задачу (в VK ничего не уходит)
  await page.eval(async () => {
    await fetch('/vk/publish', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dry_run: true, limit: 2 }),
    });
  });
  hasJob = await untilVal(page, () => !!document.querySelector('#jobsBody tr[data-job]'), null, Boolean);
}
check('журнал задач непустой', hasJob);
await page.eval(() => {
  const tr = document.querySelector('#jobsBody tr[data-job]');
  if (tr) tr.click();
});
const jobOpen = await untilVal(page, () => {
  const row = [...document.querySelectorAll('#jobsBody tr.logtr')].find(r => r.style.display !== 'none');
  const txt = row ? (row.querySelector('.joblog') || {}).textContent.trim() : '';
  return { len: txt.length, head: txt.slice(0, 40) };
}, null, (x) => x.len > 1);
check('лог задачи раскрывается по клику', jobOpen.len > 1, `${jobOpen.len} симв.: ${jobOpen.head}`);
await sleep(3000); // цикл автообновления журнала — 2.5 с
const jobKept = await page.eval(() => {
  const row = [...document.querySelectorAll('#jobsBody tr.logtr')].find(r => r.style.display !== 'none');
  return row ? (row.querySelector('.joblog') || {}).textContent.trim().length : 0;
});
check('раскрытый лог переживает автообновление', jobKept > 1, `${jobKept} симв.`);

// мобильная раскладка
await page.setViewport({ width: 390, height: 844, dsf: 2, mobile: true });
await page.eval(() => { location.hash = '#dash'; });
await sleep(1500);
const mob = await page.eval(() => ({
  overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
  burgerVisible: getComputedStyle(document.getElementById('burger')).display !== 'none',
}));
check('на 390px нет бокового скролла', !mob.overflowX);
check('бургер-меню доступно', mob.burgerVisible);
await page.setViewport({ width: 1440, height: 900 });

console.log('\nОШИБКИ');
check('нет JS-исключений', page.consoleErrors.length === 0, page.consoleErrors.slice(0, 3).join(' | '));
check('нет 4xx/5xx на API', badResponses.length === 0, badResponses.slice(0, 3).join(' | '));

const shots = [['dash', 'admin-dash'], ['ads', 'admin-ads'], ['sources', 'admin-sources'],
  ['vk', 'admin-vk'], ['jobs', 'admin-jobs'], ['settings', 'admin-settings']];
for (const [route, name] of shots) {
  await page.eval((r) => { location.hash = '#' + r; }, route);
  await untilVal(page, MEASURE, route, (x) => x.ready || x.errline > 0);
  await page.screenshot({ path: `${SHOTS}/${name}.jpg`, format: 'jpeg', quality: 72, fullPage: true });
}
await page.setViewport({ width: 390, height: 844, dsf: 2, mobile: true });
await page.eval(() => { location.hash = '#dash'; });
await sleep(1500);
await page.screenshot({ path: `${SHOTS}/admin-mobile.jpg`, format: 'jpeg', quality: 72, fullPage: true });
console.log(`\nскриншоты: ${SHOTS}/admin-*.jpg`);

console.log(fails ? `RESULT: ${fails} FAIL` : 'RESULT: 0 FAIL');
await browser.close();
process.exit(fails ? 1 : 0);
