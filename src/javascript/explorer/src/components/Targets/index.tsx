import { useTheme } from '@mui/material/styles';
import { darken, alpha, lighten } from '@mui/system';
import useMediaQuery from '@mui/material/useMediaQuery';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
//import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import Masonry from '@mui/lab/Masonry';

import { useTargets } from "../../lib/target-data";
import Loading from "../Loading";
import Error from "../Error";
import RefetchButton from "../RefetchButton";

import Target from "./Target";

type _Counts = {
  [key: string]: number
};

export const TargetsStats = () => {
  const theme = useTheme();
  const [targets, loading, error] = useTargets(["address", "targetType"]);

  if (loading) {
    return <Loading title="Loading targets data..." />;
  }

  if (error) {
    return <Error title="Failed to load target data" error={error.toString()} />;
  }

  const target_types_counts: _Counts = targets.reduce(
    (counts, target) => {
      if (target !== undefined) {
        counts[target.targetType] = (counts[target.targetType] || 0) + 1;
      }
      return counts;
    },
    {} as _Counts
  );

  const target_types_content = Object.entries(target_types_counts).sort().map(
    ([target_type, count], index) => (
      <TableRow key={index}>
        <TableCell>{target_type}</TableCell>
        <TableCell align="right">{count}</TableCell>
      </TableRow>
    )
  );

  const border_color = theme.palette.mode === 'light'
                     ? lighten(alpha(theme.palette.divider, 1), 0.88)
                     : darken(alpha(theme.palette.divider, 1), 0.68);
  const sum_row_border = `4px double ${border_color}`;

  return (
    <Card>
      <CardContent>
        <Typography variant="h6">
          Target type distribution across your repository.
        </Typography>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Target</TableCell>
                <TableCell align="right">Count</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {target_types_content}
              <TableRow>
                <TableCell sx={{ borderTop: sum_row_border }}>Total</TableCell>
                <TableCell sx={{ borderTop: sum_row_border }} align="right">{targets.length}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>
    </Card>
  );
};


export const Targets = () => {
  const theme = useTheme();
  const large = useMediaQuery(theme.breakpoints.up('xl'));
  const small = useMediaQuery(theme.breakpoints.down('lg'));
  const masonry_columns = large ? 3 : small ? 1 : 2;
  
  const [targets, loading, error, refetch] = useTargets(["address", "targetType", "fields"]);


  if (!targets.length) {
    // Skeleton placeholders..
    targets.push(undefined, undefined, undefined, undefined, undefined);
  }

  const show_targets = (targets.length > 100) ? targets.slice(0, 50) : targets;

  const content = targets.slice(0, 50).map(
    (target, index) => (
      <Target key={index} target={target} />
    )
  );

  return (
    <>
      <Stack direction="row" justifyContent="space-between">
        {!loading && !error && <Typography>Showing {show_targets.length} of {targets.length} targets</Typography>}
        {loading && <Loading title="Loading targets data..." />}
        {error && <Error title="Failed to load target data" error={error.toString()} />}
        {!loading && <RefetchButton onClick={refetch} />}
      </Stack>
      <Masonry columns={masonry_columns} spacing={3}>
        {content}
      </Masonry>
    </>
  );
};


export default Targets;
