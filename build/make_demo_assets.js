#!/usr/bin/env node
/**
 * Generate the sample PDF shown at the end of the demo.
 *
 * The app has no PDF writer for a rate-increase analysis -- its "Print / PDF"
 * button calls window.print(), so the PDF a user gets is whatever their browser
 * produces from the app's own @media print stylesheet. (jsPDF is only used for
 * the write-off export.) So rather than fake a preview, this drives the real app,
 * runs the real analysis, and prints it to PDF through that same stylesheet.
 * The file it writes is exactly what a user gets from Print -> Save as PDF.
 *
 * Run it whenever the demo cast or the app's print styles change:
 *     node build/make_demo_assets.js
 *
 * Needs Playwright (already present in this environment). It is a one-off asset
 * build -- the committed PDF is what the site serves, so visitors need nothing.
 */

const path = require('path');
const fs = require('fs');

const PLAYWRIGHT = '/opt/node22/lib/node_modules/playwright';
const { chromium } = require(PLAYWRIGHT);

const ROOT = path.resolve(__dirname, '..');
const APP = 'file://' + path.join(ROOT, 'pricing-assistant.html');
const OUT_PDF = path.join(ROOT, 'assets', 'sample-rate-increase.pdf');
const OUT_PNG = path.join(ROOT, 'assets', 'sample-rate-increase.png');

// The demo cast: five timekeepers, 40 hours total, weighted the way a real
// matter staffs -- juniors carry the hours, the equity partner supervises.
// The uneven spread is the point: it makes the blended rate a genuinely
// weighted number rather than a simple average of the five rates.
// [tkid, hours, proposed % increase over current]
const CAST = [
  ['TK005',  4, 8],   // Equity Partner
  ['TK002',  6, 7],   // Non-Equity Partner
  ['TK006',  8, 6],   // Counsel
  ['TK004', 10, 5],   // Associate
  ['TK001', 12, 5],   // Associate
];

// Current rates sit at ~91% of standard, rounded to the nearest $25, so the
// analysis has a real gap to close rather than a contrived one.
const CURRENT_RATE_FACTOR = 0.91;

async function main() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));

  await page.goto(APP, { waitUntil: 'load' });
  await page.waitForTimeout(1000);

  const summary = await page.evaluate(async ({ CAST, FACTOR }) => {
    const wm = document.getElementById('welcome-modal');
    if (wm) wm.style.display = 'none';

    document.getElementById('analysis-type').value = 'rateIncrease';
    switchAnalysis();
    CAST.forEach(([id]) => addTK(id));

    // Write through the DOM inputs: runAnalysis() calls syncFromTable(), which
    // reads the table back and would overwrite anything set on the model only.
    document.querySelectorAll('#tk-tbody tr[data-tkid]').forEach(row => {
      const id = row.dataset.tkid;
      const tk = selectedTK.find(t => t.tkid === id);
      const hours = (CAST.find(c => c[0] === id) || [])[1];
      const cur = Math.round(baseRate(tk) * FACTOR / 25) * 25;
      const pct = (CAST.find(c => c[0] === id) || [])[2];
      const hi = row.querySelector('input[data-f="hours"]');
      const ci = row.querySelector('input[data-f="currentRate"]');
      const pi = row.querySelector('input[data-f="propPct"]');
      if (hi && hours != null) { hi.value = String(hours); hi.dispatchEvent(new Event('change', { bubbles: true })); }
      if (ci) { ci.value = String(cur); ci.dispatchEvent(new Event('change', { bubbles: true })); }
      // Per-timekeeper proposed increase, graded by seniority. Without this the
      // Proposed columns just mirror Current and the sample reads as unfinished.
      if (pi && pct != null) { pi.value = String(pct); pi.dispatchEvent(new Event('change', { bubbles: true })); }
    });

    runAnalysis();
    await new Promise(r => setTimeout(r, 800));

    return {
      timekeepers: selectedTK.length,
      totalHours: selectedTK.reduce((a, t) => a + (+t.hours || 0), 0),
      kpis: [...document.querySelectorAll('.kpi-strip .kpi-card')].map(c => ({
        label: (c.querySelector('.kpi-label') || {}).textContent?.trim(),
        value: (c.querySelector('.kpi-value') || {}).textContent?.trim(),
      })),
      // did the Proposed column actually move off Current?
      proposedMoved: selectedTK.some(t => (+t.propPct || 0) > 0),
      scenarioRows: (() => {
        const t = [...document.querySelectorAll('#output-content table')]
          .find(t => [...t.querySelectorAll('th')].some(h => /Increase/i.test(h.textContent)));
        return t ? t.querySelectorAll('tbody tr').length : 0;
      })(),
    };
  }, { CAST, FACTOR: CURRENT_RATE_FACTOR });

  if (errors.length) {
    console.error('ERROR: the app reported errors:\n  ' + errors.join('\n  '));
    process.exit(1);
  }
  if (summary.totalHours !== 40) {
    console.error(`ERROR: expected 40 hours across the cast, got ${summary.totalHours}`);
    process.exit(1);
  }
  if (!summary.scenarioRows) {
    console.error('ERROR: the increase-scenario table did not render');
    process.exit(1);
  }
  if (!summary.proposedMoved) {
    console.error('ERROR: proposed rates still mirror current rates - the per-timekeeper increase did not take');
    process.exit(1);
  }

  // print CSS, not screen CSS -- this is the user's Print -> Save as PDF output
  fs.mkdirSync(path.dirname(OUT_PDF), { recursive: true });
  await page.pdf({
    path: OUT_PDF,
    format: 'Letter',
    landscape: true,
    printBackground: true,
    // 0.75 fits the whole analysis on one page. At 1.0 the fifth timekeeper
    // orphans onto page 2 on its own, which reads as a mistake in a sample.
    scale: 0.75,
    margin: { top: '0.4in', bottom: '0.4in', left: '0.4in', right: '0.4in' },
  });

  // Also render page 1 to a PNG. The demo shows the image rather than embedding
  // the PDF: <iframe src="*.pdf"> depends on the browser having a PDF viewer,
  // which is not true everywhere (and not true on most phones), whereas an
  // <img> always draws. The real PDF stays one click away.
  const shot = await ctx.newPage();
  await shot.setContent('<body style="margin:0"><canvas id="cv"></canvas></body>');
  await shot.addScriptTag({ content: fs.readFileSync(path.join(ROOT, 'build/vendor/pdf.min.js'), 'utf8') });
  const workerSrc = fs.readFileSync(path.join(ROOT, 'build/vendor/pdf.worker.min.js'), 'utf8');
  const pdfB64 = fs.readFileSync(OUT_PDF).toString('base64');
  const dataUrl = await shot.evaluate(async ({ workerSrc, pdfB64 }) => {
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      URL.createObjectURL(new Blob([workerSrc], { type: 'application/javascript' }));
    const doc = await pdfjsLib.getDocument({
      data: Uint8Array.from(atob(pdfB64), c => c.charCodeAt(0)) }).promise;
    const pg = await doc.getPage(1);
    const vp = pg.getViewport({ scale: 2 });
    const cv = document.getElementById('cv');
    cv.width = vp.width; cv.height = vp.height;
    await pg.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise;
    return cv.toDataURL('image/png');
  }, { workerSrc, pdfB64 });
  fs.writeFileSync(OUT_PNG, Buffer.from(dataUrl.split(',')[1], 'base64'));

  await browser.close();

  const kb = (fs.statSync(OUT_PDF).size / 1024).toFixed(1);
  const pngKb = (fs.statSync(OUT_PNG).size / 1024).toFixed(1);
  console.log(`  timekeepers    ${summary.timekeepers}`);
  console.log(`  total hours    ${summary.totalHours}`);
  console.log(`  scenario rows  ${summary.scenarioRows}`);
  summary.kpis.slice(0, 4).forEach(k => console.log(`  ${k.label.padEnd(26)} ${k.value}`));
  console.log(`\n  wrote          assets/sample-rate-increase.pdf (${kb} KB)`);
  console.log(`  wrote          assets/sample-rate-increase.png (${pngKb} KB)`);
}

main().catch(e => { console.error(e); process.exit(1); });
