'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { assets, assetFor, canNavigate, home } = require('../policy.cjs');

test('only bundled assets are addressable', () => {
  for (const asset of Object.keys(assets)) assert.equal(assetFor(`daf://app${asset}`), asset);
  assert.equal(canNavigate(`${home}#attention`), true);
  assert.equal(canNavigate('daf://app/app.js'), false);
  for (const url of ['https://example.com', 'http://localhost:1234/', 'file:///C:/Windows/win.ini',
    'data:text/html,test', 'javascript:alert(1)', 'daf://other/index.html', 'daf://app/',
    'daf://app/../index.html', 'daf://app/%69ndex.html', 'daf://user@app/index.html',
    'daf://app/index.html?path=secret', 'daf://app/main.cjs', 'daf://app:123/index.html',
    'daf://app/__proto__', 'not a url']) assert.equal(assetFor(url), null, url);
});
