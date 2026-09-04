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

Additional worktrees belong below `D:\FinAI\worktrees` and should be created only
after running the guard.
