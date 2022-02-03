import { createUseFunction } from './common';

export type TargetFieldInfo = {
  alias: string;
  provider: string;
  description: string;
  type_hint: string;
  required: boolean;
  default?: string | null;
};

export type TargetInfo = {
  alias: string;
  provider: string;
  summary: string;
  description: string;
  fields: TargetFieldInfo[];
};

export const useTargetTypes = createUseFunction<TargetInfo>("targetTypes");
