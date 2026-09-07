# Packaged worker execution — NIN-31

G8 can execute retained ontology analysis using an installed API wheel and a separately supervised worker, without importing the editable application checkout. Both services use a deployment-selected Temporal queue. The default queue remains compatible with existing deployments; callers cannot select a queue in workflow requests.

`scripts/g8-built-worker.ps1` verifies the wheel, installed package inventory and Python locations before launching. It records source/archive/wheel hashes, interpreter and command details, and exact process identities. Its stop operation checks and stops owned descendants before the launcher. Reusing a running worker verifies its retained launch receipt; another artifact, queue or surviving child requires an explicit stop. Liveness alone never means successful execution or release acceptance.

`scripts/install-packaged-python.ps1` installs the pinned Python 3.13.14 x64 full distribution from the official Python release manifest. Archive integrity, interpreter version, D: base prefix and library locations are checked; the license and installation receipt are retained. It changes no system registration or PATH and refuses to overwrite an installation. Existing development environments still use a C:-resident base interpreter; this proof corrects the candidate runtime only. Windows operating-system utilities remain system-provided.

## Observed execution

The candidate is built from commit `81d635eec36addcf7cf1886cf72f776bb8b8b502`, source archive `b1165f8f2277c9b919a7cf3c0f1795a4408ab8fa3f10e62dbede9a3d18edaf06`, and wheel `59f6709ececa209c8111a8bb7fa92032ad38e6990ae999fb53ed314a827d169f`. Its dependencies were installed offline from the committed hash lock. Package consistency passed.

The API-only verification helper independently proposes and reviews validation Function/Transformation resources using existing canonical source Object Sets and schema identities. It does not repoint production Function heads or publish through private service calls. Each workflow selects the two authentic SOG source observations for 2025-11-03, passes their retained result into a grouped-count Function, and verifies exact contributors, source pins, count conservation and immutable repeated history. These are observation counts; currency/unit establishment and accounting authority remain absent.

The initial run completed one workflow, then timed out on new work after restart. That failed evidence remains in `.finai/runtime-proof/built-worker-flow-4cva7_zr`. The candidate venv was then found to use C:-resident Python. After provisioning the D: interpreter, recovery reused the same wheel, queue and pending request. The pending grouped step completed, its history replayed unchanged, and a third fresh workflow completed after another worker restart. The candidate API port closed and all recorded worker processes exited.

The earlier timeout's root cause is not proven. A read-only monitor observed terminal-result insertion without lock blockers and approximately five seconds of execution during recovery. A broad resource-table scan was identified separately and is being corrected; successful recovery does not establish that it caused the earlier timeouts.

## Evidence and limits

Compact retained evidence: [nin31-packaged-worker-runtime.json](evidence/nin31-packaged-worker-runtime.json). Full local proof: `.finai/runtime-proof/built-worker-flow-2qq7d7ox/verification.json`, with its hash in the compact evidence. The proof records both worker launch receipts, interpreter provenance, three workflow identities and exact Function receipt hashes.

Focused admission tests cover queue isolation, corrupted artifacts and non-D interpreters; ownership simulation covers child-first stop, unrelated process exclusion and PID reuse. Ruff and PowerShell syntax checks passed. Actual execution demonstrated completed-history replay, resumption of the retained request, new work after restart and owned shutdown. It does not claim general mid-step crash recovery, scale, business effects, full G8 frontend acceptance or production release acceptance. NIN-31's release/SBOM, gated promotion, canary, recall and rollback contracts remain open.

`scripts/verify-built-worker-flow.py` launches an isolated API and supervised worker, retains each step and cleans up owned processes. `--resume-from` requires failed evidence for the same artifact and queue and copies original requests into a new evidence directory; it preserves the failed directory. Both a fresh worker name and explicit artifact/interpreter paths are required.
