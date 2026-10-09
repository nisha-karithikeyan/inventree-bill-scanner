import { Alert, Badge, Button, FileButton, Group, Stack, Table, Text } from '@mantine/core';
import { IconUpload } from '@tabler/icons-react';
import React from 'react';
import { STATUS_COLOR } from '../confidence';
import type { Bill } from '../types';

interface Props {
  bills: Bill[];
  selected: number | null;
  uploading: boolean;
  hasApiKey: boolean;
  maxUploadMb: number;
  onUpload: (file: File) => void;
  onSelect: (bill: Bill) => void;
}

const ACCEPT = 'application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif';

/** Upload button and the table of scanned bills. */
export function BillList({
  bills,
  selected,
  uploading,
  hasApiKey,
  maxUploadMb,
  onUpload,
  onSelect
}: Props) {
  return (
    <Stack gap='sm'>
      {!hasApiKey && (
        <Alert color='orange' title='Gemini API key missing'>
          Ask an administrator to set the key in the Bill Scanner plugin settings.
        </Alert>
      )}
      <Group justify='space-between'>
        <Text size='sm' c='dimmed'>
          Upload a photo or PDF of a supplier bill (up to {maxUploadMb} MB).
        </Text>
        <FileButton onChange={(file) => file && onUpload(file)} accept={ACCEPT}>
          {(props) => (
            <Button {...props} leftSection={<IconUpload size={16} />} loading={uploading}>
              Upload bill
            </Button>
          )}
        </FileButton>
      </Group>
      {bills.length === 0 ? (
        <Text c='dimmed'>No bills scanned yet.</Text>
      ) : (
        <Table highlightOnHover striped aria-label='Scanned bills'>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>File</Table.Th>
              <Table.Th>Supplier</Table.Th>
              <Table.Th>Bill number</Table.Th>
              <Table.Th>Date</Table.Th>
              <Table.Th>Lines</Table.Th>
              <Table.Th>Status</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {bills.map((bill) => (
              <Table.Tr
                key={bill.pk}
                onClick={() => onSelect(bill)}
                style={{ cursor: 'pointer' }}
                bg={bill.pk === selected ? 'var(--mantine-color-blue-light)' : undefined}
              >
                <Table.Td>{bill.file_name}</Table.Td>
                <Table.Td>{bill.supplier_detail?.name ?? bill.supplier_name}</Table.Td>
                <Table.Td>{bill.bill_number}</Table.Td>
                <Table.Td>{bill.bill_date ?? ''}</Table.Td>
                <Table.Td>{bill.lines.length}</Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLOR[bill.status]}>{bill.status_label}</Badge>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
