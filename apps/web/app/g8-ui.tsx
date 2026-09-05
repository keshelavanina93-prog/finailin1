"use client";

import Image from "next/image";
import type { ReactNode } from "react";
import { ArrowRight, WarningCircle, CheckCircle, Clock } from "@phosphor-icons/react";

export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="g8-brand"><Image src="/brand/nyx-core-transparent.png" alt="NYX Core" width={44} height={44} priority /><div><strong>G8</strong>{!compact && <span>by NYXCore</span>}</div></div>;
}
export function Panel({ title, aside, children, className = "" }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`g8-panel ${className}`}><header><h2>{title}</h2>{aside}</header>{children}</section>;
}
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warning" | "bad" }) {
  return <span className={`g8-badge ${tone}`}>{children}</span>;
}
export function Empty({ title, children, action, onAction }: { title: string; children: ReactNode; action?: string; onAction?: () => void }) {
  return <div className="g8-empty"><h3>{title}</h3><p>{children}</p>{action && <button className="g8-link" onClick={onAction}>{action}<ArrowRight size={15} /></button>}</div>;
}
export function Signal({ title, detail, tone = "neutral", onClick }: { title: string; detail: string; tone?: "neutral" | "good" | "warning" | "bad"; onClick?: () => void }) {
  const Icon = tone === "good" ? CheckCircle : tone === "warning" || tone === "bad" ? WarningCircle : Clock;
  const body = <><Icon size={20} className={`signal-icon tone-${tone}`} /><span><strong>{title}</strong><small>{detail}</small></span>{onClick && <ArrowRight size={15} />}</>;
  return onClick ? <button className="g8-signal" onClick={onClick}>{body}</button> : <div className="g8-signal">{body}</div>;
}
