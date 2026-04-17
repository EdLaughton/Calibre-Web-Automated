const assert = require('assert');
const path = require('path');

const flowModulePath = path.resolve(__dirname, '../../cps/static/js/shelfmark_request_flow.js');
const searchModulePath = path.resolve(__dirname, '../../cps/static/js/shelfmark_external_search.js');

class FakeClassList {
  constructor(element) {
    this.element = element;
  }

  add(...names) {
    names.filter(Boolean).forEach((name) => this.element._classes.add(name));
  }

  remove(...names) {
    names.filter(Boolean).forEach((name) => this.element._classes.delete(name));
  }

  contains(name) {
    return this.element._classes.has(name);
  }

  toggle(name, force) {
    if (typeof force === 'boolean') {
      if (force) {
        this.add(name);
        return true;
      }
      this.remove(name);
      return false;
    }
    if (this.contains(name)) {
      this.remove(name);
      return false;
    }
    this.add(name);
    return true;
  }

  toString() {
    return Array.from(this.element._classes).join(' ');
  }
}

class FakeElement {
  constructor(tagName, options) {
    const config = options || {};
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = Object.assign({}, config.dataset || {});
    this.attributes = {};
    this._classes = new Set((config.className || '').split(/\s+/).filter(Boolean));
    this.classList = new FakeClassList(this);
    this._textContent = config.textContent || '';
    this.listeners = {};
    this.checked = Boolean(config.checked);
    this.disabled = Boolean(config.disabled);

    if (config.attributes) {
      Object.entries(config.attributes).forEach(([key, value]) => {
        this.attributes[key] = value;
      });
    }
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
  }

  addEventListener(name, handler) {
    if (!this.listeners[name]) {
      this.listeners[name] = [];
    }
    this.listeners[name].push(handler);
  }

  dispatchEvent(name) {
    const handlers = this.listeners[name] || [];
    const event = {
      defaultPrevented: false,
      preventDefault() {
        this.defaultPrevented = true;
      }
    };
    handlers.forEach((handler) => handler(event));
    return event;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const matches = [];
    const className = selector.startsWith('.') ? selector.slice(1) : null;

    function walk(node) {
      node.children.forEach((child) => {
        if (className && child.classList.contains(className)) {
          matches.push(child);
        }
        walk(child);
      });
    }

    walk(this);
    return matches;
  }

  get textContent() {
    if (this.children.length) {
      return this.children.map((child) => child.textContent).join('');
    }
    return this._textContent;
  }

  set textContent(value) {
    this._textContent = String(value);
    this.children = [];
  }

  get className() {
    return this.classList.toString();
  }

  set className(value) {
    this._classes = new Set(String(value || '').split(/\s+/).filter(Boolean));
    this.classList = new FakeClassList(this);
  }
}

class FakeDocument {
  constructor(root, readyState) {
    this.root = root;
    this.readyState = readyState || 'complete';
    this.listeners = {};
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }

  querySelector(selector) {
    return this.root.querySelector(selector);
  }

  querySelectorAll(selector) {
    return this.root.querySelectorAll(selector);
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
}

function createResultNode(options) {
  const wrapper = new FakeElement('div', {
    className: `shelfmark-result-card js-shelfmark-result-row${options.statusTarget ? ' js-shelfmark-status-target' : ''}${options.batchToggle ? ' js-shelfmark-batch-row' : ''}`,
    dataset: options.statusTarget ? {
      statusProvider: options.statusProvider || 'hardcover',
      statusProviderId: options.statusProviderId || '',
      statusInLibrary: options.statusInLibrary ? '1' : '0'
    } : {}
  });
  if (options.batchToggle) {
    const select = wrapper.appendChild(new FakeElement('label', {
      className: 'shelfmark-result-card__select shelfmark-batch-select js-shelfmark-batch-select is-hidden'
    }));
    select.appendChild(new FakeElement('input', {
      className: 'js-shelfmark-batch-toggle',
      disabled: true
    }));
  }
  const header = wrapper.appendChild(new FakeElement('div', { className: 'shelfmark-result-card__header' }));
  const badges = header.appendChild(new FakeElement('div', { className: 'shelfmark-result-card__badges' }));
  if (options.statusTarget) {
    badges.appendChild(new FakeElement('span', {
      className: `label shelfmark-status-chip js-shelfmark-status-chip ${options.statusChipClass || ''}`.trim(),
      textContent: options.statusChipText || '',
      attributes: {
        'data-status-key': options.statusChipKey || ''
      }
    }));
  }
  const actionRow = wrapper.appendChild(new FakeElement('div', { className: 'btn-toolbar' }));
  const action = actionRow.appendChild(new FakeElement('a', {
    className: `btn btn-sm ${options.buttonClass} shelfmark-result-card__primary-action js-shelfmark-action`,
    dataset: {
      baseUrl: options.baseUrl,
      openUrl: options.openUrl,
      requestPayload: options.requestPayload ? JSON.stringify(options.requestPayload) : '',
      mode: options.mode,
      preferredReleaseEnabled: options.preferredReleaseEnabled ? '1' : '0',
      preferredReleaseProvider: options.preferredReleaseProvider || '',
      preferredReleaseContentType: options.preferredReleaseContentType || 'ebook',
      preferredReleaseRanking: options.preferredReleaseRanking || 'seeders_desc'
    },
    attributes: {
      href: options.openUrl,
      target: '_blank',
      rel: 'noopener noreferrer'
    }
  }));
  action.appendChild(new FakeElement('span', {
    className: `${options.iconClass} js-shelfmark-action-icon`
  }));
  action.appendChild(new FakeElement('span', {
    className: 'js-shelfmark-action-label',
    textContent: options.label
  }));

  wrapper.appendChild(new FakeElement('p', {
    className: 'help-block js-shelfmark-action-hint',
    textContent: options.hint
  }));

  return { wrapper, action };
}

function createDom(options) {
  const root = new FakeElement('div', { className: 'page-root' });
  let batchToolbar = null;
  let batchModeButton = null;
  if (options.includeBatchToolbar) {
    batchModeButton = root.appendChild(new FakeElement('button', {
      className: 'js-shelfmark-batch-mode',
      textContent: 'Bulk mode'
    }));
    batchToolbar = root.appendChild(new FakeElement('div', {
      className: 'shelfmark-batch-toolbar js-shelfmark-batch-toolbar is-hidden'
    }));
    const summary = batchToolbar.appendChild(new FakeElement('div', {
      className: 'shelfmark-batch-toolbar__summary'
    }));
    summary.appendChild(new FakeElement('span', {
      className: 'shelfmark-batch-toolbar__count js-shelfmark-batch-count',
      textContent: '0 selected'
    }));
    summary.appendChild(new FakeElement('span', {
      className: 'shelfmark-batch-toolbar__meta js-shelfmark-batch-ready',
      textContent: '0 ready on this page'
    }));
    summary.appendChild(new FakeElement('span', {
      className: 'shelfmark-batch-toolbar__message js-shelfmark-batch-message is-hidden'
    }));

    const actions = batchToolbar.appendChild(new FakeElement('div', {
      className: 'shelfmark-batch-toolbar__actions'
    }));
    actions.appendChild(new FakeElement('button', {
      className: 'js-shelfmark-batch-select-visible',
      textContent: 'Select visible',
      disabled: true
    }));
    actions.appendChild(new FakeElement('button', {
      className: 'js-shelfmark-batch-clear',
      textContent: 'Clear',
      disabled: true
    }));
    actions.appendChild(new FakeElement('button', {
      className: 'js-shelfmark-batch-request',
      textContent: 'Request selected',
      disabled: true
    }));
  }
  const status = root.appendChild(new FakeElement('div', {
    className: 'alert alert-info js-shelfmark-request-status',
    textContent: options.statusText || 'Request actions are verified in your browser against Shelfmark.',
    dataset: { baseUrl: options.baseUrl }
  }));

  const first = createResultNode({
    baseUrl: options.baseUrl,
    openUrl: options.openUrl,
    requestPayload: options.requestPayload,
    mode: options.mode || 'open',
    label: options.label || 'Open in Shelfmark',
    hint: options.hint || 'Initial hint',
    buttonClass: options.buttonClass || 'btn-default',
    iconClass: options.iconClass || 'glyphicon glyphicon-new-window',
    statusTarget: options.statusTarget,
    statusProviderId: options.statusProviderId,
    statusInLibrary: options.statusInLibrary,
    statusChipText: options.statusChipText,
    statusChipKey: options.statusChipKey,
    statusChipClass: options.statusChipClass,
    batchToggle: options.batchToggle,
    preferredReleaseEnabled: options.preferredReleaseEnabled,
    preferredReleaseProvider: options.preferredReleaseProvider,
    preferredReleaseContentType: options.preferredReleaseContentType,
    preferredReleaseRanking: options.preferredReleaseRanking
  });
  root.appendChild(first.wrapper);

  return {
    root,
    document: new FakeDocument(root, 'complete'),
    status,
    action: first.action,
    batchToolbar,
    batchModeButton,
    batchToggle: first.wrapper.querySelector('.js-shelfmark-batch-toggle'),
    batchSelect: first.wrapper.querySelector('.js-shelfmark-batch-select')
  };
}

function createProgressiveDom() {
  const root = new FakeElement('div', { className: 'page-root' });
  const visibleCount = root.appendChild(new FakeElement('span', {
    className: 'js-shelfmark-visible-count',
    textContent: '3 shown'
  }));
  const pageSummary = root.appendChild(new FakeElement('span', {
    className: 'js-shelfmark-page-summary',
    textContent: '3 shown on this page'
  }));
  const emptyState = root.appendChild(new FakeElement('div', {
    className: 'js-shelfmark-progressive-empty-state is-hidden'
  }));
  const resultsList = root.appendChild(new FakeElement('div', {
    className: 'js-shelfmark-results-list',
    dataset: {
      pageSize: '3',
      nextPage: '2',
      topUpUrl: '/search/external/shelfmark/topup?query=terry+pratchett'
    }
  }));

  function buildProgressiveRow(rowIndex) {
    const row = createResultNode({
      baseUrl: 'https://shelfmark.example.com',
      openUrl: `https://shelfmark.example.com/book/${rowIndex}`,
      mode: 'open',
      label: 'Open in Shelfmark',
      hint: '',
      buttonClass: 'btn-default',
      iconClass: 'glyphicon glyphicon-new-window',
      statusTarget: false,
      batchToggle: false
    }).wrapper;
    row.className += ' js-shelfmark-result-row js-shelfmark-progressive-row shelfmark-result-card--refining';
    row.dataset.rowIndex = String(rowIndex);
    row.dataset.provider = 'hardcover';
    row.dataset.providerId = String(rowIndex);
    row.dataset.rowEnrichUrl = `/row/${rowIndex}`;
    return row;
  }

  const rows = {
    2: resultsList.appendChild(buildProgressiveRow(2)),
    0: resultsList.appendChild(buildProgressiveRow(0)),
    1: resultsList.appendChild(buildProgressiveRow(1))
  };

  return {
    document: new FakeDocument(root, 'complete'),
    rows,
    visibleCount,
    pageSummary,
    emptyState,
    resultsList
  };
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function runScenario(options) {
  const dom = createDom(options);
  const fetchCalls = [];
  const responses = options.responses ? options.responses.slice() : [];
  const libraryStatusPayloads = options.libraryStatusPayloads ? options.libraryStatusPayloads.slice() : [];

  delete require.cache[flowModulePath];
  delete require.cache[searchModulePath];

  global.window = {
    location: {
      origin: options.currentOrigin,
      href: `${options.currentOrigin}/search/stored/?query=test`
    },
    CWA_SHELFMARK_STATUS_SETTLE_DELAY_MS: 0,
    CwaShelfmarkRequestFlow: require(flowModulePath)
  };
  global.document = dom.document;
  global.fetch = (url, fetchOptions) => {
    if (url.indexOf('/search/external/shelfmark/library-status') !== -1) {
      const nextLibraryPayload = libraryStatusPayloads.length
        ? libraryStatusPayloads.shift()
        : { ok: true, matches: {} };
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => nextLibraryPayload
      });
    }
    if (typeof options.fetchImpl === 'function') {
      return options.fetchImpl(url, fetchOptions || {}, fetchCalls, responses);
    }
    fetchCalls.push({ url, options: fetchOptions || {} });
    const next = responses.shift();
    if (!next) {
      return Promise.reject(new Error(`Unexpected fetch call for ${url}`));
    }
    if (next.error) {
      return Promise.reject(next.error);
    }
    return Promise.resolve({
      ok: next.ok !== false,
      status: next.status || 200,
      statusText: next.statusText || 'OK',
      json: async () => next.payload
    });
  };

  require(searchModulePath);
  await flush();
  await flush();
  await flush();
  await flush();

  return {
    dom,
    fetchCalls,
    async clickPrimaryAction() {
      dom.action.dispatchEvent('click');
      await flush();
      await flush();
      await flush();
      await flush();
    },
    async appendResult(rowOptions) {
      const appended = createResultNode(Object.assign({
        baseUrl: options.baseUrl,
        openUrl: options.openUrl,
        requestPayload: options.requestPayload,
        mode: options.mode || 'open',
        label: options.label || 'Open in Shelfmark',
        hint: options.hint || 'Initial hint',
        buttonClass: options.buttonClass || 'btn-default',
        iconClass: options.iconClass || 'glyphicon glyphicon-new-window',
        statusTarget: options.statusTarget,
        statusProviderId: options.statusProviderId,
        statusInLibrary: options.statusInLibrary,
        statusChipText: options.statusChipText,
        statusChipKey: options.statusChipKey,
        statusChipClass: options.statusChipClass,
        batchToggle: options.batchToggle,
        preferredReleaseEnabled: options.preferredReleaseEnabled,
        preferredReleaseProvider: options.preferredReleaseProvider,
        preferredReleaseContentType: options.preferredReleaseContentType,
        preferredReleaseRanking: options.preferredReleaseRanking
      }, rowOptions || {}));
      dom.root.appendChild(appended.wrapper);
      global.window.CwaShelfmarkExternalSearch.init(appended.wrapper);
      await flush();
      await flush();
      return appended;
    }
  };
}

async function runProgressiveScenario() {
  const dom = createProgressiveDom();
  const fetchCalls = [];
  const responses = [
    {
      payload: {
        ok: true,
        matches_filters: true,
        row_class_name: 'shelfmark-result-card js-shelfmark-result-row',
        html: ''
      }
    },
    {
      payload: {
        ok: true,
        matches_filters: true,
        row_class_name: 'shelfmark-result-card js-shelfmark-result-row',
        html: ''
      }
    },
    {
      payload: {
        ok: true,
        matches_filters: false,
        row_class_name: 'shelfmark-result-card js-shelfmark-result-row',
        html: ''
      }
    },
    {
      payload: {
        ok: true,
        next_page: null,
        rows: [
          {
            provider: 'hardcover',
            provider_id: '99',
            row_class_name: 'shelfmark-result-card js-shelfmark-result-row',
            row_status_provider: '',
            row_status_provider_id: '',
            row_status_in_library: '0',
            row_enrichment_url: '',
            html: ''
          },
          {
            provider: 'hardcover',
            provider_id: '100',
            row_class_name: 'shelfmark-result-card js-shelfmark-result-row',
            row_status_provider: '',
            row_status_provider_id: '',
            row_status_in_library: '0',
            row_enrichment_url: '',
            html: ''
          }
        ]
      }
    }
  ];

  delete require.cache[flowModulePath];
  delete require.cache[searchModulePath];

  global.window = {
    location: {
      origin: 'https://library.example.com',
      href: 'https://library.example.com/search/stored/?query=terry+pratchett'
    },
    CWA_SHELFMARK_STATUS_SETTLE_DELAY_MS: 0,
    CwaShelfmarkRequestFlow: require(flowModulePath)
  };
  global.document = dom.document;
  global.fetch = (url, fetchOptions) => {
    fetchCalls.push({ url, options: fetchOptions || {} });
    const next = responses.shift();
    if (!next) {
      return Promise.reject(new Error(`Unexpected fetch call for ${url}`));
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => next.payload
    });
  };

  require(searchModulePath);
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();

  return { dom, fetchCalls };
}

(async function main() {
  const sameOrigin = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two',
    requestPayload: {
      book_data: { provider_id: '222', title: 'External Candidate' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } },
      { payload: { success: true } }
    ]
  });

  assert.equal(sameOrigin.dom.action.dataset.mode, 'request');
  assert.match(sameOrigin.dom.action.className, /btn-primary/);
  assert.equal(
    sameOrigin.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Request in Shelfmark'
  );
  assert.equal(sameOrigin.dom.status.textContent, '');
  assert.equal(sameOrigin.dom.status.classList.contains('is-hidden'), true);
  assert.equal(sameOrigin.dom.action.getAttribute('target'), '_blank');

  await sameOrigin.clickPrimaryAction();

  assert.equal(sameOrigin.fetchCalls.length, 4);
  assert.equal(sameOrigin.fetchCalls[2].options.method, 'POST');
  assert.equal(sameOrigin.dom.action.dataset.mode, 'open');
  assert.match(sameOrigin.dom.action.className, /btn-success/);
  assert.equal(
    sameOrigin.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Requested'
  );
  assert.match(sameOrigin.dom.status.textContent, /Request sent to Shelfmark/i);
  assert.equal(sameOrigin.dom.status.classList.contains('is-hidden'), false);
  assert.equal(sameOrigin.dom.status.classList.contains('is-settled'), true);
  assert.equal(sameOrigin.dom.action.getAttribute('target'), '_blank');

  let singleRequestResolver = null;
  const immediatePending = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=Pending+Book',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '224', title: 'Pending Book' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    statusTarget: true,
    statusProviderId: '224',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    fetchImpl: (url, fetchOptions, fetchCalls) => {
      fetchCalls.push({ url, options: fetchOptions || {} });
      if (url.endsWith('/api/auth/check')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ authenticated: true, auth_required: true })
        });
      }
      if (url.endsWith('/api/request-policy')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ requests_enabled: true, defaults: { ebook: 'request_book' } })
        });
      }
      if (url.endsWith('/api/activity/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ requests: [] })
        });
      }
      if (url.endsWith('/api/requests') && fetchOptions && fetchOptions.method === 'POST') {
        return new Promise((resolve) => {
          singleRequestResolver = resolve;
        });
      }
      return Promise.reject(new Error(`Unexpected fetch call for ${url}`));
    }
  });

  immediatePending.dom.action.dispatchEvent('click');
  await flush();
  await flush();

  assert.equal(
    immediatePending.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Requesting...'
  );
  assert.equal(immediatePending.dom.action.getAttribute('aria-disabled'), 'true');

  singleRequestResolver({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => ({ success: true })
  });
  await flush();
  await flush();
  await flush();

  const preferredRelease = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=Mort+Terry+Pratchett&title=Mort&author=Terry+Pratchett',
    requestPayload: {
      book_data: {
        provider: 'hardcover',
        provider_id: '444',
        title: 'Mort',
        author: 'Terry Pratchett'
      },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    preferredReleaseEnabled: true,
    preferredReleaseProvider: 'MyAnonamouse',
    preferredReleaseContentType: 'ebook',
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      {
        payload: {
          requests_enabled: true,
          defaults: { ebook: 'request_book' },
          source_modes: [
            {
              source: 'prowlarr',
              browse_results_are_releases: false,
              modes: { ebook: 'request_release' }
            }
          ]
        }
      },
      {
        payload: {
          releases: [
            { source: 'prowlarr', source_id: 'audio-1', indexer: 'MyAnonamouse', format: 'm4b', seeders: 90 },
            { source: 'prowlarr', source_id: 'ebook-1', indexer: 'MyAnonamouse', format: 'epub', seeders: 70 },
            { source: 'prowlarr', source_id: 'ebook-2', indexer: 'OtherIndexer', format: 'epub', seeders: 500 }
          ]
        }
      },
      {
        payload: {
          id: 95,
          status: 'pending',
          request_level: 'release',
          policy_mode: 'request_release',
          release_data: {
            source: 'prowlarr',
            source_id: 'ebook-1',
            indexer: 'MyAnonamouse'
          }
        }
      }
    ]
  });

  await preferredRelease.clickPrimaryAction();

  assert.equal(preferredRelease.fetchCalls.length, 5);
  assert.match(preferredRelease.fetchCalls[2].url, /\/api\/releases\?/);
  assert.match(preferredRelease.fetchCalls[2].url, /indexers=MyAnonamouse/);
  const preferredRequestBody = JSON.parse(preferredRelease.fetchCalls[3].options.body);
  assert.equal(preferredRequestBody.context.request_level, 'release');
  assert.equal(preferredRequestBody.context.source, 'prowlarr');
  assert.equal(preferredRequestBody.release_data.source_id, 'ebook-1');
  assert.equal(preferredRequestBody.release_data.indexer, 'MyAnonamouse');
  assert.equal(
    preferredRelease.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Requested'
  );

  const preferredFallback = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=Mort+Terry+Pratchett&title=Mort&author=Terry+Pratchett',
    requestPayload: {
      book_data: {
        provider: 'hardcover',
        provider_id: '445',
        title: 'Mort',
        author: 'Terry Pratchett'
      },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    preferredReleaseEnabled: true,
    preferredReleaseProvider: 'MyAnonamouse',
    preferredReleaseContentType: 'ebook',
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      {
        payload: {
          requests_enabled: true,
          defaults: { ebook: 'request_book' },
          source_modes: [
            {
              source: 'prowlarr',
              browse_results_are_releases: false,
              modes: { ebook: 'request_release' }
            }
          ]
        }
      },
      {
        payload: {
          releases: [
            { source: 'prowlarr', source_id: 'nonmatch-1', indexer: 'Elsewhere', format: 'epub', seeders: 50 }
          ]
        }
      },
      { payload: { success: true } }
    ]
  });

  await preferredFallback.clickPrimaryAction();

  const fallbackRequestBody = JSON.parse(preferredFallback.fetchCalls[3].options.body);
  assert.equal(fallbackRequestBody.context.request_level, 'book');
  assert.equal(fallbackRequestBody.release_data, undefined);

  const crossOrigin = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://shelfmark.example.com',
    openUrl: 'https://shelfmark.example.com/?content_type=ebook&sort=relevance&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two',
    requestPayload: {
      book_data: { provider_id: '222', title: 'External Candidate' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    }
  });

  assert.equal(crossOrigin.fetchCalls.length, 0);
  assert.equal(crossOrigin.dom.action.dataset.mode, 'open');
  assert.match(crossOrigin.dom.action.className, /btn-default/);
  assert.equal(
    crossOrigin.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Open in Shelfmark'
  );
  assert.match(crossOrigin.dom.status.textContent, /same-origin|reverse-proxied/i);
  assert.equal(crossOrigin.dom.status.classList.contains('is-settled'), false);

  const releasePolicyFallback = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two',
    requestPayload: {
      book_data: { provider_id: '222', title: 'External Candidate' },
      context: { source: 'direct_download', content_type: 'ebook', request_level: 'book' }
    },
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      {
        payload: {
          requests_enabled: true,
          defaults: { ebook: 'request_book' },
          source_modes: [
            {
              source: 'direct_download',
              browse_results_are_releases: true,
              modes: { ebook: 'request_book' }
            }
          ]
        }
      }
    ]
  });

  assert.equal(releasePolicyFallback.dom.action.dataset.mode, 'open');
  assert.match(releasePolicyFallback.dom.action.className, /btn-default/);
  assert.equal(
    releasePolicyFallback.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Open in Shelfmark'
  );
  assert.match(releasePolicyFallback.dom.status.textContent, /Open in Shelfmark is required/i);

  const enrichedStatus = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two',
    requestPayload: {
      book_data: { provider_id: '222', title: 'External Candidate' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    statusTarget: true,
    statusProviderId: '222',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      {
        payload: {
          requests: [
            {
              id: 91,
              status: 'fulfilled',
              delivery_state: 'queued',
              delivery_updated_at: '2026-04-09T21:45:00Z',
              last_failure_reason: null,
              book_data: { provider: 'hardcover', provider_id: '222' }
            }
          ]
        }
      },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } }
    ]
  });

  assert.equal(enrichedStatus.fetchCalls.length, 3);
  assert.equal(
    enrichedStatus.dom.document.querySelector('.js-shelfmark-status-chip').textContent,
    'In queue'
  );
  assert.equal(
    enrichedStatus.dom.document.querySelector('.js-shelfmark-status-chip').dataset.statusKey,
    'queue'
  );
  assert.equal(
    enrichedStatus.dom.document.querySelector('.js-shelfmark-status-target').classList.contains('is-shelfmark-handled'),
    true
  );

  const importedStatus = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=Already+Present+Author+One&title=Already+Present&author=Author+One',
    requestPayload: {
      book_data: { provider_id: '999', title: 'Already Present' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    statusTarget: true,
    statusProviderId: '999',
    statusInLibrary: true,
    statusChipText: 'In library',
    statusChipKey: 'imported',
    statusChipClass: 'shelfmark-status-chip--imported',
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      {
        payload: {
          requests: [
            {
              id: 92,
              status: 'fulfilled',
              delivery_state: 'complete',
              delivery_updated_at: '2026-04-09T21:55:00Z',
              book_data: { provider: 'hardcover', provider_id: '999' }
            }
          ]
        }
      },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } }
    ]
  });

  assert.equal(
    importedStatus.dom.document.querySelector('.js-shelfmark-status-chip').textContent,
    'In library'
  );
  assert.equal(
    importedStatus.dom.document.querySelector('.js-shelfmark-status-chip').dataset.statusKey,
    'imported'
  );
  assert.equal(
    importedStatus.dom.document.querySelector('.js-shelfmark-status-target').classList.contains('is-shelfmark-handled'),
    true
  );

  const batchReady = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '222', title: 'External Candidate' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    statusTarget: true,
    statusProviderId: '222',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    includeBatchToolbar: true,
    batchToggle: true,
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      { payload: { requests: [] } },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } },
      { payload: { success: true } },
      {
        payload: {
          requests: [
            {
              id: 93,
              status: 'pending',
              created_at: '2026-04-10T09:30:00Z',
              book_data: { provider: 'hardcover', provider_id: '222' }
            }
          ]
        }
      }
    ]
  });

  const batchSelectVisible = batchReady.dom.batchToolbar.querySelector('.js-shelfmark-batch-select-visible');
  const batchClear = batchReady.dom.batchToolbar.querySelector('.js-shelfmark-batch-clear');
  const batchRequest = batchReady.dom.batchToolbar.querySelector('.js-shelfmark-batch-request');
  const batchCount = batchReady.dom.batchToolbar.querySelector('.js-shelfmark-batch-count');
  const batchReadyText = batchReady.dom.batchToolbar.querySelector('.js-shelfmark-batch-ready');
  const batchMessage = batchReady.dom.batchToolbar.querySelector('.js-shelfmark-batch-message');
  const batchModeButton = batchReady.dom.batchModeButton;

  assert.equal(batchReady.dom.batchToolbar.classList.contains('is-hidden'), true);
  assert.equal(batchReady.dom.batchSelect.classList.contains('is-hidden'), true);
  assert.equal(batchReady.dom.batchToggle.disabled, true);
  assert.equal(batchModeButton.textContent, 'Bulk mode');
  assert.equal(batchModeButton.disabled, false);
  assert.equal(
    batchReady.dom.document.querySelector('.js-shelfmark-status-chip').classList.contains('is-hidden'),
    true
  );
  assert.equal(batchCount.textContent, '0 selected');
  assert.equal(batchReadyText.textContent, '1 ready on this page');
  assert.equal(batchSelectVisible.disabled, true);
  assert.equal(batchRequest.disabled, true);

  batchModeButton.dispatchEvent('click');
  await flush();

  assert.equal(batchReady.dom.batchToolbar.classList.contains('is-hidden'), false);
  assert.equal(batchReady.dom.batchSelect.classList.contains('is-hidden'), false);
  assert.equal(batchReady.dom.batchToggle.disabled, false);
  assert.equal(batchModeButton.textContent, 'Done');
  assert.equal(batchSelectVisible.disabled, false);

  batchSelectVisible.dispatchEvent('click');
  await flush();

  assert.equal(batchReady.dom.batchToggle.checked, true);
  assert.equal(batchCount.textContent, '1 selected');
  assert.equal(batchClear.disabled, false);
  assert.equal(batchRequest.disabled, false);

  batchRequest.dispatchEvent('click');
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(batchReady.fetchCalls.length, 5);
  assert.equal(batchReady.fetchCalls[3].options.method, 'POST');
  assert.equal(batchReady.dom.action.dataset.mode, 'open');
  assert.equal(batchReady.dom.batchToolbar.classList.contains('is-hidden'), false);
  assert.equal(batchReady.dom.batchToggle.checked, false);
  assert.equal(batchReady.dom.batchToggle.disabled, true);
  assert.equal(batchReady.dom.batchSelect.classList.contains('is-hidden'), true);
  assert.equal(batchModeButton.textContent, 'Done');
  assert.equal(batchCount.textContent, '0 selected');
  assert.equal(batchReadyText.textContent, '0 ready on this page');
  assert.equal(batchRequest.disabled, true);
  assert.equal(batchMessage.textContent, 'Requested 1 book.');
  assert.equal(batchMessage.classList.contains('is-hidden'), false);
  assert.equal(
    batchReady.dom.document.querySelector('.js-shelfmark-status-chip').textContent,
    'Requested'
  );
  assert.equal(
    batchReady.dom.document.querySelector('.js-shelfmark-status-target').classList.contains('is-shelfmark-handled'),
    true
  );

  const batchBlocked = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '222', title: 'External Candidate' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    statusTarget: true,
    statusProviderId: '222',
    statusChipText: 'Requested',
    statusChipKey: 'requested',
    statusChipClass: 'shelfmark-status-chip--requested',
    includeBatchToolbar: true,
    batchToggle: true,
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      {
        payload: {
          requests: [
            {
              id: 94,
              status: 'pending',
              created_at: '2026-04-10T09:35:00Z',
              book_data: { provider: 'hardcover', provider_id: '222' }
            }
          ]
        }
      },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } }
    ]
  });

  assert.equal(batchBlocked.dom.batchToolbar.classList.contains('is-hidden'), true);
  assert.equal(batchBlocked.dom.batchSelect.classList.contains('is-hidden'), true);
  assert.equal(batchBlocked.dom.batchToggle.disabled, true);
  assert.equal(
    batchBlocked.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Requested'
  );

  const toppedUpSelection = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?query=External+Candidate',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '222', title: 'External Candidate' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    statusTarget: true,
    statusProviderId: '222',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    includeBatchToolbar: true,
    batchToggle: true,
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      { payload: { requests: [] } },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } },
      { payload: { authenticated: true, auth_required: true } },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } }
    ]
  });

  toppedUpSelection.dom.batchModeButton.dispatchEvent('click');
  await flush();
  assert.equal(toppedUpSelection.dom.batchToolbar.classList.contains('is-hidden'), false);
  assert.equal(toppedUpSelection.dom.batchSelect.classList.contains('is-hidden'), false);
  assert.equal(toppedUpSelection.dom.batchToggle.disabled, false);

  const appendedRow = await toppedUpSelection.appendResult({
    openUrl: 'https://library.example.com/shelfmark/?query=Second+Candidate',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '223', title: 'Second Candidate' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    label: 'Request in Shelfmark',
    hint: '',
    buttonClass: 'btn-primary',
    iconClass: 'glyphicon glyphicon-send',
    statusTarget: true,
    statusProviderId: '223',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    batchToggle: true
  });

  const appendedToggle = appendedRow.wrapper.querySelector('.js-shelfmark-batch-toggle');
  const appendedSelect = appendedRow.wrapper.querySelector('.js-shelfmark-batch-select');
  const toppedUpCount = toppedUpSelection.dom.batchToolbar.querySelector('.js-shelfmark-batch-count');
  const toppedUpReady = toppedUpSelection.dom.batchToolbar.querySelector('.js-shelfmark-batch-ready');

  assert.equal(appendedSelect.classList.contains('is-hidden'), false);
  assert.equal(appendedToggle.disabled, false);
  assert.equal(toppedUpReady.textContent, '2 ready on this page');

  toppedUpSelection.dom.batchToolbar.querySelector('.js-shelfmark-batch-select-visible').dispatchEvent('click');
  await flush();

  assert.equal(toppedUpSelection.dom.batchToggle.checked, true);
  assert.equal(appendedToggle.checked, true);
  assert.equal(toppedUpCount.textContent, '2 selected');

  toppedUpSelection.dom.batchModeButton.dispatchEvent('click');
  await flush();

  assert.equal(toppedUpSelection.dom.batchToolbar.classList.contains('is-hidden'), true);
  assert.equal(toppedUpSelection.dom.batchToggle.checked, false);
  assert.equal(appendedToggle.checked, false);
  assert.equal(toppedUpSelection.dom.batchSelect.classList.contains('is-hidden'), true);
  assert.equal(appendedSelect.classList.contains('is-hidden'), true);
  assert.equal(toppedUpCount.textContent, '0 selected');
  assert.equal(toppedUpReady.textContent, '2 ready on this page');

  const directQueued = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=Queued+Book',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '333', title: 'Queued Book' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    preferredReleaseEnabled: true,
    preferredReleaseProvider: 'direct_download',
    preferredReleaseContentType: 'ebook',
    mode: 'request',
    statusTarget: true,
    statusProviderId: '333',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    includeBatchToolbar: true,
    batchToggle: true,
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      { payload: { requests: [] } },
      {
        payload: {
          requests_enabled: true,
          defaults: { ebook: 'request_book' },
          source_modes: [
            {
              source: 'direct_download',
              browse_results_are_releases: true,
              modes: { ebook: 'download' }
            }
          ]
        }
      },
      {
        payload: {
          releases: [
            { source: 'direct_download', source_id: 'dd-1', format: 'epub', seeders: 0 }
          ]
        }
      },
      {
        payload: {
          kind: 'download',
          status: 'queued',
          source: 'direct_download',
          source_id: 'dd-1',
          content_type: 'ebook'
        }
      }
    ]
  });

  await directQueued.clickPrimaryAction();

  assert.equal(
    directQueued.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'In queue'
  );
  assert.equal(
    directQueued.dom.document.querySelector('.js-shelfmark-status-chip').textContent,
    'In queue'
  );
  assert.equal(directQueued.dom.batchToggle.disabled, true);
  assert.equal(directQueued.dom.batchSelect.classList.contains('is-hidden'), true);
  assert.equal(
    directQueued.dom.document.querySelector('.js-shelfmark-status-target').classList.contains('is-shelfmark-handled'),
    true
  );

  const importedAfterQueue = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&query=Imported+Book',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '556', title: 'Imported Book' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    statusTarget: true,
    statusProviderId: '556',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    libraryStatusPayloads: [
      { ok: true, matches: {} },
      {
        ok: true,
        matches: {
          '556': {
            in_library: true,
            book_id: 42,
            book_title: 'Imported Book',
            book_url: '/book/42'
          }
        }
      }
    ],
    responses: [
      { payload: { authenticated: true, auth_required: true } },
      { payload: { requests: [] } },
      { payload: { requests_enabled: true, defaults: { ebook: 'request_book' } } },
      { payload: { success: true } },
      {
        payload: {
          requests: [
            {
              id: 98,
              status: 'fulfilled',
              delivery_state: 'queued',
              delivery_updated_at: '2026-04-10T10:30:00Z',
              book_data: { provider: 'hardcover', provider_id: '556' }
            }
          ]
        }
      }
    ]
  });

  await importedAfterQueue.clickPrimaryAction();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(
    importedAfterQueue.dom.document.querySelector('.js-shelfmark-status-chip').dataset.statusKey,
    'imported'
  );
  assert.equal(
    importedAfterQueue.dom.action.querySelector('.js-shelfmark-action-label').textContent,
    'Open existing CWA book'
  );
  assert.equal(importedAfterQueue.dom.action.getAttribute('href'), '/book/42');
  assert.equal(importedAfterQueue.dom.action.getAttribute('target'), null);

  const concurrentPostResolvers = [];
  const concurrentBatch = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?query=Batch+One',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '500', title: 'Batch One' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    statusTarget: true,
    statusProviderId: '500',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    includeBatchToolbar: true,
    batchToggle: true,
    fetchImpl: (url, fetchOptions, fetchCalls) => {
      fetchCalls.push({ url, options: fetchOptions || {} });
      if (url.endsWith('/api/auth/check')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ authenticated: true, auth_required: true })
        });
      }
      if (url.endsWith('/api/request-policy')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ requests_enabled: true, defaults: { ebook: 'request_book' } })
        });
      }
      if (url.endsWith('/api/activity/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ requests: [] })
        });
      }
      if (url.endsWith('/api/requests') && fetchOptions && fetchOptions.method === 'POST') {
        return new Promise((resolve) => {
          concurrentPostResolvers.push(resolve);
        });
      }
      return Promise.reject(new Error(`Unexpected fetch call for ${url}`));
    }
  });

  await concurrentBatch.appendResult({
    openUrl: 'https://library.example.com/shelfmark/?query=Batch+Two',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '501', title: 'Batch Two' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    label: 'Request in Shelfmark',
    hint: '',
    buttonClass: 'btn-primary',
    iconClass: 'glyphicon glyphicon-send',
    statusTarget: true,
    statusProviderId: '501',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    batchToggle: true
  });
  await flush();
  await flush();
  await flush();

  concurrentBatch.dom.batchModeButton.dispatchEvent('click');
  await flush();
  await flush();
  assert.equal(concurrentBatch.dom.batchToolbar.classList.contains('is-hidden'), false);
  assert.equal(concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-ready').textContent, '2 ready on this page');
  concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-select-visible').dispatchEvent('click');
  await flush();
  concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-request').dispatchEvent('click');
  await flush();
  await flush();

  const concurrentPosts = concurrentBatch.fetchCalls.filter((call) => call.url.endsWith('/api/requests'));
  assert.equal(concurrentPosts.length, 2);
  assert.equal(concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-request').textContent, 'Requesting...');
  assert.equal(concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-count').textContent, '2 selected');

  concurrentPostResolvers.forEach((resolve) => {
    resolve({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ success: true })
    });
  });

  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-count').textContent, '0 selected');
  assert.equal(concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-ready').textContent, '0 ready on this page');
  assert.equal(concurrentBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-message').textContent, 'Requested 2 books.');

  const queuedPostResolvers = [];
  const queuedBatch = await runScenario({
    currentOrigin: 'https://library.example.com',
    baseUrl: 'https://library.example.com/shelfmark',
    openUrl: 'https://library.example.com/shelfmark/?query=Queued+Batch+One',
    requestPayload: {
      book_data: { provider: 'hardcover', provider_id: '600', title: 'Queued Batch One' },
      context: { source: '*', content_type: 'ebook', request_level: 'book' }
    },
    mode: 'request',
    statusTarget: true,
    statusProviderId: '600',
    statusChipText: 'Available to request',
    statusChipKey: 'available',
    statusChipClass: 'shelfmark-status-chip--available',
    includeBatchToolbar: true,
    batchToggle: true,
    fetchImpl: (url, fetchOptions, fetchCalls) => {
      fetchCalls.push({ url, options: fetchOptions || {} });
      if (url.endsWith('/api/auth/check')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ authenticated: true, auth_required: true })
        });
      }
      if (url.endsWith('/api/request-policy')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ requests_enabled: true, defaults: { ebook: 'request_book' } })
        });
      }
      if (url.endsWith('/api/activity/snapshot')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({ requests: [] })
        });
      }
      if (url.endsWith('/api/requests') && fetchOptions && fetchOptions.method === 'POST') {
        return new Promise((resolve) => {
          queuedPostResolvers.push(resolve);
        });
      }
      return Promise.reject(new Error(`Unexpected fetch call for ${url}`));
    }
  });

  const queuedRows = [];
  for (let index = 1; index <= 4; index += 1) {
    // Total requestable rows becomes 5, which exceeds the fixed concurrency budget of 4.
    // The last row should stay visibly in a waiting state until one active request settles.
    queuedRows.push(await queuedBatch.appendResult({
      openUrl: `https://library.example.com/shelfmark/?query=Queued+Batch+${index + 1}`,
      requestPayload: {
        book_data: { provider: 'hardcover', provider_id: String(600 + index), title: `Queued Batch ${index + 1}` },
        context: { source: '*', content_type: 'ebook', request_level: 'book' }
      },
      mode: 'request',
      label: 'Request in Shelfmark',
      hint: '',
      buttonClass: 'btn-primary',
      iconClass: 'glyphicon glyphicon-send',
      statusTarget: true,
      statusProviderId: String(600 + index),
      statusChipText: 'Available to request',
      statusChipKey: 'available',
      statusChipClass: 'shelfmark-status-chip--available',
      batchToggle: true
    }));
  }

  queuedBatch.dom.batchModeButton.dispatchEvent('click');
  await flush();
  queuedBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-select-visible').dispatchEvent('click');
  await flush();
  queuedBatch.dom.batchToolbar.querySelector('.js-shelfmark-batch-request').dispatchEvent('click');
  await flush();
  await flush();

  const queuedPostsInFlight = queuedBatch.fetchCalls.filter((call) => call.url.endsWith('/api/requests'));
  assert.equal(queuedPostsInFlight.length, 4);
  assert.equal(
    queuedRows[3].action.querySelector('.js-shelfmark-action-label').textContent,
    'Waiting'
  );
  assert.equal(
    queuedRows[3].wrapper.querySelector('.js-shelfmark-action-hint').textContent,
    'Waiting for an earlier Shelfmark request slot to free up.'
  );

  queuedPostResolvers.shift()({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => ({ success: true })
  });
  await flush();
  await flush();

  assert.equal(
    queuedBatch.fetchCalls.filter((call) => call.url.endsWith('/api/requests')).length,
    5
  );

  const progressive = await runProgressiveScenario();

  assert.deepEqual(
    progressive.fetchCalls.map((call) => call.url),
    [
      '/row/0',
      '/row/1',
      '/row/2',
      'https://library.example.com/search/external/shelfmark/topup?query=terry+pratchett&shelfmark_source_page=2'
    ]
  );
  assert.equal(progressive.dom.rows[0].classList.contains('is-shelfmark-filter-hidden'), false);
  assert.equal(progressive.dom.rows[1].classList.contains('is-shelfmark-filter-hidden'), false);
  assert.equal(progressive.dom.rows[2].classList.contains('is-shelfmark-filter-hidden'), true);
  assert.equal(progressive.dom.visibleCount.textContent, '3 shown');
  assert.equal(progressive.dom.pageSummary.textContent, '3 shown on this page');
  assert.equal(progressive.dom.emptyState.classList.contains('is-hidden'), true);
  assert.equal(progressive.dom.resultsList.children.length, 4);
  assert.equal(
    progressive.dom.resultsList.querySelectorAll('.js-shelfmark-result-row').length,
    4
  );

  console.log('test_shelfmark_external_search_dom.js: ok');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
