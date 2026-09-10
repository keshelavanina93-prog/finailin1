export type ExecutableRequirement = {
  requirement_id: string;
  kind: "ALL_OF" | "ANY_OF" | "ONE_OF" | "OPTIONAL" | "CONDITIONAL";
  fact_type: string | null;
  children: ExecutableRequirement[];
  required_dimensions: string[];
  unit: string | null;
  currency: string | null;
  valid_period: string | null;
  condition: string | null;
  optional: boolean;
};

export type ExecutableFunction = {
  function_id: string;
  domain: string;
  version: string;
  requirements: ExecutableRequirement[];
  required_authority: string | null;
  deterministic: boolean;
  approval_required: boolean;
};

export type ExecutableFinding = {
  requirement_id: string;
  fact_type: string | null;
  state: string;
  message: string;
  children: ExecutableFinding[];
};

export type ExecutablePreflight = {
  function_id: string;
  function_version: string;
  state: "READY" | "PARTIAL" | "BLOCKED" | "REFUSED" | "INCOMPARABLE";
  findings: ExecutableFinding[];
  cycle_path: string[];
};

export type ExecutableFunctionRegistry = {
  contract: "executable-function-registry/1";
  functions: ExecutableFunction[];
  authority_effect: "NONE";
};

export type ExecutablePreflightResponse = {
  preflight: ExecutablePreflight;
  function: ExecutableFunction;
  registry_state: "AUTHORITATIVE_REGISTERED" | "REQUEST_SUPPLIED_CONTRACT";
  authority_effect: "NONE";
};
