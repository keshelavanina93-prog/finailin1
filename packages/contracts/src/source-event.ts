import type { VersionReference } from "./lifecycle.js";

export interface SourceEvent {
  stream: VersionReference;
  event_id: string;
  partition_key: string;
  event_time: string;
  payload: Record<string, unknown>;
}

export interface RetainedSourceEvent {
  authority_state: "OBSERVED";
  event_id: string;
  stream_id: string;
  stream_version_id: string;
  partition_key: string;
  event_time: string;
  processing_time: string;
  arrival_sequence: number;
  admission: "IN_WINDOW" | "RETAINED_LATE";
  watermark: string | null;
  request_hash: string;
  access_entity: string;
  payload: Record<string, unknown>;
}

export interface EventReplay {
  purpose: "BACKFILL_OBSERVATION" | "AS_RECORDED_OBSERVATION";
  authority_state: "OBSERVED";
  current_use_authorized: false;
  known_at: string;
  stream_id: string;
  event_count: number;
  late_event_count: number;
  ordering: "event_time,event_id";
  admission_order: "arrival_sequence";
  projection: RetainedSourceEvent[];
}
