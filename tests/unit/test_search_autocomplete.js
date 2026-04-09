const assert = require("assert");
const autocomplete = require("../../cps/static/js/search-autocomplete.js");

assert.strictEqual(autocomplete.getNextActiveIndex(-1, 1, 4), 0);
assert.strictEqual(autocomplete.getNextActiveIndex(0, 1, 4), 1);
assert.strictEqual(autocomplete.getNextActiveIndex(0, -1, 4), 3);
assert.strictEqual(autocomplete.getNextActiveIndex(-1, -1, 4), 3);
assert.strictEqual(autocomplete.getNextActiveIndex(3, 1, 4), 0);
assert.strictEqual(
    autocomplete.highlightMatch("The Churn", "churn"),
    "The <mark class=\"cwa-autocomplete-match\">Churn</mark>"
);
assert.strictEqual(
    autocomplete.highlightMatch("James S. A. Corey", "core"),
    "James S. A. <mark class=\"cwa-autocomplete-match\">Core</mark>y"
);

console.log("ok");
