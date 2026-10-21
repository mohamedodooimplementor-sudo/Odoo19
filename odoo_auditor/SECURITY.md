# Security notes
- Engine reads business data with sudo but only with explicit company domains and never writes to it.
- Log, evidence snapshots and findings cannot be deleted or silently edited; state changes go through workflow methods.
- Confidential findings/evidence are visible only to the Confidential group. No salary data is stored on dashboards.
- Rule parameters are validated JSON of simple values; no code is executed from configuration.
