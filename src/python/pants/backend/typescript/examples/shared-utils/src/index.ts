// Shared utility functions

export * from './math.js';

import type { Result, Status } from '@pants-example/common-types';

export function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export function formatDate(date: Date): string {
  return date.toISOString().split('T')[0];
}

export function createResult<T>(status: Status, data?: T, error?: string): Result<T> {
  return { status, data, error };
}

export function isValidEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

export function capitalizeFirst(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}