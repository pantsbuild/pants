import { useState } from 'react';
import { matchPath, useLocation, useNavigate } from 'react-router-dom';
import Collapse from '@mui/material/Collapse';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import ListSubheader from '@mui/material/ListSubheader';

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
};

function NavItem({ item, active }: NavItemProps) {
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
        <ListItem button onClick={handleOpen} selected={isActive}>
          <ListItemIcon>{icon && icon}</ListItemIcon>
          <ListItemText primary={title} secondary={info} />
        </ListItem>
        <Collapse in={open} timeout="auto" unmountOnExit>
          <List component="div" disablePadding>
            {children.map((item) => {
              return <NavItem key={item.title} item={item} active={active} />;
            })}
          </List>
        </Collapse>
      </>
    );
  }

  return (
    <ListItem button selected={isActive} onClick={() => navigate(path)}>
      <ListItemIcon>{icon && icon}</ListItemIcon>
      <ListItemText primary={title} secondary={info}/>
    </ListItem>
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
