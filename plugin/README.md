# Stock Radar plugin scaffold

This directory is the plugin root. It contains metadata and instruction-only skills, not a functioning
integration. The repository backend provides a local MCP server, but this plugin has no configured connection and
has not been installed or exercised in Cowork.

Planned namespaced skills:

- `/stock-radar:collect-signals`
- `/stock-radar:prepare-triggers`
- `/stock-radar:analyze-results`
- `/stock-radar:check-status`

Read [the runtime contract](references/runtime-contract.md) for shared boundaries. These skills report
missing tools until the VPS API/MCP and account connection are implemented. They never fall back to
direct PostgreSQL access or pretend observations were saved.

Only this directory belongs in the future plugin package. Connection details and secrets will be
configured at installation time after transport/authentication support has been validated. No speculative
`.mcp.json` with a nonexistent service is included. No schedule is installed by these files.
