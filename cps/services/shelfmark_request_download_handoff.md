# Shelfmark Request and Download Handoff Design

## Scope
This note captures the verified Shelfmark request and download contract, the current CWA ingest and metadata-on-import behavior, and the safest next step for exact Hardcover provenance handoff into CWA.

It is intentionally limited to what is supported today:
- `shelfmark/` request, release, queue, and activity routes
- CWA ingest processor and metadata-on-import flow

## What Shelfmark Supports Today

### Request-only flow
- `POST /api/requests`
- `POST /api/requests/batch`

These accept `book_data`, `content_type`, `request_level`, and optional `release_data`.

If `release_data` is absent, Shelfmark defaults to a book-level request and creates a pending request row.

### Immediate download flow
There are two verified ways to queue a download:

1. `POST /api/releases/download`
   - queues one concrete release directly
   - requires at least `source` and `source_id`
   - does not create a request record by itself

2. `POST /api/requests` or `/api/requests/batch` with policy resolving to `download`
   - only works when a concrete `release_data` payload is supplied
   - requires a release-level request once `release_data` is present
   - Shelfmark then queues the selected release immediately

### Admin fulfilment flow
- `POST /api/admin/requests/<id>/fulfil`

This is the current bridge from a pending request to a queued download.

It:
- loads the pending request
- requires concrete `release_data` unless `manual_approval=true`
- persists fulfilment state
- injects `_request_id` into the queued release payload
- queues the release under the requesting user identity

### Activity and delivery-state tracking
- `GET /api/activity/snapshot`

This syncs request delivery state from queue and download state. The linkage is driven by:
- explicit `request_id` on queued tasks when available
- otherwise `source_id` extracted from `release_data`

## Safest Recommended Workflow

### Safe now
Keep the current CWA browser-side request-only workflow for generic book-level requests.

### Next safe workflow for auto-download
- Search releases in Shelfmark for the exact target book.
- Select one concrete release in CWA.
- Submit a release-level request with `release_data` so Shelfmark can queue immediately when policy mode is `download`.

This is safer than:
- generic book request followed by automatic guesswork
- direct release download without preserving request provenance

### What should not be done speculatively
- Do not assume a generic book request can be auto-approved into a correct release later without a release-selection step.
- Do not treat `POST /api/releases/download` as a full replacement for request workflow, because it bypasses request provenance.

## Release Preference Viability

Shelfmark release metadata already exposes enough fields to support a small future preference model if CWA adds release selection later.

Verified fields include:
- `source`
- `source_id`
- `protocol`
- `indexer`
- `format`
- `language`
- `content_type`
- `publisher`
- `year`

This makes the following future settings viable:
- request mode: request only, or request and auto-download preferred release
- preferred source type: any, direct, torrent, usenet
- preferred provider or indexer: any, or one explicit provider
- preferred format: any, EPUB, PDF, MOBI

These settings should wait until CWA has a concrete release-selection workflow. They should not be bolted onto the current book-request-only flow.

## Current CWA Hardcover-ID-on-Import Behavior

When "auto retrieve Hardcover ID and metadata on import" is enabled, the current generic import flow does this:
- imports the file into Calibre
- loads the newly added book
- builds a fuzzy metadata query from title and authors
- walks the configured provider hierarchy
- applies the first viable metadata result

That means an exact Hardcover ID already known upstream can still be ignored during metadata lookup unless fuzzy search rediscovers the same record.

## Recommended Provenance Handoff

### Preferred design
Use an explicit sidecar manifest next to the completed download:

`<filename>.cwa.json`

This is already a supported ingest seam in CWA and is safer than:
- filename markers
- guessing from download path names
- relying on embedded ebook metadata only

### Recommended manifest shape
```json
{
  "provenance": {
    "provider": "hardcover",
    "provider_id": "379631",
    "hardcover_edition": "91234",
    "hardcover_slug": "mort"
  }
}
```

Optional explicit identifiers also work:
```json
{
  "identifiers": {
    "hardcover-id": "379631",
    "hardcover-edition": "91234"
  }
}
```

### Why this is the cleanest handoff
- explicit
- stable across file renames
- does not affect ordinary imports
- can be produced by Shelfmark or any adjacent downloader later
- lets CWA persist exact identifiers before metadata lookup runs

## Safe Implementation Completed in CWA
- ingest now consumes identifier and provenance data from `.cwa.json` sidecars during normal import
- exact `hardcover-id` and `hardcover-edition` can land in Calibre immediately
- metadata fetch now prefers exact Hardcover lookup when the imported book already has a `hardcover-id`

This improves correctness now without changing the existing Shelfmark request flow.

## What Should Be Implemented Next
1. Extend Shelfmark’s completed-download output to write a `.cwa.json` sidecar into the CWA ingest area.
2. Decide whether the future CWA UX should remain:
   - request only
   - or add an opt-in request-and-auto-download mode
3. If auto-download is added, build it on top of Shelfmark release search and release-level request or fulfilment contracts, not book-level guesswork.
4. Only after that should CWA expose user-facing preferences for source type, provider or indexer, and format.

## What Should Wait
- speculative CWA settings UI for auto-download
- automatic release guessing without release search
- backend-side request impersonation from CWA
- any change to the existing exact duplicate contract
