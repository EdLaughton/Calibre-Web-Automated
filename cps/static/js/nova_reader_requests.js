(() => {
    "use strict";
    const panel = document.querySelector("#reader-book-requests");
    const query = panel.querySelector("#reader-book-query");
    const results = panel.querySelector("#reader-book-results");
    const message = panel.querySelector("#reader-book-message");
    const jobs = panel.querySelector("#reader-book-jobs");
    const jobsMessage = panel.querySelector("#reader-book-jobs-message");
    const seriesQuery = panel.querySelector("#reader-series-query");
    const seriesResults = panel.querySelector("#reader-series-results");
    const seriesPreview = panel.querySelector("#reader-series-preview");
    const seriesMessage = panel.querySelector("#reader-series-message");
    const states = {
        owned: "Already in the library",
        queued: "Queued",
        searching: "Searching for an EPUB",
        submitting: "Sending to Bookshelf",
        downloading: "Downloading",
        checking: "Checking the downloaded book",
        waiting_release: "Waiting for release",
        waiting_epub: "Watching for an EPUB",
        imported: "Added to the library",
        no_match: "No suitable EPUB found",
        excluded: "Unavailable for automatic requests",
        held: "Needs review",
        dismissed: "Closed by an administrator",
    };
    const activeStates = new Set(["queued", "searching", "submitting", "downloading", "checking",
        "waiting_release", "waiting_epub"]);
    const dateFormat = new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeZone: "UTC"});
    let timer;
    let searchVersion = 0;
    let seriesTimer;
    let seriesVersion = 0;

    async function load(url, options) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) {
            const error = new Error(data.error || "Request failed.");
            if (response.status === 401) error.loginUrl = data.login_url;
            throw error;
        }
        return data;
    }

    function showError(target, error, fallback) {
        target.textContent = error.loginUrl ? "Your session expired. " : fallback || error.message;
        if (error.loginUrl) {
            const link = document.createElement("a");
            link.href = error.loginUrl;
            link.className = "request-manual-link";
            link.textContent = "Sign in again";
            target.append(link);
        }
    }

    function item(title, parent, metadata, series, coverUrl = null) {
        const row = document.createElement("li");
        row.className = "request-card";
        const details = document.createElement("div");
        const heading = document.createElement("span");
        heading.className = "request-title";
        heading.textContent = title;
        details.append(heading);
        if (metadata) {
            const byline = document.createElement("span");
            byline.className = "request-byline";
            byline.textContent = metadata;
            details.append(byline);
        }
        if (series) {
            const seriesLine = document.createElement("span");
            seriesLine.className = "request-byline";
            seriesLine.textContent = series;
            details.append(seriesLine);
        }
        const summary = document.createElement("div");
        summary.className = "request-summary";
        if (parent === results) {
            const slot = document.createElement("div");
            slot.className = "request-cover-slot";
            if (coverUrl) {
                const cover = document.createElement("img");
                cover.className = "request-cover";
                cover.alt = "";
                cover.loading = "lazy";
                cover.referrerPolicy = "no-referrer";
                cover.addEventListener("error", () => cover.remove(), {once: true});
                cover.src = coverUrl;
                slot.append(cover);
            }
            summary.append(slot);
        }
        summary.append(details);
        row.append(summary);
        parent.append(row);
        return row;
    }

    function status(text) {
        const label = document.createElement("span");
        label.className = "request-status";
        label.textContent = text;
        return label;
    }

    function openBook(url, title) {
        const link = document.createElement("a");
        link.className = "request-action";
        link.href = url;
        link.textContent = "Open book";
        link.setAttribute("aria-label", "Open book: " + title);
        return link;
    }

    function notificationOption(job, kind, text, enabled) {
        const label = document.createElement("label");
        label.className = "request-notify";
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = enabled;
        label.append(box, text);
        box.addEventListener("change", async () => {
            box.disabled = true;
            try {
                await load(panel.dataset.notify, {
                    method: "POST",
                    headers: {"Content-Type": "application/json", "X-CSRFToken": panel.dataset.csrf},
                    body: JSON.stringify({work: job.work, kind, enabled: box.checked}),
                });
            } catch (error) {
                box.checked = !box.checked;
                showError(jobsMessage, error);
            } finally {
                box.disabled = false;
            }
        });
        return label;
    }

    async function refreshJobs() {
        try {
            const data = await load(panel.dataset.jobs);
            jobs.replaceChildren();
            jobsMessage.textContent = data.jobs.length ? "" : "No requests yet.";
            for (const job of data.jobs) {
                const release = job.state === "waiting_release" && job.release_date
                    ? "Expected " + dateFormat.format(new Date(job.release_date)) : null;
                const byline = [job.authors ? "by " + job.authors : null, release].filter(Boolean).join(" · ");
                const row = item(job.title, jobs, byline);
                row.append(job.book_url
                    ? openBook(job.book_url, job.title) : status(states[job.state] || job.state));
                if (data.can_notify && activeStates.has(job.state)) {
                    row.append(notificationOption(job, "email", "Email me when added", job.notice === "pending"));
                } else if (job.notice === "failed") {
                    const note = document.createElement("span");
                    note.className = "request-notify";
                    note.textContent = "Notification email could not be confirmed.";
                    row.append(note);
                }
                if (data.can_kindle && activeStates.has(job.state)) {
                    row.append(notificationOption(job, "kindle", "Send to Kindle when added", job.kindle === "pending"));
                } else if (job.kindle === "sent" || job.kindle === "failed") {
                    const note = document.createElement("span");
                    note.className = "request-notify";
                    note.textContent = job.kindle === "sent" ? "Kindle email sent" : "Kindle email could not be confirmed.";
                    row.append(note);
                }
            }
        } catch (error) {
            showError(jobsMessage, error, "Request status is temporarily unavailable.");
        }
    }

    async function requestBook(book, button) {
        button.disabled = true;
        try {
            const reply = await load(panel.dataset.jobs, {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": panel.dataset.csrf},
                body: JSON.stringify({ticket: book.ticket}),
            });
            button.replaceWith(reply.book_url
                ? openBook(reply.book_url, book.title) : status(states[reply.state] || "Requested"));
            await refreshJobs();
        } catch (error) {
            showError(message, error);
            button.disabled = false;
        }
    }

    async function search(version) {
        const term = query.value.trim();
        if (term.length < 3) return;
        message.textContent = "Searching Hardcover…";
        try {
            const data = await load(panel.dataset.search + "?" + new URLSearchParams({q: term}));
            if (version !== searchVersion) return;
            message.textContent = data.results.length ? "" : "No matching books found.";
            for (const book of data.results) {
                const publication = book.release_date
                    ? "Expected " + dateFormat.format(new Date(book.release_date)) : book.year;
                const byline = [book.authors.join(", "), publication].filter(Boolean).join(" · ");
                const series = book.series && (book.position == null ? book.series : book.series + " #" + book.position);
                const row = item(book.title, results, byline, series, book.cover_url);
                if (book.owned || !book.ticket) {
                    row.append(book.book_url
                        ? openBook(book.book_url, book.title) : status(book.owned ? states.owned : "Pilot only"));
                    continue;
                }
                const button = document.createElement("button");
                button.type = "button";
                button.className = "request-action";
                button.textContent = "Request";
                button.setAttribute("aria-label", "Request " + book.title);
                button.addEventListener("click", () => requestBook(book, button));
                row.append(button);
            }
        } catch (error) {
            if (version === searchVersion) showError(message, error);
        }
    }

    function schedule(delay) {
        clearTimeout(timer);
        const version = ++searchVersion;
        results.replaceChildren();
        message.textContent = "";
        timer = setTimeout(() => search(version), delay);
    }

    async function previewSeries(id) {
        seriesPreview.replaceChildren();
        seriesMessage.textContent = "Checking the series…";
        try {
            const data = await load(panel.dataset.seriesPreview + "?" + new URLSearchParams({id}));
            const series = data.series;
            const heading = document.createElement("h3");
            heading.textContent = series.name;
            const list = document.createElement("ol");
            list.className = "request-series-books";
            const eligible = series.books.filter(book => !book.owned && !book.compilation);
            for (const book of series.books) {
                const row = document.createElement("li");
                const place = book.position == null ? "" : "#" + book.position + " · ";
                row.textContent = place + book.title + " — " + book.authors.join(", ");
                if (book.owned) row.textContent += " · In your library";
                if (book.compilation) row.textContent += " · Compilation, skipped";
                list.append(row);
            }
            seriesPreview.append(heading, list);
            if (eligible.length) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "request-action";
                button.textContent = "Queue missing books (up to five)";
                button.addEventListener("click", async () => {
                    button.disabled = true;
                    try {
                        const reply = await load(panel.dataset.seriesRequest, {
                            method: "POST",
                            headers: {"Content-Type": "application/json", "X-CSRFToken": panel.dataset.csrf},
                            body: JSON.stringify({ticket: series.ticket}),
                        });
                        seriesMessage.textContent = reply.queued.length
                            ? "Queued " + reply.queued.length + " book(s). Check Your requests below."
                            : "No additional books queued. Check existing requests or wait for active requests to finish.";
                        await refreshJobs();
                    } catch (error) {
                        showError(seriesMessage, error);
                    } finally {
                        button.disabled = false;
                    }
                });
                seriesPreview.append(button);
            }
            seriesMessage.textContent = eligible.length
                ? eligible.length + " missing title(s) in this series. Review the list before queuing."
                : "No missing individual titles found in this series.";
        } catch (error) {
            showError(seriesMessage, error);
        }
    }

    async function findSeries(version) {
        const term = seriesQuery.value.trim();
        if (term.length < 3) return;
        seriesMessage.textContent = "Searching Hardcover series…";
        try {
            const data = await load(panel.dataset.seriesSearch + "?" + new URLSearchParams({q: term}));
            if (version !== seriesVersion) return;
            seriesMessage.textContent = data.results.length ? "Choose a series to preview its books." : "No matching series found.";
            for (const series of data.results) {
                const row = item(series.name, seriesResults, series.count == null ? null : series.count + " primary books");
                const button = document.createElement("button");
                button.type = "button";
                button.className = "request-action";
                button.textContent = "Preview";
                button.addEventListener("click", () => previewSeries(series.id));
                row.append(button);
            }
        } catch (error) {
            if (version === seriesVersion) showError(seriesMessage, error);
        }
    }

    function scheduleSeries(delay) {
        clearTimeout(seriesTimer);
        const version = ++seriesVersion;
        seriesResults.replaceChildren();
        seriesPreview.replaceChildren();
        seriesMessage.textContent = "";
        seriesTimer = setTimeout(() => findSeries(version), delay);
    }

    query.addEventListener("input", () => schedule(400));
    panel.querySelector("form").addEventListener("submit", event => {
        event.preventDefault();
        schedule(0);
    });
    seriesQuery.addEventListener("input", () => scheduleSeries(400));
    panel.querySelector("#reader-series-search").addEventListener("submit", event => {
        event.preventDefault();
        scheduleSeries(0);
    });
    refreshJobs();
    setInterval(refreshJobs, 15000);
})();
