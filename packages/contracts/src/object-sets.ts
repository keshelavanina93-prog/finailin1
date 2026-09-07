import type { CanonicalResource, SchemaField } from './ontology.js';
import type { WirePropertyFilter } from './ontology-wire.js';

/** Portable queries over canonical resources; scalar values keep their declared type. */
export type ObjectSetFilter = WirePropertyFilter;

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

export interface ObjectSetTypeGroupRoot { resource_id: string; version_id: string; }
export interface ObjectSetTypeGroupBindings {
  group: ObjectSetTypeGroupRoot & {content_hash: string};
  schemas: Array<{object_type: string; schema: ObjectSetTypeGroupRoot & {content_hash: string}}>;
  fields: Record<string, Omit<SchemaField, 'field_id'>>;
}
export interface ObjectSetTypeGroupValue {
  object_id: string;
  object_version_id: string;
  /** Expected schema pinned by the group; original object retains its actual schema. */
  schema_version_id: string;
  status: 'AVAILABLE' | 'SCHEMA_CHANGED';
}

export interface ObjectSetQuery {
  object_type: string;
  interface?: ObjectSetInterfaceRoot;
  type_group?: ObjectSetTypeGroupRoot;
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
  type_group_bindings?: ObjectSetTypeGroupBindings;
  type_group_values?: ObjectSetTypeGroupValue[];
}
