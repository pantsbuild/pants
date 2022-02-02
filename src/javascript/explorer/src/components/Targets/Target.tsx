import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Divider from '@mui/material/Divider';
import Typography from '@mui/material/Typography';
import Skeleton from '@mui/material/Skeleton';
import Stack from '@mui/material/Stack';

import { TargetData, getTargetFieldValue } from "../../lib/target-data";
import Address from "./Address";


type Props = {
  target?: TargetData;
}

export const Target = ({target}: Props) => {
  if (!target) {
    return (
      <Skeleton variant="rectangular" height={300} />
    );
  }

  const description = getTargetFieldValue<string>(target, "description");
  const tags = getTargetFieldValue<string[]>(target, "tags");
  const dependencies = getTargetFieldValue<string[]>(target, "dependencies");

  return (
    <Card>
      <CardContent>
        <Stack direction="row" justifyContent="space-between">
          <Address gutterBottom>{target.address}</Address>
          <Typography color="text.secondary" gutterBottom>
            {target.targetType}
          </Typography>
        </Stack>
        <Divider />
        <Stack>
          {description && <Typography>{description}</Typography>}
          <pre>{JSON.stringify(tags, undefined, 2)}</pre>
          <pre>{JSON.stringify(dependencies, undefined, 2)}</pre>
        </Stack>
      </CardContent>
    </Card>
  );
};

export default Target;
