// PNG -> JPEG using the local Chromium's canvas encoder (no image libraries
// are installed in this environment, and the bundled ffmpeg has no PNG decoder).
//
//   node tojpeg.mjs <quality 0-1> <file.png ...>

import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = process.env.CHROME_PATH
  || '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';

const [quality, ...files] = process.argv.slice(2);

for (const png of files) {
  const src = `data:image/png;base64,${readFileSync(png).toString('base64')}`;
  const page = join(tmpdir(), `conv-${Date.now()}.html`);
  writeFileSync(page, `<body><div id="o"></div><script>
    const i = new Image();
    i.onload = () => {
      const c = document.createElement('canvas');
      c.width = i.width; c.height = i.height;
      c.getContext('2d').drawImage(i, 0, 0);
      document.getElementById('o').textContent = c.toDataURL('image/jpeg', ${quality});
    };
    i.src = "${src}";
  </script></body>`);

  const dom = execFileSync(CHROME, ['--no-sandbox', '--disable-gpu', '--virtual-time-budget=8000',
    '--dump-dom', `file://${page}`], { maxBuffer: 1 << 30, stdio: ['ignore', 'pipe', 'ignore'] }).toString();
  unlinkSync(page);

  const b64 = (dom.match(/data:image\/jpeg;base64,([A-Za-z0-9+/=]+)/) || [])[1];
  if (!b64) throw new Error(`canvas encode failed for ${png}`);

  const out = png.replace(/\.png$/, '.jpg');
  writeFileSync(out, Buffer.from(b64, 'base64'));
  console.log(`${out}  ${(Buffer.from(b64, 'base64').length / 1024).toFixed(0)} KB`);
}
