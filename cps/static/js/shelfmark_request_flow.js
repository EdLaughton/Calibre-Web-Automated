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

  function normalizeMode(value) {
    return (value || '').toString().trim().toLowerCase();
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
      hint: hint,
      buttonClass: 'btn-primary',
      iconClass: 'glyphicon glyphicon-send'
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
        bannerText: 'Direct Request in Shelfmark needs a same-origin or reverse-proxied Shelfmark deployment. Open in Shelfmark remains the safe fallback for this setup.',
        actionState: buildOpenState('This CWA page and Shelfmark are on different browser origins. Direct browser requests are not reliable across origins, so opening Shelfmark is the safe fallback.')
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

    var defaults = policyPayload.defaults || {};
    var ebookMode = normalizeMode(defaults.ebook);
    if (ebookMode !== REQUEST_MODE) {
      return {
        kind: 'policy_blocked',
        bannerLevel: 'alert-warning',
        bannerText: 'Shelfmark is signed in, but the current policy does not allow direct book-level requests here.',
        actionState: buildOpenState('Shelfmark is signed in, but the current policy does not allow direct book-level requests for ebook results in this browser flow.')
      };
    }

    return {
        kind: 'requestable',
        bannerLevel: 'alert-success',
        bannerText: 'Shelfmark session detected. Direct requests will be attributed in Shelfmark as the current Shelfmark user.',
        actionState: buildRequestState('This browser already has a valid Shelfmark session and the current Shelfmark policy allows direct book-level requests.')
    };
  }

  function resolveRequestOutcome(options) {
    if (options && options.success) {
      return {
        kind: 'request_created',
        bannerLevel: 'alert-success',
        bannerText: 'Request created in Shelfmark as your current Shelfmark user.',
        actionState: buildOpenState(
          'The request was created in Shelfmark. Open Shelfmark to review request status.',
          'Requested in Shelfmark',
          'btn-success',
          'glyphicon glyphicon-ok'
        )
      };
    }

    var error = options && options.error ? options.error : null;
    if (error) {
      if (error.kind === 'timeout') {
        return {
          kind: 'request_timeout',
          bannerLevel: 'alert-danger',
          bannerText: 'Shelfmark did not confirm the request before the browser timed out.',
          actionState: buildOpenState('Shelfmark did not confirm the request before the browser timed out. Open Shelfmark to retry or verify whether the request was created.')
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
    normalizeMode: normalizeMode,
    buildOpenState: buildOpenState,
    buildRequestState: buildRequestState,
    createBrowserError: createBrowserError,
    isDirectRequestViable: isDirectRequestViable,
    resolveProbeState: resolveProbeState,
    resolveRequestOutcome: resolveRequestOutcome
  };
}));
