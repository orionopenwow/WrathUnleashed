const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--enable-unsafe-webgpu','--enable-features=Vulkan','--use-angle=swiftshader','--ignore-gpu-blocklist'] });
  const p = await b.newPage(); await p.addInitScript(() => { Error.stackTraceLimit = 200; });
  const lines = [];
  p.on('console', m => lines.push(`[${m.type()}] ${m.text()}`.slice(0, 4000)));
  p.on('pageerror', e => lines.push(`[pageerror] ${String(e).slice(0, 4000)}`));
  await p.goto('http://127.0.0.1:8091/index.html?softgpu=1');
  await p.waitForTimeout(45000);
  const gpu = await p.evaluate(async () => { if (!navigator.gpu) return 'no navigator.gpu'; const a = await navigator.gpu.requestAdapter(); return a ? 'adapter ok' : 'no adapter'; });
  console.log('GPU:', gpu);
  await p.screenshot({ path: 'smoke.png' });
  console.log(lines.slice(0, 80).join('\n'));
  await b.close();
})();
