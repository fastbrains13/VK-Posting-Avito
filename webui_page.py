"""HTML-страницы веб-админки: общий каркас + самостоятельные страницы разделов.

Структура (порядок правок именно такой):

  LAYOUT_SHELL  — каркас: тонированная L-рамка (сайдбар 228px + топбар 48px) и
                  белый лист (sheet) с содержимым раздела; сюда же входят CSS-токены
                  обеих тем и общий JS (api, статус, запуск задач, автообновление);
  <РАЗДЕЛ>_PAGE — разметка одного раздела (вставляется в слот @@CONTENT@@);
  LOGIN_PAGE    — экран входа, самодостаточный;
  PAGES         — карта url -> (имя раздела, заголовок, разметка, скрипт);
  render_page() — собрать готовую страницу по url-пути.

Разделы живут на отдельных URL (/, /ads, /sources, /vk, /jobs, /logs, /settings),
hash-роутинга больше нет: каждая страница независима, состояние фильтров —
в query-параметрах, поэтому переход и перезагрузка не ломают отрисовку.

Стиль: Framed sheet (light) + тёмная тема теми же ролями токенов; цвет только
на данных и одном действии, уровни — тонирование рамки → лист → карточка.
"""

from html import escape as _escape

from avito_parser.settings import GROUPS, SPECS, SettingSpec

# --------------------------------------------------------------------- #
# каркас
# --------------------------------------------------------------------- #
LAYOUT_SHELL = r"""<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script>
/* тему читаем до отрисовки, чтобы не мигало при переходе между страницами */
try {
  var t = localStorage.getItem('avito-theme');
  if (t !== 'light' && t !== 'dark') t = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.dataset.theme = t;
} catch (e) { document.documentElement.dataset.theme = 'dark'; }
</script>
<style>
:root{
  /* Framed sheet: рамка тонирована в синий цвет продукта, лист белый */
  --frame:#eef2f6; --surface:#ffffff; --raised:#f4f6f8; --active:#e7ebef;
  --border:#e2e7eb; --rule:#f0f1f2; --control:#cdced1;
  --ink:#131416; --muted:#5d5f60; --faint:#6b6b6b;
  --accent:#2f6f96; --primary:#1d1f20; --primary-ink:#ffffff;
  --positive:#1e7b4f; --negative:#c4242a; --warning:#92400e;
  --pill-positive-bg:#dcfae5; --pill-positive-ink:#04250e;
  --pill-negative-bg:#ffedea; --pill-negative-ink:#831c1e;
  --pill-warning-bg:#fffbeb; --pill-warning-ink:#92400e; --pill-warning-border:#fde68a;
  --pill-accent-bg:#e3eef4; --pill-accent-ink:#1c4f6d;
  --pill-neutral-bg:#ebedee; --pill-neutral-ink:#353736;
  --shadow-card:0 1px 2px rgba(19,20,22,.05);
  --shadow-float:0 2px 6px rgba(19,20,22,.10),0 16px 32px -18px rgba(19,20,22,.28);
  --radius-sheet:16px; --radius-card:8px; --radius-control:6px; --radius-chip:4px;
  --gap:24px; --pad:24px; --side:228px; --topbar:48px; --inset:8px;
  --row:48px; --control-height:32px;
  --fs-title:22px; --fs-section:16px; --fs-kpi:28px; --fs-body:14px; --fs-small:12px;
}
html[data-theme=dark]{
  /* те же роли, нейтральные тёмные поверхности (без navy/slate) */
  --frame:#131415; --surface:#1b1c1e; --raised:#232527; --active:#2c2e30;
  --border:#2a2c2e; --rule:#232526; --control:#4a4c4e;
  --ink:#f2f3f4; --muted:#b4b4b4; --faint:#949494;
  --accent:#79a8cf; --primary:#ffffff; --primary-ink:#131416;
  --positive:#3fc07a; --negative:#e5566f; --warning:#e5a93b;
  --pill-positive-bg:#172a1d; --pill-positive-ink:#3fc07a;
  --pill-negative-bg:#2c1a20; --pill-negative-ink:#e5566f;
  --pill-warning-bg:#2b2414; --pill-warning-ink:#e5a93b; --pill-warning-border:#3d3319;
  --pill-accent-bg:#1a2833; --pill-accent-ink:#79a8cf;
  --pill-neutral-bg:#2a2c2e; --pill-neutral-ink:#b4b4b4;
  --shadow-card:0 1px 2px rgba(0,0,0,.30);
  --shadow-float:0 2px 8px rgba(0,0,0,.45),0 18px 40px -20px rgba(0,0,0,.70);
}
*{box-sizing:border-box}
html{color-scheme:light}
html[data-theme=dark]{color-scheme:dark}
body{margin:0; background:var(--frame); color:var(--ink);
  font:400 var(--fs-body)/1.45 "IBM Plex Sans",Inter,system-ui,"Segoe UI",Roboto,sans-serif;
  display:flex; min-height:100vh;}
h1,h2,h3,p{margin:0}
.num,.mono{font-variant-numeric:tabular-nums}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace}
a{color:inherit; text-decoration:none}
::selection{background:var(--pill-accent-bg)}
.skip{position:absolute; left:-9999px}
.skip:focus{left:8px; top:8px; z-index:60; background:var(--surface); padding:8px 12px;
  border-radius:var(--radius-control); border:1px solid var(--control)}
:focus-visible{outline:2px solid var(--accent); outline-offset:2px}

/* ---------- рамка: сайдбар ---------- */
.side{position:sticky; top:0; flex:none; width:var(--side); height:100vh; overflow:auto;
  display:flex; flex-direction:column; padding:14px 12px 12px; z-index:30}
.brand{display:flex; align-items:center; gap:9px; padding:2px 8px 14px}
.brand svg{flex:none}
.brand .name{font-size:15px; font-weight:600; letter-spacing:-.01em}
.brand .scope{font-size:var(--fs-small); color:var(--muted); margin-top:2px;
  max-width:158px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.nav{flex:1; min-height:0; overflow:auto; padding-bottom:10px}
.ngroup{font-size:var(--fs-small); color:var(--muted); padding:14px 8px 6px}
.nitem{display:flex; align-items:center; gap:8px; height:34px; padding:0 10px; margin:1px 0;
  border-radius:var(--radius-control); color:var(--muted); font-size:var(--fs-body)}
.nitem:hover{background:var(--raised); color:var(--ink)}
.nitem[aria-current=page]{background:var(--active); color:var(--ink); font-weight:500}
.nitem .cnt{margin-left:auto; font-size:var(--fs-small); color:var(--muted)}
.nitem[aria-current=page] .cnt{color:var(--accent); font-weight:500}
.userrow{display:flex; align-items:center; justify-content:space-between; gap:8px;
  padding:12px 8px 2px; font-size:13px; color:var(--muted)}
.userrow a:hover{color:var(--ink)}

/* ---------- рамка: топбар ---------- */
.wrap{flex:1; min-width:0; display:flex; flex-direction:column}
.topbar{position:sticky; top:0; z-index:20; height:var(--topbar); flex:none;
  display:flex; align-items:center; gap:10px; padding:0 16px}
.crumb{font-size:13px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.stamp{font-size:var(--fs-small); color:var(--muted); white-space:nowrap}
.topspace{flex:1}
.vkswitch{display:flex; align-items:center; gap:8px; padding:0 10px; height:28px;
  border-radius:var(--radius-control); color:var(--muted); font-size:13px; max-width:280px}
.vkswitch:hover{background:var(--raised); color:var(--ink)}
.vkswitch .nm{overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.dot{width:7px; height:7px; border-radius:50%; background:var(--faint); flex:none}
.dot.ok{background:var(--positive)} .dot.err{background:var(--negative)}
.dot.acc{background:var(--accent)} .dot.warn{background:var(--warning)}
.iconbtn{display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px;
  border:1px solid var(--control); border-radius:var(--radius-control);
  background:var(--surface); color:var(--muted); cursor:pointer; flex:none}
.iconbtn:hover{color:var(--ink); background:var(--raised)}
#burger{display:none}

/* ---------- лист ---------- */
.sheet{background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius-sheet) var(--radius-sheet) 0 0;
  margin:0 var(--inset) var(--inset) 0; padding:var(--pad); min-width:0}
.page{max-width:1156px; margin:0 auto; min-width:0}
.titlerow{display:flex; align-items:flex-end; justify-content:space-between; gap:var(--gap);
  flex-wrap:wrap; margin-bottom:var(--gap)}
h1{font-size:var(--fs-title); font-weight:600; letter-spacing:-.01em}
.sub{font-size:var(--fs-body); color:var(--muted); margin-top:6px; max-width:660px}
.actions{display:flex; align-items:center; gap:8px; flex-wrap:wrap}
.sectiontitle{font-size:var(--fs-section); font-weight:600; margin:0 0 8px;
  display:flex; align-items:baseline; gap:8px}
.sectiontitle .count{font-size:var(--fs-small); font-weight:400; color:var(--muted)}
.block{margin-bottom:var(--gap)}

/* ---------- карточки ---------- */
.card{background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius-card); padding:16px; box-shadow:var(--shadow-card); min-width:0}
.card.flush{padding:0; overflow:hidden}
.cardhead{display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:14px 16px; border-bottom:1px solid var(--rule)}
.cardhead h2,.cardhead h3{font-size:var(--fs-section); font-weight:600}
.kpis{display:grid; grid-template-columns:repeat(4,1fr); gap:var(--gap); margin-bottom:var(--gap)}
.kpi{background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card);
  padding:14px 16px; box-shadow:var(--shadow-card); min-width:0; display:flex;
  flex-direction:column; gap:4px}
.kpi > span{font-size:13px; color:var(--muted)}
.kpi > b{font-size:var(--fs-kpi); font-weight:400; line-height:1.1;
  font-variant-numeric:tabular-nums; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.kpi > b small{font-size:14px; color:var(--muted); font-weight:400}
.kpi > em{font-size:var(--fs-small); color:var(--muted); font-style:normal;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.kpi a{color:var(--ink)} .kpi a:hover{color:var(--accent)}

/* ---------- дашборд: колонка + рельс ---------- */
.dashgrid{display:grid; grid-template-columns:1fr 384px; gap:var(--gap); align-items:start}
.maincol{min-width:0}
.rail{display:flex; flex-direction:column; min-width:0}
.rail .card{margin-bottom:16px}

/* конвейер — главный блок обзора */
.stages{display:flex; align-items:stretch; gap:0}
.stage{flex:1; min-width:0; padding:4px 16px; display:flex; flex-direction:column; gap:4px}
.stage:first-child{padding-left:4px}
.stage:last-child{padding-right:4px}
.slabel{font-size:var(--fs-small); color:var(--muted); display:flex; align-items:center; gap:7px}
.sval{font-size:24px; font-weight:400; font-variant-numeric:tabular-nums;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.sval a:hover{color:var(--accent)}
.ssub{font-size:var(--fs-small); color:var(--muted); overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap}
.arr{flex:none; align-self:center; color:var(--faint); padding:0 6px; font-size:14px}
.risks{display:flex; flex-wrap:wrap; gap:8px; padding:12px 16px; border-top:1px solid var(--rule)}
.risk{display:flex; align-items:baseline; gap:8px; font-size:13px; color:var(--muted);
  background:var(--pill-negative-bg); border-radius:var(--radius-chip,4px); padding:6px 10px}
.risk a{color:var(--pill-negative-ink); font-weight:500}
.risk.warn{background:var(--pill-warning-bg); border:1px solid var(--pill-warning-border)}
.risk.warn a,.risk.warn b{color:var(--pill-warning-ink)}
.risk b{color:var(--pill-negative-ink); font-weight:500}

/* карточки объявлений (продукт показывает свои снимки) */
.adcards{display:grid; grid-template-columns:repeat(3,1fr); gap:16px}
.adcard{background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card);
  overflow:hidden; min-width:0; display:flex; flex-direction:column; box-shadow:var(--shadow-card)}
.adcard .ph{height:104px; background:var(--raised); display:flex}
.adcard .ph img{width:33.333%; height:100%; object-fit:cover}
.adcard .ph .noimg{flex:1; display:flex; align-items:center; justify-content:center;
  color:var(--muted); font-size:var(--fs-small)}
.adcard .bd{padding:12px 14px 14px; display:flex; flex-direction:column; gap:4px; flex:1}
.adcard .t{font-size:var(--fs-body); font-weight:500; overflow:hidden;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical}
.adcard .t:hover{color:var(--accent)}
.adcard .pr{font-size:15px; font-weight:500; font-variant-numeric:tabular-nums; margin-top:auto}
.adcard .mt{font-size:var(--fs-small); color:var(--muted)}

/* ---------- список-строки ---------- */
.lrow{display:flex; align-items:baseline; gap:10px; padding:10px 16px;
  border-top:1px solid var(--rule); font-size:13px; min-width:0}
.lrow:first-child{border-top:0}
.lrow .lt{color:var(--muted); font-size:var(--fs-small); font-variant-numeric:tabular-nums; flex:none}
.lrow .lmain{flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.lrow .lmain:hover{color:var(--accent)}
.lrow .rlink{color:var(--accent); flex:none; font-size:var(--fs-small)}
.kv{display:flex; justify-content:space-between; align-items:baseline; gap:12px;
  padding:8px 16px; border-top:1px solid var(--rule); font-size:13px}
.kv:first-child{border-top:0}
.kv span{color:var(--muted)}
.kv b{font-weight:500; font-variant-numeric:tabular-nums; text-align:right; word-break:break-word}
.kv b a:hover{color:var(--accent)}

/* ---------- кнопки ---------- */
.btn{display:inline-flex; align-items:center; justify-content:center; gap:8px;
  height:var(--control-height); padding:0 14px; border-radius:var(--radius-control);
  border:1px solid var(--control); background:var(--surface); color:var(--ink);
  font:500 var(--fs-body) "IBM Plex Sans",system-ui,sans-serif; cursor:pointer; white-space:nowrap}
.btn:hover{background:var(--raised)}
.btn.primary{background:var(--primary); color:var(--primary-ink); border-color:var(--primary)}
.btn.primary:hover{opacity:.88; background:var(--primary)}
.btn.neg{color:var(--negative); border-color:var(--control)}
.btn.neg:hover{background:var(--pill-negative-bg); color:var(--pill-negative-ink)}
.btn.sm{height:28px; padding:0 10px; font-size:13px}
.btn.txt{background:transparent; border-color:transparent; height:28px; padding:0 8px;
  color:var(--muted); font-weight:400}
.btn.txt:hover{background:var(--raised); color:var(--ink)}
.btn.txt.acc{color:var(--accent)}
.btn.txt.neg{color:var(--negative); background:transparent}
.btn.txt.neg:hover{background:var(--pill-negative-bg); color:var(--pill-negative-ink)}
.btn[disabled]{opacity:.5; cursor:progress}

/* ---------- табы-состояния и тулбар ---------- */
.tabs{display:flex; align-items:center; gap:20px; border-bottom:1px solid var(--border);
  margin-bottom:16px; overflow-x:auto}
.tabs button{background:transparent; border:0; border-bottom:2px solid transparent;
  color:var(--muted); font:400 var(--fs-body) "IBM Plex Sans",system-ui,sans-serif;
  padding:0 0 9px; height:38px; cursor:pointer; white-space:nowrap; display:flex;
  align-items:baseline; gap:7px}
.tabs button:hover{color:var(--ink)}
.tabs button.sel{color:var(--ink); font-weight:500; border-bottom-color:var(--accent)}
.tabs button b{font-weight:400; color:var(--muted); font-variant-numeric:tabular-nums}
.tabs button.sel b{color:var(--accent)}
.toolbar{display:flex; align-items:center; gap:12px; margin-bottom:16px; flex-wrap:wrap}
.toolbar .note{font-size:13px; color:var(--muted); font-variant-numeric:tabular-nums}
input[type=text],input[type=search],input[type=password],input[type=number],select,textarea{
  background:var(--surface); color:var(--ink); border:1px solid var(--border);
  border-radius:var(--radius-card); height:40px; padding:0 12px;
  font:400 var(--fs-body) "IBM Plex Sans",system-ui,sans-serif; max-width:100%}
input[type=search]{height:var(--control-height); border-radius:var(--radius-control);
  flex:1 1 260px; min-width:170px}
input[type=number]{width:112px}
select{height:var(--control-height); border-radius:var(--radius-control); padding:0 8px}
textarea{height:auto; padding:10px 12px; font-family:"IBM Plex Mono",ui-monospace,monospace}
input::placeholder{color:var(--faint)}
.pager{display:flex; align-items:center; gap:8px; margin-left:auto;
  font-size:13px; color:var(--muted); font-variant-numeric:tabular-nums}

/* ---------- таблицы ---------- */
.tablewrap{min-width:0}
table{width:100%; border-collapse:collapse; font-size:var(--fs-body)}
th{font-size:13px; color:var(--muted); font-weight:400; text-align:left;
  padding:0 10px 8px; white-space:nowrap}
td{padding:12px 10px; border-top:1px solid var(--rule); vertical-align:middle; min-width:0}
tbody tr{height:var(--row)}
tbody tr:hover{background:var(--raised)}
th.num,td.num{text-align:right; font-variant-numeric:tabular-nums}
th.r,td.r{text-align:right}
td .cellmain{overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
td .t1{font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
td .t1:hover{color:var(--accent)}
td .t2{font-size:13px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
td .idcell{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:13px; color:var(--muted)}
.adcell{display:flex; align-items:center; gap:12px; min-width:0}
.thumb{width:48px; height:48px; border-radius:8px; object-fit:cover; background:var(--raised); flex:none}
.thumbph{width:48px; height:48px; border-radius:8px; background:var(--raised); flex:none;
  display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:11px}
.adcell .tw{min-width:0}
.srcell{max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted)}
.dtc{color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap}
.acts{display:flex; gap:2px; justify-content:flex-end; white-space:nowrap}

/* ---------- пилюли статуса ---------- */
.pill{display:inline-flex; align-items:center; gap:6px; height:20px; padding:0 8px;
  border-radius:4px; font-size:12px; font-weight:500; white-space:nowrap; flex:none}
.pill.ok{background:var(--pill-positive-bg); color:var(--pill-positive-ink)}
.pill.bad{background:var(--pill-negative-bg); color:var(--pill-negative-ink)}
.pill.warn{background:var(--pill-warning-bg); color:var(--pill-warning-ink);
  border:1px solid var(--pill-warning-border)}
.pill.acc{background:var(--pill-accent-bg); color:var(--pill-accent-ink)}
.pill.off{background:var(--pill-neutral-bg); color:var(--pill-neutral-ink)}

/* ---------- формы ---------- */
.field{display:flex; flex-direction:column; gap:8px; min-width:0}
.field > span{font-size:var(--fs-body); font-weight:500}
.field > small{font-size:var(--fs-small); color:var(--muted)}
.field input,.field select,.field textarea{background:var(--surface);
  color:var(--ink);border:1px solid var(--border);
  border-radius:var(--radius-card);height:40px;padding:0 12px;
  font:400 var(--fs-body)/1.45 "IBM Plex Sans",system-ui,sans-serif;width:100%}
.field textarea{height:auto;resize:vertical;line-height:1.5}
.field select{appearance:none;cursor:pointer;padding-right:32px;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%235d5f60' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 10px center}
.frow{display:flex; gap:16px; flex-wrap:wrap; align-items:flex-start}
/* ряд полей настроек: число колонок задаётся по количеству полей, чтобы ряды не были рваными */
.setrow{display:grid; gap:16px; align-items:start}
/* одиночное поле не растягиваем на всю панель: число и id читаются с одного взгляда */
.setrow .field:not(.wide) input,.setrow .field:not(.wide) select{max-width:320px}
.switch{display:inline-flex; align-items:center; gap:10px; cursor:pointer; font-size:var(--fs-body)}
.switch input{position:absolute; opacity:0; width:1px; height:1px}
.track{width:33px; height:18px; border-radius:999px; background:var(--control);
  position:relative; flex:none; transition:background .15s}
.track::after{content:""; position:absolute; top:2px; left:2px; width:14px; height:14px;
  border-radius:50%; background:var(--surface); transition:transform .15s}
.switch input:checked + .track{background:var(--positive)}
.switch input:checked + .track::after{transform:translateX(15px)}
.switch input:focus-visible + .track{outline:2px solid var(--accent); outline-offset:2px}
.srow{display:grid; grid-template-columns:minmax(280px,450px) minmax(0,1fr); gap:var(--pad);
  padding:32px 0; align-items:start}
.srow:first-of-type{padding-top:8px}
.srule{border-top:1px solid var(--border)}
.slabel h3{font-size:var(--fs-section); font-weight:500; margin-bottom:6px}
.slabel p{font-size:var(--fs-body); color:var(--muted); max-width:420px}
.slabel .ro{font-size:13px; color:var(--muted); margin-top:10px; line-height:1.6; word-break:break-all}
.spanel{display:flex; flex-direction:column; gap:16px; background:var(--raised);
  border-radius:var(--radius-card); padding:16px}
.spanel .t2{font-size:13px; color:var(--muted); line-height:1.5}
.spanel .t2 a{color:var(--accent); font-weight:500}
.spanel .t2 a:hover{text-decoration:underline}
/* панель сохранения: обычный ряд в конце формы (колонка центрирована, sticky тут не годится) */
.sfoot{display:flex; justify-content:flex-end; align-items:center; gap:12px; flex-wrap:wrap;
  padding-top:20px; border-top:1px solid var(--border)}
.sfoot .saved{font-size:var(--fs-small); color:var(--muted); margin-right:auto}
.field.wide{flex:1 1 100%}
.field textarea{width:100%; min-width:280px; resize:vertical; line-height:1.5}
.field .mono{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:13px}
.advfields{display:flex; flex-direction:column; gap:16px; padding-top:16px; border-top:1px solid var(--border)}
.advfields[hidden]{display:none}
/* точка на поле: значение сохранено в базе и перекрывает .env */
.field.overridden > span::after,.switchrow.overridden .tw b::after{content:""; display:inline-block;
  width:6px; height:6px; border-radius:50%; background:var(--accent); margin-left:7px; vertical-align:middle}
.switchrow{display:flex; align-items:flex-start; justify-content:space-between; gap:16px}
.switchrow .tw{display:flex; flex-direction:column; gap:3px}
.switchrow .tw b{font-size:var(--fs-body); font-weight:500}
.dangerrow .spanel{background:transparent; border:1px solid var(--pill-negative-bg);
  border-radius:var(--radius-card); padding:14px 16px}
.switchrow .tw small{font-size:var(--fs-small); color:var(--muted)}

/* ---------- вложения и предпросмотр поста ---------- */
.vkgrid{display:grid; grid-template-columns:1fr 1fr; gap:var(--gap); align-items:start}
.msg{white-space:pre-wrap; font-size:var(--fs-body); line-height:1.55}
.pvrow{display:flex; gap:16px; margin-top:12px; min-width:0}
.pvrow .ph{width:120px; height:120px; border-radius:8px; object-fit:cover; background:var(--raised); flex:none}
.pvrow .phph{width:120px; height:120px; border-radius:8px; background:var(--raised); flex:none;
  display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:var(--fs-small)}
.pvrow .msg{flex:1; min-width:0; max-height:240px; overflow:auto}

/* ---------- лог ---------- */
.logbox{background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius-card); padding:14px 16px;
  font:400 12px/1.6 "IBM Plex Mono",ui-monospace,Menlo,monospace; color:var(--muted);
  white-space:pre-wrap; word-break:break-word; overflow:auto;
  max-height:calc(100vh - 260px); min-height:320px}
.joblog{background:var(--raised); border:1px solid var(--border); border-radius:var(--radius-card);
  padding:12px 14px; margin-bottom:16px;
  font:400 12px/1.6 "IBM Plex Mono",ui-monospace,Menlo,monospace; color:var(--muted);
  white-space:pre-wrap; word-break:break-word; max-height:200px; overflow:auto}
.joblog[hidden]{display:none}
.logtr td{padding:0 10px 14px}
.logtr .joblog{margin:0; max-height:320px; background:var(--surface)}

/* ---------- состояния ---------- */
.empty{border:1px dashed var(--control); border-radius:var(--radius-card);
  padding:12px 14px; color:var(--muted); font-size:var(--fs-body)}
.emptycol{grid-column:1/-1}
.errline{display:flex; align-items:center; justify-content:space-between; gap:12px;
  border:1px solid var(--pill-negative-bg); background:var(--pill-negative-bg);
  color:var(--pill-negative-ink); border-radius:var(--radius-card); padding:10px 14px; font-size:13px}
html[data-theme=light] .errline{border-color:var(--pill-warning-border)}
.skel{background:var(--raised); border-radius:4px; display:inline-block; height:14px}
.skel.big{height:28px; width:96px}
.status{display:none; margin-bottom:16px; padding:10px 14px; border-radius:var(--radius-card);
  background:var(--raised); border:1px solid var(--border); box-shadow:var(--shadow-card);
  font-size:13px}
.status.show{display:block}
.status.err{background:var(--pill-negative-bg); border-color:var(--pill-negative-bg);
  color:var(--pill-negative-ink)}
.status.ok{background:var(--pill-positive-bg); border-color:var(--pill-positive-bg);
  color:var(--pill-positive-ink)}

/* ---------- планшет ---------- */
@media (max-width:1180px){
  .dashgrid{grid-template-columns:1fr}
  .vkgrid{grid-template-columns:1fr}
  .kpis{grid-template-columns:repeat(2,1fr)}
  .adcards{grid-template-columns:repeat(2,1fr)}
  .srow{grid-template-columns:1fr; gap:12px; padding:24px 0}
}
/* узкий лист: поля настроек в одну колонку, иначе подписи не помещаются */
@media (max-width:900px){
  .setrow{grid-template-columns:1fr !important}
}
/* ---------- телефон ---------- */
@media (max-width:760px){
  body{display:block}
  .side{position:fixed; left:0; top:0; bottom:0; width:min(280px,84vw); height:100dvh;
    background:var(--frame); transform:translateX(-105%); transition:transform .18s}
  .side.open{transform:none; box-shadow:var(--shadow-float)}
  #burger{display:inline-flex}
  .hideph{display:none}
  /* топбар на телефоне узкий — статус VK не должен вылезать за край */
  .topbar{gap:8px; padding:0 16px}
  .crumb{min-width:0}
  .stamp{display:none}
  .vkswitch{min-width:0; max-width:150px}
  .sheet{border:0; border-radius:0; margin:0; padding:16px}
  .kpis{grid-template-columns:repeat(2,1fr); gap:12px}
  .kpis .kpi:nth-last-child(1):nth-child(odd){grid-column:1/-1}
  .adcards{grid-template-columns:1fr}
  .setrow{grid-template-columns:1fr !important}
  .stages{flex-direction:column; align-items:stretch; gap:4px}
  .stage{padding:6px 0}
  .arr{transform:rotate(90deg); align-self:flex-start; padding-left:6px}
  .titlerow{align-items:flex-start}
  .pager{margin-left:0; width:100%}
  /* таблица становится списком из двух строк, поля не теряются */
  thead{display:none}
  table,tbody,tr,td{display:block; width:auto}
  tbody tr{height:auto; padding:10px 0; border-top:1px solid var(--rule)}
  td{border:0; padding:2px 0; display:flex; justify-content:space-between; gap:16px; align-items:center}
  td::before{content:attr(data-label); color:var(--muted); font-size:13px; flex:none}
  td.nolabel::before{content:none}
  td.num,td.r{text-align:left}
  .acts{justify-content:flex-end}
  .thumb,.thumbph{width:40px; height:40px}
}
.scrim{position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:25}
.scrim[hidden]{display:none}
@media (prefers-reduced-motion:reduce){*{transition:none !important; animation:none !important}}
</style>
</head>
<body data-page="@@PAGE@@">
<a class="skip" href="#main">К содержимому</a>

<!-- ======================= рамка: сайдбар ======================= -->
<aside class="side" id="side">
  <div class="brand">
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
      <rect x="1" y="3" width="12" height="16" rx="3" stroke="currentColor" stroke-width="1.5" opacity=".55"/>
      <path d="M14.5 11h5.5M17.5 8l3 3-3 3" stroke="var(--accent)" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="7" cy="7.5" r="1.6" fill="var(--accent)"/>
    </svg>
    <div>
      <div class="name">Авито → VK</div>
      <div class="scope" id="brandScope">сообщество не настроено</div>
    </div>
  </div>
  <nav class="nav" aria-label="Разделы">
    <div class="ngroup">Конвейер</div>
    <a class="nitem" href="/" data-nav="dash">Дашборд</a>
    <a class="nitem" href="/ads" data-nav="ads">Объявления <span class="cnt" id="navPending"></span></a>
    <a class="nitem" href="/sources" data-nav="sources">Источники</a>
    <div class="ngroup">Публикация</div>
    <a class="nitem" href="/vk" data-nav="vk">VK-канал</a>
    <a class="nitem" href="/jobs" data-nav="jobs">Задачи <span class="cnt" id="navJobs"></span></a>
    <div class="ngroup">Система</div>
    <a class="nitem" href="/logs" data-nav="logs">Логи</a>
    <a class="nitem" href="/settings" data-nav="settings">Настройки</a>
  </nav>
  <div class="userrow"><span>admin</span><a href="/logout">Выйти</a></div>
</aside>

<div class="wrap">
  <!-- ======================= рамка: топбар ======================= -->
  <header class="topbar">
    <button class="iconbtn" id="burger" aria-label="Меню раздела" aria-expanded="false">
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
    </button>
    <span class="crumb" id="crumb">Дашборд</span>
    <span class="topspace"></span>
    <span class="stamp" id="stamp">…</span>
    <button class="btn sm hideph" id="btnRefresh">Обновить</button>
    <button class="iconbtn" id="themeBtn" aria-label="Переключить тему">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path class="moon" d="M13 9.8A5.4 5.4 0 016.2 3 5.4 5.4 0 1013 9.8z"
              stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
        <g class="sun" style="display:none">
          <circle cx="8" cy="8" r="3.2" stroke="currentColor" stroke-width="1.4"/>
          <path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9L13 13M13 3l-1.1 1.1M4.1 11.9L3 13"
                stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
        </g>
      </svg>
    </button>
    <a class="vkswitch" href="/vk" id="vkSwitch">
      <span class="dot" id="vkDot"></span><span class="nm" id="vkName">VK не настроен</span>
    </a>
  </header>

  <!-- ======================= лист ======================= -->
  <main class="sheet" id="main">
    <div class="status" id="status" role="status" aria-live="polite"></div>
    <div class="joblog" id="joblog" hidden></div>
@@CONTENT@@
  </main>
</div>

<div class="scrim" id="scrim" hidden></div>

<script>
/* ---------- общий слой: хелперы, состояние, задачи ---------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => (s==null ? '' : String(s)).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (n) => (n==null || n==='') ? '—' : new Intl.NumberFormat('ru-RU').format(n);
const tm = (iso) => iso ? new Date(iso).toLocaleTimeString('ru-RU',
  {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
const dt = (iso) => { if(!iso) return '—'; const d = new Date(iso);
  const p = (x)=>String(x).padStart(2,'0');
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+
         ' '+p(d.getHours())+':'+p(d.getMinutes()); };

const app = { page: document.body.dataset.page, S: null, running: false, poll: null };
const PAGE_TITLES = {dash:'Дашборд', ads:'Объявления', sources:'Источники', vk:'VK-канал',
  jobs:'Задачи', logs:'Логи', settings:'Настройки'};

async function api(path, opts){
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { location.href = '/login'; throw new Error('нужен вход'); }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const post = (path, body) => api(path, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})});

function statusMsg(text, cls){
  const st = $('status'); if (!st) return;
  st.className = 'status show' + (cls ? ' ' + cls : '');
  st.textContent = text;
  if (cls === 'ok') setTimeout(() => { if (st.textContent === text) st.className = 'status'; }, 9000);
}
function pill(cls, text){ return '<span class="pill '+cls+'">'+esc(text)+'</span>'; }
function dash(v){ return (v==null || v==='') ? '<span style="color:var(--muted)">—</span>' : esc(v); }
/* ошибка показывается внутри блока, который не загрузился, а не баннером на весь экран */
function fail(el, msg){
  if (!el) return;
  el.innerHTML = '<div class="errline"><span>'+esc(msg)+'</span>'+
    '<button class="btn sm" onclick="location.reload()">Повторить</button></div>';
}
/* скачанный файл мог быть удалён из data/photos — битую миниатюру меняем на плейсхолдер */
function imgFallback(root){
  (root || document).querySelectorAll('img[data-fallback]').forEach(img => {
    img.addEventListener('error', () => {
      const ph = document.createElement('span');
      ph.className = img.classList.contains('thumb') ? 'thumbph'
        : (img.classList.contains('ph') ? 'phph' : 'noimg');
      ph.textContent = 'нет фото';
      img.replaceWith(ph);
    }, {once: true});
  });
}
/* ссылки раздела: состояние фильтров живёт в URL, а не в JS-памяти */
function linkTo(params){
  const q = new URLSearchParams(location.search);
  Object.keys(params).forEach(k => params[k] == null ? q.delete(k) : q.set(k, String(params[k])));
  const s = q.toString();
  history.replaceState(null, '', location.pathname + (s ? '?' + s : ''));
}

function renderChrome(){
  $('stamp').textContent = 'обновлено ' + tm(new Date().toISOString());
  $('crumb').textContent = PAGE_TITLES[app.page] || 'Авито → VK';
  document.querySelectorAll('.nitem').forEach(a => {
    if (a.dataset.nav === app.page) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  if (!app.S) return;
  const vk = app.S.vk || {}, db = app.S.db || {};
  $('vkDot').className = 'dot ' + (vk.error ? 'err' : (vk.token_set ? 'ok' : 'warn'));
  $('vkName').textContent = vk.error ? vk.error : (vk.group_name || 'VK не настроен');
  $('brandScope').textContent = vk.group_name || 'сообщество не настроено';
  $('navPending').textContent = db.pending ? fmt(db.pending) : '';
  const live = (app.S.jobs_live || 0);
  $('navJobs').textContent = live ? fmt(live) : '';
}
async function loadState(){
  app.S = await api('/api/state');
  renderChrome();
  return app.S;
}

/* ---------- запуск фоновой задачи: один живой лог на все разделы ---------- */
let logSeen = 0;
function logLine(msg){
  const el = $('joblog'); el.hidden = false;
  el.textContent += (el.textContent ? '\n' : '') + msg;
  el.scrollTop = el.scrollHeight;
}
function startJob(path, body, busyMsg){
  if (app.running) { statusMsg('Дождитесь завершения текущей задачи', 'err'); return Promise.resolve(); }
  app.running = true; logSeen = 0;
  $('joblog').textContent = ''; $('joblog').hidden = false;
  statusMsg(busyMsg);
  return post(path, body)
    .then(({id}) => {
      linkTo({job: id});
      app.poll = setInterval(() => pollJob(id), 2000);
    })
    .catch(err => { statusMsg('Ошибка: ' + err.message, 'err'); app.running = false; });
}
async function pollJob(id){
  let job;
  try { job = await api('/job/' + id); }
  catch (e) { clearInterval(app.poll); app.running = false; return; }
  const lines = job.log || [];
  lines.slice(logSeen).forEach(logLine);
  logSeen = lines.length;
  if (job.status === 'running') { statusMsg('Выполняется: ' + (job.progress || '…')); return; }
  clearInterval(app.poll); app.running = false;
  if (job.status === 'error') statusMsg('Ошибка: ' + job.error, 'err');
  else {
    const ok = (job.posts || []).filter(p => p.ok).length;
    statusMsg('Готово за ' + (job.elapsed || 0).toFixed(0) + ' с: объявлений ' +
      (job.ads || []).length + ', постов VK ' + ok + '/' + (job.posts || []).length, 'ok');
  }
  loadState().catch(() => {});
  if (window.afterJob) window.afterJob(job);
}

/* ---------- оболочка: меню, тема, автообновление ---------- */
function initShell(){
  const side = $('side'), scrim = $('scrim'), burger = $('burger');
  const closeMenu = () => { side.classList.remove('open'); scrim.hidden = true;
    burger.setAttribute('aria-expanded', 'false'); };
  burger.addEventListener('click', () => {
    const open = !side.classList.contains('open');
    side.classList.toggle('open', open); scrim.hidden = !open;
    burger.setAttribute('aria-expanded', String(open));
  });
  scrim.addEventListener('click', closeMenu);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });

  const themeBtn = $('themeBtn');
  const paintTheme = () => {
    const dark = document.documentElement.dataset.theme === 'dark';
    themeBtn.querySelector('.moon').style.display = dark ? '' : 'none';
    themeBtn.querySelector('.sun').style.display = dark ? 'none' : '';
    themeBtn.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
  };
  themeBtn.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('avito-theme', next); } catch (e) {}
    paintTheme();
  });
  paintTheme();

  $('btnRefresh').addEventListener('click', () => {
    loadState().catch(() => {});
    if (window.pageTick) window.pageTick(true);
  });
  /* раз в 10 секунд сверяем шапку и текущий раздел: страницы независимы,
     поэтому перезагрузка не нужна, но данные должны быть свежими */
  setInterval(() => {
    loadState().catch(() => {});
    if (window.pageTick) window.pageTick();
  }, 10000);
  const openJob = new URLSearchParams(location.search).get('job');
  if (openJob) pollJob(openJob);
  loadState().catch(() => {});
}
document.addEventListener('DOMContentLoaded', initShell);
</script>
<script>
@@SCRIPT@@
</script>
</body>
</html>
"""

# --------------------------------------------------------------------- #
# раздел: дашборд (сводка конвейера)
# --------------------------------------------------------------------- #
DASHBOARD_PAGE = r"""
    <section class="page">
      <div class="titlerow">
        <div>
          <h1>Дашборд</h1>
          <p class="sub">Состояние конвейера «Авито → VK»: что спарсилось, что ждёт
            публикации и что пошло не так.</p>
        </div>
        <div class="actions">
          <button class="btn" id="btnParseAll">Спарсить всё</button>
          <button class="btn primary" id="btnPublish">Постить очередь</button>
        </div>
      </div>

      <div class="kpis" id="kpis">
        <div class="kpi"><span>Всего объявлений</span><b class="skel big"></b><em>в базе</em></div>
        <div class="kpi"><span>В очереди</span><b class="skel big"></b><em>ждут поста</em></div>
        <div class="kpi"><span>Опубликовано</span><b class="skel big"></b><em>с постом в VK</em></div>
        <div class="kpi"><span>Новых за сутки</span><b class="skel big"></b><em>за 24 ч</em></div>
      </div>

      <div class="dashgrid">
        <div class="maincol">
          <div class="card block flush">
            <div class="cardhead">
              <h2>Конвейер</h2>
              <span class="mono" style="font-size:12px;color:var(--muted)" id="pipeHint"></span>
            </div>
            <div class="stages" id="pipe">
              <div class="stage"><span class="slabel"><span class="dot acc"></span>Парсинг</span>
                <span class="sval num">—</span><span class="ssub">последний запуск</span></div>
              <div class="arr" aria-hidden="true">→</div>
              <div class="stage"><span class="slabel"><span class="dot"></span>Очередь</span>
                <span class="sval num">—</span><span class="ssub">объявлений</span></div>
              <div class="arr" aria-hidden="true">→</div>
              <div class="stage"><span class="slabel"><span class="dot"></span>Постинг</span>
                <span class="sval num">—</span><span class="ssub">за сегодня</span></div>
              <div class="arr" aria-hidden="true">→</div>
              <div class="stage"><span class="slabel"><span class="dot"></span>На VK</span>
                <span class="sval num">—</span><span class="ssub">опубликовано всего</span></div>
            </div>
            <div class="risks" id="risks"></div>
          </div>

          <div class="block">
            <h2 class="sectiontitle">Последние объявления
              <span class="count"><a href="/ads">все →</a></span></h2>
            <div class="adcards" id="dashRecent"></div>
          </div>
        </div>

        <div class="rail">
          <div class="card flush">
            <div class="cardhead"><h3>Крон</h3><span id="schedPill"></span></div>
            <div id="schedCard"></div>
          </div>
          <div class="card flush">
            <div class="cardhead"><h3>VK-канал</h3><span id="dashVkPill"></span></div>
            <div id="dashVkCard"></div>
          </div>
          <div class="card flush">
            <div class="cardhead"><h3>Последние посты</h3>
              <span class="count"><a href="/vk">в VK-канал →</a></span></div>
            <div id="dashPosts"></div>
          </div>
          <div class="card flush">
            <div class="cardhead"><h3>Последние задачи</h3>
              <span class="count"><a href="/jobs">все →</a></span></div>
            <div id="dashJobs"></div>
          </div>
        </div>
      </div>
    </section>
"""
DASHBOARD_SCRIPT = r"""
/* ---------- дашборд ---------- */
async function dashAll(){
  let S;
  try { S = await loadState(); } catch (e) { return fail($('kpis'), 'Не удалось загрузить состояние: ' + e.message); }
  const db = S.db || {}, sch = S.scheduler || {}, vk = S.vk || {};
  const lastRun = (S.sources || []).map(s => s.last_check).filter(Boolean).sort().pop();

  $('kpis').innerHTML = [
    ['Всего объявлений', fmt(db.total), 'в базе', '/ads?filter=all'],
    ['В очереди', fmt(db.pending), 'ждут поста', '/ads?filter=pending'],
    ['Опубликовано', fmt(db.posted), 'с постом в VK', '/ads?filter=posted'],
    ['Недопаршено', fmt(db.partial), 'статус partial', '/ads?filter=partial']
  ].map(k => '<div class="kpi"><span>'+k[0]+'</span><b><a href="'+k[3]+'">'+k[1]+
      '</a></b><em>'+k[2]+'</em></div>').join('');

  /* стрелки-разделители тоже дети #pipe, поэтому берём именно стадии, а не children */
  const stages = document.querySelectorAll('#pipe .stage');
  stages[0].querySelector('.sval').textContent = sch.paused ? 'пауза' :
    (sch.next_parse ? 'след. в ' + tm(sch.next_parse) : '—');
  stages[0].querySelector('.ssub').textContent = lastRun ? 'последний обход ' + dt(lastRun)
    : (sch.last_parse_result || 'парсинга ещё не было');
  stages[1].querySelector('.sval').innerHTML = '<a href="/ads?filter=pending">'+fmt(db.pending)+'</a>';
  stages[1].querySelector('.ssub').textContent = fmt(db.complete) + ' полных карточек';
  stages[2].querySelector('.sval').textContent = vk.last_post_at ? dt(vk.last_post_at) : '—';
  stages[2].querySelector('.ssub').textContent = vk.last_post_url ? 'последний пост в ленте' : 'постов ещё не было';
  stages[3].querySelector('.sval').innerHTML = '<a href="/ads?filter=posted">'+fmt(db.posted)+'</a>';
  $('pipeHint').textContent = 'интервал парсинга ' + fmt(sch.parse_interval_min) +
    ' мин · постинга ' + fmt(sch.publish_interval_min) + ' мин';

  const risks = [];
  if (vk.error) risks.push(['bad', vk.error, '/settings']);
  else if (!vk.token_set) risks.push(['warn', 'Ключ VK не задан', '/settings']);
  if (sch.paused) risks.push(['warn', 'Крон на паузе', '/settings']);
  if (db.partial) risks.push(['warn', 'Частичные посты: ' + fmt(db.partial), '/ads?filter=partial']);
  const blocked = (S.sources || []).filter(s => s.last_status === 'blocked').length;
  if (blocked) risks.push(['bad', 'Источников заблокировано: ' + blocked, '/sources']);
  if (!(S.sources || []).length) risks.push(['warn', 'Нет источников парсинга', '/sources']);
  $('risks').innerHTML = risks.length ? risks.map(r => '<span class="risk'+
    (r[0] === 'warn' ? ' warn' : '')+'"><a href="'+r[2]+'">'+esc(r[1])+'</a></span>').join('')
    : '<span class="risk" style="background:var(--pill-positive-bg)"><a style="color:var(--pill-positive-ink)">Проблем нет</a></span>';

  const paused = !!sch.paused;
  $('schedPill').innerHTML = paused ? pill('warn', 'пауза') : pill('ok', 'активен');
  $('schedCard').innerHTML = [
    ['следующий парсинг', tm(sch.next_parse)],
    ['следующий постинг', tm(sch.next_publish)],
    ['интервалы', fmt(sch.parse_interval_min) + ' / ' + fmt(sch.publish_interval_min) + ' мин'],
    ['браузер', sch.browser_alive ? 'запущен' : 'остановлен'],
    ['итог прохода', sch.last_parse_result || '—']
  ].map(r => '<div class="kv"><span>'+r[0]+'</span><b>'+dash(r[1])+'</b></div>').join('');

  $('dashVkPill').innerHTML = vk.error ? pill('bad', 'ошибка')
    : (vk.token_set ? pill('ok', 'готов') : pill('warn', 'нет ключа'));
  const min = (vk.min_interval_sec || 0) / 60;
  $('dashVkCard').innerHTML = [
    ['ключ', vk.token_set ? (vk.token_kind || 'установлен') + ' · ' + esc(vk.token_mask || '') : 'не задан'],
    ['сообщество', vk.group_name || 'не определено'],
    ['стена', vk.wall || '—'],
    ['фото', vk.can_upload_photos ? 'разрешены ключом' : 'запрещены ключом'],
    ['очередь', fmt(vk.pending) + ' шт'],
    ['мин. пауза', min ? min.toFixed(1) + ' мин' : 'выключена'],
    ['требовать фото', vk.require_photos ? 'да' : 'нет']
  ].map(r => '<div class="kv"><span>'+r[0]+'</span><b>'+esc(r[1])+'</b></div>').join('') +
    (vk.error ? '<div style="padding:10px 16px;color:var(--negative);font-size:12px">'+esc(vk.error)+'</div>' : '');

  $('dashPosts').innerHTML = (S.recent_posts || []).length
    ? S.recent_posts.map(p => '<div class="lrow"><span class="lt">'+tm(p.posted_at)+
      '</span><a class="lmain" href="'+(p.vk_post_url || '#')+'" target="_blank" rel="noopener">'+
      esc(p.title || 'без названия')+'</a>'+
      (p.vk_post_url ? '<a class="rlink" href="'+p.vk_post_url+'" target="_blank" rel="noopener">открыть</a>' : '')+
      '</div>').join('')
    : '<div class="empty" style="margin:16px">Постов ещё не было</div>';
}
async function dashJobs(){
  const box = $('dashJobs');
  let d;
  try { d = await api('/api/jobs'); } catch (e) { return; }
  const jobs = (d.jobs || []).slice(0, 6);
  box.innerHTML = jobs.length
    ? jobs.map(j => '<div class="lrow"><span class="lt">'+tm(j.created_at)+
      '</span><span class="lmain">'+esc(j.kind)+ (j.status === 'error'
        ? ' <b style="color:var(--negative)">ошибка</b>' : ' · ' + esc(j.summary || j.status)) +
      '</span><a class="rlink" href="/jobs?job='+encodeURIComponent(j.id)+'">лог</a></div>').join('')
    : '<div class="empty" style="margin:16px">Задач ещё не было</div>';
}
async function dashRecent(){
  const box = $('dashRecent');
  try {
    const d = await api('/api/listings?per=6');
    const rows = d.items || [];
    if (!rows.length) { box.innerHTML = '<div class="empty emptycol">Пока ничего не спаррено — запустите парсинг.</div>'; return; }
    box.innerHTML = rows.map(a => {
      const ph = (a.photo_urls || []).slice(0, 3).map(u =>
        '<img src="' + esc(u) + '" alt="" loading="lazy" data-fallback>').join('');
      return '<article class="adcard"><div class="ph">' + (ph ||
        '<span class="noimg">нет фото</span>') + '</div><div class="bd">' +
        '<a class="t" href="' + (a.url || '#') + '" target="_blank" rel="noopener">' + esc(a.title) + '</a>' +
        '<span class="pr">' + dash(a.price) + '</span>' +
        '<span class="mt">' + esc(a.location || '') + ' · ' + dt(a.parsed_at) + '</span>' +
        '</div></article>';
    }).join('');
    imgFallback(box);
  } catch (e) { fail(box, 'Не удалось загрузить объявления: ' + e.message); }
}
$('btnParseAll').addEventListener('click', () =>
  startJob('/parse', {use_sources: true}, 'Парсинг всех активных источников запущен…'));
$('btnPublish').addEventListener('click', () =>
  startJob('/vk/publish', {}, 'Постинг запущен…'));
window.pageTick = () => { loadState().then(() => dashAll()).catch(() => {}); };
window.afterJob = () => { loadState().then(() => dashAll()).catch(() => {}); dashRecent().catch(() => {}); dashJobs().catch(() => {}); };
document.addEventListener('DOMContentLoaded', () => {
  loadState().then(() => dashAll()).catch(() => {});
  dashRecent().catch(() => {});
  dashJobs().catch(() => {});
});
"""

# --------------------------------------------------------------------- #
# раздел: объявления
# --------------------------------------------------------------------- #
ADS_PAGE = r"""
    <section class="page">
      <div class="titlerow">
        <div>
          <h1>Объявления</h1>
          <p class="sub">База спаренных объявлений и очередь публикаций. Фильтр и поиск —
            в адресной строке, ссылку можно передать или открыть напрямую.</p>
        </div>
        <div class="actions">
          <button class="btn" id="btnRequeueSel" disabled>Вернуть в очередь</button>
          <button class="btn" id="btnDelSel" disabled>Удалить</button>
          <a class="btn" href="/export.csv" id="adsExport">Выгрузить CSV</a>
          <a class="btn" href="/api/listings?format=json" id="adsJson">JSON</a>
        </div>
      </div>

      <div class="tabs" id="adCounts"></div>
      <div class="toolbar">
        <input type="search" id="adSearch" placeholder="Поиск по названию, описанию, городу, ID" aria-label="Поиск объявлений">
        <button class="btn sm" id="btnSearch">Искать</button>
        <span class="note" id="adsCount"></span>
        <div class="pager">
          <button class="btn sm" id="adsPrev">Назад</button>
          <span id="adsPage">1</span>
          <button class="btn sm" id="adsNext">Вперёд</button>
        </div>
      </div>

      <div class="card flush">
        <div class="tablewrap">
          <table>
            <thead><tr>
              <th style="width:34px"><input type="checkbox" id="adsAll" aria-label="Выбрать все на странице"></th>
              <th>Объявление</th>
              <th>Цена</th>
              <th>Город</th>
              <th>Источник</th>
              <th>Статус</th>
              <th>Обновлено</th>
              <th class="r">Действия</th>
            </tr></thead>
            <tbody id="adsBody"></tbody>
          </table>
        </div>
      </div>
    </section>
"""
ADS_SCRIPT = r"""
/* ---------- объявления: фильтр/поиск/страницы живут в URL ---------- */
const ads = {flt: 'all', q: '', page: 1, per: 25, counts: {}};
const picked = new Set();

function adsReadUrl(){
  const q = new URLSearchParams(location.search);
  ads.flt = q.get('filter') || 'all';
  ads.q = q.get('q') || '';
  ads.page = Math.max(1, parseInt(q.get('page') || '1', 10) || 1);
}
function adsWriteUrl(){
  linkTo({filter: ads.flt === 'all' ? null : ads.flt, q: ads.q || null,
          page: ads.page > 1 ? ads.page : null});
}
function statusPill(a){
  if (a.posted_to_vk) return pill('ok', 'опубл.' + (a.vk_post_url ? '' : ' без ссылки'));
  if (a.status === 'partial') return pill('warn', 'недопаршено');
  return pill('acc', 'в очереди');
}
function adsCounts(d){
  ads.counts = d.counts || {};
  const defs = [['all', 'Все'], ['pending', 'В очереди'], ['posted', 'Опубликовано'], ['partial', 'Частично']];
  $('adCounts').innerHTML = defs.map(f => '<button data-f="' + f[0] + '"' +
    (f[0] === ads.flt ? ' class="sel"' : '') + '>' + f[1] +
    '<b class="num">' + fmt(ads.counts[f[0]]) + '</b></button>').join('');
  $('adCounts').querySelectorAll('button[data-f]').forEach(b => b.addEventListener('click', () => {
    ads.flt = b.dataset.f; ads.page = 1; adsWriteUrl(); adsLoad();
  }));
}
async function adsLoad(){
  const body = $('adsBody');
  body.innerHTML = '<tr><td class="nolabel" colspan="8" style="color:var(--muted)">Загрузка…</td></tr>';
  const qs = 'filter=' + encodeURIComponent(ads.flt) + '&q=' + encodeURIComponent(ads.q) +
             '&page=' + ads.page + '&per=' + ads.per;
  let d;
  try { d = await api('/api/listings?' + qs); }
  catch (e) { fail(body, 'Не удалось загрузить объявления: ' + e.message); return; }
  adsCounts(d);
  const rows = d.items || [];
  const total = d.total || 0, pages = Math.max(1, Math.ceil(total / ads.per));
  $('adsCount').textContent = 'показано ' + fmt(rows.length) + ' из ' + fmt(total);
  $('adsPage').textContent = ads.page + ' / ' + pages;
  $('adsPrev').disabled = ads.page <= 1;
  $('adsNext').disabled = ads.page >= pages;
  $('adsExport').href = '/export.csv?' + qs;
  $('adsJson').href = '/api/listings?' + qs;
  $('adsAll').checked = false;
  if (!rows.length) {
    body.innerHTML = '<tr><td class="nolabel" colspan="8"><div class="empty" style="margin:8px 0">' +
      (ads.q ? 'Ничего не найдено по запросу «' + esc(ads.q) + '»' : 'В этом фильтре пока пусто') +
      '</div></td></tr>';
    syncPick();
    return;
  }
  body.innerHTML = rows.map(a => {
    const img = (a.photo_urls || [])[0];
    const thumb = img
      ? '<img class="thumb" src="' + esc(img) + '" alt="" loading="lazy" data-fallback>'
      : '<span class="thumbph">нет&nbsp;фото</span>';
    const note = a.status === 'partial'
      ? '<div class="t2" style="color:var(--warning)">карточка не дочитана (partial)</div>' : '';
    return '<tr data-id="' + esc(a.avito_id) + '">' +
      '<td class="nolabel"><input type="checkbox" class="pick" aria-label="Выбрать объявление"></td>' +
      '<td class="nolabel"><div class="adcell">' + thumb + '<div class="tw">' +
        '<a class="t1" href="' + (a.url || '#') + '" target="_blank" rel="noopener">' + esc(a.title) + '</a>' +
        '<div class="idcell mono">id ' + esc(a.avito_id) + ' · ' + esc(a.source_label || '') + '</div>' +
        note + '</div></div></td>' +
      '<td class="num" data-label="Цена">' + dash(a.price) + '</td>' +
      '<td data-label="Город"><span class="srcell">' + dash(a.location) + '</span></td>' +
      '<td data-label="Источник"><span class="srcell" title="' + esc(a.source_url || '') + '">' +
        dash(a.source_label || a.source_url) + '</span></td>' +
      '<td data-label="Статус">' + statusPill(a) + (a.vk_post_url
        ? ' <a class="rlink" href="' + esc(a.vk_post_url) + '" target="_blank" rel="noopener">пост</a>'
        : '') + '</td>' +
      '<td data-label="Парсинг" class="dtc">' + dt(a.parsed_at) + '</td>' +
      '<td class="r nolabel"><div class="acts">' +
        '<button class="btn txt acc" data-act="one">Запостить</button>' +
        '<button class="btn txt" data-act="requeue">В очередь</button>' +
        '<button class="btn txt neg" data-act="del">Удалить</button>' +
      '</div></td></tr>';
  }).join('');
  body.querySelectorAll('tr[data-id]').forEach(tr => {
    const id = tr.dataset.id;
    tr.querySelector('.pick').addEventListener('change', (e) => {
      e.target.checked ? picked.add(id) : picked.delete(id); syncPick();
    });
    tr.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => rowAction(b.dataset.act, id)));
  });
  imgFallback(body);
  syncPick();
}
function syncPick(){
  $('btnDelSel').disabled = $('btnRequeueSel').disabled = picked.size === 0;
  $('btnDelSel').textContent = picked.size ? 'Удалить (' + picked.size + ')' : 'Удалить';
  $('btnRequeueSel').textContent = picked.size ? 'Вернуть в очередь (' + picked.size + ')' : 'Вернуть в очередь';
}
async function rowAction(act, id){
  const route = act === 'one' ? '/vk/publish-one' : '/api/ads';
  const body = act === 'one' ? {avito_id: id}
    : {action: act === 'del' ? 'delete' : 'requeue', avito_id: id};
  if (act === 'del' && !confirm('Удалить объявление ' + id + ' из базы?')) return;
  try {
    if (act === 'one') await startJob(route, body, 'Постим объявление ' + id + '…');
    else { await post(route, body); statusMsg('Готово', 'ok'); adsLoad(); loadState().catch(() => {}); }
  } catch (e) { statusMsg('Ошибка: ' + e.message, 'err'); }
}
async function bulkAction(action){
  if (!picked.size) return;
  if (action === 'delete' && !confirm('Удалить ' + picked.size + ' объявлений из базы?')) return;
  const ids = [...picked];
  let done = 0, failed = 0;
  for (const id of ids) {
    try { await post('/api/ads', {action, avito_id: id}); done++; }
    catch (e) { failed++; }
  }
  picked.clear();
  statusMsg('Обработано ' + done + (failed ? ', ошибок ' + failed : ''), failed ? 'err' : 'ok');
  adsLoad(); loadState().catch(() => {});
}
$('btnSearch').addEventListener('click', () => {
  ads.q = $('adSearch').value.trim(); ads.page = 1; adsWriteUrl(); adsLoad();
});
$('adSearch').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('btnSearch').click(); });
$('adsPrev').addEventListener('click', () => { ads.page = Math.max(1, ads.page - 1); adsWriteUrl(); adsLoad(); });
$('adsNext').addEventListener('click', () => { ads.page += 1; adsWriteUrl(); adsLoad(); });
$('adsAll').addEventListener('change', (e) => {
  document.querySelectorAll('#adsBody .pick').forEach(c => {
    c.checked = e.target.checked;
    const id = c.closest('tr').dataset.id;
    e.target.checked ? picked.add(id) : picked.delete(id);
  });
  syncPick();
});
$('btnDelSel').addEventListener('click', () => bulkAction('delete'));
$('btnRequeueSel').addEventListener('click', () => bulkAction('requeue'));
window.pageTick = () => { if (!app.running) adsLoad().catch(() => {}); };
document.addEventListener('DOMContentLoaded', () => {
  adsReadUrl();
  $('adSearch').value = ads.q;
  adsWriteUrl();
  adsLoad().catch(() => {});
});
"""

# --------------------------------------------------------------------- #
# раздел: источники
# --------------------------------------------------------------------- #
SOURCES_PAGE = r"""
    <section class="page">
      <div class="titlerow">
        <div>
          <h1>Источники</h1>
          <p class="sub">Страницы Авито, которые крон обходит по кругу. Отключение не удаляет
            уже спаренные объявления.</p>
        </div>
        <div class="actions">
          <button class="btn" id="btnParseSources">Парсить все активные</button>
          <button class="btn primary" id="btnAddSource">Добавить источник</button>
        </div>
      </div>

      <div class="card block" id="srcFormCard" hidden>
        <div class="frow">
          <div class="field" style="flex:1 1 360px">
            <span>Ссылка на выдачу Авито</span>
            <input type="search" id="srcUrl" placeholder="https://www.avito.ru/...">
            <small>например: https://www.avito.ru/rossiya/prodazh_avto</small>
          </div>
          <div class="field">
            <span>Объявлений за пуск</span>
            <input type="number" id="srcLimit" min="1" max="100" placeholder="10">
            <small>лимит на карточки, не на страницы выдачи</small>
          </div>
          <div class="field" style="justify-content:flex-end">
            <button class="btn primary" id="btnSaveSource">Сохранить и спарсить</button>
          </div>
        </div>
      </div>

      <div class="card flush">
        <div class="tablewrap">
          <table>
            <thead><tr>
              <th>Источник</th><th>Метка</th><th class="num">Всего</th><th class="num">Новых</th>
              <th class="num">Запусков</th><th>Последний статус</th><th>Проверен</th>
              <th class="r">Действия</th>
            </tr></thead>
            <tbody id="srcBody"></tbody>
          </table>
        </div>
      </div>
    </section>
"""
SOURCES_SCRIPT = r"""
/* ---------- источники ---------- */
const SRC_STATUS = {ok: ['ok', 'ok'], empty: ['acc', 'пусто'],
  blocked: ['warn', 'блокировка'], error: ['bad', 'ошибка']};
async function srcLoad(){
  const body = $('srcBody');
  try { await loadState(); } catch (e) { return fail(body, 'Не удалось загрузить источники: ' + e.message); }
  const rows = app.S.sources || [];
  if (!rows.length) {
    body.innerHTML = '<tr><td class="nolabel" colspan="8"><div class="empty" style="margin:8px 0">' +
      'Источников нет — добавьте выдачу Авито</div></td></tr>';
    return;
  }
  body.innerHTML = rows.map(s => {
    const st = SRC_STATUS[s.last_status] || ['off', s.last_status || 'ещё не проверялся'];
    const off = s.enabled === false ? ' ' + pill('off', 'отключён') : '';
    return '<tr data-url="' + esc(s.url) + '">' +
      '<td class="nolabel" style="max-width:340px"><span class="srcell" title="' + esc(s.url) + '">' +
        '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.url) + '</a></span></td>' +
      '<td data-label="Метка">' + dash(s.label) + off + '</td>' +
      '<td class="num" data-label="Всего">' + fmt(s.total_new) + '</td>' +
      '<td class="num" data-label="Новых">' + fmt(s.last_new) + '</td>' +
      '<td class="num" data-label="Запусков">' + fmt(s.runs) + '</td>' +
      '<td data-label="Последний статус">' + pill(st[0], st[1]) +
        (s.last_found ? ' <span class="t2">' + fmt(s.last_found) + ' шт</span>' : '') + '</td>' +
      '<td data-label="Проверен" class="dtc">' + dt(s.last_check) + '</td>' +
      '<td class="r nolabel"><div class="acts">' +
        '<button class="btn txt acc" data-act="parse">Парсить</button>' +
        '<button class="btn txt" data-act="toggle">' + (s.enabled === false ? 'Включить' : 'Отключить') + '</button>' +
        '<button class="btn txt neg" data-act="del">Удалить</button>' +
      '</div></td></tr>';
  }).join('');
  body.querySelectorAll('tr[data-url]').forEach(tr => {
    const url = tr.dataset.url;
    tr.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => srcAction(b.dataset.act, url)));
  });
}
async function srcAction(act, url){
  if (act === 'parse') return startJob('/parse', {url}, 'Парсинг запущен…');
  if (act === 'toggle') {
    await post('/api/sources', {action: 'toggle', url});
    statusMsg('Готово', 'ok'); srcLoad(); return;
  }
  if (act === 'del') {
    if (!confirm('Удалить источник из списка отслеживаемых? Объявления останутся в базе.')) return;
    await post('/api/sources', {action: 'remove', url});
    statusMsg('Источник удалён', 'ok'); srcLoad();
  }
}
$('btnAddSource').addEventListener('click', () => {
  const card = $('srcFormCard');
  card.hidden = !card.hidden;
  if (!card.hidden) $('srcUrl').focus();
});
$('btnSaveSource').addEventListener('click', async () => {
  const url = $('srcUrl').value.trim();
  if (!url) { statusMsg('Введите ссылку на выдачу Авито', 'err'); return; }
  try {
    await post('/api/sources', {action: 'add', url});
    $('srcUrl').value = '';
    $('srcFormCard').hidden = true;
    const limit = parseInt($('srcLimit').value || '0', 10) || undefined;
    await srcLoad();
    startJob('/parse', {url, limit}, 'Парсинг запущен…');
  } catch (e) { statusMsg('Ошибка: ' + e.message, 'err'); }
});
$('btnParseSources').addEventListener('click', () =>
  startJob('/parse', {use_sources: true}, 'Парсинг всех активных запущен…'));
window.pageTick = () => { if (!app.running) srcLoad().catch(() => {}); };
document.addEventListener('DOMContentLoaded', () => srcLoad().catch(() => {}));
"""

# --------------------------------------------------------------------- #
# раздел: VK-канал
# --------------------------------------------------------------------- #
VK_PAGE = r"""
    <section class="page">
      <div class="titlerow">
        <div>
          <h1>VK-канал</h1>
          <p class="sub">Ключ сообщества, права на публикацию и фото, очередь постов и
            история уже опубликованного.</p>
        </div>
        <div class="actions">
          <button class="btn" id="btnVkCheck">Проверить права</button>
          <a class="btn" href="/settings">Настроить ключ</a>
          <button class="btn primary" id="btnVkPublish">Постить очередь</button>
        </div>
      </div>

      <div class="kpis" id="vkKpis">
        <div class="kpi"><span>В очереди</span><b class="skel big"></b><em>ждут поста</em></div>
        <div class="kpi"><span>Опубликовано всего</span><b class="skel big"></b><em>с постом в VK</em></div>
        <div class="kpi"><span>За сегодня</span><b class="skel big"></b><em>постов</em></div>
        <div class="kpi"><span>Последний пост</span><b class="skel big"></b><em>время</em></div>
      </div>

      <div class="vkgrid">
        <div class="card flush">
          <div class="cardhead"><h2>Сообщество и ключ</h2><span id="vkPill"></span></div>
          <div id="vkCard"></div>
        </div>
        <div class="card flush">
          <div class="cardhead"><h2>Предпросмотр следующего поста</h2>
            <button class="btn sm" id="btnPvRefresh">Обновить</button></div>
          <div id="pvCard" style="padding:16px"></div>
        </div>
      </div>

      <div class="block" style="margin-top:var(--gap)">
        <h2 class="sectiontitle">История публикаций
          <span class="count"><a href="/ads?filter=posted">все опубликованные →</a></span></h2>
        <div class="card flush">
          <div class="tablewrap">
            <table>
              <thead><tr>
                <th>Когда</th><th>Объявление</th><th>Пост в VK</th><th class="num">Фото</th>
              </tr></thead>
              <tbody id="vkHistBody"></tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
"""
VK_SCRIPT = r"""
/* ---------- VK-канал ---------- */
async function vkLoad(){
  const box = $('vkCard');
  let vk, S;
  try { S = app.S || await loadState(); vk = await api('/api/vk'); }
  catch (e) { return fail(box, 'Не удалось получить состояние VK: ' + e.message); }
  const min = (vk.min_interval_sec || 0) / 60;
  $('vkPill').innerHTML = vk.error ? pill('bad', 'ошибка')
    : (vk.token_set ? pill('ok', 'готов') : pill('warn', 'нет ключа'));
  const rows = [
    ['ключ', vk.token_set ? (vk.token_kind || 'установлен') + ' · ' + (vk.token_mask || '') : 'не задан'],
    ['сообщество', vk.group_name || 'не определено'],
    ['id сообщества', vk.group_id || '—'],
    ['стена', vk.wall || '—'],
    ['права', vk.is_admin ? 'подтверждены (can_post)' : 'не подтверждены'],
    ['загрузка фото', vk.can_upload_photos ? 'разрешена ключом' : 'запрещена ключом (код 27)'],
    ['приложение', vk.app_id ? 'id ' + vk.app_id + ' (standalone OAuth)' : 'VK_APP_ID не задан'],
    ['макс. фото в посте', fmt(vk.max_photos)],
    ['требовать фото', vk.require_photos ? 'да' : 'нет'],
    ['мин. пауза между постами', min ? min.toFixed(1) + ' мин' : 'выключена'],
    ['шаблон поста', vk.template ? (String(vk.template).split('\n')[0].slice(0, 40) + '…') : 'по умолчанию'],
    ['последний пост', vk.last_post_at ? dt(vk.last_post_at) : '—']
  ];
  box.innerHTML = rows.map(r => '<div class="kv"><span>' + r[0] + '</span><b>' + esc(r[1]) + '</b></div>').join('') +
    (vk.error ? '<div style="padding:12px 16px;color:var(--negative);font-size:13px;border-top:1px solid var(--rule)">' + esc(vk.error) + '</div>' : '') +
    (vk.token_set && vk.can_upload_photos === false
      ? '<div style="padding:12px 16px;font-size:13px;color:var(--muted);border-top:1px solid var(--rule)">' +
        'Ключ сообщества не умеет загружать фото на стену — нужен <b>ключ пользователя</b>, ' +
        'полученный через standalone OAuth.</div>' : '') +
    (vk.oauth_url ? '<div style="padding:12px 16px;border-top:1px solid var(--rule)">' +
      '<a class="btn sm" id="vkOauthLink" href="' + esc(vk.oauth_url) + '" target="_blank" rel="noopener">' +
      'Получить ключ пользователя</a><small style="display:block;margin-top:8px;color:var(--muted);font-size:12px">' +
      'scope: photos, wall, groups, offline · redirect: oauth.vk.com/blank.html</small></div>' : '');

  const last = (S.recent_posts || [])[0];
  $('vkKpis').innerHTML = [
    ['В очереди', fmt(vk.pending), 'ждут поста', '/ads?filter=pending'],
    ['Опубликовано', fmt(vk.posted), 'с постом в VK', '/ads?filter=posted'],
    ['Недопаршено', fmt(S.db ? S.db.partial : 0), 'не пойдут в пост', '/ads?filter=partial'],
    ['Последний пост', last ? dt(last.posted_at) : '—',
      last ? (last.title || '') : 'публикаций ещё не было', last ? (last.vk_post_url || '') : '']
  ].map(k => '<div class="kpi"><span>' + k[0] + '</span><b>' + (k[3] ? '<a href="' + esc(k[3]) +
    '" target="_blank" rel="noopener">' + k[1] + '</a>' : k[1]) +
    '</b><em>' + esc(k[2]) + '</em></div>').join('');

  await vkPreview();
  await vkHistory();
}
async function vkPreview(){
  const box = $('pvCard');
  box.innerHTML = '<span class="skel" style="width:60%"></span>';
  let p;
  try { p = await api('/api/preview'); }
  catch (e) { return fail(box, 'Нет предпросмотра: ' + e.message); }
  if (!p || p.empty || !p.title) { box.innerHTML = '<div class="empty">Очередь пуста — нечего постить</div>'; return; }
  const imgs = (p.photo_urls || []).slice(0, 3).map(u =>
    '<img class="ph" src="' + esc(u) + '" alt="" loading="lazy" data-fallback>').join('');
  box.innerHTML = '<div class="t2 mono" style="margin-bottom:8px">id ' + esc(p.avito_id || '') + ' · ' +
    esc(p.title) + '</div>' +
    '<div class="msg">' + esc(p.message || '') + '</div>' +
    (imgs ? '<div class="pvrow">' + imgs + '</div>'
           : '<div class="pvrow"><span class="phph">фото нет</span><span class="t2">пост уйдёт без вложений</span></div>');
  imgFallback(box);
}
async function vkHistory(){
  const body = $('vkHistBody');
  let d;
  try { d = await api('/api/listings?filter=posted&per=30'); }
  catch (e) { return fail(body, 'Не удалось загрузить историю: ' + e.message); }
  const rows = d.items || [];
  if (!rows.length) {
    body.innerHTML = '<tr><td class="nolabel" colspan="4"><div class="empty" style="margin:8px 0">' +
      'Опубликованных постов пока нет</div></td></tr>';
    return;
  }
  body.innerHTML = rows.map(a => '<tr>' +
    '<td class="dtc" data-label="Когда">' + dt(a.posted_at) + '</td>' +
    '<td class="nolabel" style="max-width:420px"><a class="t1" href="' + (a.url || '#') +
      '" target="_blank" rel="noopener">' + esc(a.title) + '</a>' +
      '<div class="t2">' + dash(a.price) + ' · ' + esc(a.location || '') + '</div></td>' +
    '<td data-label="Пост в VK">' + (a.vk_post_url
      ? '<a class="mono" style="color:var(--accent);font-size:13px" href="' + esc(a.vk_post_url) +
        '" target="_blank" rel="noopener">' + esc(String(a.vk_post_url).replace(/^https:\/\/vk\.com\//, '')) + '</a>'
      : '<span class="t2">ссылка не записана</span>') + '</td>' +
    '<td class="num" data-label="Фото">' + fmt((a.photo_urls || []).length) + '</td></tr>').join('');
}
$('btnVkCheck').addEventListener('click', async () => {
  statusMsg('Проверяем ключ и сообщество…');
  try { await api('/api/vk?refresh=1'); await loadState(); await vkLoad(); statusMsg('Проверено', 'ok'); }
  catch (e) { statusMsg('Ошибка: ' + e.message, 'err'); }
});
$('btnPvRefresh').addEventListener('click', () => vkPreview());
$('btnVkPublish').addEventListener('click', () =>
  startJob('/vk/publish', {}, 'Постинг очереди запущен…'));
window.afterJob = () => { loadState().then(() => vkLoad()).catch(() => {}); };
window.pageTick = () => { if (!app.running) loadState().then(() => vkLoad()).catch(() => {}); };
document.addEventListener('DOMContentLoaded', () => loadState().then(() => vkLoad()).catch(() => {}));
"""

# --------------------------------------------------------------------- #
# раздел: задачи
# --------------------------------------------------------------------- #
JOBS_PAGE = r"""
    <section class="page">
      <div class="titlerow">
        <div>
          <h1>Задачи</h1>
          <p class="sub">Журнал фонового парсинга и постинга за текущий запуск сервера:
            параметры, прогресс, лог и объявления каждой задачи.</p>
        </div>
        <div class="actions">
          <button class="btn" id="btnParseAll2">Спарсить всё</button>
          <button class="btn primary" id="btnPublish2">Постить очередь</button>
        </div>
      </div>
      <div class="card flush">
        <div class="tablewrap">
          <table>
            <thead><tr>
              <th>Начало</th><th>Тип</th><th>Статус</th><th>Прогресс</th>
              <th>Итог</th><th class="num">Секунд</th><th>Лог</th>
            </tr></thead>
            <tbody id="jobsBody"></tbody>
          </table>
        </div>
      </div>
    </section>
"""
JOBS_SCRIPT = r"""
/* ---------- задачи: детали раскрываются строкой под задачей ---------- */
const JOB_STATUS = {done: ['ok', 'готово'], running: ['acc', 'выполняется'],
  error: ['bad', 'ошибка'], queued: ['off', 'в очереди']};
const jobCache = {};
let openJobId = new URLSearchParams(location.search).get('job') || '';

function jobLogRow(job){
  const lines = (job.log || []).slice(-40);
  const ads = (job.ads || []).map(a => typeof a === 'object' ? a : {avito_id: a});
  return '<tr class="logtr"><td class="nolabel" colspan="7">' +
    '<div class="joblog">' + (lines.length ? esc(lines.join('\n')) : 'лог пуст') + '</div>' +
    ((job.sources || []).length ? '<div class="t2" style="margin-top:8px">источники: ' +
      job.sources.map(s => esc(s.label || s.url) + (s.status ? ' (' + esc(s.status) + ')' : '')).join(', ') +
      '</div>' : '') +
    (ads.length ? '<div class="t2" style="margin-top:6px">объявления задачи: ' +
      ads.slice(0, 40).map(a => '<a class="mono" href="/ads?q=' + encodeURIComponent(a.avito_id || '') +
        '">' + esc(a.avito_id) + '</a>').join(', ') + (ads.length > 40 ? ' …' : '') + '</div>' : '') +
    ((job.posts || []).length ? '<div class="t2" style="margin-top:6px">' +
      job.posts.map(p => p.ok
        ? '<a href="' + (p.post_url || '#') + '" target="_blank" rel="noopener">пост ' + esc(p.avito_id) +
          '</a> · фото ' + fmt(p.photos) + ' · ' + fmt(p.chars) + ' симв.' +
          (p.dry_run ? ' (dry-run)' : '')
        : '<span style="color:var(--negative)">ошибка ' + esc(p.avito_id) + ': ' +
          esc(p.error || p.skipped || '') + '</span>'
      ).join('<br>') + '</div>' : '') +
    '</td></tr>';
}
async function jobsLoad(){
  const body = $('jobsBody');
  let d;
  try { d = await api('/api/jobs'); }
  catch (e) { return fail(body, 'Не удалось загрузить задачи: ' + e.message); }
  const jobs = d.jobs || [];
  if (!jobs.length) {
    body.innerHTML = '<tr><td class="nolabel" colspan="7"><div class="empty" style="margin:8px 0">' +
      'Задач ещё не было</div></td></tr>';
    return;
  }
  let html = '';
  for (const j of jobs) {
    const st = JOB_STATUS[j.status] || ['off', j.status];
    html += '<tr data-job="' + esc(j.id) + '">' +
      '<td class="dtc" data-label="Начало">' + tm(j.created_at) + '</td>' +
      '<td data-label="Тип">' + esc(j.kind) + '</td>' +
      '<td data-label="Статус">' + pill(st[0], st[1]) + '</td>' +
      '<td data-label="Прогресс"><span class="t2">' + dash(j.progress) + '</span></td>' +
      '<td data-label="Итог"><span class="t2" style="' + (j.status === 'error' ? 'color:var(--negative)' : '') +
        '">' + dash(j.error || j.summary) + '</span></td>' +
      '<td class="num" data-label="Секунд">' + (j.elapsed != null ? fmt(Math.round(j.elapsed)) : '—') + '</td>' +
      '<td data-label="Лог"><button class="btn txt" data-toggle="' + esc(j.id) + '">' +
        (j.id === openJobId ? 'скрыть' : 'показать') + '</button></td></tr>';
    if (j.id === openJobId) {
      let full = j;
      try { full = await api('/job/' + j.id); } catch (e) {}
      jobCache[j.id] = full;
      html += jobLogRow(full);
    }
  }
  body.innerHTML = html;
  body.querySelectorAll('[data-toggle]').forEach(b => b.addEventListener('click', async () => {
    const id = b.dataset.toggle;
    const row = b.closest('tr');
    if (openJobId === id) {
      openJobId = ''; linkTo({job: null});
      const next = row.nextElementSibling;
      if (next && next.classList.contains('logtr')) next.remove();
      b.textContent = 'показать';
      return;
    }
    openJobId = id; linkTo({job: id});
    statusMsg('Загружаем лог задачи ' + id + '…');
    let full;
    try { full = await api('/job/' + id); }
    catch (e) { statusMsg('Ошибка: ' + e.message, 'err'); return; }
    jobCache[id] = full;
    const existing = row.nextElementSibling;
    if (existing && existing.classList.contains('logtr')) existing.remove();
    row.insertAdjacentHTML('afterend', jobLogRow(full));
    body.querySelectorAll('[data-toggle]').forEach(x => { x.textContent = 'показать'; });
    b.textContent = 'скрыть';
    statusMsg('Готово', 'ok');
  }));
}
$('btnParseAll2').addEventListener('click', () =>
  startJob('/parse', {use_sources: true}, 'Парсинг всех активных запущен…'));
$('btnPublish2').addEventListener('click', () =>
  startJob('/vk/publish', {}, 'Постинг очереди запущен…'));
window.afterJob = () => { jobsLoad().catch(() => {}); };
window.pageTick = () => { jobsLoad().catch(() => {}); };
document.addEventListener('DOMContentLoaded', () => jobsLoad().catch(() => {}));
"""

# --------------------------------------------------------------------- #
# раздел: логи
# --------------------------------------------------------------------- #
LOGS_PAGE = r"""
    <section class="page">
      <div class="titlerow">
        <div>
          <h1>Логи</h1>
          <p class="sub">Хвост файла лога сервера (<span class="mono">logs/avito_parser.log</span>).
            Открывается на нужной странице, поэтому автообновление можно выключить и перечитать
            файл целиком.</p>
        </div>
        <div class="actions">
          <label class="switch"><input type="checkbox" id="logAuto" checked><span class="track"></span>Автообновление</label>
          <button class="btn" id="btnLogRefresh">Перечитать</button>
          <a class="btn primary" href="/api/logs?download=1">Скачать лог</a>
        </div>
      </div>
      <div class="logbox" id="logbox">Читаем лог…</div>
    </section>
"""
LOGS_SCRIPT = r"""
/* ---------- логи: читаем хвост, автообновление отключаемо ---------- */
async function logsLoad(){
  const box = $('logbox');
  try {
    const d = await api('/api/logs?tail=2000');
    const text = (d.lines || []).join('\n');
    box.textContent = d.exists ? (text || 'лог пуст') : ('лог-файл ещё не создан: ' + (d.path || ''));
    /* автоскролл вниз только если пользователь и так у конца — не перебиваем чтение */
    if (box.scrollHeight - box.scrollTop - box.clientHeight < 80) box.scrollTop = box.scrollHeight;
    $('stamp').textContent = 'лог обновлён ' + tm(new Date().toISOString());
  } catch (e) { fail(box, 'Не удалось прочитать лог: ' + e.message); }
}
$('btnLogRefresh').addEventListener('click', () => logsLoad());
$('logAuto').addEventListener('change', (e) => {
  if (app.logTimer) { clearInterval(app.logTimer); app.logTimer = null; }
  if (e.target.checked) app.logTimer = setInterval(() => logsLoad(), 5000);
  statusMsg(e.target.checked ? 'Автообновление включено' : 'Автообновление выключено', 'ok');
});
window.pageTick = () => { if ($('logAuto').checked) logsLoad().catch(() => {}); };
document.addEventListener('DOMContentLoaded', () => {
  logsLoad().catch(() => {});
  app.logTimer = setInterval(() => logsLoad(), 5000);
});
"""

# --------------------------------------------------------------------- #
# раздел: настройки
# --------------------------------------------------------------------- #
# Форма целиком собирается из реестра avito_parser/settings.py: чтобы добавить
# параметр, достаточно записать его в SPECS (и, при необходимости, в GROUPS).
def _esc(value: object) -> str:
    return _escape(str(value if value is not None else ""), quote=True)


def _gnum(value: float) -> str:
    """Число для HTML-атрибута: 2.0 → '2', 0.5 → '0.5'."""
    return ("%g" % float(value))


def setting_field_html(spec: SettingSpec) -> str:
    """Одно поле формы: id s_<ключ> плюс data-setting/data-kind для JS раздела."""
    fid = "s_" + spec.key
    label = _esc(spec.label)
    hint = f"<small>{_esc(spec.hint)}</small>" if spec.hint else ""
    placeholder = f' placeholder="{_esc(spec.placeholder)}"' if spec.placeholder else ""
    common = f'id="{fid}" data-setting="{spec.key}"'

    if spec.kind == "bool":
        text = f"<b>{label}</b>" + (f"<small>{_esc(spec.hint)}</small>" if spec.hint else "")
        return (f'<div class="switchrow"><div class="tw">{text}</div>'
                f'<label class="switch"><input type="checkbox" {common} data-kind="bool"'
                f' aria-label="{label}"><span class="track"></span></label></div>')

    if spec.kind in ("int", "float"):
        bounds = ""
        if spec.minimum is not None:
            bounds += f' min="{_gnum(spec.minimum)}"'
        if spec.maximum is not None:
            bounds += f' max="{_gnum(spec.maximum)}"'
        bounds += f' step="{_gnum(spec.step if spec.step is not None else (1 if spec.kind == "int" else 0.5))}"'
        return (f'<label class="field"><span>{label}</span>'
                f'<input type="number" {common} data-kind="num"{bounds}{placeholder}>{hint}</label>')

    if spec.choices:
        options = "".join(f'<option value="{_esc(choice)}">{_esc(choice)}</option>' for choice in spec.choices)
        return (f'<label class="field"><span>{label}</span>'
                f'<select {common} data-kind="select">{options}</select>{hint}</label>')

    if spec.kind in ("multiline", "list"):
        rows = 6 if spec.kind == "multiline" else 4
        return (f'<label class="field wide"><span>{label}</span>'
                f'<textarea rows="{rows}" {common} data-kind="{spec.kind}"{placeholder}'
                f' spellcheck="false"></textarea>{hint}</label>')

    if spec.kind == "secret":
        return (f'<label class="field"><span>{label}</span>'
                f'<input type="password" {common} data-kind="secret"'
                f' autocomplete="new-password"{placeholder}>{hint}</label>')

    mono = ' class="mono"' if spec.kind == "path" else ""
    return (f'<label class="field"><span>{label}</span>'
            f'<input type="text" {common} data-kind="text"{mono}{placeholder}>{hint}</label>')


def _row_sizes(count: int) -> list[int]:
    """Сколько полей в ряду: три колонки, но без одинокого хвоста (4 -> 2+2, 7 -> 3+2+2)."""
    if count <= 0:
        return []
    if count <= 3:
        return [count]
    sizes = [3] * (count // 3)
    if count % 3:
        sizes.append(count % 3)
    if sizes[-1] == 1:
        sizes[-1] = 2
        sizes[-2] = 2
    return sizes


def _settings_panel(specs: list[SettingSpec]) -> str:
    """Панель раздела: поля рядами равной ширины, переключатели — столбцом."""
    parts: list[str] = []
    buffer: list[SettingSpec] = []

    def emit(items: list[SettingSpec]) -> None:
        for size in _row_sizes(len(items)):
            cols = f' style="grid-template-columns:repeat({size},minmax(0,1fr))"'
            parts.append("<div class=\"setrow\"" + cols + ">"
                         + "".join(setting_field_html(spec) for spec in items[:size]) + "</div>")
            items = items[size:]

    for spec in [s for s in specs if s.kind != "bool"]:
        if spec.kind in ("multiline", "list"):   # широкие поля всегда занимают весь ряд
            emit(buffer)
            buffer = []
            parts.append('<div class="setrow" style="grid-template-columns:1fr">'
                         + setting_field_html(spec) + "</div>")
        else:
            buffer.append(spec)
    emit(buffer)
    parts.extend(setting_field_html(spec) for spec in specs if spec.kind == "bool")
    return "".join(parts)


# блоки, которые нельзя вывести из реестра: статус прокси, состояние ключа, подсказки
GROUP_EXTRAS: dict[str, str] = {
    "parse": r"""
        <div class="t2">Ссылки для парсинга ведутся в разделе
          <a href="/sources">Источники</a>: крон обходит включённые строки, а новая ссылка
          в первый прогон берётся с лимитом выше. В <span class="mono">.env</span> адрес выдачи
          больше не читается.</div>""",
    "proxy": r"""
        <div class="card" id="proxyCard" style="box-shadow:none">
          <div class="cardhead" style="padding:0 0 10px;border-bottom:0">
            <h3 style="font-size:14px">Прокси</h3><span id="proxyPill"></span>
          </div>
          <div id="proxyBody" class="t2">статус прокси не загружен</div>
        </div>""",
    "vk": r"""
        <div class="t2" id="s_vktoken_state">—</div>
        <div class="t2" id="s_appid_state">—</div>""",
    "access": r"""
        <div class="t2" id="s_admin_state">—</div>""",
}


def _settings_rows() -> str:
    """Разметка всех разделов формы: левая подпись + панель полей."""
    chunks: list[str] = []
    for gid, title, note in GROUPS:
        specs = [spec for spec in SPECS if spec.group == gid]
        extra = GROUP_EXTRAS.get(gid, "")
        if not specs and not extra:
            continue
        body = _settings_panel([spec for spec in specs if not spec.advanced])
        advanced = [spec for spec in specs if spec.advanced]
        if advanced:
            body += '<div class="advfields" hidden>' + _settings_panel(advanced) + "</div>"
        body += extra
        chunks.append(
            '<div class="srow srule">\n'
            f'        <div class="slabel"><h3>{_esc(title)}</h3><p>{_esc(note)}</p></div>\n'
            f'        <div class="spanel">{body}\n        </div>\n'
            '      </div>'
        )
    return "\n\n".join(chunks)


SETTINGS_PAGE = """
    <section class="page">
      <div class="titlerow">
        <div>
          <h1>Настройки</h1>
          <p class="sub" id="settingsSub">Все параметры парсера, браузера, прокси и публикации
            живут здесь. Пустое поле возвращает параметр к <span class="mono">.env</span>.</p>
        </div>
        <div class="actions">
          <button class="btn" id="btnAdvanced" aria-expanded="false">Дополнительные параметры</button>
          <button class="btn primary" id="btnSaveSettingsTop">Сохранить</button>
        </div>
      </div>

""" + _settings_rows() + """

      <div class="srow srule dangerrow">
        <div class="slabel">
          <h3>Сброс к <span class="mono">.env</span></h3>
          <p>Удаляет сохранённые в базе значения: каждый параметр вернётся к тому, что читается
            из файла <span class="mono">.env</span>. Сам файл остаётся на месте.</p>
        </div>
        <div class="spanel">
          <div class="t2" id="s_reset_state">—</div>
          <div><button class="btn txt neg" id="btnResetSettings">Сбросить всё к .env</button></div>
        </div>
      </div>

      <div class="sfoot">
        <span class="saved" id="saveStamp"></span>
        <button class="btn" id="btnReloadSettings">Откатить к сохранённому</button>
        <button class="btn primary" id="btnSaveSettings">Сохранить</button>
      </div>
    </section>
"""

SETTINGS_SCRIPT = r"""
/* ---------- настройки: разметка полей собрана из реестра, ключ — в data-setting ---------- */
function settingFields(){
  return Array.prototype.slice.call(document.querySelectorAll('[data-setting]'));
}
var SETTINGS_SUB = '';
function settingsFill(S){
  const st = S.settings || {};
  const ovr = S.settings_overridden || [];
  const masks = S.secret_masks || {};
  settingFields().forEach(el => {
    const key = el.dataset.setting, kind = el.dataset.kind, v = st[key];
    if (kind === 'bool') el.checked = (String(v) === '1' || v === true);
    else if (kind === 'secret') el.value = '';            // секрет наружу не отдаётся
    else el.value = (v == null ? '' : v);
    const box = el.closest('.field') || el.closest('.switchrow');
    if (box) box.classList.toggle('overridden', ovr.indexOf(key) >= 0);
  });
  // главная мысль экрана: сколько параметров уже перекрывают .env
  const sub = $('settingsSub');
  if (!SETTINGS_SUB) SETTINGS_SUB = sub.innerHTML;
  const total = settingFields().length;
  sub.innerHTML = SETTINGS_SUB + (ovr.length
    ? ' · <b>' + fmt(ovr.length) + '</b> из ' + fmt(total) + ' сохранено в базе и перекрывают <span class="mono">.env</span>'
    : ' · ни один из ' + fmt(total) + ' параметров ещё не сохранён в базе, везде работает <span class="mono">.env</span>');
  const vk = S.vk || {};
  const mask = masks.vk_access_token || '';
  $('s_vktoken_state').innerHTML = (mask || vk.token_set)
    ? 'Текущий ключ: <b>' + esc(vk.token_kind || 'установлен') + '</b> · ' + esc(mask) +
      (vk.can_upload_photos === false ? ' · фото на стену этим ключом загружать нельзя' : '') +
      (vk.oauth_url ? ' · <a id="vkOauthLink" href="' + esc(vk.oauth_url) +
        '" target="_blank" rel="noopener">ссылка авторизации</a>' : '')
    : (vk.oauth_url ? 'Ключ не задан · <a id="vkOauthLink" href="' + esc(vk.oauth_url) +
        '" target="_blank" rel="noopener">получить через OAuth</a>' : 'Ключ не задан');
  $('s_appid_state').textContent = vk.app_id
    ? 'ID standalone-приложения: ' + vk.app_id + ' (нужен для ссылки авторизации)'
    : 'ID приложения не задан — ссылка авторизации не строится';
  $('s_admin_state').textContent = masks.admin_password
    ? 'Пароль сохранён в базе: ' + masks.admin_password + ' (новое значение применяется при перезапуске)'
    : 'Пароль берётся из ADMIN_PASSWORD в .env';
  $('s_reset_state').textContent = ovr.length
    ? 'Сейчас в базе перекрывается ' + fmt(ovr.length) + ' из ' + fmt(total) +
      ' значений — после сброса они вернутся к .env.'
    : 'В базе пока ничего не перекрывает .env — сбрасывать нечего.';
}
async function settingsLoad(){
  let S;
  try { S = await loadState(); } catch (e) { return statusMsg('Не удалось загрузить настройки: ' + e.message, 'err'); }
  settingsFill(S);
  settingsProxy();
}
async function settingsProxy(){
  const box = $('proxyBody');
  try {
    const p = await api('/api/proxy');
    const pool = (p.configured || []).length;
    $('proxyPill').innerHTML = pool
      ? (p.browser_alive ? pill('ok', 'браузер через прокси') : pill('acc', 'настроен'))
      : pill('off', 'не настроен');
    const rows = [
      ['адресов в пуле', fmt(pool) + (p.allow_direct ? ' · допускается прямой IP' : ' · только прокси')],
      ['здоровых', p.pool_healthy != null ? fmt(p.pool_healthy) + ' из ' + fmt(p.pool_total) : 'не проверялся'],
      ['в карантине', (p.quarantined || []).length ? (p.quarantined || []).join(', ') : 'нет'],
      ['текущий выход', p.current || (p.browser_alive ? 'прямой IP' : 'браузер не запущен')]
    ];
    box.innerHTML = rows.map(r => '<div class="kv" style="padding-left:0;padding-right:0">' +
      '<span>' + r[0] + '</span><b class="mono">' + esc(r[1]) + '</b></div>').join('') +
      '<div class="kv" style="padding-left:0;padding-right:0"><span>лог</span><b class="mono">' +
      esc(p.log_path || '—') + '</b></div>';
  } catch (e) { box.textContent = 'Статус прокси недоступен: ' + e.message; }
}
function settingsCollect(){
  const payload = {};
  settingFields().forEach(el => {
    const key = el.dataset.setting, kind = el.dataset.kind;
    if (kind === 'bool') payload[key] = el.checked ? '1' : '0';
    else if (kind === 'secret') { const v = el.value.trim(); if (v) payload[key] = v; }
    else if (kind === 'list' || kind === 'multiline') payload[key] = el.value.replace(/\r\n/g, '\n').trim();
    else payload[key] = el.value.trim();
  });
  return payload;
}
async function settingsSave(){
  statusMsg('Сохраняем настройки…');
  try {
    const res = await post('/api/settings', settingsCollect());
    settingFields().forEach(el => { if (el.dataset.kind === 'secret') el.value = ''; });
    $('saveStamp').textContent = 'сохранено ' + tm(new Date().toISOString());
    const note = (res && res.note) ? ' · ' + res.note : '';
    statusMsg('Настройки сохранены' + note, 'ok');
    await loadState().catch(() => {});
    settingsLoad();
  } catch (e) { statusMsg('Ошибка: ' + e.message, 'err'); }
}
async function settingsReset(){
  if (!confirm('Удалить все сохранённые в базе значения? Параметры вернутся к .env.')) return;
  try {
    await post('/api/settings', {action: 'reset'});
    statusMsg('Настройки сброшены к значениям из .env', 'ok');
    settingsLoad();
  } catch (e) { statusMsg('Ошибка: ' + e.message, 'err'); }
}
$('btnAdvanced').addEventListener('click', () => {
  const btn = $('btnAdvanced'), open = btn.getAttribute('aria-expanded') !== 'true';
  document.querySelectorAll('.advfields').forEach(box => { box.hidden = !open; });
  btn.setAttribute('aria-expanded', String(open));
  btn.textContent = open ? 'Скрыть дополнительные' : 'Дополнительные параметры';
  if (open) { const first = document.querySelector('.advfields [data-setting]'); if (first) first.focus(); }
});
$('btnReloadSettings').addEventListener('click', () => { settingsLoad(); statusMsg('Значения перечитаны из базы', 'ok'); });
$('btnResetSettings').addEventListener('click', settingsReset);
$('btnSaveSettings').addEventListener('click', settingsSave);
$('btnSaveSettingsTop').addEventListener('click', settingsSave);
/* настройки специально не перезаписываются автообновлением: поля могут быть заполнены */
document.addEventListener('DOMContentLoaded', () => settingsLoad().catch(() => {}));
"""

# --------------------------------------------------------------------- #
# вход
# --------------------------------------------------------------------- #
LOGIN_PAGE = r"""<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход · Авито → VK</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400&display=swap" rel="stylesheet">
<script>
try {
  var t = localStorage.getItem('avito-theme');
  if (t !== 'light' && t !== 'dark') t = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.dataset.theme = t;
} catch (e) {}
</script>
<style>
:root{--frame:#eef2f6;--surface:#fff;--raised:#f4f6f8;--border:#e2e7eb;--control:#cdced1;
  --ink:#131416;--muted:#5d5f60;--faint:#6b6b6b;--accent:#2f6f96;--negative:#c4242a;
  --primary:#1d1f20;--primary-ink:#fff;--radius-card:8px;--radius-control:6px;--shadow-card:0 1px 2px rgba(19,20,22,.05)}
html[data-theme=dark]{--frame:#131415;--surface:#1b1c1e;--raised:#232527;--border:#2a2c2e;--control:#4a4c4e;
  --ink:#f2f3f4;--muted:#b4b4b4;--faint:#949494;--accent:#79a8cf;--negative:#e5566f;
  --primary:#fff;--primary-ink:#131416;--shadow-card:0 1px 2px rgba(0,0,0,.3)}
*{box-sizing:border-box}
html{color-scheme:light}html[data-theme=dark]{color-scheme:dark}
body{margin:0;min-height:100vh;background:var(--frame);color:var(--ink);
  font:400 14px/1.45 "IBM Plex Sans",Inter,system-ui,sans-serif;
  display:flex;align-items:center;justify-content:center;padding:24px}
.box{background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:32px;width:100%;max-width:384px;box-shadow:var(--shadow-card)}
.brand{display:flex;align-items:center;gap:9px;margin-bottom:24px}
.brand .name{font-size:15px;font-weight:600}
.brand .scope{font-size:12px;color:var(--muted);margin-top:2px}
h1{font-size:22px;font-weight:600;letter-spacing:-.01em;margin:0 0 6px}
.sub{color:var(--muted);margin:0 0 24px;font-size:14px}
label{display:flex;flex-direction:column;gap:8px;font-size:14px;font-weight:500;margin-bottom:16px}
input{background:var(--surface);color:var(--ink);border:1px solid var(--border);
  border-radius:var(--radius-card);height:44px;padding:0 12px;font:400 14px "IBM Plex Sans",system-ui,sans-serif;width:100%}
input::placeholder{color:var(--faint)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button{width:100%;height:40px;border-radius:var(--radius-control);border:1px solid var(--primary);
  background:var(--primary);color:var(--primary-ink);font:500 14px "IBM Plex Sans",system-ui,sans-serif;
  cursor:pointer;margin-top:8px}
button:hover{opacity:.88}
.err{display:none;background:#ffedea;color:#831c1e;border:1px solid #fde68a;border-radius:var(--radius-card);
  padding:10px 12px;font-size:13px;margin-bottom:16px}
html[data-theme=dark] .err{background:#2c1a20;color:#e5566f;border-color:#2c1a20}
.err.show{display:block}
.foot{margin-top:24px;font-size:12px;color:var(--muted);text-align:center}
</style>
</head>
<body>
  <form class="box" id="f" method="post" action="/login" autocomplete="on">
    <div class="brand">
      <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
        <rect x="1" y="3" width="12" height="16" rx="3" stroke="currentColor" stroke-width="1.5" opacity=".55"/>
        <path d="M14.5 11h5.5M17.5 8l3 3-3 3" stroke="var(--accent)" stroke-width="1.5"
              stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="7" cy="7.5" r="1.6" fill="var(--accent)"/>
      </svg>
      <div><div class="name">Авито → VK</div><div class="scope">парсер и автопостинг</div></div>
    </div>
    <h1>Вход в админку</h1>
    <p class="sub">Доступ по логину из <span style="font-family:'IBM Plex Mono',monospace">.env</span>.</p>
    <div class="err" id="err"></div>
    <label>Логин<input name="username" id="u" autocomplete="username" placeholder="admin"></label>
    <label>Пароль<input name="password" id="p" type="password" autocomplete="current-password" placeholder="••••••••"></label>
    <button type="submit">Войти</button>
    <div class="foot">Сессия подписывается ADMIN_SECRET и живёт в cookie.</div>
  </form>
<script>
const f = document.getElementById('f'), err = document.getElementById('err');
f.addEventListener('submit', async (e) => {
  e.preventDefault();
  err.classList.remove('show');
  try {
    const res = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username: document.getElementById('u').value,
                            password: document.getElementById('p').value})});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Неверный логин или пароль');
    location.href = '/';
  } catch (ex) { err.textContent = ex.message; err.classList.add('show'); }
});
</script>
</body>
</html>
"""

# --------------------------------------------------------------------- #
# сборка страниц
# --------------------------------------------------------------------- #
# url-путь -> (имя раздела, заголовок страницы, разметка, скрипт раздела)
PAGES: dict = {
    "/": ("dash", "Дашборд · Авито → VK", DASHBOARD_PAGE, DASHBOARD_SCRIPT),
    "/ads": ("ads", "Объявления · Авито → VK", ADS_PAGE, ADS_SCRIPT),
    "/sources": ("sources", "Источники · Авито → VK", SOURCES_PAGE, SOURCES_SCRIPT),
    "/vk": ("vk", "VK-канал · Авито → VK", VK_PAGE, VK_SCRIPT),
    "/jobs": ("jobs", "Задачи · Авито → VK", JOBS_PAGE, JOBS_SCRIPT),
    "/logs": ("logs", "Логи · Авито → VK", LOGS_PAGE, LOGS_SCRIPT),
    "/settings": ("settings", "Настройки · Авито → VK", SETTINGS_PAGE, SETTINGS_SCRIPT),
}

def render_page(route: str) -> str:
    """Собрать страницу раздела по URL-пути ('/' == дашборд)."""
    name, title, content, script = PAGES[route]
    return (
        LAYOUT_SHELL
        .replace("@@TITLE@@", title)
        .replace("@@PAGE@@", name)
        .replace("@@CONTENT@@", content)
        .replace("@@SCRIPT@@", script)
    )


def page_html(route: str) -> str:
    """Готовый HTML страницы; '/' возвращает дашборд."""
    return render_page(route if route in PAGES else "/")
