import { Select } from '@mantine/core';
import React, { useEffect, useState } from 'react';
import type { Option } from '../types';

interface Props {
  label?: string;
  placeholder?: string;
  value: string | null;
  initial?: Option | null;
  disabled?: boolean;
  search: (text: string) => Promise<Option[]>;
  onChange: (value: string | null) => void;
}

/** A searchable select whose options come from an API call. */
export function RemoteSelect({
  label,
  placeholder,
  value,
  initial,
  disabled,
  search,
  onChange
}: Props) {
  const [text, setText] = useState('');
  const [options, setOptions] = useState<Option[]>(initial ? [initial] : []);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      search(text)
        .then((found) => {
          if (cancelled) return;
          const merged = initial && !found.some((o) => o.value === initial.value)
            ? [initial, ...found]
            : found;
          setOptions(merged);
        })
        .catch(() => undefined);
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [text]);

  return (
    <Select
      label={label}
      placeholder={placeholder}
      data={options}
      value={value}
      searchable
      clearable
      disabled={disabled}
      filter={({ options }) => options}
      onSearchChange={setText}
      onChange={onChange}
      nothingFoundMessage='No matches'
      comboboxProps={{ withinPortal: true }}
    />
  );
}
