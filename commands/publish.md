---
description: Publish a research or plan document to the configured GitHub thoughts repository.
model: sonnet
---

You are tasked with publishing a document to the thoughts repository.

Load and follow the protocol in the autodidact-publish skill.

If the user provided a file path after `/publish`, use that as the source file. Otherwise, look for the most recent document in `.planning/research/` or `.planning/plans/` and offer to publish it.

Requires the `AUTODIDACT_THOUGHTS_REPO` environment variable to be set (e.g., `crsdigital/crsdigital-thoughts`). If not set, inform the user how to configure it.
