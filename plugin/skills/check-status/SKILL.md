---
name: check-status
description: "Inspect Stock Radar service health, last collections, pending events and data-quality gaps through read-only tools. Does not repair, deploy or rerun collection."
---

# Check Status

1. Read [the runtime contract](../../references/runtime-contract.md). Discover actual status and quality capabilities. If no service is connected, report that directly.
2. Read service/contract version, latest successful collection, incomplete runs, pending/failed receipts and tracking coverage where supported.
3. Separate unavailable metrics from healthy zero counts. A healthy process does not prove successful collection, complete webhook delivery or valid investment results.
4. Report observed problems and the next specific diagnostic step. Do not deploy, rotate credentials, replay events, mutate records or initiate browser collection as part of this read-only check.
