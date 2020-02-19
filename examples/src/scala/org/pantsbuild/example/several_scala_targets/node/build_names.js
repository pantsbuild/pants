const fs = require('fs');
const names = [ 'Hank', 'Frank', 'Rick', 'Nick' ];
fs.mkdirSync('dist/');
fs.writeFileSync('dist/names.json', JSON.stringify(names));
