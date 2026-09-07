# Retained builds in Workflows & Actions

Transformation runs now appear as evidence builds, named from the exact retained
Transformation version. The work item carries the existing request UUID and
resource/version/hash reference. It does not acquire a company binding from the
currently selected company or from a source label.

Opening a build switches to Data / Builds and reads that request through the
existing Transformation endpoint. The returned request and Transformation version
must match the selection. No replacement run is created. Source selection clears
the prior build navigation intent, while company context and the NYX rail remain
available. Build controls remain in the existing dedicated build workbench.

The legacy source workflow read/control endpoints now refuse other workflow
families with HTTP 409 before contacting Temporal, retaining an event or sending
a signal. Existing source review separation remains enforced. Build work-list
visibility follows the existing ontology read permission.

Focused verification covers family routing, source compatibility, reviewer
separation and actual native retained build listing with exact titles and
permission filtering. `scripts/verify-build-work-navigation.py` checks the mounted
work list, opens the original SGP worksheet build, attempts a cross-family command
and verifies that its original request, events and publications are unchanged.

Actual local evidence on 2026-09-07: the mounted work list resolved request
`49b1d06c-2607-4e66-b39e-e375631ce003`, labelled **SGP source worksheet build**.
The direct legacy API control returned 409 and left its original evidence intact
(`evidence/nin29-build-work-navigation.json`). The web proxy already excluded this
foreign-family control path; the direct API check proves the server boundary too.
Authenticated browser navigation opened that retained build, its completed steps,
the named worksheet output and original `TDSheet!C1` company text. The Data tab and
NYX rail remained visible. Captures were viewed under the D: browser-verification
screenshots directory: `g8-build-work-selection.png`, `g8-build-work-output.png`
and `g8-build-work-source-cells.png`. No company was selected during this proof;
preservation of a selected company was inspected in code, not claimed as browser
evidence. Final focused lint, TypeScript and production web build passed.

This integration does not establish NIN-25 visual acceptance, financial posting
authority or completion of the NIN-29 consequential effect protocol.
