import type { CanonicalResource } from './ontology.js';

/** Portable queries over canonical resources; scalar values keep their declared type. */
export interface ObjectSetFilter {
  field: string;
  operator?: 'eq' | 'lt' | 'lte' | 'gt' | 'gte';
  value: string | number | boolean | null;
}

export interface ObjectSetTraversal {
  kind: 'reference' | 'link';
  name: string;
  direction: 'outgoing' | 'incoming';
  /** Applied to reached objects before the next relationship step. Omit when empty. */
  filters?: ObjectSetFilter[];
}

export interface ObjectSetInterfacePin { resource_id: string; version_id: string; }
export interface ObjectSetInterfaceRoot extends ObjectSetInterfacePin {
  implementations: ObjectSetInterfacePin[];
}
export interface ObjectSetInterfaceField {
  kind: string;
  required: boolean;
  target_type?: string | null;
  semantic_id?: string | null;
}
export interface ObjectSetInterfaceBindings {
  interface: ObjectSetInterfacePin & {content_hash: string};
  fields: Record<string, ObjectSetInterfaceField>;
  implementations: Array<{
    implementation: ObjectSetInterfacePin & {content_hash: string};
    schema: ObjectSetInterfacePin & {content_hash: string};
    object_type: string;
    fields: Record<string, string>;
  }>;
}
export interface ObjectSetInterfaceValue {
  object_id: string;
  object_version_id: string;
  implementation_resource_id: string;
  implementation_version_id: string;
  schema_version_id: string;
  status: 'AVAILABLE' | 'SCHEMA_CHANGED';
  values: Record<string, unknown> | null;
}

export interface ObjectSetQuery {
  object_type: string;
  interface?: ObjectSetInterfaceRoot;
  resource_ids?: string[] | null;
  search: string;
  filters: ObjectSetFilter[];
  traversal: ObjectSetTraversal[];
  offset: number;
  limit: number;
  valid_at?: string;
  known_at?: string;
}

export interface ObjectSetSchemaVersion {
  object_type: string;
  resource_id: string;
  version_id: string;
}

export interface ObjectSetTraversalSchemaVersion extends ObjectSetSchemaVersion {
  /** One-based position in query.traversal. */
  step: number;
}

export interface ObjectSetResult {
  query: ObjectSetQuery;
  total: number;
  counts_by_type: Record<string, number>;
  objects: CanonicalResource[];
  next_offset: number | null;
  definition_id?: string;
  definition_version_id?: string;
  filter_schema_versions?: ObjectSetSchemaVersion[];
  traversal_schema_versions?: ObjectSetTraversalSchemaVersion[];
  interface_bindings?: ObjectSetInterfaceBindings;
  interface_values?: ObjectSetInterfaceValue[];
}
