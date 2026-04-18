const assert = require('assert');
const path = require('path');

const notifierModulePath = path.resolve(__dirname, '../../cps/static/js/duplicate-notifier.js');

class FakeClassList {
  constructor() {
    this.classes = new Set();
  }

  add(...names) {
    names.filter(Boolean).forEach((name) => this.classes.add(name));
  }

  remove(...names) {
    names.filter(Boolean).forEach((name) => this.classes.delete(name));
  }

  contains(name) {
    return this.classes.has(name);
  }
}

class FakeElement {
  constructor(id) {
    this.id = id || '';
    this.classList = new FakeClassList();
    this.listeners = {};
    this.style = {};
    this.textContent = '';
    this.innerHTML = '';
  }

  addEventListener(name, handler) {
    if (!this.listeners[name]) {
      this.listeners[name] = [];
    }
    this.listeners[name].push(handler);
  }

  focus() {
    this.focused = true;
  }
}

function createEnvironment() {
  const duplicateBadge = new FakeElement('duplicate-count-badge');
  const modal = new FakeElement('duplicate-notification-modal');
  const backdrop = new FakeElement('duplicate-notification-backdrop');
  const closeButton = new FakeElement('duplicate-notification-close');
  const remindButton = new FakeElement('duplicate-notification-remind');
  const modalCount = new FakeElement('duplicate-notification-count');
  const preview = new FakeElement('duplicate-notification-preview');

  const elements = {
    'duplicate-count-badge': duplicateBadge,
    'duplicate-notification-modal': modal,
    'duplicate-notification-backdrop': backdrop,
    'duplicate-notification-close': closeButton,
    'duplicate-notification-remind': remindButton,
    'duplicate-notification-count': modalCount,
    'duplicate-notification-preview': preview
  };

  const documentListeners = {};
  const document = {
    readyState: 'complete',
    hidden: false,
    addEventListener(name, handler) {
      if (!documentListeners[name]) {
        documentListeners[name] = [];
      }
      documentListeners[name].push(handler);
    },
    getElementById(id) {
      return elements[id] || null;
    },
    createElement() {
      return {
        _textContent: '',
        _innerHTML: '',
        set textContent(value) {
          this._textContent = String(value);
          this._innerHTML = this._textContent;
        },
        get innerHTML() {
          return this._innerHTML;
        }
      };
    }
  };

  const sessionStorageState = new Map();
  const sessionStorage = {
    getItem(key) {
      return sessionStorageState.has(key) ? sessionStorageState.get(key) : null;
    },
    setItem(key, value) {
      sessionStorageState.set(key, String(value));
    }
  };

  const windowObject = {
    cwaDuplicateBootstrap: {
      enabled: true,
      count: 0,
      preview: [],
      cached: true,
      stale: false
    }
  };

  return {
    document,
    documentListeners,
    windowObject,
    sessionStorage,
    duplicateBadge
  };
}

(function testBootstrapDoesNotFetchFreshDuplicateStatus() {
  const env = createEnvironment();
  let fetchCalls = 0;

  global.document = env.document;
  global.window = env.windowObject;
  global.sessionStorage = env.sessionStorage;
  global.fetch = function() {
    fetchCalls += 1;
    return Promise.resolve({
      json() {
        return Promise.resolve({ success: true, enabled: true, count: 0, preview: [] });
      }
    });
  };
  global.getPath = function() {
    return '';
  };
  global.setTimeout = function(callback) {
    callback();
    return 1;
  };

  delete require.cache[notifierModulePath];
  require(notifierModulePath);

  assert.strictEqual(fetchCalls, 0, 'fresh bootstrap should not trigger an immediate status fetch');
  assert.strictEqual(env.duplicateBadge.style.display, 'none');
  assert.ok(global.window.CWADuplicates);

  env.document.hidden = false;
  (env.documentListeners.visibilitychange || []).forEach((handler) => handler());
  assert.strictEqual(fetchCalls, 0, 'fresh bootstrap should not refetch on visibility restore');
})();

console.log('duplicate notifier bootstrap tests passed');
