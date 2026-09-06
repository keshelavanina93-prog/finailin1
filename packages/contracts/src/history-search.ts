import type { CanonicalResource } from "./ontology.js";

export interface HistorySearchResult {
  resources: CanonicalResource[];
  has_more: boolean;
  /** Matching company/as-of/name results before pagination, after the selected type. */
  matched_count: number;
  /** All matching categories before the selected type filter, independent of page. */
  type_facets: Array<{ object_type: string; count: number }>;
  offset: number;
  limit: number;
  effective_at: string;
  known_at: string;
}
