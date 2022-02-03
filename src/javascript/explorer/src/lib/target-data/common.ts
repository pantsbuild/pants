import { useEffect, useState } from 'react';
import { request, gql } from "graphql-request";
import { fields2query, query2args, Query } from '../gql-utils';


export type QueryProps = {
  query?: Query;
  fields: string[];
}


export function createUseFunction<T>(queryType: string) {
  function useData({ query, fields }: QueryProps): [(T|undefined)[], boolean, any, () => void] {
    const q = gql`{ ${queryType}${query2args(query)} ${fields2query(fields)} }`;
    const [data, setData] = useState([]);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);
    const [shouldFetchData, setShouldFetchData] = useState(true);
    const refetch = () => setShouldFetchData(true);

    useEffect(() => {
      if (!shouldFetchData || loading) {
        return
      }

      setShouldFetchData(false);
      setLoading(true);
      request("/graphql", q).then(
        (result) => {
          setData(result[queryType]);
          setLoading(false);
        }
      ).catch(
        (error) => {
          setData([]);
          setError(error);
          setLoading(false);
        }
      );
    }, [loading, shouldFetchData, q]);

    return [data, loading, error, refetch];
  }
  return useData;
};
