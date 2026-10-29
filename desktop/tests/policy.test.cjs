'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { assets, assetFor, canNavigate, home } = require('../policy.cjs');
const { auditNetwork } = require('./network-audit.cjs');

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

test('network audit separates local route lookup from attempts to send traffic', () => {
  const constants = { logEventTypes: { UDP_CONNECT: 1, UDP_BYTES_SENT: 2, TCP_CONNECT: 3,
    SOCKET_BYTES_SENT: 4, HTTP_TRANSACTION_SEND_REQUEST: 5, SOCKET_ALIVE: 6,
    TCP_CONNECT_JOB_CONNECT: 7, UDP_SEND_ERROR: 8, TCP_CONNECT_ATTEMPT: 9,
    TCP_CONNECT_JOB_CONNECTOR_CONNECT_START: 10 }, logEventPhase: { PHASE_BEGIN: 1, PHASE_END: 2 } };
  const route = { type: 1, phase: 1, params: { address: '[2001:4860:4860::8888]:443' } };
  assert.deepEqual(auditNetwork({ constants, events: [route, { type: 6, phase: 1 }] }), {
    outboundTransportEvents: 0, localIPv6RouteChecks: 1, blockedConnectionJobs: 0,
  });
  for (const type of [2, 3, 4, 5, 8, 9, 10]) assert.throws(() => auditNetwork({ constants, events: [route, { type }] }));
  assert.throws(() => auditNetwork({ constants, events: [{ ...route, params: { address: '127.0.0.1:123' } }] }));
  assert.equal(auditNetwork({ constants, events: [{ type: 7, phase: 2, params: { net_error: -105 } }] }).blockedConnectionJobs, 1);
  assert.throws(() => auditNetwork({ constants, events: [{ type: 7, phase: 2, params: { net_error: 0 } }] }));
});
