(() => {
    "use strict";
    for (const panel of document.querySelectorAll(".request-file-review")) {
        const search = panel.querySelector(".request-work-search");
        const matches = panel.querySelector(".request-work-matches");
        const work = panel.querySelector(".request-selected-work");
        const edition = panel.querySelector(".request-selected-edition");
        const choices = panel.querySelector(".request-edition-choice");
        let timer;
        let version = 0;

        async function json(url) {
            const response = await fetch(url);
            const body = await response.json();
            if (!response.ok) throw new Error(body.error || "Hardcover is unavailable.");
            return body;
        }

        async function editions() {
            choices.replaceChildren(new Option("No exact edition proven", "0"));
            edition.value = "0";
            if (!work.value) return;
            try {
                const url = panel.dataset.editions + "?" + new URLSearchParams({work: panel.dataset.work,
                    target: work.value});
                const data = await json(url);
                for (const row of data.editions) {
                    const label = [row.title, row.isbn_13, (row.publisher || {}).name,
                        "Hardcover edition " + row.id].filter(Boolean).join(" · ");
                    choices.add(new Option(label, row.id));
                }
                if (data.editions.length === 1) {
                    choices.value = String(data.editions[0].id);
                    edition.value = String(data.editions[0].id);
                }
            } catch (error) {
                choices.add(new Option(error.message, "0"));
            }
        }

        async function find() {
            const q = search.value.trim();
            matches.replaceChildren();
            if (q.length < 3) return;
            const mine = ++version;
            try {
                const data = await json(panel.dataset.search + "?" + new URLSearchParams({q}));
                if (mine !== version) return;
                for (const book of data.results) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "request-work-match";
                    if (book.cover_url) {
                        const cover = document.createElement("img");
                        cover.src = book.cover_url;
                        cover.alt = "";
                        cover.loading = "lazy";
                        cover.referrerPolicy = "no-referrer";
                        button.append(cover);
                    }
                    const label = document.createElement("span");
                    label.textContent = book.title + " · " + book.authors.join(", ") +
                        " · Hardcover work " + book.work;
                    button.append(label);
                    button.addEventListener("click", () => {
                        work.value = String(book.work);
                        matches.replaceChildren();
                        editions();
                    });
                    matches.append(button);
                }
                if (!data.results.length) matches.textContent = "No matching Hardcover books.";
            } catch (error) {
                if (mine === version) matches.textContent = error.message;
            }
        }

        search.addEventListener("input", () => {
            clearTimeout(timer);
            timer = setTimeout(find, 350);
        });
        work.addEventListener("change", editions);
        choices.addEventListener("change", () => { edition.value = choices.value; });
        panel.addEventListener("toggle", () => { if (panel.open) editions(); }, {once: true});
    }
})();
