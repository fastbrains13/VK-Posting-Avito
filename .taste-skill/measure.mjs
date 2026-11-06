// Одноразовая мерилка: кто сидит у края экрана на 390px и какие блоки дают тяжёлую тень.
import { Browser, sleep } from '/Users/eryashevs/.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const url = process.argv[2] || 'http://127.0.0.1:8012/settings';
const W = parseInt(process.argv[3] || '390', 10);

const probe = () => {
  const path = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (el.className && typeof el.className === 'string'
      ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  const out = [];
  const walk = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.05) return;
    const own = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
    if (own) {
      out.push({
        text: el.textContent.trim().replace(/\s+/g, ' ').slice(0, 46), path: path(el),
        left: Math.round(r.left), right: Math.round(window.innerWidth - r.right),
        w: Math.round(r.width), h: Math.round(r.height),
      });
    }
    for (const c of el.children) walk(c);
  };
  walk(document.body);
  const heavy = [];
  for (const el of document.querySelectorAll('*')) {
    const sh = getComputedStyle(el).boxShadow;
    if (!sh || sh === 'none') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 140 || r.height < 72) continue;
    heavy.push({ path: path(el), shadow: sh.slice(0, 96), w: Math.round(r.width),
      h: Math.round(r.height), left: Math.round(r.left),
      right: Math.round(window.innerWidth - r.right) });
  }
  return { texts: out, heavy, docW: document.documentElement.scrollWidth, winW: window.innerWidth };
};

const browser = await Browser.launch();
const page = await browser.newPage({ width: W, height: 844, dsf: 1, mobile: W < 600 });
await page.goto(url, { timeoutMs: 30000, settleMs: 600 });
await sleep(2000);
const res = await page.eval(probe);
console.log('win', res.winW, 'docScrollW', res.docW);
console.log('--- text within 16px of an edge ---');
for (const t of res.texts.filter((t) => t.left < 16 || t.right < 16)) console.log(JSON.stringify(t));
console.log('--- boxes with a box-shadow ---');
for (const t of res.heavy) console.log(JSON.stringify(t));
await browser.close();
