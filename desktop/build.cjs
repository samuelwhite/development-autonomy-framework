'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');

async function build() {
  const { packager } = await import('@electron/packager');
  const pkg = require('./package.json');
  const platform = process.argv[2] || process.platform;
  if (!['win32', 'linux'].includes(platform)) throw new Error('Only win32 and linux x64 candidates are configured.');
  const root = path.resolve(__dirname, '..');
  const out = path.join(root, 'dist', 'desktop');
  const stage = path.join(out, `stage-${platform}`);
  await fs.mkdir(path.join(stage, 'ui'), { recursive: true });
  // Only named public prototype/runtime assets enter the package.
  for (const file of ['main.cjs', 'policy.cjs']) await fs.copyFile(path.join(__dirname, file), path.join(stage, file));
  const hashes = {};
  for (const file of ['index.html', 'app.js', 'simulation.js', 'style.css']) {
    let bytes = await fs.readFile(path.join(root, 'prototype', file));
    hashes[file] = createHash('sha256').update(bytes).digest('hex');
    if (file === 'index.html') bytes = Buffer.from(bytes.toString()
      .replace('>0.2</span>', '>0.2.1</span>')
      .replace('DAF v0.2 · Product preview', 'DAF v0.2.1 · Offline desktop demo')
      .replace('Runs in this page · No background work or notifications', 'Closing clears demo progress · No background work')
      .replace('This interactive offline prototype needs JavaScript enabled in your browser.', 'DAF could not start. Close it and extract the complete application ZIP again.'));
    await fs.writeFile(path.join(stage, 'ui', file), bytes);
  }
  await fs.writeFile(path.join(stage, 'package.json'), JSON.stringify({
    name: pkg.name, productName: pkg.productName, version: pkg.version,
    main: pkg.main, license: pkg.license, author: pkg.author,
  }, null, 2));
  const folders = await packager({
    dir: stage, out, platform, arch: 'x64', name: 'DAF',
    electronVersion: pkg.devDependencies.electron, appVersion: pkg.version,
    asar: true, overwrite: true, prune: true,
    win32metadata: { CompanyName: 'DAF', FileDescription: 'DAF Offline Demo', ProductName: 'DAF' },
    // No signing credentials, installer, publisher or update endpoint.
  });
  for (const folder of folders) {
    for (const file of ['LICENSE', 'NOTICE']) await fs.copyFile(path.join(root, file), path.join(folder, `DAF-${file}`));
    await fs.copyFile(path.join(__dirname, 'START-HERE.txt'), path.join(folder, 'START-HERE.txt'));
    await fs.writeFile(path.join(folder, 'BUILD-INFO.json'), JSON.stringify({
      version: pkg.version, electron: pkg.devDependencies.electron, platform, arch: 'x64',
      approvedBaseline: 'd076ee39ee3b3561cc9457d9d2988464f6788837',
      prototypeSourceSHA256: hashes, simulated: true, signed: false,
    }, null, 2) + '\n');
    console.log(folder);
  }
}
build().catch(error => { console.error(error); process.exitCode = 1; });
