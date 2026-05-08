const puppeteer = require('puppeteer');
const path = require('path');

(async () => {
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 800, deviceScaleFactor: 1 });
  const htmlPath = path.resolve('/home/user/weekly-report/valance-hr-strategy-discussion.html');
  await page.goto('file://' + htmlPath, { waitUntil: 'networkidle0' });
  await page.pdf({
    path: '/home/user/weekly-report/valance-hr-strategy-discussion-small.pdf',
    format: 'A4',
    printBackground: true,
    margin: { top: '10mm', bottom: '10mm', left: '10mm', right: '10mm' },
    scale: 0.85
  });
  await browser.close();
  console.log('done');
})();
