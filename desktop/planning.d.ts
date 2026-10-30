export interface Source { repository: string; commit_sha: string; path: string; }
export interface Provenance extends Source { git_blob_sha: string; content_sha256: string; plan_sha256: string; }
export interface Milestone { id: string; dependencies: string[]; deliverable: string;
  acceptance: Record<string,string>; proposalId: string; taskSHA256: string;
  instruction: string; allowedPaths: string[]; checks: string; }
export interface Snapshot { id: string; status: 'pinned_plan_proposal'; approval: null;
  executionAuthority: false; spendingAuthority: false;
  verification: 'local_source_observation_requirements_unverified'; source: Provenance;
  project: string; planId: string; version: number; baseline: string; scope: string[];
  deliverables: string[]; requirements: string; milestones: Milestone[]; }
export type Result = {protocol:1;requestId:string} & (
  {outcome:'imported'|'already_present'|'loaded';snapshot:Snapshot} |
  {outcome:'listed';imports:{id:string;project:string;planId:string;source:Provenance}[];damaged:string[]} |
  {outcome:'refused';error:{code:string}});
declare global { interface Window { dafPlanning: {
  importPublicPlan(source:Source):Promise<Result>;
  listImports():Promise<Result>;
  getImport(id:string):Promise<Result>;
  cancelImport():Promise<void>;
}; } }
