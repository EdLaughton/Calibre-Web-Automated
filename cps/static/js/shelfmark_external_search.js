(function () {
  'use strict';

  var DEFAULT_TIMEOUT_MS = 10000;
  var DETAIL_VIEW_PARAM = 'view';
  var DETAIL_VIEW_VALUE = 'modal';
  var DETAIL_STATE_PROVIDER_PARAM = 'shelfmark_detail_provider';
  var DETAIL_STATE_ID_PARAM = 'shelfmark_detail_id';
  var DETAIL_HTML_CACHE_TTL_MS = 300000;
  var DETAIL_HTML_CACHE_MAX_ENTRIES = 64;
  var ROW_ENRICH_TIMEOUT_MS = 12000;
  var ROW_ENRICH_MAX_CONCURRENCY = 2;
  var ROW_ENRICH_ROOT_MARGIN = '180px 0px';
  var TOP_UP_TIMEOUT_MS = 12000;
  var TOP_UP_MAX_PAGES = 3;
  var ACTIVITY_SNAPSHOT_TTL_MS = 30000;
  var STATUS_SETTLE_DELAY_MS = typeof window.CWA_SHELFMARK_STATUS_SETTLE_DELAY_MS === 'number'
    ? window.CWA_SHELFMARK_STATUS_SETTLE_DELAY_MS
    : 2600;
  var STATUS_CHIP_CLASSES = [
    'shelfmark-status-chip--available',
    'shelfmark-status-chip--requested',
    'shelfmark-status-chip--queue',
    'shelfmark-status-chip--downloaded',
    'shelfmark-status-chip--imported',
    'shelfmark-status-chip--failed'
  ];
  var statusTimers = new WeakMap();
  var boundActionNodes = new WeakSet();
  var boundDetailLinks = new WeakSet();
  var boundBatchToolbars = new WeakSet();
  var boundProgressiveRows = new WeakSet();
  var activeDetailLink = null;
  var activeDetailRequest = null;
  var detailHtmlCache = new Map();
  var activitySnapshotCache = new Map();
  var detailHistoryBound = false;
  var detailModalState = null;
  var rowEnrichmentObserver = null;
  var rowEnrichmentQueue = [];
  var rowEnrichmentInFlight = 0;
  var topUpInFlight = false;
  var topUpPagesFetched = 0;

  function toArray(value) {
    return Array.prototype.slice.call(value || []);
  }

  function getFlow() {
    return typeof window !== 'undefined' ? (window.CwaShelfmarkRequestFlow || null) : null;
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

  function toOptionalNumber(value) {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    var normalized = Number(value);
    return Number.isFinite(normalized) ? normalized : null;
  }

  function pruneTimedCache(cache, maxEntries, ttlMs) {
    var now = Date.now();
    Array.from(cache.entries()).forEach(function (entry) {
      var key = entry[0];
      var value = entry[1];
      if (!value || typeof value.fetchedAt !== 'number' || now - value.fetchedAt >= ttlMs) {
        cache.delete(key);
      }
    });
    while (cache.size > maxEntries) {
      cache.delete(cache.keys().next().value);
    }
  }

  function getDetailHtmlCacheKey(provider, providerId) {
    var normalizedProvider = toOptionalText(provider);
    var normalizedProviderId = toOptionalText(providerId);
    if (!normalizedProvider || !normalizedProviderId) {
      return '';
    }
    return normalizedProvider + '::' + normalizedProviderId;
  }

  function getCachedDetailHtml(provider, providerId) {
    var cacheKey = getDetailHtmlCacheKey(provider, providerId);
    if (!cacheKey) {
      return '';
    }
    pruneTimedCache(detailHtmlCache, DETAIL_HTML_CACHE_MAX_ENTRIES, DETAIL_HTML_CACHE_TTL_MS);
    var cached = detailHtmlCache.get(cacheKey);
    if (!cached || typeof cached.html !== 'string') {
      return '';
    }
    detailHtmlCache.delete(cacheKey);
    detailHtmlCache.set(cacheKey, cached);
    return cached.html;
  }

  function rememberDetailHtml(provider, providerId, html) {
    var cacheKey = getDetailHtmlCacheKey(provider, providerId);
    if (!cacheKey || typeof html !== 'string' || !html) {
      return;
    }
    detailHtmlCache.set(cacheKey, {
      fetchedAt: Date.now(),
      html: html
    });
    pruneTimedCache(detailHtmlCache, DETAIL_HTML_CACHE_MAX_ENTRIES, DETAIL_HTML_CACHE_TTL_MS);
  }

  function stripTrailingSlash(value) {
    return (value || '').replace(/\/+$/, '');
  }

  function toOptionalText(value) {
    return typeof value === 'string' && value.trim() ? value.trim() : '';
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

  function buildUrl(href) {
    try {
      return new URL(href, window.location.href);
    } catch (err) {
      return null;
    }
  }

  function clearDetailStateParams(url) {
    if (!url || !url.searchParams) {
      return;
    }
    url.searchParams.delete(DETAIL_STATE_PROVIDER_PARAM);
    url.searchParams.delete(DETAIL_STATE_ID_PARAM);
  }

  function buildSearchStateUrl(href) {
    var url = buildUrl(href || window.location.href);
    if (!url) {
      return href || window.location.href;
    }
    clearDetailStateParams(url);
    return url.toString();
  }

  function buildSearchStateUrlWithDetail(searchStateUrl, provider, providerId) {
    var url = buildUrl(searchStateUrl || window.location.href);
    if (!url) {
      return searchStateUrl || window.location.href;
    }
    clearDetailStateParams(url);
    if (provider) {
      url.searchParams.set(DETAIL_STATE_PROVIDER_PARAM, provider);
    }
    if (providerId) {
      url.searchParams.set(DETAIL_STATE_ID_PARAM, providerId);
    }
    return url.toString();
  }

  function parseDetailState(href) {
    var url = buildUrl(href || window.location.href);
    if (!url) {
      return { provider: '', providerId: '' };
    }
    return {
      provider: toOptionalText(url.searchParams.get(DETAIL_STATE_PROVIDER_PARAM)),
      providerId: toOptionalText(url.searchParams.get(DETAIL_STATE_ID_PARAM))
    };
  }

  function currentUrlHasDetailState() {
    var state = parseDetailState(window.location.href);
    return Boolean(state.provider && state.providerId);
  }

  function emitCustomEvent(node, name) {
    if (!node || !name) {
      return;
    }
    if (typeof node.dispatchEvent === 'function' && typeof window.Event === 'function') {
      try {
        node.dispatchEvent(new window.Event(name));
        return;
      } catch (err) {
        // Fall through to simple listener invocation.
      }
    }
    if (!node.listeners || !Array.isArray(node.listeners[name])) {
      return;
    }
    node.listeners[name].forEach(function (handler) {
      handler();
    });
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
    var requestFlow = getFlow();
    if (!requestFlow) {
      return Object.assign(new Error(message), options || {});
    }
    return requestFlow.createBrowserError(message, options || {});
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

  function getActivitySnapshotCacheKey(baseUrl) {
    return stripTrailingSlash(baseUrl || '');
  }

  function buildRequestPayloadMatchKey(requestPayload) {
    var bookData = requestPayload && requestPayload.book_data ? requestPayload.book_data : {};
    return buildStatusMatchKey(bookData.provider || 'hardcover', bookData.provider_id);
  }

  function invalidateActivitySnapshot(baseUrl) {
    var cacheKey = getActivitySnapshotCacheKey(baseUrl);
    if (!cacheKey) {
      return;
    }
    activitySnapshotCache.delete(cacheKey);
  }

  function fetchActivitySnapshot(baseUrl) {
    var cacheKey = getActivitySnapshotCacheKey(baseUrl);
    var now = Date.now();
    var cached = activitySnapshotCache.get(cacheKey);

    if (cached && cached.data && now - cached.fetchedAt < ACTIVITY_SNAPSHOT_TTL_MS) {
      return Promise.resolve(cached.data);
    }
    if (cached && cached.promise) {
      return cached.promise;
    }

    var promise = fetchJson(cacheKey + '/api/activity/snapshot', {}, DEFAULT_TIMEOUT_MS)
      .then(function (payload) {
        var data = payload && typeof payload === 'object' ? payload : {};
        activitySnapshotCache.set(cacheKey, {
          fetchedAt: Date.now(),
          data: data,
          promise: null
        });
        return data;
      })
      .catch(function (error) {
        activitySnapshotCache.delete(cacheKey);
        throw error;
      });

    activitySnapshotCache.set(cacheKey, {
      fetchedAt: cached && cached.fetchedAt ? cached.fetchedAt : 0,
      data: cached && cached.data ? cached.data : null,
      promise: promise
    });

    return promise;
  }

  function scopeHasClass(scope, className) {
    return Boolean(scope && scope.classList && scope.classList.contains(className));
  }

  function getScopedClassNodes(scope, className) {
    var selector = '.' + className;
    var matches = toArray((scope || document).querySelectorAll(selector));
    if (scopeHasClass(scope, className)) {
      matches.unshift(scope);
    }
    return matches;
  }

  function getStatusTargetNodes(scope) {
    return getScopedClassNodes(scope, 'js-shelfmark-status-target').filter(function (target) {
      return !isFilterHiddenRow(target);
    });
  }

  function isFilterHiddenRow(row) {
    return Boolean(row && row.classList && row.classList.contains('is-shelfmark-filter-hidden'));
  }

  function buildStatusMatchKey(provider, providerId) {
    var normalizedProvider = toOptionalText(provider).toLowerCase();
    var normalizedProviderId = toOptionalText(providerId);
    if (!normalizedProvider || !normalizedProviderId) {
      return '';
    }
    return normalizedProvider + ':' + normalizedProviderId;
  }

  function getTargetMatchKey(target) {
    if (!target || !target.dataset) {
      return '';
    }
    return buildStatusMatchKey(target.dataset.statusProvider, target.dataset.statusProviderId);
  }

  function parseStatusRecordBookData(record) {
    if (!record || typeof record !== 'object' || !record.book_data || typeof record.book_data !== 'object') {
      return {};
    }
    return record.book_data;
  }

  function buildRequestStatusIndex(requests) {
    var index = new Map();
    (Array.isArray(requests) ? requests : []).forEach(function (record) {
      var bookData = parseStatusRecordBookData(record);
      var matchKey = buildStatusMatchKey(bookData.provider || 'hardcover', bookData.provider_id);
      if (!matchKey || index.has(matchKey)) {
        return;
      }
      index.set(matchKey, record);
    });
    return index;
  }

  function selectStatusTimestamp(record) {
    return toOptionalText(
      record && (
        record.delivery_updated_at
        || record.reviewed_at
        || record.updated_at
        || record.created_at
      )
    );
  }

  function formatStatusTimestamp(value) {
    var rawValue = toOptionalText(value);
    if (!rawValue) {
      return '';
    }
    var parsed = Date.parse(rawValue);
    if (!Number.isFinite(parsed)) {
      return rawValue;
    }
    try {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short'
      }).format(new Date(parsed));
    } catch (err) {
      return new Date(parsed).toLocaleString();
    }
  }

  function buildWorkflowState(config) {
    return {
      key: config.key,
      label: config.label,
      chipClass: config.chipClass,
      timestamp: config.timestamp || '',
      message: config.message || ''
    };
  }

  function mapRequestRecordToWorkflowState(record) {
    if (!record || typeof record !== 'object') {
      return null;
    }

    var requestStatus = toOptionalText(record.status).toLowerCase();
    var deliveryState = toOptionalText(record.delivery_state).toLowerCase();
    var timestamp = selectStatusTimestamp(record);
    var failureReason = toOptionalText(record.last_failure_reason) || toOptionalText(record.admin_note);

    if (requestStatus === 'cancelled') {
      return null;
    }

    if (requestStatus === 'rejected') {
      return buildWorkflowState({
        key: 'failed',
        label: 'Failed',
        chipClass: 'shelfmark-status-chip--failed',
        timestamp: timestamp,
        message: failureReason || 'Request was rejected in Shelfmark.'
      });
    }

    if (requestStatus === 'pending') {
      if (failureReason) {
        return buildWorkflowState({
          key: 'failed',
          label: 'Failed',
          chipClass: 'shelfmark-status-chip--failed',
          timestamp: timestamp,
          message: failureReason
        });
      }
      return buildWorkflowState({
        key: 'requested',
        label: 'Requested',
        chipClass: 'shelfmark-status-chip--requested',
        timestamp: timestamp
      });
    }

    if (requestStatus === 'fulfilled') {
      if (deliveryState === 'complete') {
        return buildWorkflowState({
          key: 'downloaded',
          label: 'Downloaded',
          chipClass: 'shelfmark-status-chip--downloaded',
          timestamp: timestamp
        });
      }
      if (deliveryState === 'error' || deliveryState === 'cancelled') {
        return buildWorkflowState({
          key: 'failed',
          label: 'Failed',
          chipClass: 'shelfmark-status-chip--failed',
          timestamp: timestamp,
          message: failureReason || 'Delivery failed in Shelfmark.'
        });
      }
      if (deliveryState === 'queued' || deliveryState === 'resolving' || deliveryState === 'locating' || deliveryState === 'downloading') {
        return buildWorkflowState({
          key: 'queue',
          label: 'In queue',
          chipClass: 'shelfmark-status-chip--queue',
          timestamp: timestamp
        });
      }
      return buildWorkflowState({
        key: 'requested',
        label: 'Requested',
        chipClass: 'shelfmark-status-chip--requested',
        timestamp: timestamp
      });
    }

    return null;
  }

  function buildAvailableWorkflowState() {
    return buildWorkflowState({
      key: 'available',
      label: 'Available to request',
      chipClass: 'shelfmark-status-chip--available'
    });
  }

  function buildImportedWorkflowState() {
    return buildWorkflowState({
      key: 'imported',
      label: 'In library',
      chipClass: 'shelfmark-status-chip--imported'
    });
  }

  function shouldHideAvailableWorkflowState(target, workflowState) {
    if (!target || !workflowState || workflowState.key !== 'available') {
      return false;
    }
    var actionNode = target.querySelector('.js-shelfmark-action');
    var requestFlow = getFlow();
    return Boolean(actionNode && requestFlow && requestFlow.normalizeMode(actionNode.dataset.mode) === 'request');
  }

  function setWorkflowState(target, workflowState) {
    if (!target) {
      return;
    }

    var chipNode = target.querySelector('.js-shelfmark-status-chip');
    var timestampNode = target.querySelector('.js-shelfmark-status-timestamp');
    var messageNode = target.querySelector('.js-shelfmark-status-message');
    var detailStatusNode = target.querySelector('.shelfmark-detail-status');

    if (!chipNode) {
      return;
    }

    var statusKey = workflowState ? workflowState.key : '';
    var isHandled = statusKey === 'requested' || statusKey === 'queue' || statusKey === 'downloaded' || statusKey === 'imported';
    target.classList.toggle('is-shelfmark-handled', isHandled);

    STATUS_CHIP_CLASSES.forEach(function (className) {
      chipNode.classList.remove(className);
    });

    if (!workflowState) {
      chipNode.classList.add('is-hidden');
      chipNode.textContent = '';
      chipNode.dataset.statusKey = '';
      if (detailStatusNode) {
        detailStatusNode.classList.add('is-hidden');
      }
      if (timestampNode) {
        timestampNode.textContent = '';
        timestampNode.classList.add('is-hidden');
      }
      if (messageNode) {
        messageNode.textContent = '';
        messageNode.classList.add('is-hidden');
      }
      return;
    }

    var shouldHide = shouldHideAvailableWorkflowState(target, workflowState);

    chipNode.classList.toggle('is-hidden', shouldHide);
    chipNode.textContent = workflowState.label;
    chipNode.dataset.statusKey = workflowState.key;
    if (workflowState.chipClass) {
      chipNode.classList.add(workflowState.chipClass);
    }
    if (detailStatusNode) {
      detailStatusNode.classList.toggle('is-hidden', shouldHide);
    }

    if (timestampNode) {
      var formattedTimestamp = formatStatusTimestamp(workflowState.timestamp);
      if (formattedTimestamp && !shouldHide) {
        timestampNode.textContent = 'Updated ' + formattedTimestamp;
        timestampNode.classList.remove('is-hidden');
      } else {
        timestampNode.textContent = '';
        timestampNode.classList.add('is-hidden');
      }
    }

    if (messageNode) {
      if (workflowState.message && !shouldHide) {
        messageNode.textContent = workflowState.message;
        messageNode.classList.remove('is-hidden');
      } else {
        messageNode.textContent = '';
        messageNode.classList.add('is-hidden');
      }
    }
  }

  function getWorkflowStatusKey(target) {
    if (!target) {
      return '';
    }
    var chipNode = target.querySelector('.js-shelfmark-status-chip');
    if (!chipNode || !chipNode.dataset) {
      return '';
    }
    return toOptionalText(chipNode.dataset.statusKey).toLowerCase();
  }

  function resolveWorkflowStateForTarget(target, requestIndex) {
    if (!target || !target.dataset) {
      return null;
    }

    if (target.dataset.statusInLibrary === '1') {
      return buildImportedWorkflowState();
    }

    var matchKey = getTargetMatchKey(target);
    if (!matchKey) {
      return null;
    }

    var matchedRequest = requestIndex ? requestIndex.get(matchKey) : null;
    var mappedState = mapRequestRecordToWorkflowState(matchedRequest);
    if (mappedState) {
      return mappedState;
    }

    var actionNode = target.querySelector('.js-shelfmark-action');
    var requestFlow = getFlow();
    if (actionNode && requestFlow && requestFlow.normalizeMode(actionNode.dataset.mode) === 'request') {
      return buildAvailableWorkflowState();
    }

    return null;
  }

  function updateStatusTargets(scope, requestIndex) {
    getStatusTargetNodes(scope).forEach(function (target) {
      setWorkflowState(target, resolveWorkflowStateForTarget(target, requestIndex));
    });
    syncBatchUi(document);
  }

  function findRelatedStatusTargets(baseScope, requestPayload) {
    var scope = baseScope || document;
    var bookData = requestPayload && requestPayload.book_data ? requestPayload.book_data : {};
    var matchKey = buildStatusMatchKey(bookData.provider || 'hardcover', bookData.provider_id);
    if (!matchKey) {
      return [];
    }
    return getStatusTargetNodes(scope).filter(function (target) {
      return getTargetMatchKey(target) === matchKey;
    });
  }

  function applyImmediateRequestedState(scope, requestPayload) {
    var state = buildWorkflowState({
      key: 'requested',
      label: 'Requested',
      chipClass: 'shelfmark-status-chip--requested',
      timestamp: new Date().toISOString()
    });
    findRelatedStatusTargets(scope, requestPayload).forEach(function (target) {
      setWorkflowState(target, state);
    });
    syncBatchUi(document);
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
    var requestFlow = getFlow();
    var requestableCount = 0;
    var blockedCount = 0;
    var payloadCount = 0;

    actions.forEach(function (node) {
      var payload = parseJson(node.dataset.requestPayload);
      if (!payload) {
        return;
      }
      payloadCount += 1;
      var outcome = requestFlow.resolveProbeState({
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
    syncBatchUi(document);
  }

  function getBatchToolbars(scope) {
    return getScopedClassNodes(scope, 'js-shelfmark-batch-toolbar');
  }

  function getBatchRows(scope) {
    return getScopedClassNodes(scope, 'js-shelfmark-batch-row').filter(function (row) {
      return !isFilterHiddenRow(row);
    });
  }

  function getBatchToggleNode(row) {
    return row ? row.querySelector('.js-shelfmark-batch-toggle') : null;
  }

  function getBatchSelectNode(row) {
    return row ? row.querySelector('.js-shelfmark-batch-select') : null;
  }

  function getBatchActionNode(row) {
    return row ? row.querySelector('.js-shelfmark-action') : null;
  }

  function getSelectedBatchRows(scope) {
    return getBatchRows(scope).filter(function (row) {
      var toggle = getBatchToggleNode(row);
      return Boolean(toggle && toggle.checked && !toggle.disabled);
    });
  }

  function formatBatchSelectedCount(count) {
    return count === 1 ? '1 selected' : count + ' selected';
  }

  function formatBatchReadyCount(count) {
    return count === 1 ? '1 ready on this page' : count + ' ready on this page';
  }

  function clearBatchMessage(toolbar) {
    if (!toolbar) {
      return;
    }
    var messageNode = toolbar.querySelector('.js-shelfmark-batch-message');
    if (!messageNode) {
      return;
    }
    messageNode.textContent = '';
    messageNode.classList.add('is-hidden');
    messageNode.classList.remove(
      'shelfmark-batch-toolbar__message--success',
      'shelfmark-batch-toolbar__message--warning',
      'shelfmark-batch-toolbar__message--danger'
    );
  }

  function setBatchMessage(toolbar, text, tone) {
    if (!toolbar) {
      return;
    }
    var messageNode = toolbar.querySelector('.js-shelfmark-batch-message');
    if (!messageNode) {
      return;
    }
    clearBatchMessage(toolbar);
    if (!text) {
      return;
    }
    messageNode.textContent = text;
    messageNode.classList.remove('is-hidden');
    if (tone === 'success') {
      messageNode.classList.add('shelfmark-batch-toolbar__message--success');
    } else if (tone === 'warning') {
      messageNode.classList.add('shelfmark-batch-toolbar__message--warning');
    } else if (tone === 'danger') {
      messageNode.classList.add('shelfmark-batch-toolbar__message--danger');
    }
  }

  function isBatchEligibleRow(row) {
    if (!row) {
      return false;
    }
    var actionNode = getBatchActionNode(row);
    var requestFlow = getFlow();
    if (!actionNode || !parseJson(actionNode.dataset.requestPayload)) {
      return false;
    }
    if (!requestFlow || requestFlow.normalizeMode(actionNode.dataset.mode) !== 'request') {
      return false;
    }
    return getWorkflowStatusKey(row) === 'available';
  }

  function syncBatchUi(scope) {
    var toolbar = getBatchToolbars(scope)[0];
    var batchRows = getBatchRows(scope);
    if (!toolbar) {
      return;
    }

    var eligibleCount = 0;
    var selectedCount = 0;

    batchRows.forEach(function (row) {
      var toggleNode = getBatchToggleNode(row);
      var selectNode = getBatchSelectNode(row);
      if (!toggleNode || !selectNode) {
        return;
      }

      var isEligible = isBatchEligibleRow(row);
      if (!isEligible) {
        toggleNode.checked = false;
      }

      toggleNode.disabled = !isEligible;
      selectNode.classList.toggle('is-hidden', !isEligible);
      row.classList.toggle('is-batch-eligible', isEligible);
      row.classList.toggle('is-batch-selected', isEligible && Boolean(toggleNode.checked));

      if (isEligible) {
        eligibleCount += 1;
      }
      if (isEligible && toggleNode.checked) {
        selectedCount += 1;
      }
    });

    var countNode = toolbar.querySelector('.js-shelfmark-batch-count');
    var readyNode = toolbar.querySelector('.js-shelfmark-batch-ready');
    var selectVisibleNode = toolbar.querySelector('.js-shelfmark-batch-select-visible');
    var clearNode = toolbar.querySelector('.js-shelfmark-batch-clear');
    var requestNode = toolbar.querySelector('.js-shelfmark-batch-request');
    var hasMessage = Boolean(
      toolbar.querySelector('.js-shelfmark-batch-message')
      && !toolbar.querySelector('.js-shelfmark-batch-message').classList.contains('is-hidden')
    );
    var isPending = toolbar.dataset.pending === '1';

    if (countNode) {
      countNode.textContent = formatBatchSelectedCount(selectedCount);
    }
    if (readyNode) {
      readyNode.textContent = formatBatchReadyCount(eligibleCount);
    }
    if (selectVisibleNode) {
      selectVisibleNode.disabled = eligibleCount < 1 || isPending;
    }
    if (clearNode) {
      clearNode.disabled = selectedCount < 1 || isPending;
    }
    if (requestNode) {
      requestNode.disabled = selectedCount < 1 || isPending;
    }

    var shouldShowToolbar = batchRows.length > 0 && (eligibleCount > 0 || selectedCount > 0 || hasMessage);
    toolbar.classList.toggle('is-hidden', !shouldShowToolbar);
    toolbar.setAttribute('aria-hidden', shouldShowToolbar ? 'false' : 'true');
  }

  function setBatchPending(toolbar, isPending) {
    if (!toolbar) {
      return;
    }
    toolbar.dataset.pending = isPending ? '1' : '0';
    var requestNode = toolbar.querySelector('.js-shelfmark-batch-request');
    if (!requestNode) {
      return;
    }
    if (!requestNode.dataset.defaultLabel) {
      requestNode.dataset.defaultLabel = requestNode.textContent;
    }
    requestNode.textContent = isPending ? 'Requesting…' : requestNode.dataset.defaultLabel;
  }

  async function refreshWorkflowStatus(scope, baseUrl) {
    var requestFlow = getFlow();
    if (!baseUrl || !requestFlow || !requestFlow.isDirectRequestViable(baseUrl, window.location.origin)) {
      return;
    }
    try {
      var snapshot = await fetchActivitySnapshot(baseUrl);
      updateStatusTargets(scope, buildRequestStatusIndex(snapshot && snapshot.requests));
    } catch (error) {
      // Leave the current optimistic state in place when refresh is unavailable.
    }
  }

  async function submitRequest(node, payload, openUrl, statusNodes, options) {
    var requestFlow = getFlow();
    var settings = options || {};
    var showStatusBanner = !settings.silentStatus;

    setPending(node, true);
    if (showStatusBanner) {
      setStatusText(statusNodes, 'Creating request in Shelfmark…', 'alert-info', { persist: true });
    }

    try {
      await fetchJson(stripTrailingSlash(node.dataset.baseUrl) + '/api/requests', {
        method: 'POST',
        body: JSON.stringify(payload)
      }, DEFAULT_TIMEOUT_MS);

      var successOutcome = requestFlow.resolveRequestOutcome({ success: true });
      updateActionNode(node, successOutcome.actionState);
      node.setAttribute('href', openUrl);
      if (showStatusBanner) {
        setStatusText(statusNodes, successOutcome.bannerText, successOutcome.bannerLevel);
      }
      invalidateActivitySnapshot(node.dataset.baseUrl);
      applyImmediateRequestedState(document, payload);
      return {
        success: true,
        outcome: successOutcome
      };
    } catch (error) {
      var failureOutcome = requestFlow.resolveRequestOutcome({ success: false, error: error });
      updateActionNode(node, failureOutcome.actionState);
      node.setAttribute('href', openUrl);
      if (showStatusBanner) {
        setStatusText(statusNodes, failureOutcome.bannerText, failureOutcome.bannerLevel);
      }
      return {
        success: false,
        error: error,
        outcome: failureOutcome
      };
    } finally {
      setPending(node, false);
      syncBatchUi(document);
    }
  }

  async function requestSelectedRows(toolbar) {
    var requestFlow = getFlow();
    var selectedRows = getSelectedBatchRows(document);
    if (!selectedRows.length || !requestFlow) {
      syncBatchUi(document);
      return;
    }

    clearBatchMessage(toolbar);
    setBatchPending(toolbar, true);
    syncBatchUi(document);

    var requestItems = [];
    var seenKeys = new Set();
    var baseUrl = '';

    selectedRows.forEach(function (row) {
      var actionNode = getBatchActionNode(row);
      var payload = actionNode ? parseJson(actionNode.dataset.requestPayload) : null;
      if (!actionNode || !payload) {
        return;
      }
      var matchKey = buildRequestPayloadMatchKey(payload);
      if (matchKey && seenKeys.has(matchKey)) {
        return;
      }
      if (matchKey) {
        seenKeys.add(matchKey);
      }
      if (!baseUrl) {
        baseUrl = actionNode.dataset.baseUrl || '';
      }
      requestItems.push({
        actionNode: actionNode,
        payload: payload,
        openUrl: actionNode.dataset.openUrl || actionNode.getAttribute('href') || ''
      });
    });

    var successCount = 0;
    var failureCount = 0;

    for (var index = 0; index < requestItems.length; index += 1) {
      var item = requestItems[index];
      var response = await submitRequest(item.actionNode, item.payload, item.openUrl, [], {
        silentStatus: true
      });
      if (response.success) {
        successCount += 1;
      } else {
        failureCount += 1;
      }
    }

    getBatchRows(document).forEach(function (row) {
      var toggleNode = getBatchToggleNode(row);
      if (toggleNode) {
        toggleNode.checked = false;
      }
    });

    if (successCount > 0 && baseUrl) {
      await refreshWorkflowStatus(document, baseUrl);
    }

    setBatchPending(toolbar, false);

    if (successCount > 0 && failureCount === 0) {
      setBatchMessage(
        toolbar,
        successCount === 1 ? 'Requested 1 book.' : 'Requested ' + successCount + ' books.',
        'success'
      );
    } else if (successCount > 0 && failureCount > 0) {
      setBatchMessage(
        toolbar,
        'Requested ' + successCount + ' of ' + (successCount + failureCount) + '. Some rows still need attention.',
        'warning'
      );
    } else {
      setBatchMessage(toolbar, 'No Shelfmark requests were created.', 'danger');
    }

    syncBatchUi(document);
  }

  async function attachProbe(actions, baseUrl, statusNodes) {
    var requestFlow = getFlow();
    var currentOrigin = window.location.origin;
    var probeOutcome;

    if (!requestFlow.isDirectRequestViable(baseUrl, currentOrigin)) {
      probeOutcome = requestFlow.resolveProbeState({
        baseUrl: baseUrl,
        currentOrigin: currentOrigin
      });
      applyProbeOutcome(actions, probeOutcome, statusNodes);
      return;
    }

    try {
      var authPayload = await fetchJson(stripTrailingSlash(baseUrl) + '/api/auth/check', {}, DEFAULT_TIMEOUT_MS);
      if (!authPayload || !authPayload.authenticated) {
        probeOutcome = requestFlow.resolveProbeState({
          baseUrl: baseUrl,
          currentOrigin: currentOrigin,
          authPayload: authPayload
        });
        applyProbeOutcome(actions, probeOutcome, statusNodes);
        return;
      }

      var policyPayload = await fetchJson(stripTrailingSlash(baseUrl) + '/api/request-policy', {}, DEFAULT_TIMEOUT_MS);
      probeOutcome = requestFlow.resolveProbeState({
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
        syncBatchUi(document);
        return;
      }

      setStatusText(
        statusNodes,
        'Open in Shelfmark is required for the visible results.',
        'alert-warning'
      );
      syncBatchUi(document);
    } catch (error) {
      probeOutcome = requestFlow.resolveProbeState({
        baseUrl: baseUrl,
        currentOrigin: currentOrigin,
        error: error
      });
      applyProbeOutcome(actions, probeOutcome, statusNodes);
    }
  }

  async function attachWorkflowStatus(scope, baseUrl, probePromise) {
    var targets = getStatusTargetNodes(scope);
    var requestFlow = getFlow();
    if (!targets.length || !requestFlow || !requestFlow.isDirectRequestViable(baseUrl, window.location.origin)) {
      return;
    }

    try {
      var snapshot = await fetchActivitySnapshot(baseUrl);
      if (probePromise && typeof probePromise.then === 'function') {
        try {
          await probePromise;
        } catch (err) {
          // Keep the last known/default status if probe fails.
        }
      }
      updateStatusTargets(scope, buildRequestStatusIndex(snapshot && snapshot.requests));
    } catch (error) {
      // Leave the default server-rendered state in place when status enrichment is unavailable.
    }
  }

  function attachRequestHandler(node, payload, openUrl, statusNodes) {
    if (boundActionNodes.has(node)) {
      return;
    }
    boundActionNodes.add(node);

    node.addEventListener('click', async function (event) {
      var requestFlow = getFlow();
      if (!requestFlow || requestFlow.normalizeMode(node.dataset.mode) !== 'request') {
        return;
      }

      event.preventDefault();
      clearBatchMessage(getBatchToolbars(document)[0] || null);
      await submitRequest(node, payload, openUrl, statusNodes, {});
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
    emitCustomEvent(modalNode, 'cwa:modal-hidden');
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
    detailModalState = null;
  }

  function modalIsOpen(modalNode) {
    return Boolean(modalNode && modalNode.classList && modalNode.classList.contains('in'));
  }

  function findMatchingDetailLink(detailLinks, provider, providerId) {
    return (detailLinks || []).find(function (link) {
      return (
        toOptionalText(link.dataset.detailProvider) === provider &&
        toOptionalText(link.dataset.detailProviderId) === providerId
      );
    }) || null;
  }

  function getModalSearchStateUrl(modalNode) {
    var configured = toOptionalText(modalNode && modalNode.dataset ? modalNode.dataset.searchStateUrl : '');
    return configured || buildSearchStateUrl(window.location.href);
  }

  function getProgressiveRows(scope) {
    return getScopedClassNodes(scope, 'js-shelfmark-progressive-row');
  }

  function getVisibleResultRows(scope) {
    return getScopedClassNodes(scope, 'js-shelfmark-result-row').filter(function (row) {
      return !isFilterHiddenRow(row);
    });
  }

  function getResultsList() {
    return document.querySelector('.js-shelfmark-results-list');
  }

  function getConfiguredPageSize(resultsList) {
    var parsed = toOptionalNumber(resultsList && resultsList.dataset ? resultsList.dataset.pageSize : null);
    return parsed && parsed > 0 ? parsed : 0;
  }

  function getNextTopUpPage(resultsList) {
    var parsed = toOptionalNumber(resultsList && resultsList.dataset ? resultsList.dataset.nextPage : null);
    return parsed && parsed > 0 ? parsed : null;
  }

  function setNextTopUpPage(resultsList, nextPage) {
    if (!resultsList || !resultsList.dataset) {
      return;
    }
    if (nextPage && nextPage > 0) {
      resultsList.dataset.nextPage = String(nextPage);
      return;
    }
    delete resultsList.dataset.nextPage;
  }

  function getTopUpUrl(resultsList) {
    return toOptionalText(resultsList && resultsList.dataset ? resultsList.dataset.topUpUrl : '');
  }

  function isTopUpPending(resultsList) {
    return Boolean(resultsList && resultsList.dataset && resultsList.dataset.topUpPending === '1');
  }

  function setTopUpPending(resultsList, pending) {
    if (!resultsList || !resultsList.dataset) {
      return;
    }
    if (pending) {
      resultsList.dataset.topUpPending = '1';
      return;
    }
    delete resultsList.dataset.topUpPending;
  }

  function buildRowIdentityKey(provider, providerId) {
    var normalizedProvider = toOptionalText(provider).toLowerCase();
    var normalizedProviderId = toOptionalText(providerId);
    if (!normalizedProvider || !normalizedProviderId) {
      return '';
    }
    return normalizedProvider + ':' + normalizedProviderId;
  }

  function getRenderedRowIdentityKeys(resultsList) {
    return new Set(
      toArray((resultsList || document).querySelectorAll('.js-shelfmark-result-row')).map(function (row) {
        return buildRowIdentityKey(
          row && row.dataset ? row.dataset.provider : '',
          row && row.dataset ? row.dataset.providerId : ''
        );
      }).filter(Boolean)
    );
  }

  function getNextRowIndex(resultsList) {
    var maxIndex = -1;
    toArray((resultsList || document).querySelectorAll('.js-shelfmark-result-row')).forEach(function (row) {
      var parsed = toOptionalNumber(row && row.dataset ? row.dataset.rowIndex : null);
      if (parsed !== null && parsed > maxIndex) {
        maxIndex = parsed;
      }
    });
    return maxIndex + 1;
  }

  function buildTopUpRequestUrl(baseUrl, nextPage) {
    var url = buildUrl(baseUrl);
    if (!url) {
      return '';
    }
    url.searchParams.set('shelfmark_source_page', String(nextPage));
    return url.toString();
  }

  function canTopUpResults(resultsList, visibleCount) {
    var targetCount = getConfiguredPageSize(resultsList);
    if (!resultsList || !targetCount || visibleCount >= targetCount) {
      return false;
    }
    if (topUpInFlight || topUpPagesFetched >= TOP_UP_MAX_PAGES) {
      return false;
    }
    return Boolean(getTopUpUrl(resultsList) && getNextTopUpPage(resultsList));
  }

  function appendTopUpRows(resultsList, rows) {
    if (!resultsList || !rows || !rows.length || typeof document.createElement !== 'function') {
      return 0;
    }

    var appended = 0;
    var renderedKeys = getRenderedRowIdentityKeys(resultsList);
    var nextRowIndex = getNextRowIndex(resultsList);

    rows.forEach(function (rowPayload) {
      var identityKey = buildRowIdentityKey(rowPayload.provider, rowPayload.provider_id);
      if (identityKey && renderedKeys.has(identityKey)) {
        return;
      }

      var row = document.createElement('article');
      row.className = rowPayload.row_class_name || 'shelfmark-result-card js-shelfmark-result-row';
      row.setAttribute('role', 'listitem');
      row.dataset.rowIndex = String(nextRowIndex);
      nextRowIndex += 1;

      if (rowPayload.provider) {
        row.dataset.provider = rowPayload.provider;
      }
      if (rowPayload.provider_id) {
        row.dataset.providerId = rowPayload.provider_id;
      }
      if (rowPayload.row_status_provider) {
        row.dataset.statusProvider = rowPayload.row_status_provider;
        row.dataset.statusProviderId = rowPayload.row_status_provider_id || '';
        row.dataset.statusInLibrary = rowPayload.row_status_in_library || '0';
      }
      if (rowPayload.row_enrichment_url) {
        row.dataset.rowEnrichUrl = rowPayload.row_enrichment_url;
      }
      row.innerHTML = typeof rowPayload.html === 'string' ? rowPayload.html : '';
      resultsList.appendChild(row);
      if (identityKey) {
        renderedKeys.add(identityKey);
      }
      appended += 1;
      initActions(row);
      initDetailModal(row);
      initProgressiveEnrichment(row);
      initBatchToolbar(row);
    });

    return appended;
  }

  function ensurePageFilled() {
    var resultsList = getResultsList();
    var visibleCount = getVisibleResultRows(document).length;

    if (!canTopUpResults(resultsList, visibleCount)) {
      updateProgressiveCounts();
      return Promise.resolve();
    }

    var nextPage = getNextTopUpPage(resultsList);
    var requestUrl = buildTopUpRequestUrl(getTopUpUrl(resultsList), nextPage);
    if (!requestUrl) {
      updateProgressiveCounts();
      return Promise.resolve();
    }

    topUpInFlight = true;
    topUpPagesFetched += 1;
    setTopUpPending(resultsList, true);
    updateProgressiveCounts();

    return fetchJson(requestUrl, {
      method: 'GET',
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    }, TOP_UP_TIMEOUT_MS).then(function (payload) {
      if (!payload || payload.ok !== true) {
        throw new Error(payload && payload.message ? payload.message : 'Shelfmark page top-up failed.');
      }
      setNextTopUpPage(resultsList, payload.next_page);
      appendTopUpRows(resultsList, Array.isArray(payload.rows) ? payload.rows : []);
    }).catch(function () {
      setNextTopUpPage(resultsList, null);
    }).finally(function () {
      topUpInFlight = false;
      setTopUpPending(resultsList, false);
      updateProgressiveCounts();
      if (canTopUpResults(resultsList, getVisibleResultRows(document).length)) {
        ensurePageFilled();
      }
    });
  }

  function getRowOrder(row) {
    var parsed = toOptionalNumber(row && row.dataset ? row.dataset.rowIndex : null);
    return parsed === null ? Number.MAX_SAFE_INTEGER : parsed;
  }

  function sortQueuedRows() {
    rowEnrichmentQueue.sort(function (left, right) {
      return getRowOrder(left) - getRowOrder(right);
    });
  }

  function updateProgressiveCounts() {
    var resultsList = getResultsList();
    var visibleCount = getVisibleResultRows(document).length;
    var canStillTopUp = canTopUpResults(resultsList, visibleCount) || isTopUpPending(resultsList);
    var visibleCountNodes = toArray(document.querySelectorAll('.js-shelfmark-visible-count'));
    var summaryNodes = toArray(document.querySelectorAll('.js-shelfmark-page-summary'));
    var emptyState = document.querySelector('.js-shelfmark-progressive-empty-state');

    visibleCountNodes.forEach(function (node) {
      node.textContent = visibleCount === 1 ? '1 shown' : visibleCount + ' shown';
    });
    summaryNodes.forEach(function (node) {
      node.textContent = visibleCount > 0
        ? (visibleCount === 1 ? '1 shown on this page' : visibleCount + ' shown on this page')
        : 'No visible results on this page';
    });

    if (emptyState) {
      var showEmptyState = visibleCount < 1 && !canStillTopUp;
      emptyState.classList.toggle('is-hidden', !showEmptyState);
      emptyState.setAttribute('aria-hidden', showEmptyState ? 'false' : 'true');
    }
  }

  function setProgressiveRowState(row, state) {
    if (!row || !row.dataset) {
      return;
    }
    row.dataset.rowEnrichmentState = state;
  }

  function getProgressiveRowState(row) {
    if (!row || !row.dataset) {
      return '';
    }
    return toOptionalText(row.dataset.rowEnrichmentState) || '';
  }

  function queueProgressiveRow(row, options) {
    var settings = options || {};
    if (!row || !row.dataset || !toOptionalText(row.dataset.rowEnrichUrl)) {
      return;
    }
    if (isFilterHiddenRow(row)) {
      return;
    }
    var state = getProgressiveRowState(row);
    if (state === 'loading' || state === 'done' || state === 'failed') {
      return;
    }
    if (rowEnrichmentQueue.indexOf(row) === -1) {
      rowEnrichmentQueue.push(row);
      sortQueuedRows();
    }
    setProgressiveRowState(row, 'queued');
    if (!settings.deferDrain) {
      drainProgressiveRowQueue();
    }
  }

  function markProgressiveRowVisible(row) {
    if (!row || !row.dataset) {
      return;
    }
    row.dataset.rowVisible = '1';
    queueProgressiveRow(row);
  }

  function getRowEnrichmentObserver() {
    if (typeof window.IntersectionObserver !== 'function') {
      return null;
    }
    if (!rowEnrichmentObserver) {
      rowEnrichmentObserver = new window.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry || !entry.target) {
            return;
          }
          if (entry.isIntersecting || entry.intersectionRatio > 0) {
            markProgressiveRowVisible(entry.target);
          }
        });
      }, {
        rootMargin: ROW_ENRICH_ROOT_MARGIN,
        threshold: 0.01
      });
    }
    return rowEnrichmentObserver;
  }

  function applyProgressiveRowAttrs(row, payload) {
    if (!row || !payload) {
      return;
    }
    if (payload.row_class_name) {
      var preservedClasses = [
        'is-batch-eligible',
        'is-batch-selected',
        'is-shelfmark-handled'
      ].filter(function (className) {
        return row.classList.contains(className);
      });
      row.className = payload.row_class_name;
      preservedClasses.forEach(function (className) {
        row.classList.add(className);
      });
    }

    if (payload.row_status_provider) {
      row.dataset.statusProvider = payload.row_status_provider;
      row.dataset.statusProviderId = payload.row_status_provider_id || '';
      row.dataset.statusInLibrary = payload.row_status_in_library || '0';
    } else if (row.dataset) {
      delete row.dataset.statusProvider;
      delete row.dataset.statusProviderId;
      delete row.dataset.statusInLibrary;
    }
  }

  function handleProgressiveRowResponse(row, payload) {
    if (!row || !payload || payload.ok !== true) {
      throw new Error(payload && payload.message ? payload.message : 'Shelfmark row enrichment failed.');
    }

    applyProgressiveRowAttrs(row, payload);
    if (typeof payload.html === 'string') {
      row.innerHTML = payload.html;
    }
    if (payload.matches_filters === false) {
      row.classList.add('is-shelfmark-filter-hidden');
      row.setAttribute('aria-hidden', 'true');
    } else {
      row.classList.remove('is-shelfmark-filter-hidden');
      row.removeAttribute('aria-hidden');
    }

    if (row.dataset) {
      delete row.dataset.rowEnrichUrl;
      delete row.dataset.rowVisible;
    }
    row.classList.remove('shelfmark-result-card--refining');
    setProgressiveRowState(row, 'done');
    initActions(row);
    initDetailModal(row);
    initBatchToolbar(row);
    updateProgressiveCounts();
    syncBatchUi(document);
    ensurePageFilled();
  }

  function startProgressiveRowEnrichment(row) {
    var url = toOptionalText(row && row.dataset ? row.dataset.rowEnrichUrl : '');
    if (!row || !url) {
      return Promise.resolve();
    }

    setProgressiveRowState(row, 'loading');
    row.classList.add('shelfmark-result-card--refining');
    rowEnrichmentInFlight += 1;

    return fetchJson(url, {
      method: 'GET',
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    }, ROW_ENRICH_TIMEOUT_MS).then(function (payload) {
      handleProgressiveRowResponse(row, payload);
    }).catch(function () {
      row.classList.remove('shelfmark-result-card--refining');
      setProgressiveRowState(row, 'failed');
    }).finally(function () {
      rowEnrichmentInFlight = Math.max(0, rowEnrichmentInFlight - 1);
      rowEnrichmentQueue = rowEnrichmentQueue.filter(function (queuedRow) {
        return queuedRow !== row;
      });
      drainProgressiveRowQueue();
    });
  }

  function drainProgressiveRowQueue() {
    if (rowEnrichmentInFlight >= ROW_ENRICH_MAX_CONCURRENCY) {
      return;
    }
    sortQueuedRows();
    while (rowEnrichmentInFlight < ROW_ENRICH_MAX_CONCURRENCY && rowEnrichmentQueue.length) {
      var nextRow = rowEnrichmentQueue.shift();
      if (!nextRow || (typeof nextRow.isConnected === 'boolean' && !nextRow.isConnected) || isFilterHiddenRow(nextRow)) {
        continue;
      }
      if (getProgressiveRowState(nextRow) === 'loading' || getProgressiveRowState(nextRow) === 'done') {
        continue;
      }
      startProgressiveRowEnrichment(nextRow);
    }
  }

  function initProgressiveEnrichment(root) {
    var scope = root || document;
    var observer = getRowEnrichmentObserver();

    getProgressiveRows(scope).forEach(function (row) {
      if (boundProgressiveRows.has(row)) {
        return;
      }
      boundProgressiveRows.add(row);
      setProgressiveRowState(row, 'pending');
      if (observer) {
        observer.observe(row);
      }
      queueProgressiveRow(row, { deferDrain: true });
    });

    drainProgressiveRowQueue();
    updateProgressiveCounts();
    ensurePageFilled();
  }

  function initActions(root) {
    var requestFlow = getFlow();
    if (!requestFlow) {
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

    var probePromise = attachProbe(actions, baseUrl, statusNodes);
    attachWorkflowStatus(scope, baseUrl, probePromise);
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
      var closingFromHistory = Boolean(detailModalState && detailModalState.closingFromHistory);
      var restoreUrl = detailModalState && detailModalState.searchStateUrl;
      var historyPushed = Boolean(detailModalState && detailModalState.historyPushed);
      resetDetailModal(modalBody, modalTitle);
      if (closingFromHistory || !restoreUrl || !currentUrlHasDetailState()) {
        return;
      }
      if (window.history && typeof window.history.back === 'function' && historyPushed) {
        window.history.back();
        return;
      }
      if (window.history && typeof window.history.replaceState === 'function') {
        window.history.replaceState(window.history.state, '', restoreUrl);
      }
    });

    if (!detailHistoryBound && window && typeof window.addEventListener === 'function') {
      detailHistoryBound = true;
      window.addEventListener('popstate', function () {
        var state = parseDetailState(window.location.href);
        if (state.provider && state.providerId) {
          if (modalIsOpen(modalNode)) {
            return;
          }
          var matchingLink = findMatchingDetailLink(detailLinks, state.provider, state.providerId);
          if (matchingLink) {
            openDetailLink(matchingLink, {
              pushHistory: false,
              searchStateUrl: buildSearchStateUrl(window.location.href)
            });
          }
          return;
        }

        if (modalIsOpen(modalNode)) {
          if (!detailModalState) {
            detailModalState = {};
          }
          detailModalState.closingFromHistory = true;
          hideModal(modalNode);
        }
      });
    }

    function openDetailLink(link, options) {
      var settings = options || {};
      var provider = toOptionalText(link.dataset.detailProvider);
      var providerId = toOptionalText(link.dataset.detailProviderId);
      var searchStateUrl = settings.searchStateUrl || getModalSearchStateUrl(modalNode);
      var detailStateUrl = buildSearchStateUrlWithDetail(searchStateUrl, provider, providerId);
      var cachedHtml = getCachedDetailHtml(provider, providerId);

      activeDetailLink = link;
      abortActiveDetailRequest();
      detailModalState = {
        provider: provider,
        providerId: providerId,
        searchStateUrl: searchStateUrl,
        detailStateUrl: detailStateUrl,
        historyPushed: false,
        closingFromHistory: false
      };

      if (settings.pushHistory !== false && window.history && typeof window.history.pushState === 'function') {
        window.history.pushState(
          {
            shelfmarkDetail: {
              provider: provider,
              providerId: providerId
            }
          },
          '',
          detailStateUrl
        );
        detailModalState.historyPushed = true;
      }

      modalTitle.textContent = link.dataset.detailTitle || 'Shelfmark Details';
      showModal(modalNode);

      if (cachedHtml) {
        modalBody.innerHTML = cachedHtml;
        modalBody.setAttribute('aria-busy', 'false');
        var cachedTitleSource = modalBody.querySelector('[data-detail-title]');
        if (cachedTitleSource && cachedTitleSource.dataset && cachedTitleSource.dataset.detailTitle) {
          modalTitle.textContent = cachedTitleSource.dataset.detailTitle;
        }
        initActions(modalBody);
        return;
      }

      modalBody.innerHTML = '<div class="shelfmark-detail-modal__loading js-shelfmark-detail-modal-loading">Loading Shelfmark details…</div>';
      modalBody.setAttribute('aria-busy', 'true');

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
        rememberDetailHtml(provider, providerId, html);
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
        if (detailModalState) {
          detailModalState.closingFromHistory = true;
          if (
            detailModalState.searchStateUrl &&
            currentUrlHasDetailState() &&
            window.history &&
            typeof window.history.replaceState === 'function'
          ) {
            window.history.replaceState(window.history.state, '', detailModalState.searchStateUrl);
          }
        }
        hideModal(modalNode);
        window.location.assign(link.href);
      }).finally(function () {
        if (!controller || activeDetailRequest === controller) {
          activeDetailRequest = null;
        }
      });
    }

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
        openDetailLink(link, {
          pushHistory: true,
          searchStateUrl: getModalSearchStateUrl(modalNode)
        });
      });
    });

    var initialState = parseDetailState(window.location.href);
    if (initialState.provider && initialState.providerId && !modalIsOpen(modalNode)) {
      var initialLink = findMatchingDetailLink(detailLinks, initialState.provider, initialState.providerId);
      if (initialLink) {
        openDetailLink(initialLink, {
          pushHistory: false,
          searchStateUrl: buildSearchStateUrl(window.location.href)
        });
      } else if (window.history && typeof window.history.replaceState === 'function') {
        window.history.replaceState(window.history.state, '', buildSearchStateUrl(window.location.href));
      }
    }
  }

  function initBatchToolbar(root) {
    var scope = root || document;
    var toolbar = getBatchToolbars(scope)[0];
    if (!toolbar || boundBatchToolbars.has(toolbar)) {
      syncBatchUi(document);
      return;
    }
    boundBatchToolbars.add(toolbar);

    var selectVisibleNode = toolbar.querySelector('.js-shelfmark-batch-select-visible');
    var clearNode = toolbar.querySelector('.js-shelfmark-batch-clear');
    var requestNode = toolbar.querySelector('.js-shelfmark-batch-request');

    getBatchRows(document).forEach(function (row) {
      var toggleNode = getBatchToggleNode(row);
      if (!toggleNode || toggleNode.dataset.batchBound === '1') {
        return;
      }
      toggleNode.dataset.batchBound = '1';
      toggleNode.addEventListener('change', function () {
        clearBatchMessage(toolbar);
        syncBatchUi(document);
      });
    });

    if (selectVisibleNode) {
      selectVisibleNode.addEventListener('click', function () {
        clearBatchMessage(toolbar);
        getBatchRows(document).forEach(function (row) {
          var toggleNode = getBatchToggleNode(row);
          if (toggleNode && !toggleNode.disabled) {
            toggleNode.checked = true;
          }
        });
        syncBatchUi(document);
      });
    }

    if (clearNode) {
      clearNode.addEventListener('click', function () {
        clearBatchMessage(toolbar);
        getBatchRows(document).forEach(function (row) {
          var toggleNode = getBatchToggleNode(row);
          if (toggleNode) {
            toggleNode.checked = false;
          }
        });
        syncBatchUi(document);
      });
    }

    if (requestNode) {
      requestNode.addEventListener('click', function () {
        if (requestNode.disabled || toolbar.dataset.pending === '1') {
          return;
        }
        requestSelectedRows(toolbar);
      });
    }

    syncBatchUi(document);
  }

  function init(root) {
    initActions(root);
    initDetailModal(root);
    initProgressiveEnrichment(root);
    initBatchToolbar(root);
  }

  window.CwaShelfmarkExternalSearch = {
    init: init
  };

  if (document.readyState === 'loading') {
    setTimeout(init, 0);
  } else {
    init();
  }
}());
