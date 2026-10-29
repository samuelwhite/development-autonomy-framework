'use strict';
const assert = require('node:assert/strict');

// Chromium's IPv6 reachability check uses UDP connect + GetLocalAddress only;
// neither sends a packet. SOCKET_ALIVE also means allocation, not transmission.
// Source: net/dns/host_resolver_manager.cc, StartGloballyReachableCheck and
// FinishGloballyReachableCheck. Keep these local routing checks visible rather
// than mistaking them for outbound traffic or ignoring arbitrary UDP activity.
function auditNetwork(log) {
  const names = new Map(Object.entries(log.constants.logEventTypes).map(([name, id]) => [id, name]));
  const forbidden = [], routeChecks = [], blockedJobs = [];
  const actualConnects = new Set(['TCP_CONNECT', 'TCP_CONNECT_ATTEMPT',
    'TCP_CONNECT_JOB_CONNECTOR_CONNECT_START', 'TRANSPORT_CONNECT_JOB_CONNECT_ATTEMPT']);
  for (const event of log.events) {
    const name = names.get(event.type) || '';
    if (/BYTES_SENT|SEND_ERROR|SEND_REQUEST|PACKET_SENT|DNS_TRANSACTION_QUERY|DNS_TRANSACTION_HTTPS_ATTEMPT/.test(name) || actualConnects.has(name)) {
      forbidden.push({ name, phase: event.phase });
    }
    // A ConnectJob includes DNS/scheduling before a socket exists. Record jobs
    // refused before transport separately; never accept a successful job.
    // Chromium net/log/net_log_event_type_list.h distinguishes these from the
    // TCP_CONNECT and *_CONNECT_ATTEMPT events checked above.
    if (name === 'TCP_CONNECT_JOB_CONNECT' && event.phase === log.constants.logEventPhase.PHASE_END) {
      if (event.params?.net_error < 0) blockedJobs.push(event);
      else forbidden.push({ name, reason: 'Connection job did not report a refusal' });
    }
    if (name === 'UDP_CONNECT' && event.phase === log.constants.logEventPhase.PHASE_BEGIN) {
      if (event.params?.address === '[2001:4860:4860::8888]:443') routeChecks.push(event);
      else forbidden.push({ name, reason: 'Unexpected UDP destination' });
    }
  }
  assert.deepEqual(forbidden, [], 'No transport sends, TCP connections or unexpected UDP attempts are allowed');
  return { outboundTransportEvents: 0, localIPv6RouteChecks: routeChecks.length, blockedConnectionJobs: blockedJobs.length };
}
module.exports = { auditNetwork };
