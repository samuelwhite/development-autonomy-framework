/** DESIGN ONLY. No runtime, adapter implementation, authentication or execution. */
export type Evidence = "verified" | "unsupported" | "unknown";
export type Check = { id: string; evidence: Evidence; explanation: string };
export type Money = { currency: "USD"; microUnits: number }; // validated safe integer
export type Session = { connectionId: string; sessionId: string; turnId: string | null };
export type Binding = {
  protocol: 1;
  providerId: string;
  adapterVersion: string;
  attemptId: string;
  requestDigest: string;
  planDigest: string;
  projectDigest: string;
  policyDigest: string;
  stopEpoch: number;
};
export type Policy = {
  readRoots: readonly string[];
  writeRoots: readonly string[];
  deniedPaths: readonly string[];
  shell: "deny" | "ask";
  toolNetwork: "deny" | "allowlist";
  allowedHosts: readonly string[];
  modelEgress: readonly string[];
  merge: false;
  deploy: false;
  delegatedAgents: false;
  maxConcurrent: 1;
  maxAttempts: number;
  maxSeconds: number;
  maxTokens: number;
  financialCeiling: Money;
  requireHardFinancialBound: boolean;
};
export type Capabilities = {
  protocol: 1;
  providerId: string;
  adapterVersion: string;
  runtimeVersion: string;
  simulated: boolean;
  platform: "windows" | "linux";
  authentication: readonly ("managed-browser" | "managed-device" | "secret-reference" | "none")[];
  approval: Evidence;
  filesystemIsolation: Evidence;
  toolNetworkIsolation: Evidence;
  interrupt: Evidence;
  exactSessionResume: Evidence;
  authoritativeLookup: Evidence;
  idempotentSubmission: Evidence;
  hardFinancialBound: Evidence;
  usage: "exact" | "estimated" | "unknown";
};
export type Connection = {
  id: string;
  state: "disconnected" | "connecting" | "ready" | "error";
  simulated: boolean;
  billing: "subscription" | "api" | "local" | "unknown";
  checks: readonly Check[];
};
export type ConnectionAction =
  | { kind: "provider-browser"; connectionId: string; url: string; expiresAt: string }
  | { kind: "provider-device"; connectionId: string; url: string; userCode: string; expiresAt: string }
  | { kind: "secret-store-required"; connectionId: string }
  | { kind: "ready"; connection: Connection };
export type Admission = Binding & {
  admissionHandle: string; // opaque host-issued reference, never a browser checkbox
  expiresAt: string;
  isolatedProjectRoot: string;
  policy: Policy;
  prompt: string;
  reservedTokens: number;
  reservedMoney: Money;
};
export type Approval = Binding & Session & {
  requestId: string;
  actionDigest: string;
  operation: "read" | "write" | "command" | "network";
  resource: string;
  explanation: string;
  expiresAt: string;
};
export type Observation = Binding & {
  session: Session | null;
  state: "absent" | "active" | "terminal" | "unknown";
  authoritative: boolean;
  terminalReason?: "completed" | "failed" | "interrupted" | "limit";
  usage: { kind: "exact" | "estimated" | "unknown"; tokens: number | null; money: Money | null };
};
export type Event = Binding & {
  sequence: number;
  eventId: string;
  providerEventId: string | null;
  observedAt: string;
  simulated: boolean;
  session: Session | null;
  payload:
    | { kind: "progress"; text: string }
    | { kind: "approval_required"; approval: Approval }
    | { kind: "observation"; observation: Observation }
    | { kind: "error"; code: string; explanation: string; retryable: boolean };
};
export interface ProviderAdapter {
  describe(): Capabilities;
  probe(policy: Policy): Promise<readonly Check[]>;
  beginConnection(method: Capabilities["authentication"][number], secretRef?: string): Promise<ConnectionAction>;
  cancelConnection(connectionId: string): Promise<void>;
  connectionStatus(connectionId: string): Promise<Connection>;
  disconnect(connectionId: string): Promise<void>;
  start(connectionId: string, admission: Admission): Promise<Observation>;
  events(binding: Binding, afterSequence: number): AsyncIterable<Event>;
  decide(approval: Approval, decision: "allow-once" | "deny", ownerDecisionHandle: string): Promise<void>;
  interrupt(binding: Binding, session: Session | null, stopEpoch: number): Promise<{
    cancellation: "requested" | "confirmed" | "unsupported" | "unknown";
  }>;
  lookup(binding: Binding, session: Session | null): Promise<Observation>;
  resume(session: Session, admission: Admission): Promise<Observation>;
  close(): Promise<{ unresolvedAttemptIds: readonly string[] }>;
}
