// Аудит геометрии страницы настроек: шарины панелей, высоты полей, выравнивание.
import { Browser, sleep } from '/Users/eryashevs/.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const url = process.argv[2] || 'http://127.0.0.1:8012/settings';
const W = parseInt(process.argv[3] || '1440', 10);
const H = parseInt(process.argv[4] || '900', 10);

const audit = () => {
  const px = (n) => Math.round(n * 10) / 10;
  const rows = [...document.querySelectorAll('.srow')].map((row) => {
    const label = row.querySelector('.slabel');
    const panel = row.querySelector('.spanel');
    const r = row.getBoundingClientRect();
    const lb = label && label.getBoundingClientRect();
    const pb = panel && panel.getBoundingClientRect();
    const fields = [...row.querySelectorAll('.field, .switchrow')].map((f) => {
      const box = f.querySelector('input:not([type=checkbox]), select, textarea') || f;
      const fr = box.getBoundingClientRect();
      const cs = getComputedStyle(box);
      return {
        key: f.querySelector('[data-setting]') ? f.querySelector('[data-setting]').dataset.setting : 'switch',
        w: px(fr.width), h: px(fr.height), top: px(fr.top + scrollY), right: px(fr.right),
        radius: cs.borderRadius, border: cs.borderTopWidth + ' ' + cs.borderTopColor,
        bg: cs.backgroundColor, fs: cs.fontSize,
      };
    });
    return {
      title: (label && label.querySelector('h3') ? label.querySelector('h3').textContent : '').trim(),
      rowTop: px(r.top + scrollY), rowH: px(r.height),
      labelRight: lb ? px(lb.right) : null,
      labelCapTop: lb ? px(lb.top + scrollY) : null,
      panelTop: pb ? px(pb.top + scrollY) : null,
      panelLeft: pb ? px(pb.left) : null,
      panelRight: pb ? px(pb.right) : null,
      panelW: pb ? px(pb.width) : null,
      panelBottom: pb ? px(pb.bottom + scrollY) : null,
      fields,
    };
  });
  const controls = {};
  for (const el of document.querySelectorAll('.spanel input:not([type=checkbox]), .spanel select, .spanel textarea')) {
    const r = el.getBoundingClientRect();
    const k = el.tagName.toLowerCase() + ':' + Math.round(r.height);
    controls[k] = (controls[k] || 0) + 1;
  }
  const clipped = [...document.querySelectorAll('.spanel *')].filter((el) => {
    if (!el.children.length && !(el.textContent || '').trim()) return false;
    return el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow === 'hidden';
  }).map((el) => el.textContent.trim().slice(0, 40));
  const sheet = document.querySelector('.sheet').getBoundingClientRect();
  const page = document.querySelector('.page').getBoundingClientRect();
  return {
    rows, controls, clipped,
    sheet: { left: px(sheet.left), right: px(innerWidth - sheet.right), w: px(sheet.width) },
    page: { left: px(page.left), right: px(innerWidth - page.right), w: px(page.width) },
    docH: document.documentElement.scrollHeight,
  };
};

const browser = await Browser.launch();
const page = await browser.newPage({ width: W, height: H, dsf: 1, mobile: W < 600 });
await page.goto(url, { timeoutMs: 30000, settleMs: 600 });
await sleep(2200);
const a = await page.eval(audit);
console.log('viewport', W, 'doc height', a.docH);
console.log('sheet', JSON.stringify(a.sheet), 'page', JSON.stringify(a.page));
console.log('control heights', JSON.stringify(a.controls));
console.log('clipped', JSON.stringify(a.clipped));
for (const r of a.rows) {
  console.log('\n— ' + r.title + '  rowTop=' + r.rowTop + ' h=' + r.rowH);
  console.log('  label right=' + r.labelRight + ' capTop=' + r.labelCapTop +
    ' | panel left=' + r.panelLeft + ' right=' + r.panelRight + ' w=' + r.panelW +
    ' top=' + r.panelTop + ' bottom=' + r.panelBottom);
  for (const f of r.fields) console.log('    ' + JSON.stringify(f));
}
await browser.close();
