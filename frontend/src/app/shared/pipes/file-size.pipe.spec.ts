import { FileSizePipe } from './file-size.pipe';

describe('FileSizePipe', () => {
  const pipe = new FileSizePipe();

  it.each([
    [0, '0 B'],
    [512, '512 B'],
    [1536, '1.5 KB'],
    [10 * 1024, '10 KB'],
    [5 * 1024 * 1024, '5.0 MB'],
    [1024 ** 4 * 3, '3.0 TB'],
  ])('transform_%i_returns%s', (bytes, expected) => {
    expect(pipe.transform(bytes)).toBe(expected);
  });

  it('transform_invalidInput_returnsEmptyString', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
    expect(pipe.transform(-1)).toBe('');
    expect(pipe.transform(Number.NaN)).toBe('');
  });
});
