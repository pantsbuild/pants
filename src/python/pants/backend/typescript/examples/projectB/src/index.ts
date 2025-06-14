import { capitalize } from 'lodash';
import { formatMessage } from './utils';

export interface LibraryOptions {
  prefix?: string;
  suffix?: string;
}

export class SimpleLibrary {
  private options: LibraryOptions;

  constructor(options: LibraryOptions = {}) {
    this.options = options;
  }

  processText(text: string): string {
    const capitalized = capitalize(text);
    return formatMessage(capitalized, this.options);
  }

  getVersion(): string {
    return '1.0.0';
  }
}

export { formatMessage } from './utils';