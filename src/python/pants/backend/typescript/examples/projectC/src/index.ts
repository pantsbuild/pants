import { format, addDays } from 'date-fns';
import { DateHelper } from './dateUtils';

export interface TimeConfig {
  format?: string;
  timezone?: string;
}

export class TimeLibrary {
  private config: TimeConfig;
  private helper: DateHelper;

  constructor(config: TimeConfig = {}) {
    this.config = {
      format: 'yyyy-MM-dd',
      ...config
    };
    this.helper = new DateHelper();
  }

  formatDate(date: Date): string {
    return format(date, this.config.format!);
  }

  addDaysToDate(date: Date, days: number): Date {
    return addDays(date, days);
  }

  getCurrentTimestamp(): string {
    return this.helper.getTimestamp();
  }
}

export { DateHelper } from './dateUtils';