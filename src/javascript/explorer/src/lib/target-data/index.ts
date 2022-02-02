import { useEffect, useState } from 'react';
import { request, gql } from "graphql-request";
import { fields2query } from '../gql-utils';


export type TargetData = {
  address: string;
  targetType: string;
  fields: {
    [key: string]: any;
  };
};


export function getTargetFieldValue<T>(data: TargetData, fieldName: string, defaultValue: T | undefined = undefined): T | null | undefined {
  const value = data.fields[fieldName];
  if (value === undefined) {
    return defaultValue;
  }
  return value;
};


export const useTargets = (fields: string[]): [(TargetData|undefined)[], boolean, any, () => void] => {
  const query = gql`{ targets ${fields2query(fields)} }`;
  const [targets, setTargets] = useState([]);
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
      (data) => {
        setTargets(data.targets);
        setLoading(false);
      }
    ).catch(
      (error) => {
        setTargets([]);
        setError(error);
        setLoading(false);
      }
    );
  }, [loading, shouldFetchData, query]);

  return [targets, loading, error, refetch];
};


export type TargetAddress = {
  path: string;
  name: string | null;
  generated_name: string | null;
  default_name: string;
};


export const parse_address = (spec: string): TargetAddress => {
  // Adapted from Python: `pants.build_graph.address:AddessInput.parse()`.
  const spec_parts = spec.split(":", 2);
  let path_component = spec_parts[0];
  let target_component = null;
  let generated_component = null;

  if (spec_parts.length === 1) {
    const generated_parts = path_component.split("#", 2)
    if (generated_parts.length === 2) {
      [path_component, generated_component] = generated_parts;
    }
  }
  else
  {
    const generated_parts = spec_parts[1].split("#", 2)
    if (generated_parts.length === 1)  {
      target_component = generated_parts[0];
    }
    else
    {
      [target_component, generated_component] = generated_parts;
    }
  }

  return {
    path: path_component,
    name: target_component,
    generated_name: generated_component,
    default_name: path_component.split("/")[-1],
  };
};
