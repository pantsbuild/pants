import { styled } from '@mui/material/styles';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import MuiDrawer, { DrawerProps as MuiDrawerProps } from '@mui/material/Drawer';
import Toolbar from '@mui/material/Toolbar';

import NavSection from 'components/NavSection';
import sidebarConfig from './SidebarConfig';

// ----------------------------------------------------------------------

interface DrawerProps extends MuiDrawerProps {
  open: boolean;
  drawerWidth: number;
}

const _no_forward_props = ["open", "drawerWidth"];

const Drawer = styled(MuiDrawer, {
  shouldForwardProp: (prop: string) => !_no_forward_props.includes(prop),
})<DrawerProps>(({ theme, open, drawerWidth }) => ({
  '& .MuiDrawer-paper': {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
    boxSizing: 'border-box',
    ...(!open && {
      overflowX: 'hidden',
      transition: theme.transitions.create('width', {
        easing: theme.transitions.easing.sharp,
        duration: theme.transitions.duration.leavingScreen,
      }),
      width: theme.spacing(7),
      [theme.breakpoints.up('sm')]: {
        width: theme.spacing(9),
      },
    }),
  },
}));


type Props = {
  isOpenSidebar: boolean;
  onCloseSidebar: () => void;
  drawerWidth: number;
}

export default function ExplorerSidebar({ isOpenSidebar, onCloseSidebar, drawerWidth }: Props) {
  return (
    <Drawer variant="permanent" open={isOpenSidebar} drawerWidth={drawerWidth}>
      <Toolbar
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          px: [1],
        }}
      >
        <IconButton onClick={onCloseSidebar}>
          <ChevronLeftIcon />
        </IconButton>
      </Toolbar>
      <Divider />
      <NavSection navConfig={sidebarConfig} />
    </Drawer>
  );
}
