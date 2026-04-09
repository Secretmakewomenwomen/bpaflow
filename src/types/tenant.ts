export interface TenantRecord {
  tenant_id: string;
  name: string;
  database_url: string;
  config: Record<string, unknown> | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface TenantCreatePayload {
  tenant_id: string;
  name: string;
  database_url?: string;
  database_name?: string;
  config?: Record<string, unknown> | null;
}
