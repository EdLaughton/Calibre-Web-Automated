# Book requests (fork integration)

This branch adds the CWA request page, mobile entry point, Hardcover title and
series discovery, reader history, and an administrator view. It uses a shared
SQLite queue. The acquisition worker and guarded file handoff are separate
Nova services; without them, requests stay queued. This is a fork integration,
not a stock CWA acquisition service.

## Configuration

The feature is off until `reader-requests.enabled` exists beside the queue.
Defaults match Nova; deployments can set:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CWA_REQUEST_DB` | `/config/nova-ui/requests.db` | Shared queue path |
| `CWA_LIBRARY_DB` | `/calibre-library/metadata.db` | Read-only owned-work lookup |
| `CWA_SETTINGS_DB` | `/config/app.db` | Existing Hardcover token |
| `CWA_BOOK_REQUEST_MANUAL_URL` | empty | Optional manual search link |

The queue directory must exist and be writable by CWA. The external worker
needs access to the same database and uses the same schema. The Hardcover token
stays in CWA's saved settings; browser responses contain no token.

## Request flow

1. A signed-in reader chooses a Hardcover work or previews a series. Each book
   request is bound to a short-lived, reader-specific ticket and checked with
   CWA's CSRF protection. Existing Calibre work IDs are shown as owned.
2. A series preview lists every member with cover, name, series position and
   author. It marks owned books and compilations. One action queues all missing
   individual works; the worker processes one queued work per cycle.
3. The external worker checks work identity, author, exclusions, English EPUB
   editions, existing Bookshelf files, active downloads and prior grabs. It
   selects one eligible release from Bookshelf's native results and submits it
   once. A lost response is reconciled from Bookshelf history before any retry.
4. Bookshelf downloads through its configured Usenet or torrent client. Nova's
   guarded handoff verifies the completed EPUB and passes a private copy to
   CWA ingest. CWA alone writes the final Calibre library.
5. The worker sees the final Hardcover work ID in Calibre, marks the request
   imported and handles opted-in completion email or Kindle delivery.

A book added directly in Bookshelf also uses the guarded handoff. It appears
in request history only when a reader requested the same Hardcover work.

`Needs review` displays the actual hold reason to the reader. The admin view
shows the reason, release metadata, download ID, alert status and a suggested
research path. The admin records an investigation note and either approves
continuation after resolving the cause or denies the shared work for every
reader. Approval requeues the guarded checks or immediately recognises an
exactly owned CWA book. It cannot override an unsafe EPUB or resubmit an
ambiguous prior grab; those need manual reconciliation before approval. The
decision and note are audited. The external worker sends one admin email when
a request first enters the held state; ambiguous SMTP failures are recorded
and are not automatically resent.
