import { type ErrorHandler, inject, Injectable } from '@angular/core';

import { ErrorReporter } from './error-reporter.service';

@Injectable()
export class GlobalErrorHandler implements ErrorHandler {
  private readonly reporter = inject(ErrorReporter);

  handleError(error: unknown): void {
    this.reporter.report(error);
  }
}
