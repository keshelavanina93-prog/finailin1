/** A shared Function request over pinned source evidence; never caller-supplied amounts. */
import type { VersionReference } from "./lifecycle.js";

export interface AcceptedMovementFunctionInvocation {
  request_id: string;
  function: VersionReference;
  /** Exact retained source query times; independent from the journal observation time. */
  valid_at: string;
  known_at: string;
  offset?: 0;
  limit?: 50;
  input_result?: never;
  accepted_movements: {
    source_invocation_id: string;
    company_id: string;
    journal_snapshot_at: string;
    expected_reconciliation_sha256: string;
    expected_result_sha256: string;
  };
}
