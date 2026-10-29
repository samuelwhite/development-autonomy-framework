'use strict';
const assert = require('node:assert/strict');

// Chromium's IPv6 reachability check uses UDP connect + GetLocalAddress only;
// neither sends a packet. SOCKET_ALIVE also means allocation, not transmission.
// Source: net/dns/host_resolver_manager.cc, StartGloballyReachableCheck and
// FinishGloballyReachableCheck. Keep these local routing checks visible rather
// than mistaking them for outbound traffic or ignoring arbitrary UDP activity.
function auditNetwork(log) {
  const names = new Map(Object.entries(log.constants.logEventTypes).map(([name, id]) => [id, name]));
  const forbidden = [], routeChecks = [];
  for (const event of log.events) {
    const name = names.get(event.type) || '';
    if (/BYTES_SENT|SEND_REQUEST|PACKET_SENT|DNS_TRANSACTION_QUERY|DNS_TRANSACTION_HTTPS_ATTEMPT|^TCP_CONNECT/.test(name)) {
      forbidden.push({ name, phase: event.phase });
    }
    if (name === 'UDP_CONNECT' && event.phase === log.constants.logEventPhase.PHASE_BEGIN) {
      if (event.params?.address === '[2001:4860:4860::8888]:443') routeChecks.push(event);
      else forbidden.push({ name, reason: 'Unexpected UDP destination' });
    }
  }
  assert.deepEqual(forbidden, [], 'No transport sends, TCP connections or unexpected UDP attempts are allowed');
  return { outboundTransportEvents: 0, localIPv6RouteChecks: routeChecks.length };
}
module.exports = { auditNetwork };
