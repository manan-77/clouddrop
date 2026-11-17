import { CanManagePipe, CanWritePipe } from './role.pipes';

describe('role pipes', () => {
  it.each([
    ['owner', true],
    ['editor', true],
    ['viewer', false],
  ] as const)('canWrite_%s_is_%s', (role, expected) => {
    expect(new CanWritePipe().transform(role)).toBe(expected);
  });

  it.each([
    ['owner', true],
    ['editor', false],
    ['viewer', false],
  ] as const)('canManage_%s_is_%s', (role, expected) => {
    expect(new CanManagePipe().transform(role)).toBe(expected);
  });
});
