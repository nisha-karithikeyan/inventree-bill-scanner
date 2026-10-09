import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  TextInput,
  Title
} from '@mantine/core';
import React, { useState } from 'react';
import { STATUS_COLOR, confirmBlocker, isBusy } from '../confidence';
import type { BillClient } from '../client';
import type { Bill, BillLine } from '../types';
import { LineTable } from './LineTable';
import { RemoteSelect } from './RemoteSelect';

interface Props {
  bill: Bill;
  client: BillClient;
  threshold: number;
  canEdit: boolean;
  canConfirm: boolean;
  onChanged: (bill: Bill) => void;
  onDeleted: () => void;
  onError: (error: unknown) => void;
}

/** Review, correct and confirm one bill. */
export function BillReview({
  bill,
  client,
  threshold,
  canEdit,
  canConfirm,
  onChanged,
  onDeleted,
  onError
}: Props) {
  const [location, setLocation] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const editable = canEdit && bill.status === 'review';
  const blocker = confirmBlocker(bill);

  async function run(action: () => Promise<Bill | void>) {
    setBusy(true);
    try {
      const result = await action();
      if (result) onChanged(result);
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }

  const updateHeader = (data: Partial<Bill>) => run(() => client.update(bill.pk, data));

  const updateLine = (line: BillLine, data: Partial<BillLine>) =>
    run(async () => {
      await client.updateLine(bill.pk, line.pk, data);
      return client.get(bill.pk);
    });

  return (
    <Paper withBorder p='md'>
      <Stack gap='md'>
        <Group justify='space-between'>
          <Group>
            <Title order={4}>{bill.file_name}</Title>
            <Badge color={STATUS_COLOR[bill.status]}>{bill.status_label}</Badge>
          </Group>
          {bill.file_url && (
            <Anchor href={bill.file_url} target='_blank' rel='noreferrer'>
              Open original
            </Anchor>
          )}
        </Group>

        {bill.error && (
          <Alert color={bill.status === 'failed' ? 'red' : 'orange'} title='Extraction problem'>
            {bill.error} (attempt {bill.attempts})
          </Alert>
        )}
        {isBusy(bill) && <Text c='dimmed'>Gemini is reading this bill...</Text>}

        {bill.status !== 'pending' && bill.status !== 'processing' && (
          <Group grow align='flex-end'>
            <RemoteSelect
              label={`Supplier (bill says "${bill.supplier_name}")`}
              value={bill.supplier ? String(bill.supplier) : null}
              initial={
                bill.supplier_detail
                  ? { value: String(bill.supplier_detail.pk), label: bill.supplier_detail.name }
                  : null
              }
              disabled={!editable}
              search={(text) => client.search('supplier', text)}
              onChange={(value) => updateHeader({ supplier: value ? Number(value) : null })}
            />
            <TextInput
              label='Bill number'
              defaultValue={bill.bill_number}
              disabled={!editable}
              onBlur={(e) =>
                e.currentTarget.value !== bill.bill_number &&
                updateHeader({ bill_number: e.currentTarget.value })
              }
            />
            <TextInput
              label='Bill date'
              type='date'
              defaultValue={bill.bill_date ?? ''}
              disabled={!editable}
              onBlur={(e) =>
                e.currentTarget.value !== (bill.bill_date ?? '') &&
                updateHeader({ bill_date: e.currentTarget.value || null })
              }
            />
            <TextInput
              label='Currency'
              maxLength={3}
              defaultValue={bill.currency}
              disabled={!editable}
              onBlur={(e) =>
                e.currentTarget.value.toUpperCase() !== bill.currency &&
                updateHeader({ currency: e.currentTarget.value.toUpperCase() })
              }
            />
          </Group>
        )}

        {bill.lines.length > 0 && (
          <LineTable
            lines={bill.lines}
            threshold={threshold}
            editable={editable}
            searchParts={(text) => client.search('part', text)}
            onChange={updateLine}
          />
        )}

        <Group justify='space-between'>
          <Group>
            {canEdit && (bill.status === 'failed' || bill.status === 'review') && (
              <Button variant='default' disabled={busy} onClick={() => run(() => client.extract(bill.pk))}>
                Read again
              </Button>
            )}
            {canEdit && bill.status !== 'completed' && (
              <Button
                color='red'
                variant='subtle'
                disabled={busy}
                onClick={() => {
                  if (window.confirm('Delete this bill?')) {
                    run(async () => {
                      await client.remove(bill.pk);
                      onDeleted();
                    });
                  }
                }}
              >
                Delete
              </Button>
            )}
          </Group>
          {bill.status === 'review' && canConfirm && (
            <Group align='flex-end'>
              <RemoteSelect
                placeholder='Receive into location'
                value={location}
                search={(text) => client.search('location', text)}
                onChange={setLocation}
              />
              <Button
                color='green'
                loading={busy}
                disabled={blocker !== null}
                title={blocker ?? undefined}
                onClick={() => run(() => client.confirm(bill.pk, location ? Number(location) : null))}
              >
                Create order and receive
              </Button>
            </Group>
          )}
          {bill.purchase_order && (
            <Anchor href={`/web/purchasing/purchase-order/${bill.purchase_order}/`}>
              View purchase order
            </Anchor>
          )}
        </Group>
        {bill.status === 'review' && blocker && (
          <Text size='sm' c='dimmed'>
            {blocker}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
