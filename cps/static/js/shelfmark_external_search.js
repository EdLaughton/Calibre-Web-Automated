(function () {
  'use strict';

  var flow = window.CwaShelfmarkRequestFlow || null;
  var DEFAULT_TIMEOUT_MS = 10000;
  var DETAIL_VIEW_PARAM = 'view';
  var DETAIL_VIEW_VALUE = 'modal';
  var STATUS_SETTLE_DELAY_MS = typeof window.CWA_SHELFMARK_STATUS_SETTLE_DELAY_MS === 'number'
    ? window.CWA_SHELFMARK_STATUS_SETTLE_DELAY_MS
    : 2600;
  var statusTimers = new WeakMap();
  var boundActionNodes = new WeakSet();
  var boundDetailLinks = new WeakSet();
  var activeDetailLink = null;
  var activeDetailRequest = null;

  function toArray(value) {
    return Array.prototype.slice.call(value || []);
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

  function isPlainLeftClick(event) {
    return Boolean(
      event &&
      !event.defaultPrevented &&
      event.button === 0 &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey
    );
  }

  function buildDetailModalUrl(href) {
    try {
      var detailUrl = new URL(href, window.location.href);
      detailUrl.searchParams.set(DETAIL_VIEW_PARAM, DETAIL_VIEW_VALUE);
      return detailUrl.toString();
    } catch (err) {
      var separator = href.indexOf('?') === -1 ? '?' : '&';
      return href + separator + DETAIL_VIEW_PARAM + '=' + DETAIL_VIEW_VALUE;
    }
  }

  function clearStatusTimer(node) {
    var timerId = statusTimers.get(node);
    if (timerId) {
      clearTimeout(timerId);
      statusTimers.delete(node);
    }
  }

  function scheduleStatusSettle(node, delayMs) {
    clearStatusTimer(node);
    if (delayMs <= 0) {
      node.classList.add('is-settled');
      return;
    }
    statusTimers.set(node, setTimeout(function () {
      node.classList.add('is-settled');
      statusTimers.delete(node);
    }, delayMs));
  }

  function setStatusText(statusNodes, text, level, options) {
    var settings = options || {};
    var alertLevel = level || 'alert-info';
    var persist = Object.prototype.hasOwnProperty.call(settings, 'persist')
      ? Boolean(settings.persist)
      : (alertLevel === 'alert-warning' || alertLevel === 'alert-danger');
    var settleDelayMs = typeof settings.settleDelayMs === 'number'
      ? settings.settleDelayMs
      : STATUS_SETTLE_DELAY_MS;

    (statusNodes || []).forEach(function (node) {
      clearStatusTimer(node);
      if (!text) {
        node.textContent = '';
        node.classList.remove('is-visible', 'is-settled', 'alert-info', 'alert-success', 'alert-warning', 'alert-danger');
        node.classList.add('is-hidden');
        node.setAttribute('aria-hidden', 'true');
        return;
      }
      node.classList.remove('is-hidden', 'is-settled');
      node.classList.add('is-visible');
      node.removeAttribute('aria-hidden');
      node.textContent = text;
      node.classList.remove('alert-info', 'alert-success', 'alert-warning', 'alert-danger');
      node.classList.add(alertLevel);
      if (!persist) {
        scheduleStatusSettle(node, settleDelayMs);
      }
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
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
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
      hintNode.textContent = next.hint || '';
      hintNode.classList.toggle('is-hidden', !next.hint);
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
    if (!flow) {
      return Object.assign(new Error(message), options || {});
    }
    return flow.createBrowserError(message, options || {});
  }

  function fetchJson(url, options, timeoutMs) {
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timeoutId = controller && timeoutMs && timeoutMs > 0
      ? setTimeout(function () { controller.abort(); }, timeoutMs)
      : null;

    return fetch(url, {
      ...options,
      credentials: 'include',
      signal: controller ? controller.signal : undefined,
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

  function applyProbeOutcome(actions, outcome, statusNodes) {
    applyActionState(actions, outcome.actionState);
    setStatusText(statusNodes, outcome.bannerText, outcome.bannerLevel);
  }

  async function attachProbe(actions, baseUrl, statusNodes) {
    var currentOrigin = window.location.origin;
    var probeOutcome;

    if (!flow.isDirectRequestViable(baseUrl, currentOrigin)) {
      probeOutcome = flow.resolveProbeState({
        baseUrl: baseUrl,
        currentOrigin: currentOrigin
      });
      applyProbeOutcome(actions, probeOutcome, statusNodes);
      return;
    }

    try {
      var authPayload = await fetchJson(stripTrailingSlash(baseUrl) + '/api/auth/check', {}, DEFAULT_TIMEOUT_MS);
      if (!authPayload || !authPayload.authenticated) {
        probeOutcome = flow.resolveProbeState({
          baseUrl: baseUrl,
          currentOrigin: currentOrigin,
          authPayload: authPayload
        });
        applyProbeOutcome(actions, probeOutcome, statusNodes);
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
        setStatusText(statusNodes, '');
        return;
      }

      if (perActionSummary.requestableCount > 0) {
        setStatusText(statusNodes, '');
        return;
      }

      setStatusText(
        statusNodes,
        'Open in Shelfmark is required for the visible results.',
        'alert-warning'
      );
    } catch (error) {
      probeOutcome = flow.resolveProbeState({
        baseUrl: baseUrl,
        currentOrigin: currentOrigin,
        error: error
      });
      applyProbeOutcome(actions, probeOutcome, statusNodes);
    }
  }

  function attachRequestHandler(node, payload, openUrl, statusNodes) {
    if (boundActionNodes.has(node)) {
      return;
    }
    boundActionNodes.add(node);

    node.addEventListener('click', async function (event) {
      if (flow.normalizeMode(node.dataset.mode) !== 'request') {
        return;
      }

      event.preventDefault();
      setPending(node, true);
      setStatusText(statusNodes, 'Creating request in Shelfmark…', 'alert-info', { persist: true });

      try {
        await fetchJson(stripTrailingSlash(node.dataset.baseUrl) + '/api/requests', {
          method: 'POST',
          body: JSON.stringify(payload)
        }, DEFAULT_TIMEOUT_MS);

        var successOutcome = flow.resolveRequestOutcome({ success: true });
        updateActionNode(node, successOutcome.actionState);
        node.setAttribute('href', openUrl);
        setStatusText(statusNodes, successOutcome.bannerText, successOutcome.bannerLevel);
      } catch (error) {
        var failureOutcome = flow.resolveRequestOutcome({ success: false, error: error });
        updateActionNode(node, failureOutcome.actionState);
        node.setAttribute('href', openUrl);
        setStatusText(statusNodes, failureOutcome.bannerText, failureOutcome.bannerLevel);
      } finally {
        setPending(node, false);
      }
    });
  }

  function getModalJquery(modalNode) {
    if (!modalNode || !window.jQuery || typeof window.jQuery !== 'function') {
      return null;
    }
    return window.jQuery(modalNode);
  }

  function showModal(modalNode) {
    var modalApi = getModalJquery(modalNode);
    if (modalApi && typeof modalApi.modal === 'function') {
      modalApi.modal('show');
      return;
    }
    modalNode.style.display = 'block';
    modalNode.classList.add('in');
    if (document.body) {
      document.body.classList.add('modal-open');
    }
  }

  function hideModal(modalNode) {
    var modalApi = getModalJquery(modalNode);
    if (modalApi && typeof modalApi.modal === 'function') {
      modalApi.modal('hide');
      return;
    }
    modalNode.style.display = 'none';
    modalNode.classList.remove('in');
    if (document.body) {
      document.body.classList.remove('modal-open');
    }
  }

  function registerModalHiddenHandler(modalNode, handler) {
    if (!modalNode || modalNode.dataset.shelfmarkModalBound === '1') {
      return;
    }
    modalNode.dataset.shelfmarkModalBound = '1';
    var modalApi = getModalJquery(modalNode);
    if (modalApi && typeof modalApi.on === 'function') {
      modalApi.on('hidden.bs.modal', handler);
      return;
    }
    modalNode.addEventListener('cwa:modal-hidden', handler);
  }

  function abortActiveDetailRequest() {
    if (activeDetailRequest && typeof activeDetailRequest.abort === 'function') {
      activeDetailRequest.abort();
    }
    activeDetailRequest = null;
  }

  function resetDetailModal(modalBody, modalTitle) {
    abortActiveDetailRequest();
    if (modalBody) {
      modalBody.innerHTML = '<div class="shelfmark-detail-modal__loading js-shelfmark-detail-modal-loading is-hidden">Loading Shelfmark details…</div>';
      modalBody.setAttribute('aria-busy', 'false');
    }
    if (modalTitle) {
      modalTitle.textContent = 'Shelfmark Details';
    }
    if (activeDetailLink && typeof activeDetailLink.focus === 'function') {
      activeDetailLink.focus();
    }
    activeDetailLink = null;
  }

  function initActions(root) {
    if (!flow) {
      return;
    }

    var scope = root || document;
    var actions = toArray(scope.querySelectorAll('.js-shelfmark-action'));
    var statusNodes = toArray(scope.querySelectorAll('.js-shelfmark-request-status'));

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
        attachRequestHandler(node, payload, node.dataset.openUrl || node.getAttribute('href'), statusNodes);
      }
    });

    attachProbe(actions, baseUrl, statusNodes);
  }

  function initDetailModal(root) {
    var scope = root || document;
    var detailLinks = toArray(scope.querySelectorAll('.js-shelfmark-detail-link'));
    var modalNode = typeof document.getElementById === 'function'
      ? document.getElementById('shelfmarkDetailModal')
      : null;
    var modalBody = modalNode ? modalNode.querySelector('.js-shelfmark-detail-modal-body') : null;
    var modalTitle = modalNode ? modalNode.querySelector('.shelfmark-detail-modal__title') : null;

    if (!detailLinks.length || !modalNode || !modalBody || !modalTitle) {
      return;
    }

    registerModalHiddenHandler(modalNode, function () {
      resetDetailModal(modalBody, modalTitle);
    });

    detailLinks.forEach(function (link) {
      if (boundDetailLinks.has(link)) {
        return;
      }
      boundDetailLinks.add(link);

      link.addEventListener('click', function (event) {
        if (!isPlainLeftClick(event)) {
          return;
        }

        event.preventDefault();
        activeDetailLink = link;
        abortActiveDetailRequest();
        modalTitle.textContent = link.dataset.detailTitle || 'Shelfmark Details';
        modalBody.innerHTML = '<div class="shelfmark-detail-modal__loading js-shelfmark-detail-modal-loading">Loading Shelfmark details…</div>';
        modalBody.setAttribute('aria-busy', 'true');
        showModal(modalNode);

        var controller = typeof AbortController === 'function' ? new AbortController() : null;
        activeDetailRequest = controller;

        fetch(buildDetailModalUrl(link.href), {
          credentials: 'same-origin',
          headers: {
            'Accept': 'text/html',
            'X-Requested-With': 'XMLHttpRequest'
          },
          signal: controller ? controller.signal : undefined
        }).then(function (response) {
          if (!response.ok) {
            throw new Error('Shelfmark detail modal request failed.');
          }
          return response.text();
        }).then(function (html) {
          if (controller && controller !== activeDetailRequest) {
            return;
          }
          modalBody.innerHTML = html;
          modalBody.setAttribute('aria-busy', 'false');
          var titleSource = modalBody.querySelector('[data-detail-title]');
          if (titleSource && titleSource.dataset && titleSource.dataset.detailTitle) {
            modalTitle.textContent = titleSource.dataset.detailTitle;
          }
          initActions(modalBody);
        }).catch(function (error) {
          if (error && error.name === 'AbortError') {
            return;
          }
          hideModal(modalNode);
          window.location.assign(link.href);
        }).finally(function () {
          if (!controller || activeDetailRequest === controller) {
            activeDetailRequest = null;
          }
        });
      });
    });
  }

  function init(root) {
    initActions(root);
    initDetailModal(root);
  }

  window.CwaShelfmarkExternalSearch = {
    init: init
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
