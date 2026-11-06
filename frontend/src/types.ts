export interface Citation {
  chunk_id: string;
  document_id: string;
  document_name: string;
  version: number;
  locator: string;
  content: string;
  score: number;
}
export interface ChatMessage {
  id: string; question: string; answer: string; citations: Citation[];
  mode: string; latency_ms: number; token_usage: { prompt_tokens: number; completion_tokens: number };
  created_at: string; approval?: Approval | null; localFeedback?: boolean;
}
export interface DocumentItem {
  id: string; filename: string; file_type: string; version: number; status: string;
  stage: string; error?: string; chunk_count: number; active: boolean; created_at: string;
}
export interface TaskItem {
  id: string; kind: string; entity_id: string; status: string; stage: string;
  progress: number; error?: string; retry_count: number; created_at: string; updated_at: string;
}
export interface Approval {
  id: string; order_id: string; draft: TicketDraft; status: 'pending'|'approved'|'rejected';
  decision_reason?: string; ticket_id?: string; created_at: string;
}
export interface TicketDraft { order_id: string; ticket_type: string; reason: string; priority: string; }
export interface Order {
  order_id: string; customer_name: string; product: string; status: string; status_label: string;
  amount: number; ordered_at: string; delivered_at?: string; logistics: string;
}
export interface DashboardData {
  documents: number; chunks: number; tickets: number; pending_approvals: number; orders: number;
  latest_eval?: { metrics?: Partial<EvalMetrics> | null } | null;
}
export interface EvalMetrics {
  total: number; passed: number; pass_rate: number; avg_latency_ms: number;
  unapproved_writes?: number;
  unapproved_writes_scope?: string;
}
export interface EvalResult { case_id: string; type: string; passed: boolean; latency_ms: number; detail: { answer?: string; citations?: Citation[]; result?: Order; error?: string; mode?: string; usage?: Record<string,number> }; }
export interface EvalRun { id: string; status: string; metrics: EvalMetrics; results: EvalResult[]; dataset_version: string; app_version: string; token_usage: Record<string,number>; created_at: string; }
export interface AuditEvent { id: string; task_id?: string; category: string; action: string; detail: Record<string, unknown>; duration_ms?: number; created_at: string; }
export interface ToolCall { id: string; tool_name: string; parameters: Record<string, unknown>; status: string; result?: Record<string,unknown>; error?: string; latency_ms: number; created_at: string; }
export interface AuditData { events: AuditEvent[]; tool_calls: ToolCall[]; }
export interface Health { status: string; name: string; version: string; llm_enabled: boolean; }
