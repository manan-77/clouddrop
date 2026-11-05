import { TestBed } from '@angular/core/testing';

import { ErrorReporter } from './error-reporter.service';
import { GlobalErrorHandler } from './global-error-handler';

describe('GlobalErrorHandler', () => {
  it('handleError_anyError_forwardsToReporter', () => {
    const report = vi.fn();
    TestBed.configureTestingModule({
      providers: [GlobalErrorHandler, { provide: ErrorReporter, useValue: { report } }],
    });
    const failure = new Error('x');
    TestBed.inject(GlobalErrorHandler).handleError(failure);
    expect(report).toHaveBeenCalledWith(failure);
  });
});
