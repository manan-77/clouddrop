import { HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';

import {
  ERROR_MESSAGES,
  GENERIC_MESSAGE,
  NETWORK_MESSAGE,
  STATUS_MESSAGES,
} from './error-messages';

export interface ResolvedError {
  readonly message: string;
  readonly code: string | null;
  readonly requestId: string | null;
  /** First validation message per field, for showing inline next to the control. */
  readonly fieldErrors: Readonly<Record<string, string>>;
}

interface ApiErrorEnvelope {
  error: {
    code: string;
    request_id?: string;
    details?: { field: string; message: string }[];
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isEnvelope(value: unknown): value is ApiErrorEnvelope {
  return isRecord(value) && isRecord(value['error']) && typeof value['error']['code'] === 'string';
}

/** The single place API failures become text a person can read. */
@Injectable({ providedIn: 'root' })
export class ErrorResolver {
  resolve(error: unknown): ResolvedError {
    if (!(error instanceof HttpErrorResponse)) {
      return this.build(GENERIC_MESSAGE, null, null, {});
    }
    if (error.status === 0) {
      return this.build(NETWORK_MESSAGE, null, null, {});
    }
    if (isEnvelope(error.error)) {
      const { code, request_id: requestId, details } = error.error.error;
      const message =
        ERROR_MESSAGES[code] ?? STATUS_MESSAGES[error.status] ?? this.fallbackFor(error.status);
      return this.build(message, code, requestId ?? null, this.fieldErrors(details));
    }
    return this.build(
      STATUS_MESSAGES[error.status] ?? this.fallbackFor(error.status),
      null,
      null,
      {},
    );
  }

  private fallbackFor(status: number): string {
    return status >= 500
      ? 'The service is having trouble. Please try again in a moment.'
      : GENERIC_MESSAGE;
  }

  private fieldErrors(
    details: { field: string; message: string }[] | undefined,
  ): Record<string, string> {
    const result: Record<string, string> = {};
    for (const item of details ?? []) {
      if (
        typeof item.field === 'string' &&
        typeof item.message === 'string' &&
        !(item.field in result)
      ) {
        result[item.field] = item.message;
      }
    }
    return result;
  }

  private build(
    message: string,
    code: string | null,
    requestId: string | null,
    fieldErrors: Readonly<Record<string, string>>,
  ): ResolvedError {
    return { message, code, requestId, fieldErrors };
  }
}
