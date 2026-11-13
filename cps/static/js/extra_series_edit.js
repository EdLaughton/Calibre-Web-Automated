(function () {
  var add = document.getElementById('nova-add-series');
  var count = document.getElementById('nova-series-count');
  var rows = document.getElementById('nova-series-rows');
  var template = document.getElementById('nova-series-template');
  var clearPrimary = document.getElementById('nova-clear-primary');
  function updateCustomType(row, focus) {
    var select = row.querySelector('.nova-series-kind');
    var input = row.querySelector('.nova-series-custom-kind');
    if (!select || !input) return;
    var custom = select.value === 'custom';
    input.style.display = custom ? '' : 'none';
    input.disabled = !custom;
    input.required = custom;
    if (custom && focus) input.focus();
  }
  if (clearPrimary) {
    clearPrimary.addEventListener('click', function () {
      document.getElementById('series').value = '';
      document.getElementById('series_index').value = '0';
    });
  }
  if (!add || !count || !rows || !template) return;
  rows.querySelectorAll('.nova-series-row').forEach(updateCustomType);
  add.addEventListener('click', function () {
    var index = Number(count.value);
    if (!Number.isInteger(index) || index >= 100) return;
    var row = template.content.querySelector('tr').cloneNode(true);
    row.dataset.index = String(index);
    row.querySelectorAll('[name]').forEach(function (element) {
      element.name = element.name.replace('__INDEX__', String(index));
    });
    rows.appendChild(row);
    updateCustomType(row);
    count.value = String(index + 1);
    row.querySelector('[name^="nova_name_"]').focus();
  });
  rows.addEventListener('click', function (event) {
    var button = event.target.closest('.nova-series-remove');
    if (!button) return;
    var row = button.closest('.nova-series-row');
    if (row.dataset.existing === '1') {
      row.querySelector('[name^="nova_remove_"]').value = '1';
      row.style.display = 'none';
    } else {
      row.remove();
    }
  });
  rows.addEventListener('change', function (event) {
    if (event.target.classList.contains('nova-series-kind')) {
      updateCustomType(event.target.closest('.nova-series-row'), true);
    }
  });
}());
