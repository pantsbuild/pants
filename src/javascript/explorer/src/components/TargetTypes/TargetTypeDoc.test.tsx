import { act, default as renderer, ReactTestRenderer } from 'react-test-renderer';
import { TargetTypeDoc } from './TargetTypeDoc';


test('TargetTypeDoc renders help card.', async () => {
  const info = {
    alias: 'target-type',
    provider: 'test',
    summary: 'Describes the `target-type` target.',
    description: 'More help text.',
    fields: [
      {
        alias: 'field_a',
        provider: 'test',
        description: 'Info for `field_a`.',
        type_hint: 'str',
        required: true,
        default: 'foo',
      },
      {
        alias: 'field_b',
        provider: 'plugged',
        description: 'Info for `field_b`.',
        type_hint: 'str',
        required: false,
        default: null,
      },
    ],
  };

  let component
  await act(async () => {
    component = renderer.create(
      <TargetTypeDoc info={info} />
    );
  });

  let tree = (component as unknown as ReactTestRenderer).toJSON();
  expect(tree).toMatchSnapshot();
});
