import { useEffect, useState } from 'react';
import { request, gql } from "graphql-request";
import { fields2query } from '../gql-utils';


export function createUseFunction<T>(queryType: string) {
  function useData(fields: string[]): [(T|undefined)[], boolean, any, () => void] {
    const query = gql`{ ${queryType} ${fields2query(fields)} }`;
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
      request("/graphql", query).then(
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
    }, [loading, shouldFetchData, query]);

    return [data, loading, error, refetch];
  }
  return useData;
};
