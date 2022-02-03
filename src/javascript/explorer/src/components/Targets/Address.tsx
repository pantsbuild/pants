import { styled } from '@mui/material/styles';
import Tooltip, { TooltipProps, tooltipClasses } from '@mui/material/Tooltip';
import Typography, { TypographyProps } from '@mui/material/Typography';
import { parse_address } from "../../lib/target-data";


const AddressTooltip = styled(({ className, ...props }: TooltipProps) => (
  <Tooltip {...props} classes={{ popper: className }} />
))({
  [`& .${tooltipClasses.tooltip}`]: {
    maxWidth: 'none',
  },
});


type AddressProps = TypographyProps & {
  children: string;
  tooltip?: boolean;
};


export const Address = ({ children, tooltip, ...props }: AddressProps) => {
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
    <AddressTooltip arrow title={<Typography variant="subtitle2">{children}</Typography>}>
      {content}
    </AddressTooltip>
  );
};

export default Address;
