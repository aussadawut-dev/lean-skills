# Conditional delivery checks

- **User-facing work.** For user-facing work verify affected accessibility, keyboard/focus, screen sizes and loading/empty/error/recovery states.
- **Security.** Security work maps protected data, entry points, trust transitions and permissions, then probes relevant abuse cases.
- **Release.** Before release check artifact/environment, dependencies/configuration/migration compatibility, health criteria and authorized recovery. Verify deployment and observation. Inspect uncertain state before retrying. Application rollback grants no destructive data-restore authority; a failed release followed by recovery remains a failed release. Requested publication remains part of acceptance and requires matching authorization and tools.
