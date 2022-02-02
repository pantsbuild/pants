type QueryObject = {
  [key: string]: QueryObject | string;
};


function fields2object(fields: string[], obj: QueryObject): QueryObject {
  return fields.reduce(
    (res: QueryObject, field: string) => {
      if (field.includes(".")) {
        const [name, rest] = field.split(".", 2);
        if (!res.hasOwnProperty(name) || typeof res[name] === "string") {
          res[name] = {};
        }
        fields2object([rest], res[name] as QueryObject);
      } else {
        res[field] = field
      }

      return res;
    },
    obj
  );
}


function object2query(obj: QueryObject): string {
  return " {" + Object.entries(obj).reduce(
    (query: string, [name, field]) => {
      if (name === field) {
        query += field + " ";
      } else {
        query += name + " " + object2query(field as QueryObject);
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
