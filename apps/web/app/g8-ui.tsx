"use client";

import Image from "next/image";
import type { ReactNode } from "react";
import { ArrowRight, WarningCircle, CheckCircle, Clock, LockKey, ShieldCheck, SlidersHorizontal, XCircle } from "@phosphor-icons/react";

type BadgeTone = "neutral" | "good" | "warning" | "bad";
type DimensionalState = { code: string; label: string; tone: BadgeTone; detail: string };
type BadgeProps = { children?: ReactNode; value?: unknown; title?: string; className?: string };

const AUTHORITY_STATES = {
  APPROVED: { code: "APPROVED", label: "Approved authority", tone: "good", detail: "Accepted for governed use." },
  ACCEPTED: { code: "ACCEPTED", label: "Accepted authority", tone: "good", detail: "Accepted for governed use." },
  CURRENT: { code: "CURRENT", label: "Current authority", tone: "good", detail: "Current authority is retained." },
  PENDING: { code: "PENDING", label: "Pending authority", tone: "warning", detail: "Independent review is still required." },
  REVIEW: { code: "REVIEW", label: "Review required", tone: "warning", detail: "Authority has not been accepted." },
  REVIEW_REQUIRED: { code: "REVIEW_REQUIRED", label: "Review required", tone: "warning", detail: "Authority has not been accepted." },
  DRAFT: { code: "DRAFT", label: "Draft authority", tone: "warning", detail: "Draft authority cannot govern use." },
  REJECTED: { code: "REJECTED", label: "Rejected authority", tone: "bad", detail: "Authority was rejected." },
  DENIED: { code: "DENIED", label: "Authority denied", tone: "bad", detail: "This identity is not permitted to use it." },
  REFUSED: { code: "REFUSED", label: "Authority refused", tone: "bad", detail: "The system refused to establish authority." },
  UNAVAILABLE: { code: "UNAVAILABLE", label: "Authority unavailable", tone: "warning", detail: "Authority could not be read." },
  EMPTY: { code: "EMPTY", label: "No authority recorded", tone: "neutral", detail: "No authority value was provided." },
} as const satisfies Record<string, DimensionalState>;

const EVIDENCE_STATES = {
  VERIFIED: { code: "VERIFIED", label: "Evidence verified", tone: "good", detail: "Evidence was retained and verified." },
  OBSERVED: { code: "OBSERVED", label: "Evidence observed", tone: "good", detail: "Observed evidence is retained." },
  RETAINED: { code: "RETAINED", label: "Evidence retained", tone: "good", detail: "Evidence is retained." },
  DERIVED: { code: "DERIVED", label: "Derived evidence", tone: "warning", detail: "Derived evidence requires lineage review." },
  PENDING: { code: "PENDING", label: "Evidence pending", tone: "warning", detail: "Evidence is not complete yet." },
  MISSING: { code: "MISSING", label: "Evidence missing", tone: "bad", detail: "Required evidence was not retained." },
  REFUSED: { code: "REFUSED", label: "Evidence refused", tone: "bad", detail: "Evidence access or use was refused." },
  UNAVAILABLE: { code: "UNAVAILABLE", label: "Evidence unavailable", tone: "warning", detail: "Evidence could not be read." },
  EMPTY: { code: "EMPTY", label: "No evidence recorded", tone: "neutral", detail: "No evidence value was provided." },
} as const satisfies Record<string, DimensionalState>;

const GATE_STATES = {
  PASS: { code: "PASS", label: "Gate passed", tone: "good", detail: "Acceptance gate passed." },
  PASSED: { code: "PASSED", label: "Gate passed", tone: "good", detail: "Acceptance gate passed." },
  READY: { code: "READY", label: "Gate ready", tone: "good", detail: "Gate is ready." },
  PENDING: { code: "PENDING", label: "Gate pending", tone: "warning", detail: "Gate is waiting for evidence." },
  PARTIAL: { code: "PARTIAL", label: "Gate partial", tone: "warning", detail: "Gate is only partially satisfied." },
  BLOCKED: { code: "BLOCKED", label: "Gate blocked", tone: "bad", detail: "Gate is blocked." },
  FAIL: { code: "FAIL", label: "Gate failed", tone: "bad", detail: "Gate failed." },
  FAILED: { code: "FAILED", label: "Gate failed", tone: "bad", detail: "Gate failed." },
  REFUSED: { code: "REFUSED", label: "Gate refused", tone: "bad", detail: "Gate evaluation was refused." },
  UNAVAILABLE: { code: "UNAVAILABLE", label: "Gate unavailable", tone: "warning", detail: "Gate state could not be read." },
  EMPTY: { code: "EMPTY", label: "No gate recorded", tone: "neutral", detail: "No gate value was provided." },
} as const satisfies Record<string, DimensionalState>;

function stateKey(value: unknown) {
  if (value === null || value === undefined || value === "") return "EMPTY";
  return String(value).trim().toUpperCase().replace(/[\s-]+/g, "_") || "EMPTY";
}

function unknownState(kind: string, value: unknown): DimensionalState {
  return { code: stateKey(value), label: `${kind}: ${String(value)}`, tone: "warning", detail: "Unmapped state retained literally." };
}

export function describeAuthorityState(value: unknown): DimensionalState {
  const key = stateKey(value);
  return AUTHORITY_STATES[key as keyof typeof AUTHORITY_STATES] ?? unknownState("Authority", value);
}

export function describeEvidenceState(value: unknown): DimensionalState {
  const key = stateKey(value);
  return EVIDENCE_STATES[key as keyof typeof EVIDENCE_STATES] ?? unknownState("Evidence", value);
}

export function describeGateState(value: unknown): DimensionalState {
  const key = stateKey(value);
  return GATE_STATES[key as keyof typeof GATE_STATES] ?? unknownState("Gate", value);
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="g8-brand"><Image src="/brand/nyx-core-transparent.png" alt="NYX Core" width={44} height={44} priority /><div><strong>G8</strong>{!compact && <span>by NYXCore</span>}</div></div>;
}
export function Panel({ title, aside, children, className = "" }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`g8-panel ${className}`}><header><h2>{title}</h2>{aside}</header>{children}</section>;
}
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`g8-badge ${tone}`}>{children}</span>;
}
export function AuthorityBadge({ value, children, title, className = "" }: BadgeProps) {
  const state = describeAuthorityState(value ?? children);
  return <span className={`g8-badge ${state.tone} g8-dimensional-badge authority ${className}`} title={title ?? state.detail} data-state={state.code}><LockKey size={12} />{children ?? state.label}</span>;
}
export function EvidenceBadge({ value, children, title, className = "" }: BadgeProps) {
  const state = describeEvidenceState(value ?? children);
  return <span className={`g8-badge ${state.tone} g8-dimensional-badge evidence ${className}`} title={title ?? state.detail} data-state={state.code}><ShieldCheck size={12} />{children ?? state.label}</span>;
}
export function ScopeChip({ label, value, className = "" }: { label: string; value?: ReactNode; className?: string }) {
  return <span className={`g8-scope-chip ${className}`}><SlidersHorizontal size={12} /><span>{label}</span>{value !== undefined && value !== null && value !== "" && <strong>{value}</strong>}</span>;
}
export function TimeBadge({ value, label = "As of", className = "" }: { value: string | Date | null | undefined; label?: string; className?: string }) {
  const empty = value === null || value === undefined || value === "";
  const text = empty ? "Time unavailable" : value instanceof Date ? value.toLocaleString() : value;
  return <span className={`g8-time-badge ${empty ? "unavailable" : ""} ${className}`}><Clock size={12} /><span>{empty ? text : `${label} ${text}`}</span></span>;
}
export function GateBadge({ value, children, title, className = "" }: BadgeProps) {
  const state = describeGateState(value ?? children);
  return <span className={`g8-badge ${state.tone} g8-dimensional-badge gate ${className}`} title={title ?? state.detail} data-state={state.code}>{children ?? state.label}</span>;
}
export function RefusalState({ title = "Request refused", children, action, onAction }: { title?: string; children: ReactNode; action?: string; onAction?: () => void }) {
  return <div className="g8-refusal-state" role="status"><XCircle size={22} /><div><h3>{title}</h3><p>{children}</p>{action && <button className="g8-link" onClick={onAction}>{action}<ArrowRight size={15} /></button>}</div></div>;
}
export function Empty({ title, children, action, onAction }: { title: string; children: ReactNode; action?: string; onAction?: () => void }) {
  return <div className="g8-empty"><h3>{title}</h3><p>{children}</p>{action && <button className="g8-link" onClick={onAction}>{action}<ArrowRight size={15} /></button>}</div>;
}
export function Signal({ title, detail, tone = "neutral", onClick }: { title: string; detail: string; tone?: "neutral" | "good" | "warning" | "bad"; onClick?: () => void }) {
  const Icon = tone === "good" ? CheckCircle : tone === "warning" || tone === "bad" ? WarningCircle : Clock;
  const body = <><Icon size={20} className={`signal-icon tone-${tone}`} /><span><strong>{title}</strong><small>{detail}</small></span>{onClick && <ArrowRight size={15} />}</>;
  return onClick ? <button className="g8-signal" onClick={onClick}>{body}</button> : <div className="g8-signal">{body}</div>;
}
