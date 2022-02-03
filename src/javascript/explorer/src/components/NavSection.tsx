import { useState } from 'react';
import { matchPath, useLocation, useNavigate } from 'react-router-dom';
import Collapse from '@mui/material/Collapse';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import ListSubheader from '@mui/material/ListSubheader';
import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';

// ----------------------------------------------------------------------

export interface NavConfig {
  title: string;
  path: string;
  icon: React.ReactNode;
  info?: React.ReactNode;
  children?: NavConfig[];
};

// ----------------------------------------------------------------------

type NavItemProps = {
  active: (path: string) => boolean;
  item: NavConfig;
  indent?: number;
};

function NavItem({ item, active, indent = 0 }: NavItemProps) {
  const isActive = active(item.path);
  const navigate = useNavigate();
  const { title, path, icon, info, children } = item;
  const [open, setOpen] = useState(isActive);

  const handleOpen = () => {
    setOpen((prev) => !prev);
  };

  if (children) {
    return (
      <>
        <ListItemButton onClick={handleOpen} selected={isActive} sx={indent ? { pl: indent * 4 } : undefined}>
          <ListItemIcon>{icon && icon}</ListItemIcon>
          <ListItemText primary={title} secondary={info} />
          {open ? <ExpandLess /> : <ExpandMore />}
        </ListItemButton>
        <Collapse in={open} timeout="auto" unmountOnExit>
          <List component="div" disablePadding>
            {children.map((item) => {
              return <NavItem key={item.title} item={item} active={active} indent={indent + 1} />;
            })}
          </List>
        </Collapse>
      </>
    );
  }

  return (
    <ListItemButton selected={isActive} onClick={() => navigate(path)} sx={indent ? { pl: indent * 4 } : undefined}>
      <ListItemIcon>{icon && icon}</ListItemIcon>
      <ListItemText primary={title} secondary={info}/>
    </ListItemButton>
  );
}

type NavSectionProps = {
  navConfig: NavConfig[];
};

export default function NavSection({ navConfig, ...other } : NavSectionProps) {
  const { pathname } = useLocation();
  const match = (path: string) => (path ? !!matchPath({ path, end: false }, pathname) : false);

  return (
    <List disablePadding component="nav" {...other}>
      {navConfig.map((item) => (
        <NavItem key={item.title} item={item} active={match} />
      ))}
    </List>
  );
}
