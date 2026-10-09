import { Badge, Checkbox, NumberInput, Table, Text, Tooltip } from '@mantine/core';
import React from 'react';
import { LEVEL_BACKGROUND, confidenceColor, lineLevel, percent } from '../confidence';
import type { BillLine, Option } from '../types';
import { RemoteSelect } from './RemoteSelect';

interface Props {
  lines: BillLine[];
  threshold: number;
  editable: boolean;
  searchParts: (text: string) => Promise<Option[]>;
  onChange: (line: BillLine, data: Partial<BillLine>) => void;
}

const METHOD_LABEL: Record<string, string> = {
  supplier_sku: 'Supplier SKU',
  sku: 'Other supplier SKU',
  mpn: 'MPN',
  ipn: 'IPN',
  name: 'Name',
  manual: 'Chosen',
  '': 'No match'
};

function partOption(line: BillLine): Option | null {
  const part = line.part_detail;
  if (!part) return null;
  return { value: String(part.pk), label: part.IPN ? `${part.IPN} | ${part.name}` : part.name };
}

/** Extracted lines with their suggested parts. Low-confidence rows are highlighted. */
export function LineTable({ lines, threshold, editable, searchParts, onChange }: Props) {
  return (
    <Table aria-label='Bill lines' verticalSpacing='xs'>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>#</Table.Th>
          <Table.Th>Description on bill</Table.Th>
          <Table.Th>SKU</Table.Th>
          <Table.Th w={110}>Quantity</Table.Th>
          <Table.Th w={130}>Unit price</Table.Th>
          <Table.Th>Read</Table.Th>
          <Table.Th miw={260}>Part</Table.Th>
          <Table.Th>Match</Table.Th>
          <Table.Th>Skip</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {lines.map((line) => {
          const level = lineLevel(line, threshold);
          return (
            <Table.Tr key={line.pk} bg={LEVEL_BACKGROUND[level]} data-level={level}>
              <Table.Td>{line.line_number}</Table.Td>
              <Table.Td>
                <Text size='sm' td={line.skip ? 'line-through' : undefined}>
                  {line.description}
                </Text>
              </Table.Td>
              <Table.Td>{line.sku}</Table.Td>
              <Table.Td>
                <NumberInput
                  aria-label={`Quantity line ${line.line_number}`}
                  size='xs'
                  min={0}
                  defaultValue={Number(line.quantity)}
                  disabled={!editable}
                  onBlur={(event) => {
                    const value = event.currentTarget.value.replace(/,/g, '');
                    if (value && Number(value) !== Number(line.quantity)) {
                      onChange(line, { quantity: value });
                    }
                  }}
                />
              </Table.Td>
              <Table.Td>
                <NumberInput
                  aria-label={`Unit price line ${line.line_number}`}
                  size='xs'
                  min={0}
                  decimalScale={6}
                  defaultValue={line.unit_price === null ? '' : Number(line.unit_price)}
                  disabled={!editable}
                  onBlur={(event) => {
                    const value = event.currentTarget.value.replace(/,/g, '');
                    const current = line.unit_price === null ? '' : String(Number(line.unit_price));
                    if (value !== current) {
                      onChange(line, { unit_price: value === '' ? null : value });
                    }
                  }}
                />
              </Table.Td>
              <Table.Td>
                <Tooltip label='How clearly Gemini could read this line'>
                  <Badge variant='light' color={confidenceColor(line.confidence, threshold)}>
                    {percent(line.confidence)}
                  </Badge>
                </Tooltip>
              </Table.Td>
              <Table.Td>
                <RemoteSelect
                  placeholder='Search parts'
                  value={line.part ? String(line.part) : null}
                  initial={partOption(line)}
                  disabled={!editable}
                  search={searchParts}
                  onChange={(value) => onChange(line, { part: value ? Number(value) : null })}
                />
              </Table.Td>
              <Table.Td>
                {line.part ? (
                  <Badge variant='light' color={confidenceColor(line.match_confidence, threshold)}>
                    {METHOD_LABEL[line.match_method] ?? line.match_method}{' '}
                    {percent(line.match_confidence)}
                  </Badge>
                ) : (
                  <Badge variant='light' color='red'>No part</Badge>
                )}
              </Table.Td>
              <Table.Td>
                <Checkbox
                  aria-label={`Skip line ${line.line_number}`}
                  checked={line.skip}
                  disabled={!editable}
                  onChange={(event) => onChange(line, { skip: event.currentTarget.checked })}
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </Table.Tbody>
    </Table>
  );
}
