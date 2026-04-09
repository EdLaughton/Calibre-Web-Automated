const assert = require("assert");
const autocomplete = require("../../cps/static/js/search-autocomplete.js");

class FakeClassList {
    constructor() {
        this._classes = new Set();
    }

    add(name) {
        this._classes.add(name);
    }

    remove(name) {
        this._classes.delete(name);
    }

    toggle(name, force) {
        if (force === true) {
            this._classes.add(name);
            return true;
        }
        if (force === false) {
            this._classes.delete(name);
            return false;
        }
        if (this._classes.has(name)) {
            this._classes.delete(name);
            return false;
        }
        this._classes.add(name);
        return true;
    }

    contains(name) {
        return this._classes.has(name);
    }
}

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.eventHandlers = {};
        this.attributes = {};
        this.classList = new FakeClassList();
        this.hidden = false;
        this.className = "";
        this.parentNode = null;
        this.value = "";
        this._innerHTML = "";
    }

    appendChild(child) {
        child.parentNode = this;
        this.children.push(child);
        return child;
    }

    addEventListener(type, handler) {
        this.eventHandlers[type] = handler;
    }

    dispatch(type, event) {
        if (this.eventHandlers[type]) {
            this.eventHandlers[type](event || {});
        }
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === "id") {
            this.id = String(value);
        }
    }

    getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
    }

    removeAttribute(name) {
        delete this.attributes[name];
    }

    contains(target) {
        if (target === this) {
            return true;
        }
        return this.children.some((child) => child.contains(target));
    }

    get innerHTML() {
        return this._innerHTML;
    }

    set innerHTML(value) {
        this._innerHTML = String(value);
        if (value === "") {
            this.children = [];
        }
    }
}

function createEnvironment() {
    const input = new FakeElement("input");
    const menu = new FakeElement("div");
    const form = new FakeElement("form");
    const docHandlers = {};
    const locationCalls = [];
    const fetchCalls = [];
    const timeoutQueue = [];

    input.value = "";
    input.setAttribute("aria-expanded", "false");

    form.querySelector = function (selector) {
        if (selector === "#query") {
            return input;
        }
        if (selector === "#query_autocomplete") {
            return menu;
        }
        return null;
    };
    form.getAttribute = function (name) {
        if (name === "data-autocomplete-url") {
            return "/search/autocomplete";
        }
        return null;
    };
    form.contains = function (target) {
        return target === form || target === input || target === menu || menu.contains(target);
    };

    const document = {
        readyState: "complete",
        querySelector(selector) {
            return selector === ".cwa-navbar-search" ? form : null;
        },
        createElement(tagName) {
            return new FakeElement(tagName);
        },
        addEventListener(type, handler) {
            docHandlers[type] = handler;
        }
    };

    const windowObject = {
        location: {
            assign(href) {
                locationCalls.push(href);
            }
        },
        setTimeout(handler) {
            timeoutQueue.push(handler);
            return timeoutQueue.length;
        },
        clearTimeout() {
            return undefined;
        }
    };

    global.document = document;
    global.window = windowObject;
    global.fetch = function (url) {
        fetchCalls.push(url);
        return Promise.resolve({
            ok: true,
            json() {
                return Promise.resolve({
                    query: "corey",
                    suggestions: [
                        {
                            type: "author",
                            icon: "user",
                            label: "Author",
                            primary_text: "James S. A. Corey",
                            secondary_text: "12 books",
                            href: "/author/7"
                        }
                    ],
                    show_all: {
                        label: 'Show all results for "corey"',
                        href: "/search?query=corey"
                    }
                });
            }
        });
    };

    return {
        form,
        input,
        menu,
        document,
        documentHandlers: docHandlers,
        locationCalls,
        fetchCalls,
        flushTimeout() {
            while (timeoutQueue.length) {
                const handler = timeoutQueue.shift();
                handler();
            }
        }
    };
}

async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((resolve) => setImmediate(resolve));
}

async function run() {
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

    const deferredDocument = {
        readyState: "loading",
        addEventListener(type, handler) {
            this.boundType = type;
            this.boundHandler = handler;
        },
        querySelector() {
            return null;
        }
    };
    assert.strictEqual(autocomplete.bootNavbarAutocomplete(deferredDocument), "deferred");
    assert.strictEqual(deferredDocument.boundType, "DOMContentLoaded");

    const env = createEnvironment();
    const instance = autocomplete.bootNavbarAutocomplete(env.document);
    assert.ok(instance);
    assert.strictEqual(autocomplete.initNavbarAutocomplete(env.document), instance);

    env.input.value = "corey";
    env.input.dispatch("input");
    env.flushTimeout();
    assert.deepStrictEqual(env.fetchCalls, ["/search/autocomplete?q=corey"]);
    assert.strictEqual(env.form.classList.contains("is-loading"), true);

    await flushPromises();

    assert.strictEqual(env.menu.hidden, false);
    assert.strictEqual(env.form.classList.contains("is-open"), true);
    assert.strictEqual(env.form.classList.contains("is-loading"), false);
    assert.strictEqual(env.menu.children[0].className, "cwa-autocomplete-item cwa-autocomplete-item-author");
    assert.ok(env.menu.children[0].innerHTML.includes("Author"));
    assert.ok(env.menu.children[0].innerHTML.includes("James S. A."));
    assert.ok(env.menu.children[0].innerHTML.includes("cwa-autocomplete-match"));

    env.menu.children[0].dispatch("click");
    assert.deepStrictEqual(env.locationCalls, ["/author/7"]);

    instance.renderPayload({
        query: "nomatch",
        suggestions: [],
        show_all: {
            label: 'Show all results for "nomatch"',
            href: "/search?query=nomatch"
        }
    });
    assert.strictEqual(env.menu.hidden, false);
    assert.strictEqual(env.menu.children[0].className, "cwa-autocomplete-message cwa-autocomplete-message-empty");
    assert.ok(env.menu.children[0].innerHTML.includes("No local matches for"));
    assert.ok(env.menu.children[0].innerHTML.includes("nomatch"));

    console.log("ok");
}

run().catch((error) => {
    console.error(error);
    process.exit(1);
});
