const assert = require('assert');
const path = require('path');

const flow = require(path.resolve(__dirname, '../../cps/static/js/shelfmark_request_flow.js'));

const SAME_ORIGIN_BASE = 'https://library.example.com/shelfmark';
const SAME_ORIGIN_CURRENT = 'https://library.example.com';

assert.equal(flow.isDirectRequestViable(SAME_ORIGIN_BASE, SAME_ORIGIN_CURRENT), true);
assert.equal(
  flow.isDirectRequestViable('https://shelfmark.example.com', SAME_ORIGIN_CURRENT),
  false
);

const crossOriginOutcome = flow.resolveProbeState({
  baseUrl: 'https://shelfmark.example.com',
  currentOrigin: SAME_ORIGIN_CURRENT,
});
assert.equal(crossOriginOutcome.kind, 'cross_origin');
assert.equal(crossOriginOutcome.actionState.mode, 'open');
assert.equal(crossOriginOutcome.actionState.buttonClass, 'btn-default');
assert.match(crossOriginOutcome.bannerText, /same-origin|reverse-proxied/i);

const authOutcome = flow.resolveProbeState({
  baseUrl: SAME_ORIGIN_BASE,
  currentOrigin: SAME_ORIGIN_CURRENT,
  authPayload: { authenticated: false, auth_required: true },
});
assert.equal(authOutcome.kind, 'auth_required');
assert.equal(authOutcome.actionState.mode, 'open');
assert.match(authOutcome.actionState.hint, /log in/i);

const policyOutcome = flow.resolveProbeState({
  baseUrl: SAME_ORIGIN_BASE,
  currentOrigin: SAME_ORIGIN_CURRENT,
  authPayload: { authenticated: true, auth_required: true },
  policyPayload: { requests_enabled: true, defaults: { ebook: 'download' } },
  requestPayload: {
    book_data: { provider_id: '222', title: 'External Candidate' },
    context: { source: '*', content_type: 'ebook', request_level: 'book' }
  }
});
assert.equal(policyOutcome.kind, 'policy_blocked');
assert.equal(policyOutcome.actionState.mode, 'open');
assert.match(policyOutcome.bannerText, /download\/release handling|does not allow/i);

const requestableOutcome = flow.resolveProbeState({
  baseUrl: SAME_ORIGIN_BASE,
  currentOrigin: SAME_ORIGIN_CURRENT,
  authPayload: { authenticated: true, auth_required: true },
  policyPayload: { requests_enabled: true, defaults: { ebook: 'request_book' } },
  requestPayload: {
    book_data: { provider_id: '222', title: 'External Candidate' },
    context: { source: '*', content_type: 'ebook', request_level: 'book' }
  }
});
assert.equal(requestableOutcome.kind, 'requestable');
assert.equal(requestableOutcome.actionState.mode, 'request');
assert.equal(requestableOutcome.actionState.buttonClass, 'btn-primary');
assert.equal(requestableOutcome.actionState.iconClass, 'glyphicon glyphicon-send');
assert.equal(requestableOutcome.actionState.hint, '');
assert.match(requestableOutcome.bannerText, /current Shelfmark user/i);

const sourceReleaseOutcome = flow.resolveProbeState({
  baseUrl: SAME_ORIGIN_BASE,
  currentOrigin: SAME_ORIGIN_CURRENT,
  authPayload: { authenticated: true, auth_required: true },
  policyPayload: {
    requests_enabled: true,
    defaults: { ebook: 'request_book' },
    source_modes: [
      {
        source: 'direct_download',
        browse_results_are_releases: true,
        modes: { ebook: 'request_book' }
      }
    ]
  },
  requestPayload: {
    book_data: { provider_id: '222', title: 'External Candidate' },
    context: { source: 'direct_download', content_type: 'ebook', request_level: 'book' }
  }
});
assert.equal(sourceReleaseOutcome.kind, 'policy_blocked');
assert.equal(sourceReleaseOutcome.actionState.mode, 'open');
assert.match(sourceReleaseOutcome.actionState.hint, /selecting a concrete release/i);

const identityUnavailableOutcome = flow.resolveProbeState({
  baseUrl: SAME_ORIGIN_BASE,
  currentOrigin: SAME_ORIGIN_CURRENT,
  error: flow.createBrowserError('Identity unavailable', {
    kind: 'http',
    status: 403,
    code: 'user_identity_unavailable'
  }),
});
assert.equal(identityUnavailableOutcome.kind, 'probe_identity_unavailable');
assert.equal(identityUnavailableOutcome.actionState.mode, 'open');
assert.match(identityUnavailableOutcome.bannerText, /not mapped to a requestable Shelfmark user/i);

const probeFailureOutcome = flow.resolveProbeState({
  baseUrl: SAME_ORIGIN_BASE,
  currentOrigin: SAME_ORIGIN_CURRENT,
  error: flow.createBrowserError('Unauthorized', { kind: 'auth', status: 401 }),
});
assert.equal(probeFailureOutcome.kind, 'probe_auth_failed');
assert.equal(probeFailureOutcome.actionState.mode, 'open');

const requestSuccess = flow.resolveRequestOutcome({ success: true });
assert.equal(requestSuccess.kind, 'request_created');
assert.equal(requestSuccess.actionState.mode, 'open');
assert.equal(requestSuccess.actionState.label, 'Requested');
assert.equal(requestSuccess.actionState.buttonClass, 'btn-success');
assert.equal(requestSuccess.actionState.iconClass, 'glyphicon glyphicon-ok');
assert.equal(requestSuccess.actionState.hint, '');

const requestPolicyFailure = flow.resolveRequestOutcome({
  success: false,
  error: flow.createBrowserError('Policy blocked', { kind: 'http', status: 403 }),
});
assert.equal(requestPolicyFailure.kind, 'request_policy_failed');
assert.equal(requestPolicyFailure.actionState.mode, 'open');
assert.match(requestPolicyFailure.bannerText, /Policy blocked|rejected/i);

const requestNetworkFailure = flow.resolveRequestOutcome({
  success: false,
  error: flow.createBrowserError('Network blocked', { kind: 'network' }),
});
assert.equal(requestNetworkFailure.kind, 'request_network_failed');
assert.equal(requestNetworkFailure.actionState.mode, 'open');
assert.match(requestNetworkFailure.bannerText, /could not reach Shelfmark directly/i);

const requestRequiresRelease = flow.resolveRequestOutcome({
  success: false,
  error: flow.createBrowserError('Policy requires download', {
    kind: 'http',
    status: 403,
    code: 'policy_requires_download',
    requiredMode: 'request_release'
  }),
});
assert.equal(requestRequiresRelease.kind, 'request_requires_release');
assert.equal(requestRequiresRelease.actionState.mode, 'open');
assert.match(requestRequiresRelease.bannerText, /concrete release|download path/i);

const requestTimeoutPending = flow.resolveRequestOutcome({
  success: false,
  error: flow.createBrowserError('Timed out', { kind: 'timeout' }),
});
assert.equal(requestTimeoutPending.kind, 'request_confirmation_pending');
assert.equal(requestTimeoutPending.actionState.mode, 'open');
assert.equal(requestTimeoutPending.actionState.label, 'Checking...');
assert.match(requestTimeoutPending.bannerText, /keep checking/i);

const preferredSettings = flow.normalizePreferredReleaseSettings({
  enabled: true,
  provider: 'MyAnonamouse',
  contentType: 'ebook',
  ranking: 'seeders_desc'
});
assert.equal(preferredSettings.enabled, true);
assert.equal(preferredSettings.provider, 'MyAnonamouse');
assert.equal(preferredSettings.contentType, 'ebook');
assert.equal(preferredSettings.ranking, 'seeders_desc');

const selectedPreferredRelease = flow.selectPreferredRelease(
  [
    { source: 'prowlarr', source_id: 'audio-1', indexer: 'MyAnonamouse', format: 'm4b', seeders: 120 },
    { source: 'prowlarr', source_id: 'ebook-1', indexer: 'OtherIndexer', format: 'epub', seeders: 400 },
    { source: 'prowlarr', source_id: 'ebook-2', indexer: 'MyAnonamouse', format: 'pdf', seeders: 20 },
    { source: 'prowlarr', source_id: 'ebook-3', indexer: 'MyAnonamouse', format: 'epub', seeders: 75 }
  ],
  preferredSettings,
  {
    source_modes: [{ source: 'prowlarr', modes: { ebook: 'request_release' } }]
  }
);
assert.equal(selectedPreferredRelease.source_id, 'ebook-3');

const sourceFilteredRelease = flow.selectPreferredRelease(
  [
    { source: 'direct_download', source_id: 'direct-1', format: 'epub', seeders: 0 },
    { source: 'prowlarr', source_id: 'prowlarr-1', indexer: 'Elsewhere', format: 'epub', seeders: 99 }
  ],
  flow.normalizePreferredReleaseSettings({
    enabled: true,
    provider: 'direct_download',
    contentType: 'ebook',
    ranking: 'seeders_desc'
  }),
  {
    source_modes: [{ source: 'direct_download', modes: { ebook: 'download' } }]
  }
);
assert.equal(sourceFilteredRelease.source_id, 'direct-1');

const defaultSourceMode = flow.resolveSourceModeFromPolicy(
  {
    requests_enabled: true,
    defaults: { ebook: 'request_book' },
    source_modes: [{ source: 'prowlarr', modes: { ebook: 'request_release' } }]
  },
  'prowlarr',
  'ebook'
);
assert.equal(defaultSourceMode, 'request_book');

const preferredSourceMode = flow.resolveSourceModeFromPolicy(
  {
    requests_enabled: true,
    defaults: { ebook: 'request_book' },
    source_modes: [{ source: 'prowlarr', modes: { ebook: 'request_release' } }]
  },
  'prowlarr',
  'ebook',
  { preferSourceSpecific: true }
);
assert.equal(preferredSourceMode, 'request_release');

const preferredPayload = flow.buildPreferredReleaseRequestPayload(
  {
    book_data: {
      title: 'Mort',
      author: 'Terry Pratchett',
      provider: 'hardcover',
      provider_id: '222',
      series_name: 'Discworld',
      series_position: 4,
      series_count: 41
    },
    context: { source: '*', content_type: 'ebook', request_level: 'book' }
  },
  {
    source: 'prowlarr',
    source_id: 'mam-1',
    title: 'Mort [EPUB]',
    format: 'epub',
    size: '1 MB',
    seeders: 55,
    indexer: 'MyAnonamouse'
  },
  preferredSettings
);
assert.equal(preferredPayload.context.request_level, 'release');
assert.equal(preferredPayload.context.source, 'prowlarr');
assert.equal(preferredPayload.release_data.source_id, 'mam-1');
assert.equal(preferredPayload.release_data.indexer, 'MyAnonamouse');
assert.equal(preferredPayload.release_data.content_type, 'ebook');

const queuedOutcome = flow.resolveRequestOutcome({
  success: true,
  response: { kind: 'download', status: 'queued' }
});
assert.equal(queuedOutcome.kind, 'release_queued');
assert.equal(queuedOutcome.actionState.label, 'In queue');
assert.equal(queuedOutcome.actionState.buttonClass, 'btn-warning');

console.log('test_shelfmark_request_flow.js: ok');
