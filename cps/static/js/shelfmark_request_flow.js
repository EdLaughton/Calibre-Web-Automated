(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.CwaShelfmarkRequestFlow = api;
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var REQUEST_MODE = 'request_book';
  var REQUEST_RELEASE_MODE = 'request_release';
  var DOWNLOAD_MODE = 'download';
  var BLOCKED_MODE = 'blocked';
  var DEFAULT_PREFERRED_RELEASE_CONTENT_TYPE = 'ebook';
  var DEFAULT_PREFERRED_RELEASE_RANKING = 'seeders_desc';
  var AUDIO_FORMATS = {
    aac: true,
    aax: true,
    aaxc: true,
    flac: true,
    m4a: true,
    m4b: true,
    mp3: true,
    ogg: true,
    opus: true,
    wav: true
  };
  var EBOOK_FORMATS = {
    azw: true,
    azw3: true,
    cb7: true,
    cba: true,
    cbr: true,
    cbt: true,
    cbz: true,
    djvu: true,
    doc: true,
    docx: true,
    epub: true,
    fb2: true,
    kepub: true,
    kepub_epub: true,
    lit: true,
    lrf: true,
    mobi: true,
    pdf: true,
    rtf: true,
    txt: true
  };
  var EBOOK_FORMAT_RANK = {
    epub: 0,
    azw3: 1,
    kepub: 2,
    kepub_epub: 2,
    mobi: 3,
    pdf: 4
  };
  var AUDIO_FORMAT_RANK = {
    m4b: 0,
    mp3: 1,
    aax: 2,
    aaxc: 3,
    m4a: 4
  };
  var MODE_RANK = {
    download: 0,
    request_release: 1,
    request_book: 2,
    blocked: 3
  };
  var MATRIX_MODES = {
    download: true,
    request_release: true,
    blocked: true
  };

  function normalizeMode(value) {
    return (value || '').toString().trim().toLowerCase();
  }

  function normalizeContentType(value) {
    return normalizeMode(value) === 'audiobook' ? 'audiobook' : 'ebook';
  }

  function normalizeSource(value) {
    var source = normalizeMode(value);
    return source || '*';
  }

  function normalizeText(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function normalizePreferredReleaseContentType(value) {
    var normalized = normalizeMode(value);
    if (normalized === 'audiobook') {
      return 'audiobook';
    }
    return DEFAULT_PREFERRED_RELEASE_CONTENT_TYPE;
  }

  function normalizePreferredReleaseRanking(value) {
    var normalized = normalizeMode(value);
    if (normalized === DEFAULT_PREFERRED_RELEASE_RANKING) {
      return normalized;
    }
    return DEFAULT_PREFERRED_RELEASE_RANKING;
  }

  function normalizePreferredReleaseSettings(settings) {
    var raw = settings || {};
    return {
      enabled: Boolean(raw.enabled),
      provider: normalizeText(raw.provider),
      contentType: normalizePreferredReleaseContentType(raw.contentType),
      ranking: normalizePreferredReleaseRanking(raw.ranking)
    };
  }

  function isPreferredReleaseWorkflowEnabled(settings) {
    return Boolean(normalizePreferredReleaseSettings(settings).enabled);
  }

  function resolvePreferredReleaseSource(settings, policy) {
    var normalizedSettings = normalizePreferredReleaseSettings(settings);
    var preferred = normalizeSource(normalizedSettings.provider);
    if (preferred === '*') {
      return '';
    }
    var sourceModes = Array.isArray(policy && policy.source_modes) ? policy.source_modes : [];
    var matched = sourceModes.find(function (entry) {
      return normalizeSource(entry && entry.source) === preferred;
    });
    return matched ? preferred : '';
  }

  function normalizeReleaseFormat(value) {
    return normalizeMode(value).replace(/\s+/g, '').replace(/\./g, '');
  }

  function resolveReleaseContentType(release) {
    var releaseContentType = normalizeMode(release && release.content_type);
    if (releaseContentType === 'ebook' || releaseContentType === 'audiobook') {
      return releaseContentType;
    }

    var extraContentType = normalizeMode(
      release && release.extra && typeof release.extra === 'object'
        ? release.extra.content_type
        : ''
    );
    if (extraContentType === 'ebook' || extraContentType === 'audiobook') {
      return extraContentType;
    }

    var format = normalizeReleaseFormat(release && release.format);
    if (format && AUDIO_FORMATS[format]) {
      return 'audiobook';
    }
    if (format && EBOOK_FORMATS[format]) {
      return 'ebook';
    }

    return '';
  }

  function releaseMatchesPreferredProvider(release, settings, policy) {
    var normalizedSettings = normalizePreferredReleaseSettings(settings);
    if (!normalizedSettings.provider) {
      return true;
    }

    var preferredSource = resolvePreferredReleaseSource(normalizedSettings, policy);
    if (preferredSource) {
      return normalizeSource(release && release.source) === preferredSource;
    }

    return normalizeText(release && release.indexer).toLowerCase() === normalizedSettings.provider.toLowerCase();
  }

  function releaseMatchesPreferredContentType(release, settings) {
    var normalizedSettings = normalizePreferredReleaseSettings(settings);
    return resolveReleaseContentType(release) === normalizedSettings.contentType;
  }

  function getReleaseSeeders(release) {
    var raw = release && typeof release.seeders !== 'undefined' ? Number(release.seeders) : NaN;
    return Number.isFinite(raw) ? raw : -1;
  }

  function getReleaseFormatRank(release, settings) {
    var normalizedSettings = normalizePreferredReleaseSettings(settings);
    var format = normalizeReleaseFormat(release && release.format);
    if (!format) {
      return Number.MAX_SAFE_INTEGER;
    }
    if (normalizedSettings.contentType === 'audiobook') {
      return Object.prototype.hasOwnProperty.call(AUDIO_FORMAT_RANK, format)
        ? AUDIO_FORMAT_RANK[format]
        : 999;
    }
    return Object.prototype.hasOwnProperty.call(EBOOK_FORMAT_RANK, format)
      ? EBOOK_FORMAT_RANK[format]
      : 999;
  }

  function comparePreferredReleases(left, right, settings) {
    var seederDelta = getReleaseSeeders(right) - getReleaseSeeders(left);
    if (seederDelta !== 0) {
      return seederDelta;
    }

    var formatDelta = getReleaseFormatRank(left, settings) - getReleaseFormatRank(right, settings);
    if (formatDelta !== 0) {
      return formatDelta;
    }

    var leftTitle = normalizeText(left && left.title).toLowerCase();
    var rightTitle = normalizeText(right && right.title).toLowerCase();
    if (leftTitle < rightTitle) {
      return -1;
    }
    if (leftTitle > rightTitle) {
      return 1;
    }
    return 0;
  }

  function selectPreferredRelease(releases, settings, policy) {
    var normalizedSettings = normalizePreferredReleaseSettings(settings);
    if (!normalizedSettings.enabled) {
      return null;
    }

    var matches = (Array.isArray(releases) ? releases : []).filter(function (release) {
      return releaseMatchesPreferredProvider(release, normalizedSettings, policy)
        && releaseMatchesPreferredContentType(release, normalizedSettings);
    });

    if (!matches.length) {
      return null;
    }

    return matches.slice().sort(function (left, right) {
      return comparePreferredReleases(left, right, normalizedSettings);
    })[0] || null;
  }

  function buildPreferredReleaseRequestPayload(requestPayload, release, settings) {
    var normalizedSettings = normalizePreferredReleaseSettings(settings);
    var basePayload = requestPayload && typeof requestPayload === 'object' ? requestPayload : {};
    var bookData = basePayload.book_data && typeof basePayload.book_data === 'object'
      ? Object.assign({}, basePayload.book_data)
      : {};
    var normalizedRelease = release && typeof release === 'object' ? release : {};
    var releaseTitle = normalizeText(normalizedRelease.title);

    if (normalizedSettings.contentType) {
      bookData.content_type = normalizedSettings.contentType;
    }

    return {
      book_data: bookData,
      note: basePayload.note,
      on_behalf_of_user_id: basePayload.on_behalf_of_user_id,
      release_data: {
        source: normalizeSource(normalizedRelease.source),
        source_id: normalizeText(normalizedRelease.source_id || normalizedRelease.id),
        title: releaseTitle || bookData.title || 'Unknown title',
        author: bookData.author,
        year: bookData.year,
        format: normalizeReleaseFormat(normalizedRelease.format) || normalizeText(normalizedRelease.format),
        size: normalizedRelease.size,
        size_bytes: normalizedRelease.size_bytes,
        download_url: normalizedRelease.download_url,
        protocol: normalizedRelease.protocol,
        indexer: normalizedRelease.indexer,
        seeders: typeof normalizedRelease.seeders === 'number'
          ? normalizedRelease.seeders
          : (Number.isFinite(Number(normalizedRelease.seeders)) ? Number(normalizedRelease.seeders) : undefined),
        extra: normalizedRelease.extra,
        preview: bookData.preview,
        content_type: normalizedSettings.contentType,
        series_name: bookData.series_name,
        series_position: bookData.series_position,
        series_count: bookData.series_count,
        subtitle: bookData.subtitle
      },
      context: {
        source: normalizeSource(normalizedRelease.source),
        content_type: normalizedSettings.contentType,
        request_level: 'release'
      }
    };
  }

  function buildOpenState(hint, label, buttonClass, iconClass) {
    return {
      mode: 'open',
      label: label || 'Open in Shelfmark',
      hint: hint,
      buttonClass: buttonClass || 'btn-default',
      iconClass: iconClass || 'glyphicon glyphicon-new-window'
    };
  }

  function buildRequestState(hint) {
    return {
      mode: 'request',
      label: 'Request in Shelfmark',
      hint: hint || '',
      buttonClass: 'btn-primary',
      iconClass: 'glyphicon glyphicon-send'
    };
  }

  function buildQueuedState(hint) {
    return {
      mode: 'open',
      label: 'In queue',
      hint: hint || '',
      buttonClass: 'btn-warning',
      iconClass: 'glyphicon glyphicon-time'
    };
  }

  function buildCheckingState(hint) {
    return {
      mode: 'open',
      label: 'Checking...',
      hint: hint || '',
      buttonClass: 'btn-default',
      iconClass: 'glyphicon glyphicon-time'
    };
  }

  function createBrowserError(message, options) {
    var error = new Error(message || 'Shelfmark request flow failed.');
    var data = options || {};
    error.name = 'ShelfmarkBrowserError';
    error.kind = data.kind || 'unknown';
    error.status = typeof data.status === 'number' ? data.status : null;
    error.payload = data.payload || null;
    error.code = data.code || null;
    error.requiredMode = data.requiredMode || null;
    error.isShelfmarkBrowserError = true;
    return error;
  }

  function capModeToCeiling(mode, ceiling) {
    var modeRank = MODE_RANK[mode];
    var ceilingRank = MODE_RANK[ceiling];
    if (typeof modeRank !== 'number' || typeof ceilingRank !== 'number') {
      return mode;
    }
    return modeRank < ceilingRank ? ceiling : mode;
  }

  function normalizeReleaseResultMode(policy, source, mode) {
    if (mode !== REQUEST_MODE) {
      return mode;
    }
    var normalizedSource = normalizeSource(source);
    var sourceModes = Array.isArray(policy && policy.source_modes) ? policy.source_modes : [];
    var sourceMode = sourceModes.find(function (entry) {
      return normalizeSource(entry && entry.source) === normalizedSource;
    });
    return sourceMode && sourceMode.browse_results_are_releases ? REQUEST_RELEASE_MODE : mode;
  }

  function normalizeRuleSource(value) {
    if (typeof value !== 'string') {
      return null;
    }
    var normalized = normalizeMode(value);
    if (!normalized || normalized === 'any') {
      return '*';
    }
    return normalized;
  }

  function normalizeRuleContentType(value) {
    if (typeof value !== 'string') {
      return null;
    }
    var normalized = normalizeMode(value);
    if (!normalized || normalized === 'any' || normalized === '*') {
      return '*';
    }
    return normalizeContentType(normalized);
  }

  function parseMatrixMode(value) {
    var normalized = normalizeMode(value);
    return MATRIX_MODES[normalized] ? normalized : null;
  }

  function resolveDefaultModeFromPolicy(policy, contentType) {
    if (!policy || !policy.requests_enabled) {
      return DOWNLOAD_MODE;
    }
    var defaults = policy.defaults || {};
    return normalizeMode(defaults[normalizeContentType(contentType)]) || DOWNLOAD_MODE;
  }

  function resolveSourceModeFromPolicy(policy, source, contentType, options) {
    var settings = options || {};
    var normalizedSource = normalizeSource(source);
    var normalizedContentType = normalizeContentType(contentType);
    var defaultMode = resolveDefaultModeFromPolicy(policy, normalizedContentType);
    var preferSourceSpecific = Boolean(settings.preferSourceSpecific && normalizedSource !== '*');
    if (defaultMode === DOWNLOAD_MODE && (!policy || !policy.requests_enabled)) {
      return DOWNLOAD_MODE;
    }

    var sourceModes = Array.isArray(policy && policy.source_modes) ? policy.source_modes : [];
    var sourceMode = sourceModes.find(function (entry) {
      return normalizeSource(entry && entry.source) === normalizedSource;
    });
    if (sourceMode && sourceMode.modes) {
      var fromSource = normalizeMode(sourceMode.modes[normalizedContentType]);
      if (fromSource) {
        return normalizeReleaseResultMode(
          policy,
          normalizedSource,
          preferSourceSpecific ? fromSource : capModeToCeiling(fromSource, defaultMode)
        );
      }
    }

    var rules = Array.isArray(policy && policy.rules) ? policy.rules : [];
    var precedence = [
      [normalizedSource, normalizedContentType],
      [normalizedSource, '*'],
      ['*', normalizedContentType],
      ['*', '*']
    ];

    for (var i = 0; i < precedence.length; i += 1) {
      var sourceMatch = precedence[i][0];
      var contentTypeMatch = precedence[i][1];
      var matchedRule = rules.find(function (rule) {
        if (!rule || typeof rule !== 'object') {
          return false;
        }
        return normalizeRuleSource(rule.source) === sourceMatch
          && normalizeRuleContentType(rule.content_type) === contentTypeMatch;
      });

      if (!matchedRule || typeof matchedRule !== 'object') {
        continue;
      }

      var parsedMode = parseMatrixMode(matchedRule.mode);
      if (!parsedMode) {
        continue;
      }

      return normalizeReleaseResultMode(
        policy,
        normalizedSource,
        preferSourceSpecific && sourceMatch === normalizedSource
          ? parsedMode
          : capModeToCeiling(parsedMode, defaultMode)
      );
    }

    return normalizeReleaseResultMode(policy, normalizedSource, defaultMode);
  }

  function getRequestPayloadContentType(requestPayload) {
    return normalizeContentType(
      requestPayload
      && requestPayload.context
      && requestPayload.context.content_type
      || requestPayload && requestPayload.content_type
      || requestPayload && requestPayload.book_data && requestPayload.book_data.content_type
      || 'ebook'
    );
  }

  function getRequestPayloadSource(requestPayload) {
    return normalizeSource(
      requestPayload
      && requestPayload.context
      && requestPayload.context.source
    );
  }

  function getRequestPayloadLevel(requestPayload) {
    var explicit = normalizeMode(
      requestPayload
      && requestPayload.context
      && requestPayload.context.request_level
    );
    if (explicit) {
      return explicit;
    }
    return requestPayload && requestPayload.release_data ? 'release' : 'book';
  }

  function describeRequiredMode(mode) {
    if (mode === REQUEST_RELEASE_MODE) {
      return 'Shelfmark policy for this result requires selecting a concrete release in Shelfmark before requesting.';
    }
    if (mode === DOWNLOAD_MODE) {
      return 'Shelfmark policy for this result routes directly to download/release handling instead of a book-level request.';
    }
    if (mode === BLOCKED_MODE) {
      return 'Shelfmark policy blocks direct requests for this result.';
    }
    return 'Shelfmark policy does not allow a direct book-level request for this result.';
  }

  function getOrigin(value, currentOrigin) {
    if (!value) {
      return null;
    }
    try {
      return new URL(value, currentOrigin || 'http://localhost').origin;
    } catch (err) {
      return null;
    }
  }

  function isDirectRequestViable(baseUrl, currentOrigin) {
    var browserOrigin = getOrigin(currentOrigin, currentOrigin);
    var shelfmarkOrigin = getOrigin(baseUrl, currentOrigin);
    if (!browserOrigin || !shelfmarkOrigin) {
      return false;
    }
    return browserOrigin === shelfmarkOrigin;
  }

  function resolveProbeState(options) {
    var currentOrigin = options && options.currentOrigin ? options.currentOrigin : null;
    var baseUrl = options && options.baseUrl ? options.baseUrl : null;
    var authPayload = options && options.authPayload ? options.authPayload : null;
    var policyPayload = options && options.policyPayload ? options.policyPayload : null;
    var error = options && options.error ? options.error : null;

    if (!isDirectRequestViable(baseUrl, currentOrigin)) {
      return {
        kind: 'cross_origin',
        bannerLevel: 'alert-warning',
        bannerText: 'Direct Request in Shelfmark needs a same-origin or reverse-proxied browser URL for Shelfmark. Open in Shelfmark remains the safe fallback for this setup.',
        actionState: buildOpenState('This CWA page and the browser-facing Shelfmark URL are on different origins. Configure Shelfmark Browser URL to the same-origin or reverse-proxied Shelfmark address if you want direct request buttons here.')
      };
    }

    if (error) {
      if (error.kind === 'timeout') {
        return {
          kind: 'probe_timeout',
          bannerLevel: 'alert-warning',
          bannerText: 'Timed out while checking your Shelfmark session. Open in Shelfmark to continue or retry after the network/proxy recovers.',
          actionState: buildOpenState('Shelfmark did not respond before the browser timed out. Open Shelfmark directly or retry after the network/proxy recovers.')
        };
      }

      if (error.kind === 'auth' || error.status === 401) {
        return {
          kind: 'probe_auth_failed',
          bannerLevel: 'alert-warning',
          bannerText: 'Shelfmark requires a live login in this browser before requests can be attributed to your user.',
          actionState: buildOpenState('Shelfmark is not currently signed in for this browser. Log in there first, then return here to retry.')
        };
      }

      if (error.status === 403) {
        if (error.code === 'user_identity_unavailable') {
          return {
            kind: 'probe_identity_unavailable',
            bannerLevel: 'alert-warning',
            bannerText: 'Shelfmark is signed in in this browser, but that session is not mapped to a requestable Shelfmark user yet.',
            actionState: buildOpenState('Shelfmark did not expose a request user identity for this browser session. Re-open Shelfmark, confirm the synced user is logged in there, and retry.')
          };
        }
        if (error.code === 'requests_unavailable') {
          return {
            kind: 'probe_requests_unavailable',
            bannerLevel: 'alert-warning',
            bannerText: 'Shelfmark reports that the request workflow is unavailable for the current auth mode or policy.',
            actionState: buildOpenState('Shelfmark reports that the request workflow is unavailable for the current auth mode or policy.')
          };
        }
        return {
          kind: 'probe_policy_failed',
          bannerLevel: 'alert-warning',
          bannerText: 'Shelfmark rejected the direct request workflow for this browser session or policy configuration.',
          actionState: buildOpenState('Shelfmark rejected direct request actions for this browser session or policy. Open Shelfmark directly to review the current policy and login state.')
        };
      }

      if (error.kind === 'network') {
        return {
          kind: 'probe_network_failed',
          bannerLevel: 'alert-warning',
          bannerText: 'The browser could not reach Shelfmark directly. Open in Shelfmark remains the safe fallback.',
          actionState: buildOpenState('The browser could not reach Shelfmark directly. This usually means the network or proxy blocked the request, or the apps are not deployed under a compatible same-origin setup.')
        };
      }

      return {
        kind: 'probe_failed',
        bannerLevel: 'alert-warning',
        bannerText: error.message || 'Shelfmark request actions could not be verified from this browser.',
        actionState: buildOpenState('Shelfmark request availability could not be confirmed from this browser. Open Shelfmark directly to continue.')
      };
    }

    if (!authPayload || !authPayload.authenticated) {
      var authRequired = authPayload ? Boolean(authPayload.auth_required) : true;
      return {
        kind: 'auth_required',
        bannerLevel: 'alert-warning',
        bannerText: authRequired
          ? 'Shelfmark login is required in this browser before requests can be attributed to your user.'
          : 'Shelfmark is not currently authenticated in this browser.',
        actionState: buildOpenState(authRequired
          ? 'Shelfmark is not currently signed in for this browser. Log in there first, then return here to retry.'
          : 'Shelfmark did not report an active authenticated browser session.')
      };
    }

    if (!policyPayload || !policyPayload.requests_enabled) {
      return {
        kind: 'policy_unavailable',
        bannerLevel: 'alert-warning',
        bannerText: 'Shelfmark is signed in, but the request workflow is disabled by the current Shelfmark policy.',
        actionState: buildOpenState('Shelfmark is signed in, but the request workflow is disabled by the current Shelfmark policy.')
      };
    }

    if (!options || !options.requestPayload) {
      return {
        kind: 'requestable',
        bannerLevel: 'alert-success',
        bannerText: 'Shelfmark session detected. Request buttons are enabled where the current policy allows direct book-level requests.',
        actionState: buildRequestState('')
      };
    }

    var requestPayload = options.requestPayload;
    var effectiveMode = resolveSourceModeFromPolicy(
      policyPayload,
      getRequestPayloadSource(requestPayload),
      getRequestPayloadContentType(requestPayload)
    );
    var requestLevel = getRequestPayloadLevel(requestPayload);
    if (effectiveMode !== REQUEST_MODE || requestLevel !== 'book') {
      return {
        kind: 'policy_blocked',
        bannerLevel: 'alert-warning',
        bannerText: describeRequiredMode(effectiveMode),
        actionState: buildOpenState(
          describeRequiredMode(effectiveMode),
          'Open in Shelfmark',
          'btn-default',
          'glyphicon glyphicon-new-window'
        )
      };
    }

    return {
      kind: 'requestable',
      bannerLevel: 'alert-success',
      bannerText: 'Shelfmark session detected. Direct requests will be attributed in Shelfmark as the current Shelfmark user.',
      actionState: buildRequestState('')
    };
  }

  function resolveRequestOutcome(options) {
    var response = options && options.response ? options.response : null;
    if (options && options.success) {
      if (response && normalizeMode(response.kind) === 'download' && normalizeMode(response.status) === 'queued') {
        return {
          kind: 'release_queued',
          bannerLevel: 'alert-success',
          bannerText: '',
          actionState: buildQueuedState('Shelfmark has queued the preferred release.')
        };
      }
      return {
        kind: 'request_created',
        bannerLevel: 'alert-success',
        bannerText: 'Request sent to Shelfmark.',
        actionState: buildOpenState(
          '',
          'Requested',
          'btn-success',
          'glyphicon glyphicon-ok'
        )
      };
    }

    var error = options && options.error ? options.error : null;
    if (error) {
      if (error.kind === 'timeout') {
        return {
          kind: 'request_confirmation_pending',
          bannerLevel: 'alert-warning',
          bannerText: 'Shelfmark has not confirmed this request yet. CWA will keep checking for queue or library updates.',
          actionState: buildCheckingState('Shelfmark has not confirmed this request yet. CWA will keep checking for queue or library updates before you need to retry.')
        };
      }

      if (error.kind === 'auth' || error.status === 401) {
        return {
          kind: 'request_auth_failed',
          bannerLevel: 'alert-warning',
          bannerText: 'Shelfmark no longer has a valid login in this browser, so the request could not be attributed.',
          actionState: buildOpenState('Shelfmark login has expired or is missing for this browser. Log in there first, then retry the request.')
        };
      }

      if (error.status === 403) {
        if (error.code === 'user_identity_unavailable') {
          return {
            kind: 'request_identity_failed',
            bannerLevel: 'alert-warning',
            bannerText: 'Shelfmark is signed in, but that browser session is not mapped to a requestable Shelfmark user yet.',
            actionState: buildOpenState('Shelfmark did not expose a request user identity for this browser session. Open Shelfmark directly, confirm the synced user is logged in there, and retry.')
          };
        }
        if (error.requiredMode === REQUEST_RELEASE_MODE || error.code === 'policy_requires_download') {
          return {
            kind: 'request_requires_release',
            bannerLevel: 'alert-warning',
            bannerText: 'Shelfmark policy requires a concrete release or download path for this result, so CWA cannot submit a direct book request here.',
            actionState: buildOpenState('Shelfmark policy requires a concrete release or download path for this result. Open Shelfmark to choose the release there.')
          };
        }
        return {
          kind: 'request_policy_failed',
          bannerLevel: 'alert-warning',
          bannerText: error.message || 'Shelfmark rejected the request under the current policy or browser session.',
          actionState: buildOpenState('Shelfmark rejected the request under the current policy or browser session. Open Shelfmark directly to review policy and login state.')
        };
      }

      if (error.kind === 'network') {
        return {
          kind: 'request_network_failed',
          bannerLevel: 'alert-danger',
          bannerText: 'The browser could not reach Shelfmark directly, so the request was not created here.',
          actionState: buildOpenState('The browser could not reach Shelfmark directly. This usually means the network or proxy blocked the request, or the apps are not deployed under a compatible same-origin setup.')
        };
      }

      return {
        kind: 'request_failed',
        bannerLevel: 'alert-danger',
        bannerText: error.message || 'Shelfmark request creation failed.',
        actionState: buildOpenState('Shelfmark request creation failed from this browser. Open Shelfmark directly to retry or inspect the error state.')
      };
    }

    return {
      kind: 'request_failed',
      bannerLevel: 'alert-danger',
      bannerText: 'Shelfmark request creation failed.',
      actionState: buildOpenState('Shelfmark request creation failed from this browser. Open Shelfmark directly to retry or inspect the error state.')
    };
  }

  return {
    REQUEST_MODE: REQUEST_MODE,
    REQUEST_RELEASE_MODE: REQUEST_RELEASE_MODE,
    DOWNLOAD_MODE: DOWNLOAD_MODE,
    BLOCKED_MODE: BLOCKED_MODE,
    normalizeMode: normalizeMode,
    normalizeContentType: normalizeContentType,
    normalizeSource: normalizeSource,
    normalizePreferredReleaseSettings: normalizePreferredReleaseSettings,
    isPreferredReleaseWorkflowEnabled: isPreferredReleaseWorkflowEnabled,
    resolvePreferredReleaseSource: resolvePreferredReleaseSource,
    resolveReleaseContentType: resolveReleaseContentType,
    releaseMatchesPreferredProvider: releaseMatchesPreferredProvider,
    releaseMatchesPreferredContentType: releaseMatchesPreferredContentType,
    selectPreferredRelease: selectPreferredRelease,
    buildPreferredReleaseRequestPayload: buildPreferredReleaseRequestPayload,
    buildOpenState: buildOpenState,
    buildRequestState: buildRequestState,
    buildQueuedState: buildQueuedState,
    buildCheckingState: buildCheckingState,
    createBrowserError: createBrowserError,
    resolveDefaultModeFromPolicy: resolveDefaultModeFromPolicy,
    resolveSourceModeFromPolicy: resolveSourceModeFromPolicy,
    getRequestPayloadContentType: getRequestPayloadContentType,
    getRequestPayloadSource: getRequestPayloadSource,
    getRequestPayloadLevel: getRequestPayloadLevel,
    describeRequiredMode: describeRequiredMode,
    isDirectRequestViable: isDirectRequestViable,
    resolveProbeState: resolveProbeState,
    resolveRequestOutcome: resolveRequestOutcome
  };
}));
