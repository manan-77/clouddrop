import { TestBed } from '@angular/core/testing';

import { ErrorReporter } from './error-reporter.service';

describe('ErrorReporter', () => {
  it('report_inDevMode_writesToConsole', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const failure = new Error('x');
    TestBed.inject(ErrorReporter).report(failure);
    expect(spy).toHaveBeenCalledWith(failure);
    spy.mockRestore();
  });
});
