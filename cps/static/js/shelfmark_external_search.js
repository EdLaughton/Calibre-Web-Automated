(function () {
  'use strict';

  var flow = window.CwaShelfmarkRequestFlow;
  var DEFAULT_TIMEOUT_MS = 10000;

  if (!flow) {
    return;
  }

  function parseJson(value) {
    if (!value) {
      return null;
    }
    try {
      return JSON.parse(value);
    } catch (err) {
      return null;
    }
  }

  function stripTrailingSlash(value) {
    return (value || '').replace(/\/+$/, '');
  }

  function setStatusText(text, level) {
    var nodes = document.querySelectorAll('.js-shelfmark-request-status');
    nodes.forEach(function (node) {
      node.textContent = text;
      node.classList.remove('alert-info', 'alert-success', 'alert-warning', 'alert-danger');
      node.classList.add(level || 'alert-info');
    });
  }

  function findHintNode(node) {
    if (!node || !node.parentNode || !node.parentNode.parentNode) {
      return null;
    }
    return node.parentNode.parentNode.querySelector('.js-shelfmark-action-hint');
  }

  function applyButtonClass(node, buttonClass) {
    node.classList.remove('btn-default', 'btn-primary', 'btn-success', 'btn-info', 'btn-warning', 'btn-danger');
    if (buttonClass) {
      node.classList.add(buttonClass);
    }
  }

  function updateActionNode(node, next) {
    var hintNode = findHintNode(node);
    var iconNode = node.querySelector('.js-shelfmark-action-icon');
    var labelNode = node.querySelector('.js-shelfmark-action-label');

    node.dataset.mode = next.mode;
    applyButtonClass(node, next.buttonClass);

    if (iconNode) {
      iconNode.className = (next.iconClass || '') + ' js-shelfmark-action-icon';
    }
    if (labelNode) {
      labelNode.textContent = next.label;
    } else {
      node.textContent = next.label;
    }
    if (hintNode) {
      hintNode.textContent = next.hint;
    }
  }

  function setPending(node, isPending) {
    var iconNode = node.querySelector('.js-shelfmark-action-icon');
    var labelNode = node.querySelector('.js-shelfmark-action-label');

    if (isPending) {
      node.classList.add('disabled');
      node.setAttribute('aria-disabled', 'true');
      if (iconNode) {
        iconNode.className = 'glyphicon glyphicon-refresh js-shelfmark-action-icon';
      }
      if (labelNode) {
        labelNode.textContent = 'Requesting...';
      } else {
        node.textContent = 'Requesting...';
      }
      return;
    }
    node.classList.remove('disabled');
    node.removeAttribute('aria-disabled');
  }

  function createRequestError(message, options) {
    return flow.createBrowserError(message, options || {});
  }

  function fetchJson(url, options, timeoutMs) {
    var controller = new AbortController();
    var timeoutId = timeoutMs && timeoutMs > 0
      ? setTimeout(function () { controller.abort(); }, timeoutMs)
      : null;

    return fetch(url, {
      ...options,
      credentials: 'include',
      signal: controller.signal,
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(options && options.headers ? options.headers : {})
      }
    }).then(async function (response) {
      var payload = null;
      try {
        payload = await response.json();
      } catch (err) {
        payload = null;
      }

      if (!response.ok) {
        var message = response.status + ' ' + response.statusText;
        if (payload && typeof payload === 'object') {
          if (typeof payload.message === 'string' && payload.message) {
            message = payload.message;
          } else if (typeof payload.error === 'string' && payload.error) {
            message = payload.error;
          }
        }

        throw createRequestError(message, {
          kind: response.status === 401 ? 'auth' : 'http',
          status: response.status,
          payload: payload,
          code: payload && typeof payload.code === 'string' ? payload.code : null,
          requiredMode: payload && typeof payload.required_mode === 'string' ? payload.required_mode : null
        });
      }

      return payload || {};
    }).catch(function (error) {
      if (error && error.name === 'AbortError') {
        throw createRequestError('Request timed out while contacting Shelfmark.', { kind: 'timeout' });
      }
      if (error && error.isShelfmarkBrowserError) {
        throw error;
      }
      throw createRequestError(
        'The browser could not reach Shelfmark directly. This usually means the network/proxy blocked the request, or the apps are not on a compatible same origin.',
        { kind: 'network' }
      );
    }).finally(function () {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    });
  }

  function applyActionState(actions, nextState) {
    actions.forEach(function (node) {
      if (!parseJson(node.dataset.requestPayload)) {
        return;
      }
      updateActionNode(node, nextState);
    });
  }

  function applyPerActionProbeStates(actions, probeOptions) {
    var requestableCount = 0;
    var blockedCount = 0;
    var payloadCount = 0;

    actions.forEach(function (node) {
      var payload = parseJson(node.dataset.requestPayload);
      if (!payload) {
        return;
      }
      payloadCount += 1;
      var outcome = flow.resolveProbeState({
        baseUrl: probeOptions.baseUrl,
        currentOrigin: probeOptions.currentOrigin,
        authPayload: probeOptions.authPayload,
        policyPayload: probeOptions.policyPayload,
        requestPayload: payload
      });
      updateActionNode(node, outcome.actionState);
      node.dataset.probeKind = outcome.kind;
      if (outcome.actionState.mode === 'request') {
        requestableCount += 1;
      } else {
        blockedCount += 1;
      }
    });

    return {
      payloadCount: payloadCount,
      requestableCount: requestableCount,
      blockedCount: blockedCount
    };
  }

  function applyProbeOutcome(actions, outcome) {
    applyActionState(actions, outcome.actionState);
    setStatusText(outcome.bannerText, outcome.bannerLevel);
  }

  async function attachProbe(actions, baseUrl) {
    var currentOrigin = window.location.origin;
    var probeOutcome;

    if (!flow.isDirectRequestViable(baseUrl, currentOrigin)) {
      probeOutcome = flow.resolveProbeState({
        baseUrl: baseUrl,
        currentOrigin: currentOrigin
      });
      applyProbeOutcome(actions, probeOutcome);
      return;
    }

    setStatusText('Checking your Shelfmark session for direct request availability…', 'alert-info');

    try {
      var authPayload = await fetchJson(stripTrailingSlash(baseUrl) + '/api/auth/check', {}, DEFAULT_TIMEOUT_MS);
      if (!authPayload || !authPayload.authenticated) {
        probeOutcome = flow.resolveProbeState({
          baseUrl: baseUrl,
          currentOrigin: currentOrigin,
          authPayload: authPayload
        });
        applyProbeOutcome(actions, probeOutcome);
        return;
      }

      var policyPayload = await fetchJson(stripTrailingSlash(baseUrl) + '/api/request-policy', {}, DEFAULT_TIMEOUT_MS);
      probeOutcome = flow.resolveProbeState({
        baseUrl: baseUrl,
        currentOrigin: currentOrigin,
        authPayload: authPayload,
        policyPayload: policyPayload
      });
      var perActionSummary = applyPerActionProbeStates(actions, {
        baseUrl: baseUrl,
        currentOrigin: currentOrigin,
        authPayload: authPayload,
        policyPayload: policyPayload
      });

      if (!perActionSummary.payloadCount) {
        setStatusText(
          'Shelfmark session detected. These results can be opened directly in Shelfmark, but none of them expose enough exact metadata for a direct request here.',
          'alert-info'
        );
        return;
      }

      if (perActionSummary.requestableCount > 0 && perActionSummary.blockedCount > 0) {
        setStatusText(
          'Shelfmark session detected. Request buttons are enabled for requestable rows, and other rows still open in Shelfmark when policy or metadata requires it.',
          'alert-success'
        );
        return;
      }

      if (perActionSummary.requestableCount > 0) {
        setStatusText(probeOutcome.bannerText, probeOutcome.bannerLevel);
        return;
      }

      setStatusText(
        'Shelfmark session detected, but these results still need Open in Shelfmark because the current policy or metadata does not allow direct book-level requests here.',
        'alert-warning'
      );
    } catch (error) {
      probeOutcome = flow.resolveProbeState({
        baseUrl: baseUrl,
        currentOrigin: currentOrigin,
        error: error
      });
      applyProbeOutcome(actions, probeOutcome);
    }
  }

  function attachRequestHandler(node, payload, openUrl) {
    node.addEventListener('click', async function (event) {
      if (flow.normalizeMode(node.dataset.mode) !== 'request') {
        return;
      }

      event.preventDefault();
      setPending(node, true);
      setStatusText('Creating request in Shelfmark…', 'alert-info');

      try {
        await fetchJson(stripTrailingSlash(node.dataset.baseUrl) + '/api/requests', {
          method: 'POST',
          body: JSON.stringify(payload)
        }, DEFAULT_TIMEOUT_MS);

        var successOutcome = flow.resolveRequestOutcome({ success: true });
        updateActionNode(node, successOutcome.actionState);
        node.setAttribute('href', openUrl);
        setStatusText(successOutcome.bannerText, successOutcome.bannerLevel);
      } catch (error) {
        var failureOutcome = flow.resolveRequestOutcome({ success: false, error: error });
        updateActionNode(node, failureOutcome.actionState);
        node.setAttribute('href', openUrl);
        setStatusText(failureOutcome.bannerText, failureOutcome.bannerLevel);
      } finally {
        setPending(node, false);
      }
    });
  }

  function init() {
    var actions = Array.prototype.slice.call(document.querySelectorAll('.js-shelfmark-action'));
    var statusNodes = Array.prototype.slice.call(document.querySelectorAll('.js-shelfmark-request-status'));

    if (!actions.length && !statusNodes.length) {
      return;
    }

    var baseUrl = '';
    if (actions.length) {
      baseUrl = actions[0].dataset.baseUrl || '';
    }
    if (!baseUrl && statusNodes.length) {
      baseUrl = statusNodes[0].dataset.baseUrl || '';
    }
    if (!baseUrl) {
      return;
    }

    actions.forEach(function (node) {
      var payload = parseJson(node.dataset.requestPayload);
      if (payload) {
        attachRequestHandler(node, payload, node.dataset.openUrl || node.getAttribute('href'));
      }
    });

    attachProbe(actions, baseUrl);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
