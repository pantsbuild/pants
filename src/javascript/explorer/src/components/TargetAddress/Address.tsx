import Typography from '@mui/material/Typography';
import Tooltip from './Tooltip';
import { AddressProps } from './types';
import { parse_address } from './parser';


export default ({ children, tooltip, ...props }: AddressProps) => {
  const address = parse_address(children);
  const content = (
    <div>
      <Typography variant="body1" {...props}>
        {address.generated_name || address.name || address.default_name}
      </Typography>
      <Typography variant="body2" {...props}>
        {address.path}
      </Typography>
    </div>
  );

  if (!tooltip) {
    return content;
  }

  return (
    <Tooltip arrow title={<Typography variant="subtitle2">{children}</Typography>}>
      {content}
    </Tooltip>
  );
};
