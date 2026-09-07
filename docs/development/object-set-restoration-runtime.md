# Reviewed restoration of a saved source selection

This proof uses one canonical ObjectSetDefinition, `d41d343c-c791-581b-969d-cb48d1526b54` (`sog-source-contexts:restoration:v1`). Its first reviewed version selects Region and Department CompanyDimension observations with evidence `71f45f39-35fb-56c1-b4b7-61e7edc56368` and source columns Y/AA. A second reviewed version narrows the same identity to Y. No source objects or business identities are created or changed.

`scripts/verify-object-set-restoration-runtime.py --prepare` publishes those two definitions and retains their exact query results at one frozen valid/known time. The browser must create the restoration proposal from the first exact version through existing history and rollback authority. The helper does not generate that proposal or restore automatically.

After the retained diff is inspected, `--review-proposal UUID` checks the exact restored version, expected current head and original definition content before using the existing independent reviewer. `--read-only` then checks all three versions: original remains two observations, narrowed remains Region only, and the newly approved restoration returns the original exact source objects. Repeated readback preserves the original query time and immutable version results.

## Prepared evidence and focused verification

[Runtime evidence](evidence/nin6-object-set-restoration-runtime.json) records `REVIEWED_RESTORATION_VERIFIED`. Original version `2ae0e50c-4617-5ad5-a397-a4d0345093e3` returns Region and Department; narrowed version `c20b0a0c-25c9-5225-abdc-c7a87a569c67` returns Region only. Both exact-version queries retain valid and known time `2026-09-07T14:22:12.970247+00:00` and the original canonical source objects.

The [browser evidence](evidence/nin6-object-set-restoration-browser.json) records `trace_before` and `trace_return`: returning from an exact source trace preserved the prior temporal-extent view and its expanded witness text. The browser displayed the restoration comparison against the first retained version before submission.

## Reviewed restoration and restart readback

The browser created proposal `8bda522b-81fa-46b7-b4cf-6e851e524b31`, effective `2026-09-07T14:34:51.571198Z`. The existing independent `local-steward-reviewer` approved it through the helper after exact restoration-content and expected-version validation. Publication created version `521ff085-3ea2-55c1-b38d-8d1d3054d8c3` under the same ObjectSet identity; neither retained predecessor was rewritten.

The restored selection returned both original canonical source objects in the browser at frozen valid/known time `2026-09-07T14:37:15.325108Z`. After the API restarted, helper `--read-only` verified unchanged original, narrowed and restored exact-version results at the earlier helper query time. A full browser reload then reopened the restored selection with the entire captured query text unchanged, including definition pins, source versions and its browser query time. The browser evidence retains this as `after_restart`.

One focused native restoration test and two permanent timestamp tests passed. Helper lint and the final production web build passed after the timestamp and responsive comparison fixes. The improved comparison capture was visually inspected. This proves the bounded source-selection restoration and retained readback journey; it does not establish financial authority, whole-product acceptance or release acceptance.
