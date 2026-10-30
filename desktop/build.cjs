'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const {bundlePython} = require('./bundle-python.cjs');

async function build() {
  const { packager } = await import('@electron/packager');
  const pkg = require('./package.json');
  const platform = process.argv[2] || process.platform;
  if (!['win32', 'linux'].includes(platform)) throw new Error('Only win32 and linux x64 candidates are configured.');
  const root = path.resolve(__dirname, '..');
  const out = path.join(root, 'dist', 'm1.2-desktop');
  await fs.mkdir(out, { recursive: true });
  // A fresh staging directory prevents stale/debug files entering later builds.
  const stage = await fs.mkdtemp(path.join(out, `stage-${platform}-`));
  await fs.mkdir(path.join(stage, 'ui'), { recursive: true });
  // Only named public prototype/runtime assets enter the package.
  for (const file of ['main.cjs', 'policy.cjs', 'preload.cjs', 'planning-contract.cjs', 'planning-process.cjs', 'planning-ipc.cjs', 'planning-protocol.json']) await fs.copyFile(path.join(__dirname, file), path.join(stage, file));
  const hashes = {};
  for (const file of ['index.html', 'app.js', 'simulation.js', 'style.css']) {
    let bytes = await fs.readFile(path.join(root, 'prototype', file));
    hashes[file] = createHash('sha256').update(bytes).digest('hex');
    if (file === 'index.html') bytes = Buffer.from(bytes.toString()
      .replace('>0.2</span>', '>M1.2</span>')
      .replace('DAF v0.2 · Product preview', 'DAF M1.2 · Offline desktop demo')
      .replace('<nav aria-label="Setup progress"', '<p><a class="workspace-nav" href="planning.html">Import from GitHub →</a></p><nav aria-label="Setup progress"')
      .replace('Runs in this page · No background work or notifications', 'Closing clears demo progress · No background work')
      .replace('This interactive offline prototype needs JavaScript enabled in your browser.', 'DAF could not start. Close it and extract the complete application ZIP again.'));
    await fs.writeFile(path.join(stage, 'ui', file), bytes);
  }
  for (const file of ['planning.html','planning.js','planning.css']) await fs.copyFile(path.join(__dirname,file),path.join(stage,'ui',file));
  const planning = await fs.mkdtemp(path.join(out,`planning-${platform}-`));
  const python = await bundlePython(platform,planning);
  await fs.writeFile(path.join(stage, 'package.json'), JSON.stringify({
    name: pkg.name, productName: pkg.productName, version: pkg.version,
    main: pkg.main, license: pkg.license, author: pkg.author,
  }, null, 2));
  const folders = await packager({
    dir: stage, out, platform, arch: 'x64', name: 'DAF',
    electronVersion: pkg.devDependencies.electron, appVersion: pkg.version,
    asar: true, overwrite: true, prune: true,
    win32metadata: { CompanyName: 'DAF', FileDescription: 'DAF read-only planning', ProductName: 'DAF' },
    // No signing credentials, installer, publisher or update endpoint.
  });
  for (const folder of folders) {
    await fs.cp(planning,path.join(folder,'resources/planning'),{recursive:true});
    for (const file of ['LICENSE', 'NOTICE']) await fs.copyFile(path.join(root, file), path.join(folder, `DAF-${file}`));
    await fs.copyFile(path.join(__dirname, 'START-HERE.txt'), path.join(folder, 'START-HERE.txt'));
    await fs.writeFile(path.join(folder, 'BUILD-INFO.json'), JSON.stringify({
      version: pkg.version, electron: pkg.devDependencies.electron, platform, arch: 'x64',
      approvedBaseline: 'd076ee39ee3b3561cc9457d9d2988464f6788837',
      prototypeSourceSHA256: hashes, capabilities:['offline_simulation','public_read_only_planning'],
      executionAuthority:false,spendingAuthority:false,python,signed:false,
    }, null, 2) + '\n');
    console.log(folder);
  }
}
build().catch(error => { console.error(error); process.exitCode = 1; });
