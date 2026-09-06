# G8 local system runtime

From `D:\FinAI\finailinear1`, use PowerShell 7:

```powershell
.\scripts\g8-system.ps1 -Action start -ApiPort 8062 -WebPort 3062
.\scripts\g8-system.ps1 -Action status
.\scripts\g8-system.ps1 -Action stop -ApiPort 8062 -WebPort 3062
```

The entry point composes the existing supervisors. It starts the retained native
PostgreSQL cluster, MinIO, Temporal, API, workflow worker and built web application
in that order. A running PostgreSQL cluster is reused without provisioning it
again. Missing dependencies or the web production build must be installed/built
using the existing repository setup instructions. This command does not download
dependencies or build application code. Default API/web ports remain 8061/3061;
the current inspection instance uses 8062/3062.

Stop runs in reverse application dependency order. PostgreSQL remains running:
this entry point does not claim ownership of the retained database service.
Existing application and workflow supervisors retain their exact process identity
checks. A conflicting process is preserved. A partial startup reports failure;
services already started are retained for diagnosis and a subsequent retry.
This is not an atomic deployment or rollback mechanism.

Status is read-only: it neither bootstraps directories nor rewrites ownership
records. It reports PostgreSQL readiness, owned application processes and HTTP
health, owned Temporal process and TCP reachability, and owned worker process
liveness. TCP reachability and a live worker do not prove workflow execution.
Use the authenticated shared workflow workbench for retained schedules and
execution outcomes. An enabled schedule does not establish regulatory source
completeness or legal applicability.

All retained process registries, logs, Temporal history and object/database data
remain under the existing D: runtime. This local integration does not close NIN-8
release acceptance, NIN-29 generic workflow acceptance, or authenticated browser
acceptance for the G8 shell.
