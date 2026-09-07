# Local browser verification

Use `scripts/g8-browser.ps1` for the managed verification browser. It loads the
canonical local environment, checks all path ancestors for reparse points, and
writes a dedicated CLI configuration under `.finai/browser-verification/`.
Profile, sockets, downloads and default screenshots all remain below that directory.
The browser executable remains the installed tool under `.finai/tools/browser/`.

Actions are `paths`, `start`, `snapshot`, `screenshot` and `close`. The default
inspection URL is `http://127.0.0.1:3062`; `-WebPort` selects another local port.
This uses a separate `g8-local-verification` session. It does not attach to or close
the user's own browser. Login is not persisted by this script or printed to its logs.

For other browser interactions, use the generated `agent-browser.json` and the same
session/socket environment from this entry point. The launcher avoids arbitrary
artifact destinations; direct CLI use outside it is not a D:-only guarantee.

Verified on 2026-09-07: launched the running G8 application, captured a screenshot
in `.finai/browser-verification/screenshots/`, and closed the dedicated session.
The former default screenshot escape is documented in the worksheet execution proof.
This is development verification tooling, not NIN-31 release acceptance.
