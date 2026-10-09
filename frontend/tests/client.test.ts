import { describe, expect, it } from 'vitest';
import { BillClient, errorMessage } from '../src/client';
import { fakeApi } from './fixtures';

describe('BillClient', () => {
  it('calls the plugin endpoints', async () => {
    const api = fakeApi();
    const client = new BillClient(api, '/plugin/bill-scanner/api');
    await client.list();
    await client.updateLine(1, 5, { skip: true });
    await client.confirm(1, 9);
    expect(api.get).toHaveBeenCalledWith('/plugin/bill-scanner/api/bills/');
    expect(api.patch).toHaveBeenCalledWith('/plugin/bill-scanner/api/bills/1/lines/5/', { skip: true });
    expect(api.post).toHaveBeenCalledWith('/plugin/bill-scanner/api/bills/1/confirm/', { location: 9 });
  });

  it('uploads as multipart form data', async () => {
    const api = fakeApi();
    await new BillClient(api, '/x').upload(new File(['%PDF'], 'a.pdf'));
    const body = api.post.mock.calls[0][1] as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect((body.get('file') as File).name).toBe('a.pdf');
  });

  it('maps search results to options', async () => {
    const api = fakeApi();
    api.get.mockResolvedValueOnce({ data: { results: [{ pk: 4, name: 'Screw', IPN: 'S-1' }] } });
    const options = await new BillClient(api, '/x').search('part', 'scr');
    expect(options).toEqual([{ value: '4', label: 'S-1 | Screw' }]);
    expect(api.get).toHaveBeenCalledWith('/api/part/', {
      params: { active: true, purchaseable: true, search: 'scr', limit: 20 }
    });
  });
});

describe('errorMessage', () => {
  it('reads DRF error bodies', () => {
    expect(errorMessage({ response: { data: { file: ['Too big'] } } })).toBe('Too big');
    expect(errorMessage({ response: { data: { detail: 'Denied' } } })).toBe('Denied');
    expect(errorMessage({ message: 'Network Error' })).toBe('Network Error');
  });
});
