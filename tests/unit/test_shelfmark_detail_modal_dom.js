const assert = require('assert');
const path = require('path');

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
}

class FakeElement {
  constructor(tagName, options) {
    const config = options || {};
    this.tagName = tagName.toUpperCase();
    this.id = config.id || '';
    this.children = [];
    this.parentNode = null;
    this.dataset = Object.assign({}, config.dataset || {});
    this.attributes = Object.assign({}, config.attributes || {});
    this._classes = new Set((config.className || '').split(/\s+/).filter(Boolean));
    this.classList = new FakeClassList(this);
    this.listeners = {};
    this.style = {};
    this._textContent = config.textContent || '';
    this.innerHTML = config.innerHTML || '';
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  addEventListener(name, handler) {
    if (!this.listeners[name]) {
      this.listeners[name] = [];
    }
    this.listeners[name].push(handler);
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
      if (selector === '[data-detail-title]') {
        return Boolean(node.dataset.detailTitle);
      }
      return false;
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

  dispatchClick(options) {
    const config = options || {};
    const handlers = this.listeners.click || [];
    const event = {
      button: typeof config.button === 'number' ? config.button : 0,
      ctrlKey: Boolean(config.ctrlKey),
      metaKey: Boolean(config.metaKey),
      shiftKey: Boolean(config.shiftKey),
      altKey: Boolean(config.altKey),
      defaultPrevented: false,
      preventDefault() {
        this.defaultPrevented = true;
      }
    };
    handlers.forEach((handler) => handler(event));
    return event;
  }

  focus() {
    this.focused = true;
  }

  get textContent() {
    if (this.children.length) {
      return this.children.map((child) => child.textContent).join('');
    }
    return this._textContent;
  }

  set textContent(value) {
    this._textContent = String(value);
  }
}

class FakeDocument {
  constructor(body) {
    this.body = body;
    this.readyState = 'complete';
    this.listeners = {};
  }

  querySelectorAll(selector) {
    return this.body.querySelectorAll(selector);
  }

  querySelector(selector) {
    return this.body.querySelector(selector);
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }

  getElementById(id) {
    return this.body.querySelector(`#${id}`);
  }
}

function createDom() {
  const body = new FakeElement('body', { className: 'page-body' });
  const link = body.appendChild(new FakeElement('a', {
    className: 'btn btn-default btn-sm shelfmark-result-card__secondary-action js-shelfmark-detail-link',
    dataset: { detailTitle: 'External Candidate' },
    attributes: { href: '/search/external/shelfmark/hardcover/222?query=dune' },
    textContent: 'Details'
  }));

  const modal = body.appendChild(new FakeElement('div', {
    id: 'shelfmarkDetailModal',
    className: 'modal fade shelfmark-detail-modal'
  }));
  const modalDialog = modal.appendChild(new FakeElement('div', {
    className: 'modal-dialog modal-lg shelfmark-detail-modal__dialog'
  }));
  const modalContent = modalDialog.appendChild(new FakeElement('div', {
    className: 'modal-content shelfmark-detail-modal__content'
  }));
  const modalHeader = modalContent.appendChild(new FakeElement('div', {
    className: 'modal-header shelfmark-detail-modal__header'
  }));
  const modalTitle = modalHeader.appendChild(new FakeElement('h4', {
    className: 'modal-title shelfmark-detail-modal__title',
    textContent: 'Shelfmark Details'
  }));
  const modalBody = modalContent.appendChild(new FakeElement('div', {
    className: 'modal-body shelfmark-detail-modal__body js-shelfmark-detail-modal-body'
  }));

  return {
    document: new FakeDocument(body),
    link,
    modal,
    modalTitle,
    modalBody
  };
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function runScenario(clickOptions) {
  const dom = createDom();
  const fetchCalls = [];
  const assignedUrls = [];

  delete require.cache[searchModulePath];

  global.window = {
    location: {
      href: 'https://library.example.com/search?query=dune',
      assign(value) {
        assignedUrls.push(value);
      }
    }
  };
  global.document = dom.document;
  global.fetch = (url, options) => {
    fetchCalls.push({ url, options: options || {} });
    return Promise.resolve({
      ok: true,
      text: async () => '<div class="shelfmark-detail-pane shelfmark-detail-pane--modal" data-detail-title="External Candidate">Loaded</div>'
    });
  };

  require(searchModulePath);
  const event = dom.link.dispatchClick(clickOptions);
  await flush();
  await flush();

  return {
    dom,
    event,
    fetchCalls,
    assignedUrls
  };
}

(async function main() {
  const plainClick = await runScenario();

  assert.equal(plainClick.event.defaultPrevented, true);
  assert.equal(plainClick.fetchCalls.length, 1);
  assert.match(plainClick.fetchCalls[0].url, /view=modal/);
  assert.equal(plainClick.dom.modal.classList.contains('in'), true);
  assert.equal(plainClick.dom.modalTitle.textContent, 'External Candidate');
  assert.match(plainClick.dom.modalBody.innerHTML, /shelfmark-detail-pane--modal/);
  assert.deepEqual(plainClick.assignedUrls, []);

  const ctrlClick = await runScenario({ ctrlKey: true });

  assert.equal(ctrlClick.event.defaultPrevented, false);
  assert.equal(ctrlClick.fetchCalls.length, 0);
  assert.equal(ctrlClick.dom.modal.classList.contains('in'), false);
  assert.deepEqual(ctrlClick.assignedUrls, []);

  console.log('test_shelfmark_detail_modal_dom.js: ok');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
