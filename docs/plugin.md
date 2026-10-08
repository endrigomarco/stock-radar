# Claude plugin

The plugin root is `plugin/`, not the repository root. Only that directory is the future installable
package. Its manifest is `plugin/.claude-plugin/plugin.json`; skills and runtime references are siblings
of `.claude-plugin/`. Development documents are outside the package.

Current state: manifest and four instruction-only skills. No MCP configuration, credentials, browser
adapter, API client, schedule, installation or packaged release exists. Skills must report missing
capabilities rather than simulate success. Manifest validation alone does not prove Cowork compatibility.

| Skill | Role |
|---|---|
| collect-signals | Browser observations and additive ingestion |
| prepare-triggers | Request levels from the backend and prepare manual alert setup |
| analyze-results | Read backend metrics and explain findings |
| check-status | Read collection, coverage and processing health |

Runtime rules are in `plugin/references/runtime-contract.md` so a copied plugin remains self-contained.
Do not make skills depend on `../../docs` outside their installable root. Update that compact runtime
contract when the API or product rules change, without duplicating the full engineering documentation.

Verify the browser identity, account, target URL and actual table columns. Traverse pagination or virtual
rows explicitly. A visible subset is not the full list. Keep original labels and never guess missing fields.
No trading actions, subscriptions, provider messages or unrelated browser mutations are part of collection.

Before release, validate packaging, capability discovery, authentication, namespaced skill discovery and
one synthetic write/read cycle in the actual Cowork environment. Configure daily scheduling separately
only when requested; account for the MacBook being asleep/offline. Do not silently collect yesterday's
list and label it as today's completed run.
