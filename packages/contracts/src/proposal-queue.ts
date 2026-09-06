import type { ProposalSummary } from "./ontology.js";

export interface ProposalQueueCursor {
  created_at: string;
  proposal_id: string;
}

export interface ProposalQueuePage {
  proposals: ProposalSummary[];
  has_more: boolean;
  next_cursor: ProposalQueueCursor | null;
  snapshot_at: string;
  decision_mode: "CURRENT_RETAINED_DECISION";
  limit: number;
}
