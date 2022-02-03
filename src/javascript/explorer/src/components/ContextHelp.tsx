import { styled, useTheme } from '@mui/material/styles';
import { alpha, Breakpoint } from '@mui/system';
import { ReactNode, useState } from 'react';
import Badge from '@mui/material/Badge';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import HelpIcon from '@mui/icons-material/HelpOutline';


type ContextHelpProps = {
  children: ReactNode;
  title?: ReactNode;
  help: ReactNode;
  maxWidth?: Breakpoint | false;
};


export const ContextHelp = ({ children, title, help, maxWidth }: ContextHelpProps) => {
  const theme = useTheme();
  const [open, setOpen] = useState(false);

  const doClose = () => {
    setOpen(false);
  };

  const doOpen = () => {
    setOpen(true);
  };

  const icon_color = alpha(theme.palette.divider, 0.2);

  return (
    <>
      <div onClick={doOpen}>
        <Badge badgeContent={<HelpIcon fontSize="small" sx={{color: icon_color}} />}>
          {children}
        </Badge>
      </div>
      <Dialog open={open} onClose={doClose} maxWidth={maxWidth}>
        {title && <DialogTitle>{title}</DialogTitle>}
        <div
          style={{
            overflowY: "scroll",
            paddingLeft: theme.spacing(1),
            paddingRight: theme.spacing(1),
            paddingBottom: theme.spacing(3),
          }}
        >
          {help}
        </div>
      </Dialog>
    </>
  );
};

export default ContextHelp;
