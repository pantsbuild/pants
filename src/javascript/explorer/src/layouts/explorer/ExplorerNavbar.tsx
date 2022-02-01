import { styled } from '@mui/material/styles';
import Badge from '@mui/material/Badge';
import IconButton from '@mui/material/IconButton';
import MenuIcon from '@mui/icons-material/Menu';
import MuiAppBar, { AppBarProps as MuiAppBarProps } from '@mui/material/AppBar';
import NotificationsIcon from '@mui/icons-material/Notifications';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';

// ----------------------------------------------------------------------

interface AppBarProps extends MuiAppBarProps {
  open: boolean;
  drawerWidth: number;
}

const _no_forward_props = ["open", "drawerWidth"];

const AppBar = styled(MuiAppBar, {
  shouldForwardProp: (prop: string) => !_no_forward_props.includes(prop),
})<AppBarProps>(({ theme, open, drawerWidth }) => ({
  zIndex: theme.zIndex.drawer + 1,
  transition: theme.transitions.create(['width', 'margin'], {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.leavingScreen,
  }),
  ...(open && {
    marginLeft: drawerWidth,
    width: `calc(100% - ${drawerWidth}px)`,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  }),
}));


type Props = {
  isOpenSidebar: boolean;
  onOpenSidebar: () => void;
  drawerWidth: number;
};

export default function ExplorerNavbar({ isOpenSidebar, onOpenSidebar, drawerWidth }: Props) {
  return (
    <AppBar position="absolute" open={isOpenSidebar} drawerWidth={drawerWidth}>
      <Toolbar
        sx={{
          pr: '24px', // keep right padding when drawer closed
        }}
      >
        <IconButton
          edge="start"
          color="inherit"
          aria-label="open drawer"
          onClick={onOpenSidebar}
          sx={{
            marginRight: '36px',
            ...(isOpenSidebar && { display: 'none' }),
          }}
        >
          <MenuIcon />
        </IconButton>
        <Typography
          component="h1"
          variant="h6"
          color="inherit"
          noWrap
          sx={{ flexGrow: 1 }}
        >
          Pants Build System | Explorer
        </Typography>
        <IconButton color="inherit">
          <Badge badgeContent={4} color="secondary">
            <NotificationsIcon />
          </Badge>
        </IconButton>
      </Toolbar>
    </AppBar>
  );
}
