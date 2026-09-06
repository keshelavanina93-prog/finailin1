import type { CanonicalResource } from "./ontology.js";

export interface HistorySearchResult {
  resources: CanonicalResource[];
  has_more: boolean;
  offset: number;
  limit: number;
  effective_at: string;
  known_at: string;
}
