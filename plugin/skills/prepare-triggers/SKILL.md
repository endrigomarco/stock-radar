---
name: prepare-triggers
description: "Prepare fixed 1%, 2% and 3% upside and downside tracking levels for explicitly selected Stock Radar signals. Does not create provider alerts or place trades."
---

# Prepare Triggers

1. Read [the runtime contract](../../references/runtime-contract.md) and discover the actual tracking tools. Report missing capabilities without creating substitute local records.
2. Resolve the selected persisted signals and experiment version. Require a defined reference price, source, timestamp, actual activation policy and observation window. If a material rule is missing, ask for it instead of using the last visible price silently.
3. Call the authorized backend tracking operation. Reuse stable request identity on retries. The server must return the tracking ID, locked reference and six levels.
4. Present the returned levels and supported message fields for manual alert configuration. Keep each alert mapped to its exact tracking run, not just a ticker. Explain any period before activation that lacks coverage.
5. Do not report alerts active merely because levels exist. Record provider setup evidence only through an available tool and explicit confirmation or verified provider state. Automatic provider alert creation is not implemented.
