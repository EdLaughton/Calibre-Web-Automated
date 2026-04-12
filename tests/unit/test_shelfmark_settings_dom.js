const assert = require('assert');
const path = require('path');

const modulePath = path.resolve(__dirname, '../../cps/static/js/shelfmark_settings.js');

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
    this.listeners = {};
    this._classes = new Set((config.className || '').split(/\s+/).filter(Boolean));
    this.classList = new FakeClassList(this);
    this._textContent = config.textContent || '';
    this.value = config.value || '';
    this.checked = Boolean(config.checked);
    this.disabled = Boolean(config.disabled);
    this.id = config.id || '';
    if (this.id) {
      this.attributes.id = this.id;
    }
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    this.children = this.children.filter((item) => item !== child);
    child.parentNode = null;
    return child;
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get options() {
    return this.tagName === 'SELECT' ? this.children : undefined;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'id') {
      this.id = String(value);
    }
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
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const matches = [];

    function matchesSelector(node) {
      if (selector.startsWith('.')) {
        return node.classList.contains(selector.slice(1));
      }
      if (selector.startsWith('#')) {
        return node.id === selector.slice(1);
      }
      return node.tagName.toLowerCase() === selector.toLowerCase();
    }

    function walk(node) {
      node.children.forEach((child) => {
        if (matchesSelector(child)) {
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
}

class FakeDocument {
  constructor(root) {
    this.root = root;
    this.readyState = 'complete';
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

  addEventListener() {}
}

function addInput(root, tagName, id, value, extra) {
  return root.appendChild(new FakeElement(tagName, Object.assign({ id, value }, extra || {})));
}

function createDom(currentProviderValue) {
  const root = new FakeElement('div', { className: 'settings-root' });
  addInput(root, 'input', 'config_shelfmark_search', '', { checked: true });
  addInput(root, 'input', 'config_shelfmark_url', 'https://shelfmark.example.com');
  addInput(root, 'input', 'config_shelfmark_browser_url', 'https://books.example.com/shelfmark');
  addInput(root, 'input', 'config_shelfmark_username', 'search');
  addInput(root, 'input', 'config_shelfmark_password_e', '');
  const contentType = addInput(root, 'select', 'config_shelfmark_preferred_release_content_type', 'ebook');
  contentType.appendChild(new FakeElement('option', { value: 'ebook', textContent: 'Ebook' }));
  contentType.appendChild(new FakeElement('option', { value: 'audiobook', textContent: 'Audiobook' }));

  const hidden = addInput(root, 'input', 'config_shelfmark_preferred_release_provider', currentProviderValue || '');
  const select = addInput(root, 'select', 'config_shelfmark_preferred_release_provider_select', '');
  select.appendChild(new FakeElement('option', { value: '', textContent: 'Any compatible source or indexer' }));
  select.appendChild(new FakeElement('option', { value: '__custom__', textContent: 'Custom source or indexer…' }));

  const manualGroup = root.appendChild(new FakeElement('div', {
    id: 'config_shelfmark_preferred_release_provider_manual_group',
    className: 'is-hidden'
  }));
  const manualInput = manualGroup.appendChild(new FakeElement('input', {
    id: 'config_shelfmark_preferred_release_provider_manual',
    value: currentProviderValue || ''
  }));

  const diagnostics = root.appendChild(new FakeElement('div', {
    className: 'js-shelfmark-settings-diagnostics is-hidden',
    dataset: { diagnosticsUrl: '/admin/test_shelfmark_connection' }
  }));
  const button = root.appendChild(new FakeElement('button', {
    className: 'js-test-shelfmark-connection',
    textContent: 'Test Shelfmark connection'
  }));

  return {
    document: new FakeDocument(root),
    root,
    hidden,
    select,
    manualGroup,
    manualInput,
    diagnostics,
    button
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

async function runScenario(currentProviderValue, responsePayload) {
  const dom = createDom(currentProviderValue);
  const fetchCalls = [];

  delete require.cache[modulePath];
  global.document = dom.document;
  global.window = {};
  global.fetch = async (url, options) => {
    fetchCalls.push({ url, options });
    return {
      ok: true,
      async json() {
        return responsePayload;
      }
    };
  };

  const moduleApi = require(modulePath);
  moduleApi.init(dom.document);
  await flush();

  dom.button.dispatchEvent('click');
  await flush();
  await flush();

  return { dom, fetchCalls, moduleApi };
}

(async function main() {
  const discovered = await runScenario('MyAnonamouse', {
    success: true,
    checks: [
      { label: 'Shelfmark base URL', status: 'ok', summary: 'Reachable.' },
      { label: 'Auth/session', status: 'ok', summary: 'Authenticated.' },
      { label: 'Request policy', status: 'ok', summary: 'Loaded.' },
      { label: 'Release lookup', status: 'ok', summary: 'Responded.' },
      { label: 'Preferred provider/indexer options', status: 'ok', summary: 'Loaded.' }
    ],
    provider_options: [
      { value: 'prowlarr', label: 'Prowlarr (source)', kind: 'source' },
      { value: 'MyAnonamouse', label: 'MyAnonamouse (indexer)', kind: 'indexer' }
    ],
    provider_options_message: 'Loaded source and indexer options.'
  });

  assert.equal(discovered.fetchCalls.length, 1);
  assert.equal(discovered.fetchCalls[0].url, '/admin/test_shelfmark_connection');
  const requestPayload = JSON.parse(discovered.fetchCalls[0].options.body);
  assert.equal(requestPayload.config_shelfmark_url, 'https://shelfmark.example.com');
  assert.equal(requestPayload.config_shelfmark_preferred_release_provider, 'MyAnonamouse');
  assert.equal(discovered.dom.select.value, 'MyAnonamouse');
  assert.equal(discovered.dom.hidden.value, 'MyAnonamouse');
  assert.equal(discovered.dom.manualGroup.classList.contains('is-hidden'), true);
  assert.equal(discovered.dom.diagnostics.classList.contains('is-hidden'), false);
  assert.match(discovered.dom.diagnostics.textContent, /Shelfmark connection test completed/i);
  assert.match(discovered.dom.diagnostics.textContent, /Loaded source and indexer options/i);

  const customFallback = await runScenario('CustomIndexer', {
    success: false,
    checks: [
      { label: 'Shelfmark base URL', status: 'ok', summary: 'Reachable.' },
      { label: 'Auth/session', status: 'ok', summary: 'Authenticated.' },
      { label: 'Request policy', status: 'ok', summary: 'Loaded.' },
      { label: 'Release lookup', status: 'warning', summary: 'No indexers exposed.' },
      { label: 'Preferred provider/indexer options', status: 'warning', summary: 'Source-only options loaded.' }
    ],
    provider_options: [
      { value: 'direct_download', label: 'Direct Download (source)', kind: 'source' }
    ],
    provider_options_message: 'Custom indexer fallback remains available.'
  });

  assert.equal(customFallback.dom.select.value, customFallback.moduleApi.CUSTOM_PROVIDER_VALUE);
  assert.equal(customFallback.dom.hidden.value, 'CustomIndexer');
  assert.equal(customFallback.dom.manualInput.value, 'CustomIndexer');
  assert.equal(customFallback.dom.manualGroup.classList.contains('is-hidden'), false);
  assert.match(customFallback.dom.diagnostics.textContent, /Custom indexer fallback remains available/i);

  console.log('test_shelfmark_settings_dom.js: ok');
}()).catch((error) => {
  console.error(error);
  process.exit(1);
});
