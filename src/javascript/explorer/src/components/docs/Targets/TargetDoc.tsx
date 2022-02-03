import ReactMarkdown from 'react-markdown'
import Card, { CardProps } from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { TargetInfo, TargetFieldInfo } from "../../../lib/target-data/docs";

type TargetFieldDocProps = CardProps & {
  info: TargetFieldInfo;
};

export const TargetFieldDoc = ({ info, ...props }: TargetFieldDocProps) => (
  <Card {...props}>
    <CardContent>
      <Typography variant="h6"><code>{info.alias}</code>{info.required && " *"}</Typography>
      <Typography variant="subtitle2">{info.provider}</Typography>
      <Divider />
      <ReactMarkdown>{info.description}</ReactMarkdown>
    </CardContent>
  </Card>
);

type TargetDocProps = CardProps & {
  info?: TargetInfo;
};

export const TargetDoc = ({ info, sx, ...props }: TargetDocProps) => info ? (
  <>
    <Card sx={sx} {...props}>
      <CardContent>
        <Typography variant="h6"><code>{info.alias}</code></Typography>
        <Typography variant="subtitle2">{info.summary}</Typography>
        <Divider />
        <ReactMarkdown>{info.description}</ReactMarkdown>
      </CardContent>
    </Card>
    {info.fields.map((field, index) => (
      <TargetFieldDoc key={index} info={field} sx={{ mx: 3, ...sx}}{...props} />
    ))}
  </>
) : null;

export default TargetDoc;
