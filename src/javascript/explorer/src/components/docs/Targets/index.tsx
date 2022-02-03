import { useState } from 'react';
import { useTheme } from '@mui/material/styles';
import { darken, alpha, lighten } from '@mui/system';
import useMediaQuery from '@mui/material/useMediaQuery';
import Grid from '@mui/material/Grid';
//import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';

import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import ListSubheader from '@mui/material/ListSubheader';
import Skeleton from '@mui/material/Skeleton';

import { useTargetTypes } from "../../../lib/target-data/docs";
import Loading from "../../Loading";
import Error from "../../Error";

import { TargetDoc, target_types_fields } from './TargetDoc';


type TargetTypeDocsProps = {
  alias: string;
};

export const TargetTypeDocs = ({ alias }: TargetTypeDocsProps) => {
  const query = {alias, limit: 1};
  const [targetTypes, loading, error] = useTargetTypes({ query: {query}, fields: target_types_fields });
  if (loading) {
    return <Loading title="Loading target reference doc..." />;
  }
  if (error) {
    return <Error title="Failed to load target reference doc" error={error.toString()} />;
  }

  if (targetTypes.length > 0) {
    return (
      <TargetDoc info={targetTypes[0]} />
    );
  }

  return <Error title="Documentation not found" error={`Searched for "${alias}" but came up empty.`} />;
};


export const TargetTypes = () => {
  const [selected, setSelected] = useState(-1);
  const [targetTypes, loading, error] = useTargetTypes({ fields: target_types_fields });

  if (!targetTypes.length) {
    // Skeleton placeholders..
    targetTypes.push(undefined, undefined, undefined, undefined, undefined);
  }

  const list_content = targetTypes.map(
    (target, index) => target === undefined ? (
      <Skeleton variant="rectangular" height={80} />
    ) : (
      <ListItemButton key={index} selected={selected === index} onClick={() => setSelected(index)}>
        <ListItemText primary={target.alias} secondary={target.description.split("\n", 1)[0]} />
      </ListItemButton>
    )
  );

  const scrollStyle = { maxHeight: "80vh", overflowY: "scroll" };

  return (
    <>
      <Stack>
        {loading && <Loading title="Loading target reference docs..." />}
        {error && <Error title="Failed to load target reference docs" error={error.toString()} />}
      </Stack>
      <Grid container spacing={3}>
        <Grid item xs={12} sm={6} lg={2}>
          <List disablePadding sx={scrollStyle}>
            {list_content}
          </List>
        </Grid>
        <Grid item xs={12} sm={6} lg={10}>
          <List sx={scrollStyle}>
            {selected >= 0 && selected < targetTypes.length && <TargetDoc info={targetTypes[selected]} />}
          </List>
        </Grid>
      </Grid>
    </>
  );
};


export default TargetTypes;
