import { act, default as renderer } from 'react-test-renderer';
import { TargetDoc } from './TargetDoc';


test('TargetDoc renders help card.', async () => {
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

  let component;
  await act(async () => {
    component = renderer.create(
      <TargetDoc info={info} />
    );
  });

  let tree = component.toJSON();
  expect(tree).toMatchSnapshot();
});
