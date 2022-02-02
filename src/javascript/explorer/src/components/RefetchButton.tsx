import IconButton from '@mui/material/IconButton';
import { IconButtonProps } from '@mui/material/IconButton';
import RefreshIcon from '@mui/icons-material/Refresh';


export const RefetchButton = (props: IconButtonProps) => (
  <IconButton {...props}>
    <RefreshIcon />
  </IconButton>
);

export default RefetchButton;
