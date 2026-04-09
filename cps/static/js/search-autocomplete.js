/* global window, document */
(function (root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = factory();
    } else {
        root.CWASearchAutocomplete = factory();
    }
}(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function highlightMatch(text, query) {
        var source = String(text || "");
        var needle = String(query || "").trim();
        if (!needle) {
            return escapeHtml(source);
        }

        var lowerSource = source.toLowerCase();
        var lowerNeedle = needle.toLowerCase();
        var index = lowerSource.indexOf(lowerNeedle);
        if (index === -1) {
            return escapeHtml(source);
        }

        var before = escapeHtml(source.slice(0, index));
        var match = escapeHtml(source.slice(index, index + needle.length));
        var after = escapeHtml(source.slice(index + needle.length));
        return before + '<mark class="cwa-autocomplete-match">' + match + "</mark>" + after;
    }

    function getNextActiveIndex(currentIndex, direction, itemCount) {
        if (!itemCount) {
            return -1;
        }
        if (currentIndex === -1) {
            return direction > 0 ? 0 : itemCount - 1;
        }
        return (currentIndex + direction + itemCount) % itemCount;
    }

    function buildItemMarkup(item, query) {
        var secondary = item.secondary_text
            ? '<div class="cwa-autocomplete-secondary">' + escapeHtml(item.secondary_text) + "</div>"
            : "";
        return ''
            + '<span class="glyphicon glyphicon-' + escapeHtml(item.icon) + ' cwa-autocomplete-icon" aria-hidden="true"></span>'
            + '<span class="cwa-autocomplete-copy">'
            + '<span class="cwa-autocomplete-primary">' + highlightMatch(item.primary_text, query) + "</span>"
            + secondary
            + "</span>"
            + '<span class="label label-default cwa-autocomplete-badge">' + escapeHtml(item.label) + "</span>";
    }

    function buildShowAllMarkup(item) {
        return ''
            + '<span class="glyphicon glyphicon-search cwa-autocomplete-icon" aria-hidden="true"></span>'
            + '<span class="cwa-autocomplete-copy">'
            + '<span class="cwa-autocomplete-primary">' + escapeHtml(item.label) + "</span>"
            + "</span>";
    }

    function requestJson(url, signal) {
        var options = {
            credentials: "same-origin",
            headers: {
                "Accept": "application/json"
            }
        };
        if (signal) {
            options.signal = signal;
        }
        return fetch(url, options).then(function (response) {
            if (!response.ok) {
                throw new Error("Autocomplete request failed");
            }
            return response.json();
        });
    }

    function createNavbarAutocomplete(form) {
        var input = form.querySelector("#query");
        var menu = form.querySelector("#query_autocomplete");
        var endpoint = form.getAttribute("data-autocomplete-url");

        if (!input || !menu || !endpoint) {
            return null;
        }

        var debounceTimer = null;
        var state = {
            activeIndex: -1,
            items: [],
            requestId: 0,
            controller: null
        };

        function closeMenu() {
            state.activeIndex = -1;
            state.items = [];
            menu.innerHTML = "";
            menu.hidden = true;
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
        }

        function setActiveIndex(index) {
            state.activeIndex = index;
            state.items.forEach(function (item, itemIndex) {
                var isActive = itemIndex === index;
                item.element.classList.toggle("is-active", isActive);
                item.element.setAttribute("aria-selected", isActive ? "true" : "false");
                if (isActive) {
                    input.setAttribute("aria-activedescendant", item.element.id);
                }
            });
            if (index === -1) {
                input.removeAttribute("aria-activedescendant");
            }
        }

        function navigateTo(href) {
            window.location.assign(href);
        }

        function renderPayload(payload) {
            menu.innerHTML = "";
            state.items = [];
            state.activeIndex = -1;

            (payload.suggestions || []).forEach(function (item, index) {
                var button = document.createElement("button");
                button.type = "button";
                button.className = "cwa-autocomplete-item";
                button.id = "cwa-autocomplete-item-" + index;
                button.setAttribute("role", "option");
                button.setAttribute("aria-selected", "false");
                button.innerHTML = buildItemMarkup(item, payload.query);
                button.addEventListener("mouseenter", function () {
                    setActiveIndex(state.items.indexOf(entry));
                });
                button.addEventListener("click", function () {
                    navigateTo(item.href);
                });

                var entry = {
                    href: item.href,
                    element: button
                };
                state.items.push(entry);
                menu.appendChild(button);
            });

            if (payload.show_all) {
                var divider = state.items.length ? document.createElement("div") : null;
                if (divider) {
                    divider.className = "cwa-autocomplete-divider";
                    menu.appendChild(divider);
                }
                var showAll = document.createElement("button");
                showAll.type = "button";
                showAll.className = "cwa-autocomplete-item cwa-autocomplete-show-all";
                showAll.id = "cwa-autocomplete-item-show-all";
                showAll.setAttribute("role", "option");
                showAll.setAttribute("aria-selected", "false");
                showAll.innerHTML = buildShowAllMarkup(payload.show_all);
                showAll.addEventListener("mouseenter", function () {
                    setActiveIndex(state.items.indexOf(entryShowAll));
                });
                showAll.addEventListener("click", function () {
                    navigateTo(payload.show_all.href);
                });

                var entryShowAll = {
                    href: payload.show_all.href,
                    element: showAll
                };
                state.items.push(entryShowAll);
                menu.appendChild(showAll);
            }

            if (!state.items.length) {
                closeMenu();
                return;
            }

            menu.hidden = false;
            input.setAttribute("aria-expanded", "true");
        }

        function fetchSuggestions(query) {
            var trimmed = String(query || "").trim();
            if (!trimmed) {
                closeMenu();
                return;
            }

            state.requestId += 1;
            var requestId = state.requestId;
            if (state.controller && typeof state.controller.abort === "function") {
                state.controller.abort();
            }
            state.controller = typeof AbortController !== "undefined" ? new AbortController() : null;

            requestJson(endpoint + "?q=" + encodeURIComponent(trimmed), state.controller ? state.controller.signal : null)
                .then(function (payload) {
                    if (requestId !== state.requestId) {
                        return;
                    }
                    renderPayload(payload);
                })
                .catch(function (error) {
                    if (error && error.name === "AbortError") {
                        return;
                    }
                    closeMenu();
                });
        }

        function queueFetch() {
            window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(function () {
                fetchSuggestions(input.value);
            }, 120);
        }

        input.addEventListener("input", queueFetch);
        input.addEventListener("focus", function () {
            if (input.value.trim()) {
                queueFetch();
            }
        });
        input.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closeMenu();
                return;
            }
            if (menu.hidden || !state.items.length) {
                return;
            }
            if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex(getNextActiveIndex(state.activeIndex, 1, state.items.length));
                return;
            }
            if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex(getNextActiveIndex(state.activeIndex, -1, state.items.length));
                return;
            }
            if (event.key === "Enter" && state.activeIndex !== -1) {
                event.preventDefault();
                navigateTo(state.items[state.activeIndex].href);
            }
        });

        menu.addEventListener("mousedown", function (event) {
            event.preventDefault();
        });

        document.addEventListener("click", function (event) {
            if (!form.contains(event.target)) {
                closeMenu();
            }
        });

        form.addEventListener("submit", function () {
            closeMenu();
        });

        return {
            close: closeMenu,
            renderPayload: renderPayload,
            fetchSuggestions: fetchSuggestions,
            getState: function () {
                return state;
            }
        };
    }

    function initNavbarAutocomplete() {
        if (typeof document === "undefined") {
            return null;
        }
        var form = document.querySelector(".cwa-navbar-search");
        if (!form) {
            return null;
        }
        return createNavbarAutocomplete(form);
    }

    if (typeof document !== "undefined") {
        document.addEventListener("DOMContentLoaded", function () {
            initNavbarAutocomplete();
        });
    }

    return {
        escapeHtml: escapeHtml,
        highlightMatch: highlightMatch,
        getNextActiveIndex: getNextActiveIndex,
        createNavbarAutocomplete: createNavbarAutocomplete,
        initNavbarAutocomplete: initNavbarAutocomplete
    };
}));
