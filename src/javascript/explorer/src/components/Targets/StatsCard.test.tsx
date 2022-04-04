import { act, default as renderer, ReactTestRenderer } from 'react-test-renderer';
import { StatsCard } from './StatsCard';


test('StatsCard renders table.', async () => {
  const targets = [
    {address: "//.gitignore:files", targetType: "file", fields: {}},
    {address: "//BUILD_ROOT:files", targetType: "file", fields: {}},
    {address: "//cargo:scripts", targetType: "shell_source", fields: {}},
    {address: "//pants:scripts", targetType: "shell_source", fields: {}},
    {address: "//pants.toml:files", targetType: "file", fields: {}},
    {address: "3rdparty/jvm/com/fasterxml/jackson/core:jackson-databind", targetType: "jvm_artifact", fields: {}},
    {address: "3rdparty/jvm/io/circe:circe-generic", targetType: "jvm_artifact", fields: {}},
    {address: "3rdparty/jvm/org/scalameta:scalameta", targetType: "jvm_artifact", fields: {}},
    {address: "3rdparty/python#PyYAML", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#ansicolors", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#chevron", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#fastapi", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#fasteners", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#freezegun", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#humbug", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#ijson", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#mypy-typing-asserts", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#packaging", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#pex", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#psutil", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#pytest", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#python-lsp-jsonrpc", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#requests", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#setproctitle", targetType: "python_requirement", fields: {}},
    {address: "3rdparty/python#setuptools", targetType: "python_requirement", fields: {}},
  ];

  let component;
  await act(async () => {
    component = renderer.create(
      <StatsCard targets={targets} />
    );
  });

  let tree = (component as unknown as ReactTestRenderer).toJSON();
  expect(tree).toMatchSnapshot();
});
