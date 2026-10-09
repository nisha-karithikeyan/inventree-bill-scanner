/** Minimal shapes of the InvenTree plugin context and the plugin's API. */

export interface HttpClient {
  get<T = any>(url: string, config?: { params?: Record<string, unknown> }): Promise<{ data: T }>;
  post<T = any>(url: string, data?: unknown, config?: Record<string, unknown>): Promise<{ data: T }>;
  patch<T = any>(url: string, data?: unknown): Promise<{ data: T }>;
  delete(url: string): Promise<unknown>;
}

export interface PanelSettings {
  api: string;
  low_confidence: number;
  max_upload_mb: number;
  has_api_key: boolean;
  can_edit: boolean;
  can_confirm: boolean;
}

export interface PluginContext {
  api: HttpClient;
  navigate?: (path: string) => void;
  context: PanelSettings;
}

export type BillStatus =
  | 'pending'
  | 'processing'
  | 'retry'
  | 'failed'
  | 'review'
  | 'completed';

export interface PartDetail {
  pk: number;
  name: string;
  IPN: string;
  description: string;
  thumbnail: string | null;
}

export interface BillLine {
  pk: number;
  line_number: number;
  description: string;
  sku: string;
  quantity: string;
  unit_price: string | null;
  confidence: number;
  part: number | null;
  part_detail: PartDetail | null;
  supplier_part: number | null;
  match_method: string;
  match_confidence: number;
  skip: boolean;
}

export interface Bill {
  pk: number;
  file_url: string | null;
  file_name: string;
  status: BillStatus;
  status_label: string;
  attempts: number;
  error: string;
  supplier_name: string;
  bill_number: string;
  bill_date: string | null;
  currency: string;
  supplier: number | null;
  supplier_detail: { pk: number; name: string } | null;
  supplier_confidence: number;
  purchase_order: number | null;
  created_by: string | null;
  created: string;
  lines: BillLine[];
}

export interface Option {
  value: string;
  label: string;
}
