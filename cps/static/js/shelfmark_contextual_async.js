(function () {
  'use strict';

  function toArray(value) {
    return Array.prototype.slice.call(value || []);
  }

  function parseHtml(html) {
    var template = document.createElement('template');
    template.innerHTML = html || '';
    return template.content;
  }

  function getExternalSearchRuntime() {
    return window.CwaShelfmarkExternalSearch || null;
  }

  function initInjectedShelfmark(root) {
    var runtime = getExternalSearchRuntime();
    if (runtime && typeof runtime.init === 'function') {
      runtime.init(root);
    }
  }

  function setLoadingState(container, isLoading) {
    container.classList.toggle('is-loading', Boolean(isLoading));
  }

  function renderFailure(container, message) {
    var shell = container.closest ? container.closest('.js-shelfmark-contextual-shell') : null;
    container.innerHTML = (
      '<p class="shelfmark-contextual-page__message">' +
      (message || container.dataset.failureMessage || 'Shelfmark is unavailable right now.') +
      '</p>'
    );
    container.classList.remove('is-hidden');
    if (shell && shell.classList) {
      shell.classList.remove('is-hidden');
    }
  }

  function hideContainer(container) {
    var shell = container.closest ? container.closest('.js-shelfmark-contextual-shell') : null;
    container.innerHTML = '';
    container.classList.add('is-hidden');
    if (shell && shell.classList) {
      shell.classList.add('is-hidden');
    }
  }

  function fetchHtml(url) {
    return fetch(url, {
      credentials: 'same-origin',
      headers: {
        'Accept': 'text/html',
        'X-Requested-With': 'XMLHttpRequest'
      }
    }).then(function (response) {
      if (!response.ok) {
        throw new Error('Shelfmark contextual request failed.');
      }
      return response.text();
    });
  }

  function replaceSection(container, html) {
    var shell = container.closest ? container.closest('.js-shelfmark-contextual-shell') : null;
    if (!html || !html.trim()) {
      hideContainer(container);
      return;
    }
    container.innerHTML = html;
    container.classList.remove('is-hidden');
    if (shell && shell.classList) {
      shell.classList.remove('is-hidden');
    }
    initInjectedShelfmark(container);
  }

  function replaceLoadMoreControl(container, fragment) {
    var currentWrap = container.querySelector('.js-shelfmark-contextual-load-more-wrap');
    var nextWrap = fragment.querySelector('.js-shelfmark-contextual-load-more-wrap');
    if (currentWrap && currentWrap.parentNode) {
      currentWrap.parentNode.removeChild(currentWrap);
    }
    if (nextWrap) {
      container.appendChild(nextWrap);
    }
  }

  function appendMoreRows(container, html) {
    if (!html || !html.trim()) {
      replaceLoadMoreControl(container, document.createDocumentFragment());
      return;
    }

    var fragment = parseHtml(html);
    var currentList = container.querySelector('.js-shelfmark-results-list');
    var responseList = fragment.querySelector('.js-shelfmark-results-list');
    var appendedNodes = [];

    if (currentList && responseList) {
      toArray(responseList.children).forEach(function (node) {
        appendedNodes.push(node);
        currentList.appendChild(node);
      });
    }

    replaceLoadMoreControl(container, fragment);
    appendedNodes.forEach(function (node) {
      initInjectedShelfmark(node);
    });
  }

  function setLoadMoreFailure(button, message) {
    var wrap = button && button.closest ? button.closest('.js-shelfmark-contextual-load-more-wrap') : null;
    var messageNode = wrap ? wrap.querySelector('.js-shelfmark-contextual-load-more-message') : null;
    if (!messageNode) {
      return;
    }
    messageNode.textContent = message;
    messageNode.classList.remove('is-hidden');
  }

  function clearLoadMoreFailure(button) {
    var wrap = button && button.closest ? button.closest('.js-shelfmark-contextual-load-more-wrap') : null;
    var messageNode = wrap ? wrap.querySelector('.js-shelfmark-contextual-load-more-message') : null;
    if (!messageNode) {
      return;
    }
    messageNode.textContent = '';
    messageNode.classList.add('is-hidden');
  }

  function bindContainer(container) {
    if (!container || container.dataset.asyncBound === '1') {
      return;
    }
    container.dataset.asyncBound = '1';

    container.addEventListener('click', function (event) {
      var button = event.target && event.target.closest
        ? event.target.closest('.js-shelfmark-contextual-load-more')
        : null;
      if (!button) {
        return;
      }

      event.preventDefault();
      if (button.disabled || !button.dataset.loadUrl) {
        return;
      }

      clearLoadMoreFailure(button);
      button.disabled = true;
      button.dataset.defaultLabel = button.dataset.defaultLabel || button.textContent;
      button.textContent = 'Loading…';

      fetchHtml(button.dataset.loadUrl).then(function (html) {
        appendMoreRows(container, html);
      }).catch(function () {
        button.disabled = false;
        button.textContent = button.dataset.defaultLabel || 'Load more';
        setLoadMoreFailure(
          button,
          container.dataset.loadMoreFailureMessage || 'Could not load more Shelfmark results right now.'
        );
      });
    });
  }

  function loadInitialSection(container) {
    if (!container || !container.dataset.initialUrl) {
      return Promise.resolve();
    }

    setLoadingState(container, true);
    bindContainer(container);
    return fetchHtml(container.dataset.initialUrl).then(function (html) {
      replaceSection(container, html);
      bindContainer(container);
    }).catch(function () {
      renderFailure(
        container,
        container.dataset.failureMessage || 'Shelfmark is unavailable right now.'
      );
    }).finally(function () {
      setLoadingState(container, false);
    });
  }

  function init(root) {
    toArray((root || document).querySelectorAll('.js-shelfmark-contextual-async')).forEach(function (container) {
      loadInitialSection(container);
    });
  }

  window.CwaShelfmarkContextualAsync = {
    init: init
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      init(document);
    });
  } else {
    init(document);
  }
}());
