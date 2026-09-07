# Windows D:-only development policy

The canonical Windows checkout is `D:\FinAI\finailinear1`. All mutable project
state must also remain on D:, including worktrees, dependency caches, virtual
environments, databases, object-store data, generated artifacts, test output, and
temporary files.

Run `scripts\bootstrap-local.ps1` from PowerShell. It creates repository-local
runtime directories below `.finai`, creates `.venv` on D:, and configures the pnpm,
pip, uv, temp, data, and artifact paths for the current process.

New Python environments use only the pinned full CPython 3.13.14 x64 runtime at
`.finai/python/cpython-3.13.14-windows-x86_64/python.exe`. Installation bootstrap
invokes `scripts/install-packaged-python.ps1` if that interpreter is missing and
validates its base prefix and standard library on D: before installing dependencies.
An existing environment with a C: base is refused with migration guidance; bootstrap
never removes or silently rebinds it. Preserve the old environment and stop its
dependent services before an explicit migration. `scripts/load-local.ps1` and
`bootstrap-local.ps1 -SkipInstall` continue routine configuration loading without
installing an interpreter or enforcing migration of an existing legacy environment.

`scripts\assert-d-drive.ps1` fails closed when the repository is not at its
canonical path or a guarded process variable points away from D:. Linux CI is not
subject to a Windows drive-letter policy; it still uses isolated runner paths.

Additional worktree storage is reserved below `.finai/worktrees`. The current
bootstrap permits development only from the canonical checkout; it does not
authorize running builds from another checkout.

Guards reject unset cache/temp/runtime locations, paths outside the canonical
checkout, and reparse-point ancestors. npm, Corepack, uv Python/tool installations,
Python bytecode, pnpm and Playwright browser caches are explicitly redirected.
Bootstrap guards run in Windows PowerShell as well as PowerShell 7; Linux CI is
exempt from drive letters. Provision/load scripts use PowerShell 7.

Run bootstrap in every new process before invoking tools. These controls govern
the supplied development commands, not arbitrary third-party commands launched
outside them. Existing system executables may be read from C:; no project data is
written there by these scripts. Docker engine storage must be independently
verified on D: before use. Prefer the isolated native PostgreSQL script locally.

On 2026-09-07 the integration operator stopped the owned API, observer and workflow
worker, verified that no development Python process still used `.venv`, and moved
the previous environment to `.finai/environment-backups/venv-c-base-20260907`.
A fresh `.venv` was created from the pinned D: interpreter, its dependencies
installed offline from the hash lock, and the project installed as editable source.
Package consistency passed. The environment backup is retained; it was not deleted
or silently rebound.

The API, worker and observer now run with the D: base interpreter and standard
library. The web supervisor uses `.finai/tools/node/node.exe` (the existing
v22.22.2 runtime). All services restarted; the observer retained its exact previous
desired-state selection. A real SOG source-window/grouped-count workflow completed
through the API and worker after migration051, with immutable repeat evidence and
two exact source contributors. This is local integration evidence, not release or
financial acceptance. See [retained runtime evidence](evidence/nin31-d-native-development.json).
