import type { Bill, BillLine, HttpClient, Option } from './types';

/** Typed wrapper around InvenTree's axios instance for this plugin's endpoints. */
export class BillClient {
  constructor(
    private readonly http: HttpClient,
    private readonly base: string
  ) {}

  async list(): Promise<Bill[]> {
    return (await this.http.get<Bill[]>(`${this.base}/bills/`)).data;
  }

  async get(pk: number): Promise<Bill> {
    return (await this.http.get<Bill>(`${this.base}/bills/${pk}/`)).data;
  }

  async upload(file: File): Promise<Bill> {
    const form = new FormData();
    form.append('file', file);
    return (await this.http.post<Bill>(`${this.base}/bills/`, form)).data;
  }

  async update(pk: number, data: Partial<Bill>): Promise<Bill> {
    return (await this.http.patch<Bill>(`${this.base}/bills/${pk}/`, data)).data;
  }

  async updateLine(bill: number, line: number, data: Partial<BillLine>): Promise<BillLine> {
    return (await this.http.patch<BillLine>(`${this.base}/bills/${bill}/lines/${line}/`, data)).data;
  }

  async extract(pk: number): Promise<Bill> {
    return (await this.http.post<Bill>(`${this.base}/bills/${pk}/extract/`)).data;
  }

  async confirm(pk: number, location: number | null): Promise<Bill> {
    return (await this.http.post<Bill>(`${this.base}/bills/${pk}/confirm/`, { location })).data;
  }

  async remove(pk: number): Promise<void> {
    await this.http.delete(`${this.base}/bills/${pk}/`);
  }

  async search(kind: 'part' | 'supplier' | 'location', text: string): Promise<Option[]> {
    const { url, params, label } = SEARCHES[kind];
    const response = await this.http.get<{ results: any[] } | any[]>(url, {
      params: { ...params, search: text, limit: 20 }
    });
    const rows = Array.isArray(response.data) ? response.data : response.data.results;
    return rows.map((row) => ({ value: String(row.pk), label: label(row) }));
  }
}

const SEARCHES = {
  part: {
    url: '/api/part/',
    params: { active: true, purchaseable: true },
    label: (row: any) => (row.IPN ? `${row.IPN} | ${row.name}` : row.name)
  },
  supplier: {
    url: '/api/company/',
    params: { is_supplier: true, active: true },
    label: (row: any) => row.name
  },
  location: {
    url: '/api/stock/location/',
    params: {},
    label: (row: any) => row.pathstring ?? row.name
  }
};

/** Pull a readable message out of an axios/DRF error. */
export function errorMessage(error: any): string {
  const data = error?.response?.data;
  if (typeof data === 'string') return data.slice(0, 300);
  if (data && typeof data === 'object') {
    const first = Object.values(data)[0];
    return Array.isArray(first) ? String(first[0]) : String(first);
  }
  return error?.message ?? 'Request failed';
}
