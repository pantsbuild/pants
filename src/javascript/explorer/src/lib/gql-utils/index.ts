
export type QueryValue = string | number | boolean;
export type Query = {
  [key: string]: QueryValue | Query;
};

function object2args(query: Query): string {
  return Object.entries(query).map(
    ([name, value]) => {
      if (value instanceof Object) {
        return `${name}: {${object2args(value)}}`;
      }
      return `${name}: ${JSON.stringify(value)}`;
    },
  ).join(", ");
}

export const query2args = (query: Query | undefined): string => {
  if (query === undefined) {
    return "";
  }

  return "(" + object2args(query) + ")"
};


export type FieldQuery = {
  [key: string]: FieldQuery | string;
};


function fields2object(fields: string[], obj: FieldQuery): FieldQuery {
  return fields.reduce(
    (res: FieldQuery, field: string) => {
      if (field.includes(".")) {
        const [name, rest] = field.split(".", 2);
        if (!res.hasOwnProperty(name) || typeof res[name] === "string") {
          res[name] = {};
        }
        fields2object([rest], res[name] as FieldQuery);
      } else {
        res[field] = field
      }

      return res;
    },
    obj
  );
}


function object2query(obj: FieldQuery): string {
  return " {" + Object.entries(obj).reduce(
    (query: string, [name, field]) => {
      if (name === field) {
        query += field + " ";
      } else {
        query += name + " " + object2query(field as FieldQuery);
      }
      return query;
    },
    "",
  ) + "} ";
}


export const fields2query = (fields: string[]): string => {
  const obj = fields2object(fields, {});
  return object2query(obj);
};
