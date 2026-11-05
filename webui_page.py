"""HTML-страницы веб-админки (вынесены из webui.py для удобства правок).

PAGE — основная админка: сайдбар + топбар + 7 разделов с hash-роутингом.
LOGIN_PAGE — экран входа.

Стиль: true-black-flat (тёмная тема на чистом чёрном, elevation светлотой,
цвет только на данных — VK-синий), shell «Ruled T-frame»: сайдбар 210px +
топбар 64px на одном фоне, разделены 1px-линиями.
"""

PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Админка — Авито → VK</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --ground:#000000; --surface:#111111; --raised:#2a2a2a;
  --border:#1a1a1a; --rule:#161616; --control:#444444;
  --text:#ffffff; --muted:#b4b4b4; --faint:#949494;
  --accent:#4cb3f0; --positive:#3fc07a; --negative:#e5566f; --warning:#e5a93b;
  --pill-accent-bg:#10202d; --pill-accent-ink:#4cb3f0;
  --pill-positive-bg:#172a1d; --pill-positive-ink:#3fc07a;
  --pill-negative-bg:#2c1a20; --pill-negative-ink:#e5566f;
  --pill-warning-bg:#2b2414; --pill-warning-ink:#e5a93b;
  --pill-neutral-bg:#222222; --pill-neutral-ink:#b4b4b4;
  --radius-card:20px; --gap:16px; --pad:22px;
  --side:210px; --topbar:64px; --gutter:29px;
}
*{box-sizing:border-box}
html{color-scheme:dark}
body{margin:0; background:var(--ground); color:var(--text);
  font:14px/1.5 Inter,system-ui,'Segoe UI',Roboto,sans-serif;
  display:grid; grid-template-columns:var(--side) 1fr; grid-template-rows:var(--topbar) 1fr;
  min-height:100vh;}
.num{font-variant-numeric:tabular-nums}
a{color:inherit}
::selection{background:#2c3e50}

/* ---------- сайдбар ---------- */
.side{grid-row:1/3; background:var(--ground); border-right:1px solid var(--rule);
  display:flex; flex-direction:column; padding:0 12px; z-index:30;}
.brand{padding:18px 10px 16px; border-bottom:1px solid var(--rule);}
.brand .name{font-size:15px; font-weight:600; letter-spacing:-.01em;}
.brand .scope{font-size:12px; color:var(--faint); margin-top:3px;
  max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.nav{flex:1; padding:8px 0 14px; overflow:auto;}
.ngroup{font-size:12px; color:var(--faint); padding:16px 10px 6px;}
.nitem{display:flex; align-items:center; gap:8px; height:34px; padding:0 10px;
  border-radius:8px; color:var(--muted); font-size:14px; text-decoration:none; cursor:pointer;}
.nitem:hover{color:var(--text);}
.nitem.on{color:#fff;}
.nitem .cnt{margin-left:auto; font-size:12px; color:var(--faint); font-variant-numeric:tabular-nums;}
.nitem .cnt.act{color:var(--accent);}
.userrow{border-top:1px solid var(--rule); padding:14px 10px; display:flex;
  align-items:center; justify-content:space-between; font-size:13px; color:var(--muted);}
.userrow a{color:var(--muted); text-decoration:none;}
.userrow a:hover{color:var(--text);}

/* ---------- топбар ---------- */
.topbar{grid-column:2; display:flex; align-items:center; padding:0 var(--gutter);
  border-bottom:1px solid var(--rule); gap:12px; min-width:0;}
.stamp{font-size:12px; color:var(--faint); white-space:nowrap;}
.topspacer{flex:1;}
#burger{display:none;}
.vkswitch{display:flex; align-items:center; gap:9px; height:100%; padding:0 0 0 var(--gutter);
  border-left:1px solid var(--rule); font-size:13px; color:var(--muted);
  text-decoration:none; max-width:320px;}
.vkswitch:hover{color:var(--text);}
.vkswitch .nm{overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.dot{width:7px; height:7px; border-radius:50%; background:var(--faint); flex:none;}
.dot.ok{background:var(--positive);} .dot.err{background:var(--negative);}
.dot.acc{background:var(--accent);} .dot.warn{background:var(--warning);}

/* ---------- контент ---------- */
main{grid-column:2; padding:26px var(--gutter) 64px; max-width:1400px; width:100%; min-width:0;}
.view{display:none;} .view.on{display:block;}
.titlerow{display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:20px;}
h1{font-size:24px; font-weight:600; margin:0; letter-spacing:-.01em;}
.sub{font-size:14px; color:var(--muted); margin:6px 0 0; max-width:640px;}
.actions{display:flex; gap:8px; align-items:center; flex:none; flex-wrap:wrap;}

/* кнопки */
.btn{height:36px; padding:0 18px; border-radius:999px; border:0;
  font:500 14px Inter,system-ui,sans-serif; cursor:pointer;
  display:inline-flex; align-items:center; gap:8px; text-decoration:none;
  color:var(--text); background:var(--surface); white-space:nowrap;}
.btn:hover{background:var(--raised);}
.btn.primary{background:#fff; color:#000;} .btn.primary:hover{background:#e6e6e6;}
.btn.out{background:transparent; border:1px solid var(--control);}
.btn.out:hover{background:var(--surface);}
.btn.sm{height:28px; padding:0 12px; font-size:13px;}
.btn.txt{background:transparent; height:auto; padding:2px 6px; font-size:13px; color:var(--muted);}
.btn.txt:hover{color:var(--text); background:transparent;}
.btn.txt.neg{color:var(--negative);} .btn.txt.acc{color:var(--accent);}
button:disabled{opacity:.45; cursor:progress;}

/* панели и заголовки блоков */
.panel{background:var(--surface); border-radius:var(--radius-card); padding:var(--pad); min-width:0;}
.chead{font-size:16px; font-weight:600; margin:0 0 10px;}

/* KPI-полоса: один контейнер, делённый линиями */
.kstrip{display:grid; grid-template-columns:repeat(5,1fr); background:var(--surface);
  border-radius:var(--radius-card); overflow:hidden; margin-bottom:16px;}
.kstrip .k{padding:16px 20px; border-left:1px solid var(--rule); min-width:0;}
.kstrip .k:first-child{border-left:0;}
.kstrip .k span{display:block; font-size:12px; color:var(--faint); margin-bottom:6px;}
.kstrip .k b{font-size:24px; font-weight:500; font-variant-numeric:tabular-nums;}
.kstrip .k b small{font-size:14px; color:var(--faint); font-weight:400;}

/* дашборд: главная колонка + рельс 384px */
.dashgrid{display:grid; grid-template-columns:1fr 384px; gap:16px; align-items:start;}
.maincol{min-width:0; display:flex; flex-direction:column; gap:16px;}
.rail{display:flex; flex-direction:column; gap:8px; min-width:0;}

/* конвейер */
.stages{display:flex; align-items:center; gap:14px;}
.stage{flex:1; min-width:0; display:flex; flex-direction:column; gap:5px;}
.slabel{font-size:12px; color:var(--faint); display:flex; align-items:center; gap:7px;}
.sval{font-size:22px; font-weight:500; font-variant-numeric:tabular-nums;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.sval a{color:var(--accent); text-decoration:none;}
.sval a:hover{text-decoration:underline;}
.ssub{font-size:12px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.arr{color:var(--faint); font-size:15px; flex:none;}

/* списки-строки в карточках (посты, расписание) */
.lrow{display:flex; align-items:baseline; gap:10px; padding:11px 2px;
  border-top:1px solid var(--rule); font-size:13px; min-width:0;}
.lrow:first-child{border-top:0;}
.lrow .lt{color:var(--faint); font-size:12px; font-variant-numeric:tabular-nums; flex:none;}
.lrow .lmain{flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.lrow a{color:var(--text); text-decoration:none;}
.lrow a:hover{color:var(--accent);}
.lrow .rlink{color:var(--accent); text-decoration:none; flex:none; font-size:12.5px;}
.lrow .rlink:hover{text-decoration:underline;}
.kv{display:flex; justify-content:space-between; gap:12px; padding:7px 2px; font-size:13px;}
.kv span{color:var(--muted);}
.kv b{font-weight:500; font-variant-numeric:tabular-nums; text-align:right;}
.viewall{display:inline-block; margin:10px 2px 0; font-size:13px; color:var(--muted);
  text-decoration:none; height:30px; line-height:30px; border:1px solid var(--control);
  border-radius:999px; padding:0 14px; align-self:flex-start;}
.viewall:hover{color:var(--text);}

/* карточки объявлений на дашборде */
.adcards{display:grid; grid-template-columns:repeat(4,1fr); gap:16px;}
.adcard{background:var(--surface); border-radius:var(--radius-card); overflow:hidden; min-width:0;}
.adcard .ph{height:92px; background:var(--raised); display:flex;}
.adcard .ph img{width:33.33%; height:100%; object-fit:cover;}
.adcard .ph .noimg{flex:1; display:flex; align-items:center; justify-content:center;
  color:var(--faint); font-size:12px;}
.adcard .bd{padding:12px 14px 14px; display:flex; flex-direction:column; gap:5px;}
.adcard a.t{color:var(--text); text-decoration:none; font-size:14px; font-weight:500;
  overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;}
.adcard a.t:hover{color:var(--accent);}
.adcard .pr{font-size:15px; font-weight:600; font-variant-numeric:tabular-nums;}
.adcard .mt{font-size:12px; color:var(--faint);}

/* счётчики-фильтры на «Объявлениях» */
.counts{display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:14px;}
.counts button{background:var(--surface); border:1px solid var(--rule); border-radius:16px;
  padding:11px 16px; text-align:left; cursor:pointer; color:var(--text); font:inherit;}
.counts button:hover{border-color:var(--control);}
.counts button.sel{border:1.5px solid var(--accent); background:var(--pill-accent-bg);}
.counts span{font-size:13px; color:var(--faint);}
.counts b{display:block; font-size:16px; font-weight:600; margin-top:2px; font-variant-numeric:tabular-nums;}

/* таблицы */
.tablewrap{padding:6px 14px 10px;}
table{width:100%; border-collapse:collapse; font-size:14px;}
th{font-size:12px; color:var(--faint); font-weight:400; text-align:left; padding:12px 10px 8px;}
td{padding:11px 10px; border-top:1px solid var(--rule); vertical-align:middle; min-width:0;}
th.num,td.num{text-align:right; font-variant-numeric:tabular-nums;}
th.r,td.r{text-align:right;}
td .cellmain{overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
td a{color:var(--text); text-decoration:none;}
td a:hover{color:var(--accent);}
td a.pillink{color:var(--accent);}
.adcell{display:flex; align-items:center; gap:12px; min-width:0;}
.thumb{width:48px; height:48px; border-radius:8px; object-fit:cover; background:var(--raised); flex:none;}
.thumbph{width:48px; height:48px; border-radius:8px; background:var(--raised); flex:none;
  display:flex; align-items:center; justify-content:center; color:var(--faint); font-size:10px;}
.adcell .tw{min-width:0;}
.adcell .t1{overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:500;}
.adcell .t2{font-size:12px; color:var(--faint); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.srcell{font-size:12px; color:var(--faint); max-width:130px; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap;}
.dtc{font-size:12.5px; color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap;}

/* пилюли статусов */
.pill{display:inline-block; padding:3px 10px; border-radius:999px; font-size:12px;
  white-space:nowrap; flex:none;}
.pill.ok{background:var(--pill-positive-bg); color:var(--pill-positive-ink);}
.pill.bad{background:var(--pill-negative-bg); color:var(--pill-negative-ink);}
.pill.warn{background:var(--pill-warning-bg); color:var(--pill-warning-ink);}
.pill.acc{background:var(--pill-accent-bg); color:var(--pill-accent-ink);}
.pill.off{background:var(--pill-neutral-bg); color:var(--pill-neutral-ink);}

/* панели инструментов и пагинация */
.toolbar{display:flex; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap;}
input[type=text],input[type=search],input[type=password],input[type=number],select{
  background:var(--surface); color:var(--text); border:1px solid var(--control);
  border-radius:999px; height:36px; padding:0 15px; font:14px Inter,system-ui,sans-serif;}
input[type=search]{flex:1 1 260px; min-width:180px;}
input[type=number]{width:96px;}
input:focus-visible,select:focus-visible,.btn:focus-visible,a:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
.pager{display:flex; align-items:center; gap:10px; font-size:13px; color:var(--muted);
  margin-left:auto; font-variant-numeric:tabular-nums;}

/* пустые состояния и ошибки */
.empty{border:1px dashed var(--control); border-radius:12px; padding:16px 18px;
  color:var(--faint); font-size:14px; grid-column:1/-1;}
.errline{border:1px solid var(--pill-negative-bg); border-radius:12px; padding:12px 16px;
  color:var(--pill-negative-ink); font-size:13px; grid-column:1/-1;
  display:flex; align-items:center; gap:12px;}
.skel{background:var(--raised); border-radius:6px; display:inline-block; height:14px;}

/* формы и тумблеры */
.field{display:flex; flex-direction:column; gap:8px;}
.field > span{font-size:14px; font-weight:500;}
.field > small{font-size:12px; color:var(--faint); margin-top:-2px;}
.frow{display:flex; gap:16px; flex-wrap:wrap; align-items:flex-start;}
.switch{display:flex; align-items:center; gap:10px; cursor:pointer; font-size:14px;}
.switch input{position:absolute; opacity:0; width:0; height:0;}
.track{width:34px; height:20px; border-radius:999px; background:var(--raised);
  position:relative; flex:none; transition:background .15s;}
.track::after{content:""; position:absolute; top:2px; left:2px; width:16px; height:16px;
  border-radius:50%; background:var(--muted); transition:transform .15s, background .15s;}
.switch input:checked + .track{background:var(--pill-positive-bg);}
.switch input:checked + .track::after{transform:translateX(14px); background:var(--positive);}
.switch input:focus-visible + .track{outline:2px solid var(--accent); outline-offset:2px;}

/* VK-страница */
.vkgrid{display:grid; grid-template-columns:1fr 1fr; gap:16px; align-items:start; margin-bottom:16px;}
.msg{white-space:pre-wrap; font-size:14px; line-height:1.55; color:var(--text);}
.pvrow{display:flex; gap:16px; margin-top:10px;}
.pvrow .ph{width:120px; height:120px; border-radius:12px; object-fit:cover; background:var(--raised); flex:none;}
.pvrow .phph{width:120px; height:120px; border-radius:12px; background:var(--raised); flex:none;
  display:flex; align-items:center; justify-content:center; color:var(--faint); font-size:12px;}

/* настройки: двухколонные секции */
.srow{display:grid; grid-template-columns:450px 1fr; gap:24px; padding:28px 0;}
.srow:first-of-type{padding-top:6px;}
.srule{border-top:1px solid var(--rule);}
.slabel h3{font-size:16px; font-weight:600; margin:0 0 6px;}
.slabel p{font-size:14px; color:var(--muted); margin:0; max-width:420px;}
.slabel .ro{font-size:12.5px; color:var(--faint); margin-top:10px; line-height:1.7; word-break:break-all;}
.spanel{display:flex; flex-direction:column; gap:16px;}
.sfoot{display:flex; justify-content:flex-end; align-items:center; gap:12px;}
.switchrow{display:flex; align-items:center; justify-content:space-between; gap:16px;}
.switchrow .tw{display:flex; flex-direction:column; gap:3px;}
.switchrow .tw b{font-size:14px; font-weight:500;}
.switchrow .tw small{font-size:12px; color:var(--faint);}

/* лог */
.logbox{background:var(--surface); border-radius:var(--radius-card); padding:16px 20px;
  font:12px/1.65 ui-monospace,Menlo,'SF Mono',monospace; color:var(--muted);
  white-space:pre-wrap; word-break:break-word; overflow:auto;
  max-height:calc(100vh - 300px); min-height:320px;}

/* журнал задач */
.joblog{background:var(--ground); border-radius:12px; padding:12px 16px; margin:2px 0 8px;
  font:12px/1.6 ui-monospace,Menlo,monospace; color:var(--muted);
  white-space:pre-wrap; word-break:break-word; max-height:320px; overflow:auto;}

/* живой лог текущей задачи: один на весь экран, виден из любого раздела */
.joblog.live{border-left:2px solid var(--accent); margin:0 0 12px; max-height:180px; color:var(--ink);}

/* статус-строка задач */
.status{display:none; margin:0 0 12px; padding:11px 16px; border-radius:12px;
  background:var(--surface); font-size:13.5px;}
.status.show{display:block;}
.status.err{color:var(--pill-negative-ink); background:var(--pill-negative-bg);}
.status.ok{color:var(--pill-positive-ink); background:var(--pill-positive-bg);}

/* ---------- телефон ---------- */
@media (max-width:1100px){
  .dashgrid{grid-template-columns:1fr;}
  .vkgrid{grid-template-columns:1fr;}
  .adcards{grid-template-columns:repeat(2,1fr);}
  .srow{grid-template-columns:1fr; gap:10px; padding:22px 0;}
}
@media (max-width:760px){
  body{grid-template-columns:1fr; grid-template-rows:56px 1fr;}
  .side{position:fixed; left:0; top:0; bottom:0; width:250px; transform:translateX(-105%);
    transition:transform .18s; border-right:1px solid var(--rule); background:var(--ground);}
  .side.open{transform:translateX(0);}
  main{grid-column:1; padding:18px 16px 56px; max-width:none;}
  .topbar{grid-column:1; padding:0 16px;}
  #burger{display:inline-flex; align-items:center; justify-content:center; width:34px; height:34px;
    border-radius:999px; border:1px solid var(--control); background:transparent; color:var(--muted);
    font-size:16px; cursor:pointer;}
  .kstrip{grid-template-columns:repeat(2,1fr);}
  .kstrip .k{border-top:1px solid var(--rule);}
  .kstrip .k:nth-child(-n+2){border-top:0;}
  .kstrip .k:nth-child(odd){border-left:0;}
  .counts{grid-template-columns:repeat(2,1fr);}
  .adcards{grid-template-columns:1fr;}
  .stages{flex-direction:column; align-items:stretch;}
  .arr{transform:rotate(90deg); align-self:center;}
  .titlerow{flex-direction:column; align-items:flex-start;}
  .hideph{display:none;}
  .tablewrap{padding:4px 8px 8px;}
  td,th{padding:9px 6px;}
}
</style>
</head>
<body>

<!-- ======================= сайдбар ======================= -->
<aside class="side" id="side">
  <div class="brand">
    <div class="name">Авито → VK</div>
    <div class="scope" id="brandScope">сообщество не настроено</div>
  </div>
  <nav class="nav">
    <div class="ngroup">Конвейер</div>
    <a class="nitem on" href="#dash" data-view="dash">Дашборд</a>
    <a class="nitem" href="#ads" data-view="ads">Объявления <span class="cnt act" id="navPending"></span></a>
    <a class="nitem" href="#sources" data-view="sources">Источники</a>
    <div class="ngroup">Постинг</div>
    <a class="nitem" href="#vk" data-view="vk">VK-канал</a>
    <div class="ngroup">Система</div>
    <a class="nitem" href="#jobs" data-view="jobs">Задачи</a>
    <a class="nitem" href="#logs" data-view="logs">Логи</a>
    <a class="nitem" href="#settings" data-view="settings">Настройки</a>
  </nav>
  <div class="userrow"><span id="whoami">admin</span><a href="/logout">Выйти</a></div>
</aside>

<!-- ======================= топбар ======================= -->
<header class="topbar">
  <button id="burger" aria-label="Меню">≡</button>
  <span class="stamp" id="stamp">…</span>
  <button class="btn out sm hideph" id="btnRefresh" title="Обновить данные">Обновить</button>
  <span class="topspacer"></span>
  <a class="vkswitch" href="#vk" title="Перейти к настройкам VK">
    <span class="dot" id="vkDot"></span>
    <span class="nm" id="vkName">VK не настроен</span>
  </a>
</header>

<main>
<div class="status" id="status"></div>
<div class="joblog live" id="joblog" style="display:none"></div>

<!-- ======================= ДАШБОРД ======================= -->
<section class="view on" id="view-dash">
  <div class="titlerow">
    <div><h1>Дашборд</h1><p class="sub">Конвейер: парсинг Авито → очередь → автопостинг в сообщество VK</p></div>
    <div class="actions">
      <button class="btn out" id="btnPublishDash">Опубликовать пачку</button>
      <button class="btn primary" id="btnParseDash">Парсить сейчас</button>
    </div>
  </div>

  <div class="kstrip" id="kpi">
    <div class="k"><span>Всего объявлений</span><b><span class="skel" style="width:64px"></span></b></div>
    <div class="k"><span>В очереди VK</span><b><span class="skel" style="width:48px"></span></b></div>
    <div class="k"><span>Опубликовано</span><b><span class="skel" style="width:40px"></span></b></div>
    <div class="k"><span>Недолитые</span><b><span class="skel" style="width:40px"></span></b></div>
    <div class="k"><span>Ссылок вкл</span><b><span class="skel" style="width:32px"></span></b></div>
  </div>

  <div class="dashgrid">
    <div class="maincol">
      <div>
        <h3 class="chead">Конвейер</h3>
        <div class="panel"><div class="stages" id="pipe">
          <div class="stage"><span class="skel" style="width:120px"></span><span class="skel" style="width:80px"></span><span class="skel" style="width:150px"></span></div>
          <div class="arr">→</div>
          <div class="stage"><span class="skel" style="width:120px"></span><span class="skel" style="width:80px"></span><span class="skel" style="width:150px"></span></div>
          <div class="arr">→</div>
          <div class="stage"><span class="skel" style="width:120px"></span><span class="skel" style="width:80px"></span><span class="skel" style="width:150px"></span></div>
        </div></div>
      </div>
      <div>
        <h3 class="chead">Последние объявления <span style="color:var(--faint);font-weight:400;font-size:13px" id="recentCap"></span></h3>
        <div class="adcards" id="dashRecent"><div class="empty">Загружаю…</div></div>
      </div>
    </div>
    <aside class="rail">
      <h3 class="chead">Расписание</h3>
      <div class="panel" id="schedCard"><div class="skel" style="width:180px"></div></div>
      <h3 class="chead" style="margin-top:8px">Последние посты VK</h3>
      <div class="panel" id="dashPosts"><div class="skel" style="width:200px"></div></div>
      <a class="viewall" href="#vk">Все посты</a>
    </aside>
  </div>
</section>

<!-- ======================= ОБЪЯВЛЕНИЯ ======================= -->
<section class="view" id="view-ads">
  <div class="titlerow">
    <div><h1>Объявления</h1><p class="sub" id="adsSub">Что спарсено, что ждёт постинга и что уже вышло в VK</p></div>
    <div class="actions"><a class="btn out" id="btnExport" href="/export.csv">Экспорт CSV</a></div>
  </div>
  <div class="counts" id="adCounts"></div>
  <div class="toolbar">
    <input type="search" id="adSearch" placeholder="Поиск: название, описание, id">
  </div>
  <div class="panel tablewrap"><table id="adsTable">
    <thead><tr>
      <th style="width:38%">Объявление</th><th class="num">Цена</th><th class="hideph">Источник</th>
      <th class="num hideph">Разобрано</th><th>Статус</th><th class="hideph">VK</th><th class="r">Действия</th>
    </tr></thead>
    <tbody id="adsBody"></tbody>
  </table></div>
</section>

<!-- ======================= ИСТОЧНИКИ ======================= -->
<section class="view" id="view-sources">
  <div class="titlerow">
    <div><h1>Источники</h1><p class="sub">Ссылки выдачи Авито, которые крон обходит по расписанию.
      Новая ссылка в первый прогон парсится не более <b id="frlHint">…</b> объявлений, дальше — только свежие.</p></div>
    <div class="actions"><button class="btn out" id="btnParseAll">Парсить все ссылки</button></div>
  </div>

  <div class="panel" style="margin-bottom:16px">
    <div class="frow">
      <div class="field" style="flex:1 1 420px">
        <span>Добавить ссылку на выдачу</span>
        <input type="text" id="newUrl" placeholder="https://www.avito.ru/saransk/telefony" style="border-radius:12px">
        <small>Категория или поиск с фильтрами — крон будет проверять её по расписанию</small>
      </div>
      <button class="btn primary" id="addSource" style="align-self:flex-end">Добавить ссылку</button>
    </div>
  </div>

  <div class="panel tablewrap"><table id="srcTable">
    <thead><tr>
      <th style="width:30%">Ссылка</th><th>Статус</th><th class="num">Найдено</th>
      <th class="num">Новых (прогон)</th><th class="num hideph">Объявлений</th>
      <th class="num hideph">Прогонов</th><th class="num hideph">Проверка</th><th class="r">Действия</th>
    </tr></thead>
    <tbody id="srcBody"></tbody>
  </table></div>

  <div class="panel" style="margin-top:16px">
    <div class="frow">
      <div class="field" style="flex:1 1 420px">
        <span>Разовый парсинг произвольной ссылки</span>
        <input type="text" id="oneUrls" placeholder="https://www.avito.ru/…" style="border-radius:12px">
        <small>Не сохраняется в источники — один прогон прямо сейчас</small>
      </div>
      <button class="btn out" id="btnOne" style="align-self:flex-end">Парсить разово</button>
    </div>
  </div>
</section>

<!-- ======================= VK ======================= -->
<section class="view" id="view-vk">
  <div class="titlerow">
    <div><h1>VK-канал</h1><p class="sub" id="vkSub">Куда уходит очередь объявлений</p></div>
    <div class="actions">
      <button class="btn out" id="btnPreview">Предпросмотр</button>
      <button class="btn primary" id="btnPublishVK">Опубликовать пачку</button>
    </div>
  </div>

  <div class="vkgrid">
    <div class="panel" id="vkCard"><div class="skel" style="width:220px"></div></div>
    <div class="panel" id="pvCard"><div class="skel" style="width:220px"></div></div>
  </div>

  <h3 class="chead">История постов <span style="color:var(--faint);font-weight:400;font-size:13px" id="vkHistCap"></span></h3>
  <div class="panel tablewrap" style="margin-bottom:16px"><table id="vkHistTable">
    <thead><tr><th style="width:34%">Объявление</th><th class="num hideph">Фото</th>
      <th>Опубликован</th><th class="r">Пост</th></tr></thead>
    <tbody id="vkHistBody"></tbody>
  </table></div>

  <div class="srule"></div>
  <div class="srow">
<div class="slabel">
      <h3>Настройки канала</h3>
      <p>Ключ сообщества умеет постить текст. VK запрещает ему загрузку фото (код 27):
      чтобы посты выходили с картинками, вставьте сюда user-ключ standalone-приложения
      с правами photos, wall, groups, offline.</p>
      <div id="oauthBox" style="display:none; margin-top:12px; max-width:420px">
        <a id="vkOauthLink" class="btn out sm" target="_blank" rel="noopener">Получить user-ключ (для фото)</a>
        <p class="ro" style="margin-top:8px">Откроется VK — разрешите права photos, wall, groups, offline.
        Токен появится в адресной строке после <b>access_token=</b>: скопируйте его
        в поле «VK: ключ доступа» выше и сохраните.</p>
      </div>
    </div>
    <div class="panel spanel">
      <div class="frow">
        <div class="field"><span>Пауза между постами, сек</span><input type="number" id="s_vkpauze" min="30" max="7200"></div>
        <div class="field"><span>Пачка за цикл</span><input type="number" id="s_batch" min="1" max="50"></div>
        <div class="field" style="justify-content:flex-end"><span>&nbsp;</span>
          <label class="switch"><input type="checkbox" id="s_reqphotos"><span class="track"></span>Только посты с фото</label>
        </div>
      </div>
      <div class="frow">
        <div class="field" style="flex:1 1 300px"><span>VK: ключ доступа</span>
          <input type="password" id="s_vktoken" placeholder="введите новый ключ, чтобы заменить" autocomplete="off" style="border-radius:12px">
          <small id="vkTokenHint"></small></div>
        <div class="field" style="flex:1 1 240px"><span>VK: сообщество</span>
          <input type="text" id="s_vkgroup" placeholder="public12345 или -12345" style="border-radius:12px">
          <small>id или короткий адрес; применяется сразу после сохранения</small></div>
      </div>
      <div class="sfoot"><span class="sub" id="vkSaved" style="margin:0"></span>
        <button class="btn primary" id="saveVK">Сохранить</button></div>
    </div>
  </div>
</section>

<!-- ======================= ЗАДАЧИ ======================= -->
<section class="view" id="view-jobs">
  <div class="titlerow">
    <div><h1>Задачи</h1><p class="sub">Парсинги и публикации с живым логом; история хранится до следующего рестарта</p></div>
    <div class="actions"><button class="btn out" id="btnJobsRefresh">Обновить</button></div>
  </div>
  <div class="panel tablewrap"><table id="jobsTable">
    <thead><tr><th style="width:16%">Тип</th><th style="width:14%">Статус</th>
      <th>Итог</th><th class="num hideph">Начата</th><th class="num hideph">Длительность</th></tr></thead>
    <tbody id="jobsBody"></tbody>
  </table></div>
</section>

<!-- ======================= ЛОГИ ======================= -->
<section class="view" id="view-logs">
  <div class="titlerow">
    <div><h1>Логи</h1><p class="sub" id="logPath"></p></div>
    <div class="actions">
      <label class="switch hideph"><input type="checkbox" id="logAuto" checked><span class="track"></span>Авто</label>
      <a class="btn out" id="logDownload" href="/api/logs?download=1">Скачать</a>
    </div>
  </div>
  <div class="logbox" id="logbox">Загружаю…</div>
</section>

<!-- ======================= НАСТРОЙКИ ======================= -->
<section class="view" id="view-settings">
  <div class="titlerow">
    <div><h1>Настройки</h1><p class="sub">Расписание и параметры конвейера. Изменения подхватываются кроном без перезапуска.</p></div>
  </div>

  <div class="srow">
    <div class="slabel"><h3>Расписание крона</h3>
      <p>Как часто обходить источники и публиковать очередь. Пока крон на паузе,
      парсинг и постинг не запускаются, но очередь и ручные задачи работают.</p></div>
    <div class="panel spanel">
      <div class="frow">
        <div class="field"><span>Парсить каждые, мин</span><input type="number" id="s_parse" min="1" max="360"></div>
        <div class="field"><span>Публиковать каждые, мин</span><input type="number" id="s_publish" min="1" max="360"></div>
      </div>
      <div class="switchrow">
        <div class="tw"><b>Крон на паузе</b><small>Останавливает циклы парсинга и постинга</small></div>
        <label class="switch"><input type="checkbox" id="s_paused"><span class="track"></span></label>
      </div>
      <div class="sfoot"><span class="sub" id="schedSaved" style="margin:0"></span>
        <button class="btn primary" id="saveSched">Сохранить</button></div>
    </div>
  </div>
  <div class="srule"></div>
  <div class="srow">
    <div class="slabel"><h3>Парсинг</h3>
      <p>Что качать и сколько. «Лимит первого прогона» ограничивает первую выгрузку
      новой ссылки, чтобы сразу не улетать в сотню карточек.</p></div>
    <div class="panel spanel">
      <div class="frow">
        <div class="field"><span>Лимит первого прогона</span><input type="number" id="s_frl" min="1" max="100"></div>
        <div class="field"><span>Страниц на ссылку</span><input type="number" id="s_pages" min="1" max="10"></div>
      </div>
      <div class="switchrow">
        <div class="tw"><b>Качать описания</b><small>Заходить в карточку и забирать текст</small></div>
        <label class="switch"><input type="checkbox" id="s_details"><span class="track"></span></label>
      </div>
      <div class="switchrow">
        <div class="tw"><b>Качать фото</b><small>Складывать фото в data/photos для постов</small></div>
        <label class="switch"><input type="checkbox" id="s_photos"><span class="track"></span></label>
      </div>
      <div class="sfoot"><span class="sub" id="parseSaved" style="margin:0"></span>
        <button class="btn primary" id="saveParse">Сохранить</button></div>
    </div>
  </div>
  <div class="srule"></div>
  <div class="srow">
    <div class="slabel"><h3>Прокси и пути</h3>
      <p>Прокси задаются в .env (PROXY_STRING). Браузер сам карантинит забаненные
      адреса и уходит в прямой IP, если пул пуст.</p></div>
    <div class="panel spanel" id="proxyCard"><div class="skel" style="width:260px"></div></div>
  </div>
</section>
</main>

<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => (s==null ? '' : String(s)).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (n) => (n==null || n==='') ? '—' : new Intl.NumberFormat('ru-RU').format(n);
const tm = (iso) => iso ? new Date(iso).toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
const dt = (iso) => { if(!iso) return '—'; const d = new Date(iso);
  const p = (x)=>String(x).padStart(2,'0');
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes()); };

const app = { view:'dash', S:null, running:false,
  ads:{filter:'all', q:'', page:1, per:50, total:0, counts:{}},
  hist:{page:1, per:15, total:0}, timers:[] };

async function api(path, opts){
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
function statusMsg(text, cls){ const st = $('status'); if(!st) return;
  st.className = 'status show' + (cls ? ' ' + cls : ''); st.textContent = text; }
function pill(cls, text){ return '<span class="pill '+cls+'">'+esc(text)+'</span>'; }
function skelErr(el, msg){ el.innerHTML = '<div class="errline"><span>'+esc(msg)+'</span>'+
  '<button class="btn out sm" onclick="location.reload()">Повторить</button></div>'; }

/* ---------- топбар, сайдбар, роутинг ---------- */
function renderChrome(){
  $('stamp').textContent = 'обновлено ' + tm(new Date().toISOString());
  if (!app.S) return;
  const vk = app.S.vk;
  $('vkDot').className = 'dot ' + (vk.error ? 'err' : (vk.token_set && vk.group_set ? 'ok' : 'warn'));
  $('vkName').textContent = vk.error ? 'VK: ' + vk.error : (vk.group_name || 'VK не настроен');
  $('brandScope').textContent = vk.group_name || 'сообщество не настроено';
  $('navPending').textContent = app.S.db.pending ? fmt(app.S.db.pending) : '';
}
function stopTimers(){ app.timers.forEach(clearInterval); app.timers = []; }
function show(v){
  app.view = v;
  document.querySelectorAll('.view').forEach(x => x.classList.toggle('on', x.id === 'view-'+v));
  document.querySelectorAll('.nitem').forEach(a => a.classList.toggle('on', a.dataset.view === v));
  $('side').classList.remove('open');
  stopTimers();
  if (v === 'dash') loadDash();
  else if (v === 'ads') loadAds();
  else if (v === 'sources') loadState().then(renderSources).catch(()=>{});
  else if (v === 'vk') loadVK();
  else if (v === 'jobs') { loadJobs(); app.timers.push(setInterval(loadJobs, 2500)); }
  else if (v === 'logs') { loadLogs(); app.timers.push(setInterval(loadLogs, 3000)); }
  else if (v === 'settings') loadState().then(renderSettings).catch(()=>{});
}
window.addEventListener('hashchange', () => show(location.hash.slice(1) || 'dash'));
$('burger').addEventListener('click', () => $('side').classList.toggle('open'));
$('btnRefresh').addEventListener('click', () => show(app.view));

/* ---------- состояние ---------- */
async function loadState(){
  app.S = await api('/api/state');
  renderChrome();
  return app.S;
}
function srcStatus(s){
  if (!s.enabled) return pill('off', 'выкл');
  const st = s.last_status || 'новая';
  if (st === 'ok') return pill('ok', 'ok');
  if (st === 'blocked') return pill('bad', 'blocked');
  if (st === 'error') return pill('bad', 'ошибка');
  if (st === 'empty') return pill('warn', 'пусто');
  return pill('off', st);
}

/* ---------- ДАШБОРД ---------- */
async function loadDash(){
  try {
    await loadState();
    const s = app.S, sch = s.scheduler, vk = s.vk, db = s.db;
    $('kpi').innerHTML = [
      ['Всего объявлений', fmt(db.total)],
      ['В очереди VK', fmt(db.pending)],
      ['Опубликовано', fmt(db.posted)],
      ['Недолитые', fmt(db.partial)],
      ['Ссылок вкл', s.sources.filter(x=>x.enabled).length + '<small> / ' + s.sources.length + '</small>'],
    ].map(([k,v]) => '<div class="k"><span>'+k+'</span><b>'+v+'</b></div>').join('');

    const srcs = s.sources, en = srcs.filter(x=>x.enabled);
    const badSrc = srcs.filter(x=>x.enabled && (x.last_status==='blocked'||x.last_status==='error')).length;
    const srcDot = !en.length ? 'warn' : (badSrc ? 'warn' : 'ok');
    const srcSub = sch.last_parse_result
      ? 'последний прогон: ' + esc(sch.last_parse_result) : 'прогонов ещё не было';
    $('pipe').innerHTML =
      '<div class="stage"><span class="slabel"><span class="dot '+srcDot+'"></span>Источники</span>' +
      '<span class="sval">'+en.length+'<small style="color:var(--faint)"> / '+srcs.length+'</small></span>' +
      '<span class="ssub">'+srcSub+'</span></div>' +
      '<div class="arr">→</div>' +
      '<div class="stage"><span class="slabel"><span class="dot acc"></span>Очередь</span>' +
      '<span class="sval">'+fmt(db.pending)+'</span>' +
      '<span class="ssub">следующая публикация в '+tm(sch.next_publish)+'</span></div>' +
      '<div class="arr">→</div>' +
      '<div class="stage"><span class="slabel"><span class="dot '+(vk.error?'err':'ok')+'"></span>VK</span>' +
      '<span class="sval">' + (vk.group_name
        ? '<a href="#vk">'+esc(vk.group_name)+'</a>'
        : '<a href="#vk" style="color:var(--warning)">не настроен</a>') + '</span>' +
      '<span class="ssub">' + (vk.last_post_url
        ? 'последний пост: <a href="'+esc(vk.last_post_url)+'" target="_blank" rel="noopener" style="color:var(--accent)">'+esc(vk.last_post_url.replace('https://vk.com/',''))+'</a>'
        : 'постов ещё не было') + '</span></div>';

    $('schedCard').innerHTML =
      '<div class="kv"><span>Парсинг</span><b>каждые '+sch.parse_interval_min+' мин</b></div>' +
      '<div class="kv"><span>следующий</span><b>'+tm(sch.next_parse)+'</b></div>' +
      '<div class="kv"><span>Публикация VK</span><b>каждые '+sch.publish_interval_min+' мин</b></div>' +
      '<div class="kv"><span>следующая</span><b>'+tm(sch.next_publish)+'</b></div>' +
      '<div class="kv"><span>Браузер</span><b>'+(sch.browser_alive ? 'живёт' : 'поднимется при задаче')+'</b></div>' +
      (sch.paused ? '<div class="kv"><span>Крон</span><b style="color:var(--warning)">на паузе</b></div>' : '');

    const posts = await api('/api/listings?filter=posted&per=5&page=1');
    $('dashPosts').innerHTML = (posts.items || []).map(p =>
      '<div class="lrow"><span class="lt">'+tm(p.posted_at)+'</span>' +
      '<span class="lmain"><a href="'+esc(p.vk_post_url||p.url||'#')+'" target="_blank" rel="noopener">'+esc(p.title||'без названия')+'</a></span>' +
      '<a class="rlink" href="'+esc(p.vk_post_url||'#')+'" target="_blank" rel="noopener">пост</a></div>'
    ).join('') || '<div class="empty" style="padding:12px">Опубликованных постов пока нет.</div>';

    const rec = s.recent || [];
    $('recentCap').textContent = rec.length ? '— последние ' + rec.length + ' из очереди' : '';
    $('dashRecent').innerHTML = rec.slice(0, 4).map(a =>
      '<div class="adcard"><div class="ph">' +
      ((a.photo_urls||[]).slice(0,3).map(u => '<img src="'+esc(u)+'" loading="lazy" alt="">').join('') ||
       '<span class="noimg">без фото</span>') + '</div>' +
      '<div class="bd"><a class="t" href="'+esc(a.url||'#')+'" target="_blank" rel="noopener">'+esc(a.title||'без названия')+'</a>' +
      '<span class="pr num">'+(esc(a.price||'') || (a.price_rub ? fmt(a.price_rub)+' ₽' : 'цена не указана'))+'</span>' +
      '<span class="mt">'+esc(a.source_label||'')+'</span></div></div>'
    ).join('') || '<div class="empty">Очередь пуста: крон положит сюда свежие объявления.</div>';
  } catch (e) { skelErr($('pipe'), 'Не удалось загрузить дашборд: ' + e.message); }
}

/* ---------- ОБЪЯВЛЕНИЯ ---------- */
const FLTL = {all:'Все', pending:'В очереди', posted:'Опубликованные', partial:'Недолитые'};
let adsReq = 0;
async function loadAds(){
  const a = app.ads;
  const req = ++adsReq; // только последний запрос должен попасть в DOM
  try {
    const off = (a.page-1) * a.per;
    const d = await api('/api/listings?filter='+a.filter+'&q='+encodeURIComponent(a.q)+
                        '&page='+a.page+'&per='+a.per);
    if (req !== adsReq) return;
    a.total = d.total; a.counts = d.counts || a.counts;
    $('adsSub').textContent = 'Всего под фильтром: ' + fmt(d.total) +
      ' · на странице ' + (d.items ? d.items.length : 0);
    $('adCounts').innerHTML = Object.keys(FLTL).map(k =>
      '<button data-f="'+k+'" class="'+(a.filter===k?'sel':'')+'"><span>'+FLTL[k]+'</span><b>'+
      fmt((d.counts||{})[k] ?? 0)+'</b></button>').join('');
    renderAdsTable(d.items || [], off);
    $('btnExport').href = '/export.csv?filter='+a.filter+'&q='+encodeURIComponent(a.q);
  } catch (e) { if (req === adsReq) skelErr($('adsTable'), 'Не удалось загрузить объявления: ' + e.message); }
}
function renderAdsTable(items, off){
  $('adsBody').innerHTML = items.map(x => {
    const st = x.posted_to_vk ? pill('ok','опубликовано')
      : (x.status==='partial' ? pill('warn','недолито') : pill('acc','в очереди'));
    const vk = x.posted_to_vk
      ? '<a class="pillink" href="'+esc(x.vk_post_url||'#')+'" target="_blank" rel="noopener">пост</a>'
      : '<span style="color:var(--faint)">—</span>';
    const thumb = (x.photo_urls && x.photo_urls[0])
      ? '<img class="thumb" src="'+esc(x.photo_urls[0])+'" loading="lazy" alt="">'
      : '<span class="thumbph">—</span>';
    const price = esc(x.price||'') || (x.price_rub ? fmt(x.price_rub)+' ₽' : '<span style="color:var(--faint)">—</span>');
    const acts = [];
    if (!x.posted_to_vk && x.status==='complete')
      acts.push('<button class="btn txt acc" data-act="pubone" data-id="'+esc(x.avito_id)+'">Опубликовать</button>');
    if (x.posted_to_vk)
      acts.push('<button class="btn txt" data-act="requeue" data-id="'+esc(x.avito_id)+'">В очередь</button>');
    acts.push('<button class="btn txt neg" data-act="del" data-id="'+esc(x.avito_id)+'">Удалить</button>');
    return '<tr>' +
      '<td><div class="adcell">'+thumb+'<div class="tw"><div class="t1"><a href="'+esc(x.url||'#')+'" target="_blank" rel="noopener">'+esc(x.title||'без названия')+'</a></div>' +
      '<div class="t2">id '+esc(x.avito_id)+' · '+esc(x.location||'—')+'</div></div></div></td>' +
      '<td class="num">'+price+'</td>' +
      '<td class="hideph"><span class="srcell">'+esc(x.source_label||'—')+'</span></td>' +
      '<td class="num hideph dtc">'+dt(x.parsed_at)+'</td>' +
      '<td>'+st+'</td><td class="hideph">'+vk+'</td>' +
      '<td class="r" style="white-space:nowrap">'+acts.join(' ')+'</td></tr>';
  }).join('') || '<tr><td colspan="7"><div class="empty">Под этот фильтр ничего не нашлось.</div></td></tr>';

  const from = items.length ? off+1 : 0, to = off + items.length;
  const pages = Math.max(1, Math.ceil(app.ads.total / app.ads.per));
  const pg = '<span>'+from+'–'+to+' из '+fmt(app.ads.total)+'</span>' +
    '<button class="btn out sm" id="pgPrev" '+(app.ads.page<=1?'disabled':'')+'>Назад</button>' +
    '<button class="btn out sm" id="pgNext" '+(app.ads.page>=pages?'disabled':'')+'>Вперёд</button>';
  let bar = $('adsPager'); if (!bar) {
    bar = document.createElement('div'); bar.className = 'pager'; bar.id = 'adsPager';
    document.querySelector('#view-ads .toolbar').appendChild(bar); }
  bar.innerHTML = pg;
  $('pgPrev').onclick = () => { app.ads.page--; loadAds(); };
  $('pgNext').onclick = () => { app.ads.page++; loadAds(); };
}
$('adCounts').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-f]'); if (!b) return;
  app.ads.filter = b.dataset.f; app.ads.page = 1; loadAds();
});
let searchT = null;
$('adSearch').addEventListener('input', (e) => {
  clearTimeout(searchT);
  searchT = setTimeout(() => { app.ads.q = e.target.value.trim(); app.ads.page = 1; loadAds(); }, 350);
});
document.addEventListener('click', async (e) => {
  const b = e.target.closest('button[data-act]'); if (!b) return;
  const act = b.dataset.act, id = b.dataset.id;
  if (act === 'del' && !confirm('Удалить объявление '+id+' из базы? Фото на диске останутся.')) return;
  b.disabled = true;
  try {
    if (act === 'del') await api('/api/ads', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'delete', avito_id:id})});
    else if (act === 'requeue') await api('/api/ads', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'requeue', avito_id:id})});
    else if (act === 'pubone') await startJob('/vk/publish-one', {avito_id:id}, 'Публикую объявление '+id+'…');
    loadAds();
  } catch (err) { statusMsg('Ошибка: ' + err.message, 'err'); b.disabled = false; }
});

/* ---------- ИСТОЧНИКИ ---------- */
function renderSources(){
  const s = app.S; if (!s) return;
  $('frlHint').textContent = s.settings.first_run_limit;
  $('srcBody').innerHTML = (s.sources || []).map(x =>
    '<tr><td><div class="tw"><div class="t1"><a href="'+esc(x.url)+'" target="_blank" rel="noopener">'+
    esc(x.label || x.url)+'</a></div><div class="t2">'+esc(x.url)+'</div></div></td>' +
    '<td>'+srcStatus(x)+'</td>' +
    '<td class="num">'+fmt(x.last_found)+'</td>' +
    '<td class="num">'+fmt(x.last_new)+'<small style="color:var(--faint)"> / '+fmt(x.total_new)+'</small></td>' +
    '<td class="num hideph">'+fmt(x.ads)+'</td>' +
    '<td class="num hideph">'+fmt(x.runs)+'</td>' +
    '<td class="num hideph dtc">'+(x.last_check ? dt(x.last_check) : '—')+'</td>' +
    '<td class="r" style="white-space:nowrap">' +
    '<button class="btn txt acc" data-sact="parse" data-url="'+esc(x.url)+'">Парсить</button>' +
    '<button class="btn txt" data-sact="toggle" data-url="'+esc(x.url)+'">'+(x.enabled?'Выключить':'Включить')+'</button>' +
    '<button class="btn txt neg" data-sact="remove" data-url="'+esc(x.url)+'">Удалить</button></td></tr>'
  ).join('') || '<tr><td colspan="8"><div class="empty">Источников нет — добавьте первую ссылку на выдачу Авито.</div></td></tr>';
}
$('srcTable').addEventListener('click', async (e) => {
  const b = e.target.closest('button[data-sact]'); if (!b) return;
  const url = b.dataset.url, act = b.dataset.sact;
  if (act === 'remove' && !confirm('Удалить источник '+url+'?')) return;
  b.disabled = true;
  try {
    if (act === 'parse') { await startJob('/parse', {urls:url, headless:true}, 'Парсинг '+url+'…'); }
    else await api('/api/sources', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:act, url})});
    await loadState(); renderSources();
  } catch (err) { statusMsg('Ошибка: ' + err.message, 'err'); b.disabled = false; }
});
$('addSource').addEventListener('click', async () => {
  const url = $('newUrl').value.trim(); if (!url) return;
  $('addSource').disabled = true;
  try {
    await api('/api/sources', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'add', url})});
    $('newUrl').value = '';
    statusMsg('Ссылка добавлена: распарсится в ближайший цикл крона.', 'ok');
    await loadState(); renderSources();
  } catch (err) { statusMsg('Ошибка: ' + err.message, 'err'); }
  $('addSource').disabled = false;
});
$('btnParseAll').addEventListener('click', () =>
  startJob('/parse', {urls:'', use_sources:true, headless:true}, 'Запускаю парсинг всех включённых ссылок…'));
$('btnOne').addEventListener('click', () => {
  const url = $('oneUrls').value.trim();
  if (!url) { statusMsg('Вставьте ссылку', 'err'); return; }
  startJob('/parse', {urls:url, headless:true}, 'Разовый парсинг ссылки…');
});

/* ---------- VK ---------- */
async function loadVK(){
  try {
    await loadState();
    const s = app.S, vk = s.vk;
    $('vkSub').textContent = vk.group_name
      ? 'Сообщество «'+vk.group_name+'» (id '+ (vk.group_id || '—') +')'
      : 'Канал не настроен — задайте ключ и сообщество ниже';
    $('vkCard').innerHTML =
      '<h3 class="chead">Канал</h3>' +
      '<div class="kv"><span>Сообщество</span><b>' + (vk.group_name ? esc(vk.group_name) : '—') + '</b></div>' +
      (vk.wall ? '<div class="kv"><span>Стена</span><b><a href="'+esc(vk.wall)+'" target="_blank" rel="noopener" style="color:var(--accent)">'+esc(vk.wall.replace('https://',''))+'</a></b></div>' : '') +
      '<div class="kv"><span>Ключ</span><b>' + (vk.token_set ? 'задан' : '<span style="color:var(--warning)">не задан</span>') + '</b></div>' +
      '<div class="kv"><span>Только посты с фото</span><b>' + (vk.require_photos ? 'да' : 'нет') + '</b></div>' +
      '<div class="kv"><span>В очереди / опубликовано</span><b>'+fmt(vk.pending)+' / '+fmt(vk.posted)+'</b></div>' +
      (vk.error ? '<div class="errline" style="margin-top:8px">'+esc(vk.error)+'</div>' : '');

    const pv = await api('/api/preview');
    if (pv.empty) {
      $('pvCard').innerHTML = '<h3 class="chead">Следующий пост</h3><div class="empty">Очередь пуста: когда крон разберёт источники, здесь появится предпросмотр следующего поста.</div>';
    } else {
      $('pvCard').innerHTML = '<h3 class="chead">Следующий пост</h3>' +
        '<div class="sub" style="margin:0 0 2px">id '+esc(pv.avito_id)+' · '+esc(pv.title||'')+'</div>' +
        '<div class="pvrow">' + ((pv.photo_urls||[])[0]
          ? '<img class="ph" src="'+esc(pv.photo_urls[0])+'" alt="">'
          : '<span class="phph">без фото</span>') +
        '<div class="msg">'+esc(pv.message||'')+'</div></div>';
    }

    const h = app.hist, off = (h.page-1)*h.per;
    const d = await api('/api/listings?filter=posted&page='+h.page+'&per='+h.per);
    h.total = d.total;
    $('vkHistCap').textContent = d.total ? '— всего '+fmt(d.total) : '';
    $('vkHistBody').innerHTML = (d.items||[]).map(x =>
      '<tr><td><div class="tw"><div class="t1">'+esc(x.title||'без названия')+'</div>' +
      '<div class="t2">id '+esc(x.avito_id)+'</div></div></td>' +
      '<td class="num hideph">'+fmt((x.photo_urls||[]).length)+'</td>' +
      '<td class="dtc">'+dt(x.posted_at)+'</td>' +
      '<td class="r"><a class="pillink" href="'+esc(x.vk_post_url||'#')+'" target="_blank" rel="noopener">'+esc((x.vk_post_url||'').replace('https://vk.com/','')||'—')+'</a></td></tr>'
    ).join('') || '<tr><td colspan="4"><div class="empty">Постов ещё не было: опубликуйте пачку кнопкой выше.</div></td></tr>';
    let bar = $('histPager');
    if (!bar) { bar = document.createElement('div'); bar.className='pager'; bar.id='histPager';
      document.querySelector('#view-vk .tablewrap').before(bar); }
    const pages = Math.max(1, Math.ceil(h.total/h.per));
    bar.innerHTML = '<span>'+((d.items||[]).length ? off+1 : 0)+'–'+(off+(d.items||[]).length)+' из '+fmt(h.total)+'</span>' +
      '<button class="btn out sm" id="hPrev" '+(h.page<=1?'disabled':'')+'>Назад</button>' +
      '<button class="btn out sm" id="hNext" '+(h.page>=pages?'disabled':'')+'>Вперёд</button>';
    $('hPrev').onclick = () => { h.page--; loadVK(); };
    $('hNext').onclick = () => { h.page++; loadVK(); };

    $('s_vkpauze').value = s.settings.vk_min_interval_sec;
    $('s_batch').value = s.settings.publish_batch;
    $('s_reqphotos').checked = !!Number(s.settings.vk_require_photos);
    $('s_vkgroup').value = s.settings.vk_group_id || '';
    $('s_vktoken').value = '';
    $('vkTokenHint').textContent = s.settings.vk_access_token_mask
      ? 'Сохранённый ключ: ' + s.settings.vk_access_token_mask
      : 'Ключ пока берётся из .env (VK_ACCESS_TOKEN); сохранённый здесь имеет приоритет.';

    const appId = vk.app_id || s.settings.vk_app_id || '';
    if (appId) {
      $('oauthBox').style.display = '';
      $('vkOauthLink').href = 'https://oauth.vk.com/authorize?client_id=' + encodeURIComponent(appId) +
        '&display=page&redirect_uri=https%3A%2F%2Foauth.vk.com%2Fblank.html' +
        '&scope=photos%2Cwall%2Cgroups%2Coffline&response_type=token&v=5.199';
    } else {
      $('oauthBox').style.display = 'none';
    }
  } catch (e) { skelErr($('vkCard'), 'Не удалось загрузить VK-канал: ' + e.message); }
}
$('saveVK').addEventListener('click', async () => {
  $('saveVK').disabled = true;
  try {
    const body = {
      vk_min_interval_sec: Number($('s_vkpauze').value) || 240,
      publish_batch: Number($('s_batch').value) || 5,
      vk_require_photos: $('s_reqphotos').checked ? 1 : 0,
      vk_group_id: $('s_vkgroup').value.trim(),
    };
    const tok = $('s_vktoken').value.trim();
    if (tok) body.vk_access_token = tok;
    await api('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)});
    $('vkSaved').textContent = 'сохранено ' + new Date().toLocaleTimeString('ru-RU');
    statusMsg('Настройки канала сохранены.', 'ok');
    loadVK();
  } catch (err) { statusMsg('Ошибка: ' + err.message, 'err'); }
  $('saveVK').disabled = false;
});
$('btnPreview').addEventListener('click', () =>
  startJob('/vk/publish', {dry_run:true}, 'Собираю предпросмотр постов…'));
$('btnPublishVK').addEventListener('click', () =>
  startJob('/vk/publish', {dry_run:false}, 'Публикую очередь в VK…'));

/* ---------- ЗАДАЧИ ---------- */
const KINDL = {parse:'Парсинг', publish:'Публикация VK', one:'Пост объявления'};
let openJob = null, openJobLog = '';

async function loadJobs(){
  let d;
  try { d = await api('/api/jobs'); }
  catch (e) { $('jobsBody').innerHTML = '<tr><td colspan="5"><div class="empty">Не удалось загрузить задачи: ' + esc(e.message) + '</div></td></tr>'; return; }
  $('jobsBody').innerHTML = (d.jobs || []).map(j => {
    const st = j.status==='running' ? pill('acc','выполняется')
      : (j.status==='error' ? pill('bad','ошибка') : pill('off','готово'));
    const sum = j.status==='running' ? (j.progress || '…')
      : (j.status==='error' ? (j.error||'ошибка') : (j.summary || '—'));
    return '<tr data-job="'+esc(j.id)+'" style="cursor:pointer">' +
      '<td>'+esc(KINDL[j.kind]||j.kind)+'</td><td>'+st+'</td>' +
      '<td><span class="cellmain">'+esc(String(sum).slice(0,160))+'</span></td>' +
      '<td class="num hideph dtc">'+tm(j.created_at)+'</td>' +
      '<td class="num hideph dtc">'+(j.elapsed ? j.elapsed.toFixed(0)+' с' : '—')+'</td></tr>' +
      '<tr class="logtr" style="display:none"><td colspan="5"><div class="joblog">…</div></td></tr>';
  }).join('') || '<tr><td colspan="5"><div class="empty">Задач ещё не было: запустите парсинг или подождите крон.</div></tr>';
  // Восстановить раскрытие после автообновления
  if (openJob) {
    const tr = $('jobsBody').querySelector('tr[data-job="'+CSS.escape(openJob)+'"]');
    if (tr) {
      const logtr = tr.nextElementSibling;
      if (logtr && logtr.classList.contains('logtr')) {
        logtr.style.display = '';
        logtr.querySelector('.joblog').textContent = openJobLog || '…';
      }
    } else { openJob = null; openJobLog = ''; }
  }
}
$('jobsTable').addEventListener('click', async (e) => {
  const tr = e.target.closest('tr[data-job]'); if (!tr) return;
  const logtr = tr.nextElementSibling; if (!logtr || !logtr.classList.contains('logtr')) return;
  if (logtr.style.display !== 'none') { logtr.style.display = 'none'; openJob = null; openJobLog = ''; return; }
  logtr.style.display = '';
  openJob = tr.dataset.job; openJobLog = '…';
  const box = logtr.querySelector('.joblog');
  try {
    const j = await api('/job/' + tr.dataset.job);
    openJobLog = (j.log || []).join('\n') || 'Лог пуст.';
    box.textContent = openJobLog;
    box.scrollTop = box.scrollHeight;
  } catch (err) { openJobLog = 'Не удалось получить лог: ' + err.message; box.textContent = openJobLog; }
});

/* ---------- ЛОГИ ---------- */
let logAuto = true;
$('logAuto').addEventListener('change', (e) => { logAuto = e.target.checked; if (logAuto) loadLogs(); });
async function loadLogs(){
  try {
    const d = await api('/api/logs?tail=300');
    $('logPath').textContent = d.path;
    const box = $('logbox');
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    box.textContent = (d.lines || []).join('\n') || 'Лог пуст.';
    if (atBottom) box.scrollTop = box.scrollHeight;
  } catch (e) { $('logbox').textContent = 'Не удалось прочитать лог: ' + e.message; }
}
$('logDownload').addEventListener('click', () =>
  $('logDownload').href = '/api/logs?download=1&tail=2000');

/* ---------- НАСТРОЙКИ ---------- */
function renderSettings(){
  const s = app.S; if (!s) return;
  $('s_parse').value = s.settings.parse_interval_min;
  $('s_publish').value = s.settings.publish_interval_min;
  $('s_paused').checked = !!Number(s.settings.cron_paused || 0);
  $('s_frl').value = s.settings.first_run_limit;
  $('s_pages').value = s.settings.pages_per_source;
  $('s_details').checked = !!Number(s.settings.details_on);
  $('s_photos').checked = !!Number(s.settings.photos_on);
  api('/api/proxy').then(p => {
    let html = '';
    if (p.configured && p.configured.length)
      html += '<div class="kv"><span>В .env настроено</span><b>'+p.configured.length+' адресов</b></div>';
    else html += '<div class="kv"><span>В .env настроено</span><b style="color:var(--warning)">нет — прямой IP</b></div>';
    if (p.browser_alive)
      html += '<div class="kv"><span>Сейчас работает</span><b>'+esc(p.current||'—')+'</b></div>' +
              '<div class="kv"><span>Пул живых / всего</span><b>'+(p.pool_healthy??'—')+' / '+(p.pool_total??'—')+'</b></div>' +
              '<div class="kv"><span>В карантине</span><b>'+((p.quarantined||[]).length ? esc(p.quarantined.join(', ')) : 'нет')+'</b></div>';
    else html += '<div class="kv"><span>Браузер</span><b>не запущен — поднимется при задаче</b></div>';
    html += '<div class="kv"><span>Прямой IP при пустом пуле</span><b>'+(p.allow_direct ? 'разрешён' : 'запрещён')+'</b></div>';
    html += '<div class="kv"><span>База / фото / лог</span><b style="font-weight:400;color:var(--faint);text-align:right;word-break:break-all">avito.db · data/photos · '+esc(p.log_path||'logs/')+'</b></div>';
    $('proxyCard').innerHTML = html;
  }).catch(() => { $('proxyCard').innerHTML = '<div class="errline">Не удалось получить статус прокси</div>'; });
}
async function saveSettingsPart(body, stampId){
  await api('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  $(stampId).textContent = 'сохранено ' + new Date().toLocaleTimeString('ru-RU');
  statusMsg('Настройки сохранены, крон подхватит их в следующем цикле.', 'ok');
  loadState();
}
$('saveSched').addEventListener('click', async () => {
  $('saveSched').disabled = true;
  try {
    await saveSettingsPart({
      parse_interval_min: Number($('s_parse').value) || 15,
      publish_interval_min: Number($('s_publish').value) || 30,
      cron_paused: $('s_paused').checked ? 1 : 0,
    }, 'schedSaved');
  } catch (err) { statusMsg('Ошибка: ' + err.message, 'err'); }
  $('saveSched').disabled = false;
});
$('saveParse').addEventListener('click', async () => {
  $('saveParse').disabled = true;
  try {
    await saveSettingsPart({
      first_run_limit: Number($('s_frl').value) || 10,
      pages_per_source: Number($('s_pages').value) || 1,
      details_on: $('s_details').checked ? 1 : 0,
      photos_on: $('s_photos').checked ? 1 : 0,
    }, 'parseSaved');
  } catch (err) { statusMsg('Ошибка: ' + err.message, 'err'); }
  $('saveParse').disabled = false;
});

/* ---------- запуск задач и журнал ---------- */
let pollTimer = null;
function logLine(msg){ const el = $('joblog'); el.style.display = '';
  el.textContent += (el.textContent ? '\n' : '') + msg; el.scrollTop = el.scrollHeight; }
function startJob(path, body, busyMsg){
  if (app.running) { statusMsg('Дождитесь завершения текущей задачи', 'err');
    return Promise.resolve(); }
  app.running = true;
  $('joblog').textContent = ''; $('joblog').style.display = '';
  statusMsg(busyMsg);
  return api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(({id}) => {
      if (app.view !== 'jobs') show('jobs');
      pollTimer = setInterval(async () => {
        let job;
        try { job = await api('/job/' + id); } catch (e) { return; }
        (job.log || []).forEach(l => logLine(l));
        if (job.status === 'running') { statusMsg('Выполняется: ' + (job.progress || '…')); return; }
        clearInterval(pollTimer); app.running = false;
        if (job.status === 'error') statusMsg('Ошибка: ' + job.error, 'err');
        else {
          const ok = (job.posts || []).filter(p => p.ok).length;
          statusMsg('Готово за ' + (job.elapsed||0).toFixed(0) + ' с: объявлений ' +
            (job.ads||[]).length + ', постов VK ' + ok + '/' + (job.posts||[]).length, 'ok');
        }
        loadJobs();
      }, 2000);
    })
    .catch(err => { if (err.message !== 'busy') statusMsg('Ошибка: ' + err.message, 'err'); app.running = false; });
}
$('btnParseDash').addEventListener('click', () =>
  startJob('/parse', {urls:'', use_sources:true, headless:true}, 'Запускаю парсинг всех ссылок…'));
$('btnPublishDash').addEventListener('click', () =>
  startJob('/vk/publish', {dry_run:false}, 'Публикую очередь в VK…'));

/* ---------- старт ---------- */
const qv = new URLSearchParams(location.search).get('view');
const startView = (qv && $('view-'+qv)) ? qv : (location.hash.slice(1) || 'dash');
history.replaceState(null, '', '#' + startView);
show(startView);
loadState().catch(() => {});
setInterval(() => { loadState().catch(() => {}); if (app.view === 'dash') loadDash(); }, 10000);
</script>
</body>
</html>
"""

LOGIN_PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход — Админка Авито → VK</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--surface:#111111;--raised:#2a2a2a;--rule:#161616;--control:#444444;
  --text:#ffffff;--muted:#b4b4b4;--faint:#949494;--accent:#4cb3f0;
  --pill-negative-bg:#2c1a20;--pill-negative-ink:#e5566f;}
*{box-sizing:border-box}
html{color-scheme:dark}
body{margin:0; background:#000; color:var(--text);
  font:14px/1.5 Inter,system-ui,'Segoe UI',Roboto,sans-serif;
  display:flex; min-height:100vh; align-items:center; justify-content:center; padding:20px;}
.box{background:var(--surface); border-radius:20px; padding:30px; width:380px; max-width:100%;}
h1{font-size:20px; font-weight:600; margin:0; letter-spacing:-.01em;}
.sub{color:var(--faint); font-size:13px; margin:8px 0 20px;}
label{display:block; font-size:14px; font-weight:500; margin:0 0 8px;}
input{width:100%; background:#000; color:var(--text); border:1px solid var(--control);
  border-radius:12px; padding:11px 14px; font:14px Inter,system-ui,sans-serif; margin-bottom:14px;}
input:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
button{width:100%; background:#fff; color:#000; border:0; border-radius:999px;
  padding:11px 18px; font:500 14px Inter,system-ui,sans-serif; cursor:pointer;}
button:hover{background:#e6e6e6;}
.err{color:var(--pill-negative-ink); background:var(--pill-negative-bg); border-radius:12px;
  padding:10px 14px; font-size:13px; display:none; margin-bottom:14px;}
</style>
</head>
<body>
<div class="box">
  <h1>Авито → VK</h1>
  <div class="sub">Админка парсера и постинга. Вход по логину и паролю из .env (ADMIN_USERNAME / ADMIN_PASSWORD)</div>
  <div class="err" id="err">Неверный логин или пароль</div>
  <form id="f">
    <label for="u">Логин</label>
    <input id="u" name="username" autocomplete="username" required>
    <label for="p">Пароль</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>
    <button>Войти</button>
  </form>
</div>
<script>
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  const res = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)});
  if (res.ok) { location.href = '/'; return; }
  document.getElementById('err').style.display = 'block';
});
</script>
</body>
</html>
"""