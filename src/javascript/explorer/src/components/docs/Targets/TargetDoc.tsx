import { Remark } from 'react-remark'
import Card, { CardProps } from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { TargetInfo, TargetFieldInfo } from "../../../lib/target-data/docs";

export const target_types_fields = [
  "alias",
  "provider",
  "summary",
  "description",
  "fields.alias",
  "fields.provider",
  "fields.description",
  "fields.typeHint",
  "fields.required",
  "fields.default",
];

type TargetFieldDocProps = CardProps & {
  info: TargetFieldInfo;
};

export const TargetFieldDoc = ({ info, sx, ...props }: TargetFieldDocProps) => (
  <Card sx={{ mt: 2, mx: 3, ...sx }} {...props}>
    <CardContent>
      <Typography variant="h6"><code>{info.alias}</code>{info.required && " *"}</Typography>
      <Typography variant="subtitle2">{info.provider}</Typography>
      <Divider />
      <Remark>{info.description}</Remark>
    </CardContent>
  </Card>
);

type TargetDocProps = {
  info?: TargetInfo;
};

export const TargetDoc = ({ info }: TargetDocProps) => info ? (
  <>
    <Card>
      <CardContent>
        <Typography variant="h6"><code>{info.alias}</code></Typography>
        <Typography variant="subtitle2">{info.summary}</Typography>
        <Divider />
        <Remark>{info.description}</Remark>
      </CardContent>
    </Card>
    {info.fields.map((field, index) => (
      <TargetFieldDoc key={index} info={field} />
    ))}
  </>
) : null;

export default TargetDoc;
