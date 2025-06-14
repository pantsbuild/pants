import { LibraryOptions } from './index';

export function formatMessage(message: string, options: LibraryOptions): string {
  const { prefix = '', suffix = '' } = options;
  return `${prefix}${message}${suffix}`;
}

export function isValidString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

export const DEFAULT_CONFIG = {
  prefix: '[INFO] ',
  suffix: ''
} as const;