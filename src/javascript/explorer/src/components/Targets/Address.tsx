import Typography, { TypographyProps } from '@mui/material/Typography';
import { parse_address } from "../../lib/target-data";


interface Props extends TypographyProps {
  children: string;
};


export const Address = ({ children, ...props }: Props) => {
  const address = parse_address(children);
  return (
    <Typography variant="body1" {...props}>
      <Typography>
        {address.generated_name || address.name || address.default_name}
      </Typography>
      <Typography variant="body2">
        {address.path}
      </Typography>
    </Typography>
  );
};

export default Address;
