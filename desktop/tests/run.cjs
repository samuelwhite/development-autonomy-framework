'use strict';
const path = require('node:path');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const executable = process.env.DAF_DESKTOP_EXECUTABLE || path.join(root, 'dist/desktop', `DAF-${process.platform}-x64`, process.platform === 'win32' ? 'DAF.exe' : 'DAF');
if (!fs.existsSync(executable)) throw new Error('Build the candidate first: npm run build');
const result = spawnSync(process.execPath, ['--test', '--test-concurrency=1',
  path.join(root, 'prototype/browser.test.cjs'), path.join(__dirname, 'packaged.test.cjs')], {
  stdio: 'inherit', env: { ...process.env, DAF_DESKTOP_EXECUTABLE: executable,
    DAF_PLAYWRIGHT_PATH: path.resolve(__dirname, '../node_modules/playwright'),
    DAF_UI_ARTIFACT_DIR: path.resolve(__dirname, '../test-output/screenshots') },
});
process.exitCode = result.status || (result.error ? 1 : 0);
