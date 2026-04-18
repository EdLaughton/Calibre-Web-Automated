(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.CwaShelfmarkSettings = api;
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var CUSTOM_PROVIDER_VALUE = '__custom__';

  function toText(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function toArray(value) {
    return Array.prototype.slice.call(value || []);
  }

  function dedupeProviderOptions(options) {
    var seen = new Set();
    return (Array.isArray(options) ? options : []).filter(function (option) {
      var value = toText(option && option.value);
      if (!value || seen.has(value)) {
        return false;
      }
      seen.add(value);
      return true;
    }).map(function (option) {
      return {
        value: toText(option && option.value),
        label: toText(option && option.label) || toText(option && option.value),
        kind: toText(option && option.kind) || 'source'
      };
    });
  }

  function clearChildren(node) {
    if (!node) {
      return;
    }
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function appendOption(selectNode, value, label) {
    var optionNode = document.createElement('option');
    optionNode.value = value;
    optionNode.textContent = label;
    selectNode.appendChild(optionNode);
  }

  function optionValues(selectNode) {
    return toArray(selectNode && selectNode.options).map(function (option) {
      return toText(option.value);
    });
  }

  function showManualProviderInput(selectNode, manualGroup, manualInput, hiddenInput) {
    var selectedValue = toText(selectNode && selectNode.value);
    var isCustom = selectedValue === CUSTOM_PROVIDER_VALUE;
    if (manualGroup && manualGroup.classList) {
      manualGroup.classList.toggle('is-hidden', !isCustom);
    }
    if (!hiddenInput) {
      return;
    }
    if (isCustom) {
      hiddenInput.value = toText(manualInput && manualInput.value);
      return;
    }
    hiddenInput.value = selectedValue;
  }

  function populatePreferredProviderSelect(selectNode, manualGroup, manualInput, hiddenInput, options) {
    if (!selectNode || !hiddenInput) {
      return;
    }

    var currentValue = toText(hiddenInput.value);
    var normalizedOptions = dedupeProviderOptions(options);

    clearChildren(selectNode);
    appendOption(selectNode, '', 'Any compatible source or indexer');
    normalizedOptions.forEach(function (option) {
      appendOption(selectNode, option.value, option.label);
    });
    appendOption(selectNode, CUSTOM_PROVIDER_VALUE, 'Custom source or indexer…');

    if (!currentValue) {
      selectNode.value = '';
    } else if (optionValues(selectNode).indexOf(currentValue) !== -1) {
      selectNode.value = currentValue;
    } else {
      selectNode.value = CUSTOM_PROVIDER_VALUE;
      if (manualInput) {
        manualInput.value = currentValue;
      }
    }

    showManualProviderInput(selectNode, manualGroup, manualInput, hiddenInput);
  }

  function buildDiagnosticSummary(response) {
    if (response && response.success) {
      return 'Shelfmark connection test completed.';
    }
    return 'Shelfmark connection test needs attention.';
  }

  function diagnosticTone(checks) {
    var statuses = (Array.isArray(checks) ? checks : []).map(function (check) {
      return toText(check && check.status);
    });
    if (statuses.indexOf('error') !== -1) {
      return 'danger';
    }
    if (statuses.indexOf('warning') !== -1) {
      return 'warning';
    }
    return 'success';
  }

  function renderDiagnostics(container, response) {
    if (!container) {
      return;
    }

    clearChildren(container);
    container.classList.remove('is-hidden', 'shelfmark-settings-diagnostics--success', 'shelfmark-settings-diagnostics--warning', 'shelfmark-settings-diagnostics--danger');

    var checks = Array.isArray(response && response.checks) ? response.checks : [];
    var tone = diagnosticTone(checks);
    container.classList.add('shelfmark-settings-diagnostics--' + tone);

    var summary = document.createElement('div');
    summary.className = 'shelfmark-settings-diagnostics__summary';
    summary.textContent = buildDiagnosticSummary(response);
    container.appendChild(summary);

    var list = document.createElement('ul');
    list.className = 'shelfmark-settings-diagnostics__list';
    checks.forEach(function (check) {
      var item = document.createElement('li');
      item.className = 'shelfmark-settings-diagnostics__item shelfmark-settings-diagnostics__item--' + (toText(check.status) || 'warning');

      var label = document.createElement('strong');
      label.className = 'shelfmark-settings-diagnostics__label';
      label.textContent = toText(check.label);
      item.appendChild(label);

      var summaryNode = document.createElement('span');
      summaryNode.className = 'shelfmark-settings-diagnostics__text';
      summaryNode.textContent = toText(check.summary);
      item.appendChild(summaryNode);

      var detail = toText(check.detail);
      if (detail) {
        var detailNode = document.createElement('div');
        detailNode.className = 'shelfmark-settings-diagnostics__detail';
        detailNode.textContent = detail;
        item.appendChild(detailNode);
      }

      list.appendChild(item);
    });
    container.appendChild(list);

    var providerMessage = toText(response && response.provider_options_message);
    if (providerMessage) {
      var note = document.createElement('div');
      note.className = 'shelfmark-settings-diagnostics__note';
      note.textContent = providerMessage;
      container.appendChild(note);
    }
  }

  function renderDiagnosticError(container, message) {
    renderDiagnostics(container, {
      success: false,
      checks: [
        {
          label: 'Shelfmark connection',
          status: 'error',
          summary: toText(message) || 'Shelfmark connection test failed.'
        }
      ],
      provider_options_message: ''
    });
  }

  function collectDiagnosticPayload(root) {
    var panel = root || document;
    var hiddenProvider = panel.querySelector('#config_shelfmark_preferred_release_provider');
    var providerSelect = panel.querySelector('#config_shelfmark_preferred_release_provider_select');
    var providerManual = panel.querySelector('#config_shelfmark_preferred_release_provider_manual');
    var providerManualGroup = panel.querySelector('#config_shelfmark_preferred_release_provider_manual_group');

    showManualProviderInput(providerSelect, providerManualGroup, providerManual, hiddenProvider);

    return {
      config_shelfmark_search: Boolean(panel.querySelector('#config_shelfmark_search') && panel.querySelector('#config_shelfmark_search').checked),
      config_shelfmark_url: toText(panel.querySelector('#config_shelfmark_url') && panel.querySelector('#config_shelfmark_url').value),
      config_shelfmark_browser_url: toText(panel.querySelector('#config_shelfmark_browser_url') && panel.querySelector('#config_shelfmark_browser_url').value),
      config_shelfmark_username: toText(panel.querySelector('#config_shelfmark_username') && panel.querySelector('#config_shelfmark_username').value),
      config_shelfmark_password_e: toText(panel.querySelector('#config_shelfmark_password_e') && panel.querySelector('#config_shelfmark_password_e').value),
      config_shelfmark_preferred_release_content_type: toText(panel.querySelector('#config_shelfmark_preferred_release_content_type') && panel.querySelector('#config_shelfmark_preferred_release_content_type').value) || 'ebook',
      config_shelfmark_preferred_release_provider: toText(hiddenProvider && hiddenProvider.value)
    };
  }

  function populateFromDiagnostics(root, response) {
    var panel = root || document;
    var selectNode = panel.querySelector('#config_shelfmark_preferred_release_provider_select');
    var manualGroup = panel.querySelector('#config_shelfmark_preferred_release_provider_manual_group');
    var manualInput = panel.querySelector('#config_shelfmark_preferred_release_provider_manual');
    var hiddenInput = panel.querySelector('#config_shelfmark_preferred_release_provider');
    populatePreferredProviderSelect(
      selectNode,
      manualGroup,
      manualInput,
      hiddenInput,
      response && response.provider_options
    );
  }

  async function runDiagnostics(root, button, container) {
    var panel = root || document;
    var endpoint = toText(container && container.dataset ? container.dataset.diagnosticsUrl : '');
    if (!endpoint) {
      renderDiagnosticError(container, 'Shelfmark diagnostics endpoint is not configured.');
      return;
    }

    var payload = collectDiagnosticPayload(panel);
    var originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Testing...';
    renderDiagnostics(container, {
      success: false,
      checks: [
        {
          label: 'Shelfmark connection',
          status: 'warning',
          summary: 'Testing current Shelfmark settings...'
        }
      ],
      provider_options_message: ''
    });

    try {
      var response = await fetch(endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      var data = await response.json();
      renderDiagnostics(container, data);
      populateFromDiagnostics(panel, data);
    } catch (error) {
      renderDiagnosticError(container, error && error.message ? error.message : 'Shelfmark connection test failed.');
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }

  function init(root) {
    var panel = root || document;
    var container = panel.querySelector('.js-shelfmark-settings-diagnostics');
    var button = panel.querySelector('.js-test-shelfmark-connection');
    var selectNode = panel.querySelector('#config_shelfmark_preferred_release_provider_select');
    var manualGroup = panel.querySelector('#config_shelfmark_preferred_release_provider_manual_group');
    var manualInput = panel.querySelector('#config_shelfmark_preferred_release_provider_manual');
    var hiddenInput = panel.querySelector('#config_shelfmark_preferred_release_provider');

    if (!button || !container || !selectNode || !manualInput || !hiddenInput) {
      return;
    }

    populatePreferredProviderSelect(selectNode, manualGroup, manualInput, hiddenInput, []);

    if (selectNode.dataset.bound !== '1') {
      selectNode.dataset.bound = '1';
      selectNode.addEventListener('change', function () {
        showManualProviderInput(selectNode, manualGroup, manualInput, hiddenInput);
      });
    }

    if (manualInput.dataset.bound !== '1') {
      manualInput.dataset.bound = '1';
      manualInput.addEventListener('input', function () {
        showManualProviderInput(selectNode, manualGroup, manualInput, hiddenInput);
      });
    }

    if (button.dataset.bound !== '1') {
      button.dataset.bound = '1';
      button.addEventListener('click', function () {
        runDiagnostics(panel, button, container);
      });
    }
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        init(document);
      });
    } else {
      init(document);
    }
  }

  return {
    CUSTOM_PROVIDER_VALUE: CUSTOM_PROVIDER_VALUE,
    collectDiagnosticPayload: collectDiagnosticPayload,
    dedupeProviderOptions: dedupeProviderOptions,
    init: init,
    populatePreferredProviderSelect: populatePreferredProviderSelect,
    renderDiagnostics: renderDiagnostics,
    showManualProviderInput: showManualProviderInput
  };
}));
