'use strict';
// Maintainer packaging dependency checks; never imported by the desktop runtime.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
// Use the import condition, as ASAR does. Importing a require.resolve() path
// instead loads the CJS bundle, whose inferred named exports vary by Node version.
// The reviewed lockfile has one shared copy of each of these packages.
const asarModule = import('@electron/asar');
const globModule = import('glob');
const minimatchModule = import('minimatch');

async function fixture(t) {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'daf-packaging-'));
  assert.equal(path.dirname(root), path.resolve(os.tmpdir()));
  assert.ok(path.basename(root).startsWith('daf-packaging-'));
  t.after(() => fsp.rm(root, {recursive: true, force: true}));
  const source = path.join(root, 'input');
  const files = {
    'main.cjs': "'use strict';\n",
    '.hidden': 'included dot file\n',
    'ui/space name.txt': 'space\n',
    'ui/[review].txt': 'literal brackets\n',
    'ui/{plan}.txt': 'literal braces\n',
    'ui/caf\u00e9.txt': 'unicode\n',
    'ui/addon.node': 'synthetic native placeholder\n',
    'assets/deep/data.bin': Buffer.from([0, 1, 2, 255]),
  };
  for (const [name, data] of Object.entries(files)) {
    const file = path.join(source, name);
    await fsp.mkdir(path.dirname(file), {recursive: true});
    await fsp.writeFile(file, data);
  }
  return {root, source, files, archive: path.join(root, 'fixture.asar')};
}

function inventory(files) {
  const names = new Set();
  for (const name of Object.keys(files)) {
    const parts = name.split('/');
    for (let i = 1; i <= parts.length; i++) names.add('/' + parts.slice(0, i).join('/'));
  }
  return [...names].sort();
}

test('ASAR preserves exact named, hidden, Unicode and special-character fixture bytes', async t => {
  const {createPackageWithOptions, listPackage, extractFile} = await asarModule;
  const {source, files, archive} = await fixture(t);
  await createPackageWithOptions(source, archive, {});
  assert.deepEqual(listPackage(archive).map(p => p.replaceAll('\\', '/')).sort(), inventory(files));
  for (const [name, data] of Object.entries(files)) {
    assert.deepEqual(extractFile(archive, path.normalize(name)), Buffer.from(data), name);
  }
  t.diagnostic('fixture archive SHA-256: ' + createHash('sha256').update(await fsp.readFile(archive)).digest('hex'));
});

test('ASAR minimatch unpack and unpackDir options preserve exact contents', async t => {
  const {createPackageWithOptions, extractFile, statFile} = await asarModule;
  const {source, files, archive} = await fixture(t);
  await createPackageWithOptions(source, archive, {unpack: '*.node', unpackDir: 'assets/**'});
  for (const [name, data] of Object.entries(files)) {
    assert.deepEqual(extractFile(archive, path.normalize(name)), Buffer.from(data), name);
    assert.equal(Boolean(statFile(archive, path.normalize(name)).unpacked), name.endsWith('.node') || name.startsWith('assets/'), name);
  }
});

test('ASAR rejects a directory link escaping the staged tree', async t => {
  const {createPackageWithOptions} = await asarModule;
  const {root, source, archive} = await fixture(t);
  const outside = path.join(root, 'outside');
  await fsp.mkdir(outside);
  await fsp.writeFile(path.join(outside, 'secret.txt'), 'synthetic outside fixture');
  await fsp.symlink(outside, path.join(source, 'escape'), process.platform === 'win32' ? 'junction' : 'dir');
  await assert.rejects(createPackageWithOptions(source, archive, {}), /outside|out of|escap|link/i);
});

test('glob abort stops recursive reads after the first completed directory read', {timeout: 5000}, async t => {
  const {glob} = await globModule;
  const {source} = await fixture(t);
  const controller = new AbortController();
  const reason = new Error('synthetic packaging cancellation');
  let reads = 0;
  const interceptedFs = {
    readdir(dir, options, callback) {
      reads++;
      fs.readdir(dir, options, (error, entries) => {
        if (reads === 1) controller.abort(reason);
        callback(error, entries);
      });
    },
  };
  await assert.rejects(glob('**/*', {cwd: source, dot: true, signal: controller.signal, fs: interceptedFs}), error => error === reason);
  // Let already queued callbacks drain; no recursive read may be scheduled after abort.
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(reads, 1);
});

test('minimatch and the shipped glob bundle bound globparts expansion', {timeout: 5000}, async () => {
  const {Minimatch} = await minimatchModule;
  const pattern = Array(8).fill('**/../a/b').join('/') + '/target';
  const matcher = new Minimatch(pattern, {optimizationLevel: 2, braceExpandMax: 16});
  assert.ok(matcher.globParts.length <= 16, 'preprocessing exceeded its explicit expansion budget');
  const {Glob} = await globModule;
  const walker = new Glob(pattern, {braceExpandMax: 16});
  assert.ok(walker.patterns.length <= 16, 'shipped glob bundle exceeded its expansion budget');
});
