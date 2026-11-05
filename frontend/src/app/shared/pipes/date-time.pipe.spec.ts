import { DatePipe, DateTimePipe } from './date-time.pipe';

describe('DateTimePipe', () => {
  const pipe = new DateTimePipe();

  it('transform_date_returnsZeroPaddedDayMonthYear24Hour', () => {
    expect(pipe.transform(new Date(2026, 3, 5, 9, 7))).toBe('05/04/2026 09:07');
    expect(pipe.transform(new Date(2026, 11, 31, 23, 59))).toBe('31/12/2026 23:59');
  });

  it('transform_isoString_isShownInLocalTime', () => {
    const local = new Date(2026, 0, 31, 18, 30);
    expect(pipe.transform(local.toISOString())).toBe('31/01/2026 18:30');
  });

  it('transform_midnight_isShownAs0000NotTwelve', () => {
    expect(pipe.transform(new Date(2026, 5, 1, 0, 0))).toBe('01/06/2026 00:00');
  });

  it('transform_emptyOrInvalid_returnsEmptyString', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform('')).toBe('');
    expect(pipe.transform('not a date')).toBe('');
  });
});

describe('DatePipe', () => {
  it('transform_date_returnsDayMonthYearOnly', () => {
    expect(new DatePipe().transform(new Date(2026, 3, 5, 9, 7))).toBe('05/04/2026');
  });
});
