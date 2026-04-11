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
    className: `shelfmark-result-card${options.statusTarget ? ' js-shelfmark-status-target' : ''}${options.batchToggle ? ' js-shelfmark-batch-row' : ''}`,
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
      mode: options.mode
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
  if (options.includeBatchToolbar) {
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
    batchToggle: options.batchToggle
  });
  root.appendChild(first.wrapper);

  return {
    document: new FakeDocument(root, 'complete'),
    status,
    action: first.action,
    batchToolbar,
    batchToggle: first.wrapper.querySelector('.js-shelfmark-batch-toggle'),
    batchSelect: first.wrapper.querySelector('.js-shelfmark-batch-select')
  };
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function runScenario(options) {
  const dom = createDom(options);
  const fetchCalls = [];
  const responses = options.responses ? options.responses.slice() : [];

  delete require.cache[flowModulePath];
  delete require.cache[searchModulePath];

  global.window = {
    location: { origin: options.currentOrigin },
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
    }
  };
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

  assert.equal(sameOrigin.fetchCalls.length, 3);
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

  assert.equal(batchReady.dom.batchToolbar.classList.contains('is-hidden'), false);
  assert.equal(batchReady.dom.batchSelect.classList.contains('is-hidden'), false);
  assert.equal(batchReady.dom.batchToggle.disabled, false);
  assert.equal(
    batchReady.dom.document.querySelector('.js-shelfmark-status-chip').classList.contains('is-hidden'),
    true
  );
  assert.equal(batchCount.textContent, '0 selected');
  assert.equal(batchReadyText.textContent, '1 ready on this page');
  assert.equal(batchSelectVisible.disabled, false);
  assert.equal(batchRequest.disabled, true);

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
  assert.equal(batchReady.dom.batchToggle.checked, false);
  assert.equal(batchReady.dom.batchToggle.disabled, true);
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

  console.log('test_shelfmark_external_search_dom.js: ok');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
