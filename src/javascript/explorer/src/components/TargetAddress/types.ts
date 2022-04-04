import { TypographyProps } from '@mui/material/Typography';

export type AddressProps = TypographyProps & {
  children: string;
  tooltip?: boolean;
};

export type TargetAddress = {
  path: string;
  name: string | null;
  generated_name: string | null;
  default_name: string;
};
