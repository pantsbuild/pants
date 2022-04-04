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

import { useTargets } from "lib/target-data";
import Loading from "components/Loading";
import Error from "components/Error";
import RefetchButton from "components/RefetchButton";
import { StatsCardProps } from './types';


type _Counts = {
  [key: string]: number
};


export const StatsCard = ({ targets }: StatsCardProps) => {
  const theme = useTheme();
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


export default () => {
  const [targets, loading, error] = useTargets(["address", "targetType"]);

  if (loading) {
    return <Loading title="Loading targets data..." />;
  }

  if (error) {
    return <Error title="Failed to load target data" error={error.toString()} />;
  }

  return <StatsCard targets={targets} />
}
