# NIN-25 company context and shell correction

The shared shell previously substituted the legacy intake-bound company when the explicit selection was cleared or unavailable. Regulation consumed the explicit ID while other pages consumed the substitute. This is removed: an empty selection means all authorized contexts; an unavailable saved company never silently selects another identity.

The company picker uses the canonical company-context projection and separates configured workspaces, source accounting contexts and companies in dated filings. It supports registration/name/source-alias search, clean display labels, keyboard focus, dismissal and narrow screens. No filing relationship is promoted to current ownership or operating scope.

Company source rendering waits for the matching resolved context. Shared snapshot requests publish independently. Unrequested initial work inspection is removed. Ontology resources, Object Sets/definitions and accounting contracts occupy separate views. A system trace occupies the primary canvas; module navigation closes that canvas while retaining inspector selection. Recent receipt/proposal activity is labeled review activity, not canonical Findings.

Validation: production Next build, focused ESLint; authenticated browser on 1440px and 390px widths with real SGG selection across Companies/Data/Ontology/Operations/Regulation, reload and reauthentication, clearing and another reload, SGP name selection on mobile; no browser errors or mobile document overflow. Artifacts: `.finai/artifacts/company-context-fix.cjs`, `company-context-desktop.png`, `company-context-mobile.png`.

Remaining: Finance/Planning/Reporting/Workflows are still disconnected; full company operating structure, shared accounting tuple propagation, canonical investigations and all NIN-25 cross-surface acceptance remain open. Shared ontology queries/contracts retain their explicit query scope and do not pretend to inherit a company filter. This change is not acceptance of the overall visual system or business modules.
