import type {AnalysisContributor,AnalysisFilter,AnalysisPin,AnalysisProjection} from "./semantic-analysis.js";

export type ReportSectionReference={section_id:string;title:string;invocation_id:string;receipt_hash:string;descriptor_sha256:string;columns:string[];filters:AnalysisFilter[];group_by:string|null};
export type ReportComposition={company_id:string;valid_at:string;known_at:string;title:string;commentary:string;sections:ReportSectionReference[]};
export type ReportSectionResult={reference:ReportSectionReference;projection:AnalysisProjection;contributors:Record<string,AnalysisContributor[]>;authority_observation:{roots:AnalysisPin[];upstream:Array<Record<string,unknown>>};current_use_authorized:false;business_effect_authorized:false};
export type RetainedReportSnapshot={contract:"retained-report-snapshot/1";composition:ReportComposition;company:AnalysisPin;company_label:string;sections:ReportSectionResult[];current_use_authorized:false;business_effect_authorized:false};
export type ReportPreview={contract:"retained-report-preview/1";snapshot:RetainedReportSnapshot;snapshot_sha256:string};
export type SaveRetainedReport={request_id:string;report_id:string;previous_proposal_id:string|null;expected_preview_sha256:string;composition:ReportComposition};
export type ReportVersionReference={report_id:string;proposal_id:string;content_hash:string};
export type ReportArtifactMetadata={media_type:string;filename:string;size_bytes:number;sha256:string};
export type RetainedReport={contract:"retained-report/1";reference:ReportVersionReference;previous_proposal_id:string|null;company_id:string;title:string;created_at:string;created_by:string;review_state:"DRAFT"|"APPROVED"|"REJECTED";snapshot:RetainedReportSnapshot;exports:{xlsx:ReportArtifactMetadata;html:ReportArtifactMetadata};current_use_authorized:false;business_effect_authorized:false};
export type RetainedReportListItem=Omit<RetainedReport,"snapshot"|"exports">;
export type RetainedReportPage={contract:"retained-report-list/1";company_id:string;items:RetainedReportListItem[];next_cursor:{created_at:string;proposal_id:string}|null};
