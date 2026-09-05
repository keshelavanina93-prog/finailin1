# Windows D:-only development policy

The canonical Windows checkout is `D:\FinAI\finailinear1`. All mutable project
state must also remain on D:, including worktrees, dependency caches, virtual
environments, databases, object-store data, generated artifacts, test output, and
temporary files.

Run `scripts\bootstrap-local.ps1` from PowerShell. It creates repository-local
runtime directories below `.finai`, creates `.venv` on D:, and configures the pnpm,
pip, uv, temp, data, and artifact paths for the current process.

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
