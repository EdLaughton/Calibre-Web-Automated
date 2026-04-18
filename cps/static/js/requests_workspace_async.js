(function () {
  'use strict';

  var MAX_CONCURRENT_REQUESTS = 2;

  function getShells(root) {
    return Array.prototype.slice.call((root || document).querySelectorAll('.js-requests-section-shell[data-section-url]'));
  }

  function trimHtml(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function replaceNodeFromHtml(node, html) {
    var template = document.createElement('template');
    template.innerHTML = trimHtml(html);
    var replacement = template.content.firstElementChild;
    if (!replacement) {
      node.classList.add('is-hidden');
      return null;
    }
    node.replaceWith(replacement);
    return replacement;
  }

  function initShelfmarkScope(scope) {
    if (window.CwaShelfmarkExternalSearch && typeof window.CwaShelfmarkExternalSearch.init === 'function') {
      window.CwaShelfmarkExternalSearch.init(scope || document);
    }
  }

  function renderFailure(shell) {
    var placeholder = shell.querySelector('.requests-workspace-section__placeholder');
    if (!placeholder) {
      return;
    }
    placeholder.classList.add('is-error');
    placeholder.innerHTML = (
      '<span class="glyphicon glyphicon-warning-sign" aria-hidden="true"></span>' +
      '<span>' + (shell.getAttribute('data-failure-message') || 'Could not load this Requests section right now.') + '</span>'
    );
  }

  function fetchSection(shell) {
    if (!shell || shell.dataset.loaded === '1' || shell.dataset.pending === '1') {
      return Promise.resolve();
    }
    shell.dataset.pending = '1';
    return fetch(shell.getAttribute('data-section-url'), {
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    }).then(function (response) {
      if (!response.ok) {
        throw new Error('requests_section_failed');
      }
      return response.text();
    }).then(function (html) {
      var replacement = replaceNodeFromHtml(shell, html);
      if (replacement) {
        initShelfmarkScope(replacement);
      }
    }).catch(function () {
      renderFailure(shell);
    }).finally(function () {
      shell.dataset.pending = '0';
      shell.dataset.loaded = '1';
    });
  }

  function drainQueue(shells) {
    var queue = shells.slice();
    var active = 0;

    function schedule() {
      while (active < MAX_CONCURRENT_REQUESTS && queue.length) {
        active += 1;
        fetchSection(queue.shift()).finally(function () {
          active -= 1;
          schedule();
        });
      }
    }

    schedule();
  }

  function init(root) {
    var shells = getShells(root);
    if (!shells.length) {
      return;
    }
    drainQueue(shells);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      init(document);
    });
  } else {
    init(document);
  }
}());
