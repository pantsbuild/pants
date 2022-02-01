import { useState, useEffect } from "react";
import { request, gql } from "graphql-request";

const query = gql`{ targets }`;

export default () => {
  const [targets, setTargets] = useState([]);
  const [shouldFetchData, setShouldFetchData] = useState(true);

  useEffect(() => {
    if (!shouldFetchData) {
      return
    }

    setShouldFetchData(false);
    request("/graphql", query).then(
      (data) => {
        setTargets(data.targets);
      }
    );
  });

  return (
    <div>
      Target data.
      <pre>{JSON.stringify(targets)}</pre>
    </div>
  );
};
