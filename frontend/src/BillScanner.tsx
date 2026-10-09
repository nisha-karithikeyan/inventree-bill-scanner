import { Stack } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BillClient, errorMessage } from './client';
import { BillList } from './components/BillList';
import { BillReview } from './components/BillReview';
import { isBusy } from './confidence';
import type { Bill, PluginContext } from './types';

const POLL_MS = 3000;

export function BillScannerPanel({ context }: { context: PluginContext }) {
  const settings = context.context;
  const client = useMemo(() => new BillClient(context.api, settings.api), [context.api]);
  const [bills, setBills] = useState<Bill[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);

  const showError = useCallback((error: unknown) => {
    notifications.show({ color: 'red', title: 'Bill scanner', message: errorMessage(error) });
  }, []);

  const refresh = useCallback(
    () => client.list().then(setBills).catch(showError),
    [client]
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while any bill is still being read by Gemini.
  const waiting = bills.some(isBusy);
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, refresh]);

  const replace = (bill: Bill) =>
    setBills((current) => current.map((b) => (b.pk === bill.pk ? bill : b)));

  async function upload(file: File) {
    setUploading(true);
    try {
      const bill = await client.upload(file);
      setBills((current) => [bill, ...current]);
      setSelected(bill.pk);
    } catch (error) {
      showError(error);
    } finally {
      setUploading(false);
    }
  }

  const current = bills.find((bill) => bill.pk === selected) ?? null;

  return (
    <Stack gap='lg'>
      <BillList
        bills={bills}
        selected={selected}
        uploading={uploading}
        hasApiKey={settings.has_api_key}
        maxUploadMb={settings.max_upload_mb}
        onUpload={upload}
        onSelect={(bill) => setSelected(bill.pk)}
      />
      {current && (
        <BillReview
          key={`${current.pk}-${current.status}-${current.supplier}`}
          bill={current}
          client={client}
          threshold={settings.low_confidence}
          canEdit={settings.can_edit}
          canConfirm={settings.can_confirm}
          onChanged={(bill) => {
            replace(bill);
            if (bill.status === 'completed') {
              notifications.show({ color: 'green', title: 'Bill received', message: 'Purchase order created.' });
            }
          }}
          onDeleted={() => {
            setSelected(null);
            setBills((list) => list.filter((b) => b.pk !== current.pk));
          }}
          onError={showError}
        />
      )}
    </Stack>
  );
}

/** Entry point called by InvenTree's plugin panel loader (one argument = React element). */
export function renderBillScannerPanel(context: PluginContext) {
  return <BillScannerPanel context={context} />;
}
