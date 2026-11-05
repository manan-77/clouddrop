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

interface ParsedEnvelope {
  code: string;
  requestId: string | null;
  details: readonly unknown[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function parseEnvelope(body: unknown): ParsedEnvelope | null {
  if (!isRecord(body) || !isRecord(body['error'])) {
    return null;
  }
  const { code, request_id: requestId, details } = body['error'];
  if (typeof code !== 'string') {
    return null;
  }
  return {
    code,
    requestId: typeof requestId === 'string' ? requestId : null,
    details: Array.isArray(details) ? details : [],
  };
}

// Own-property lookups only: a server-sent code such as "constructor" must not hit Object.prototype.
function lookup(
  table: Readonly<Record<string | number, string>>,
  key: string | number,
): string | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/** The single place API failures become text a person can read. */
@Injectable({ providedIn: 'root' })
export class ErrorResolver {
  resolve(error: unknown): ResolvedError {
    if (!(error instanceof HttpErrorResponse)) {
      return this.build(GENERIC_MESSAGE);
    }
    if (error.status === 0) {
      return this.build(NETWORK_MESSAGE);
    }
    const envelope = parseEnvelope(error.error);
    if (envelope) {
      const message =
        lookup(ERROR_MESSAGES, envelope.code) ??
        lookup(STATUS_MESSAGES, error.status) ??
        this.fallbackFor(error.status);
      return this.build(
        message,
        envelope.code,
        envelope.requestId,
        this.fieldErrors(envelope.details),
      );
    }
    return this.build(lookup(STATUS_MESSAGES, error.status) ?? this.fallbackFor(error.status));
  }

  private fallbackFor(status: number): string {
    return status >= 500
      ? 'The service is having trouble. Please try again in a moment.'
      : GENERIC_MESSAGE;
  }

  // Field messages come from the server's validation layer and are deliberately shown as sent (the
  // API contract marks them safe); they are only ever interpolated, never injected as HTML.
  private fieldErrors(details: readonly unknown[]): Record<string, string> {
    const first = new Map<string, string>();
    for (const item of details) {
      if (
        isRecord(item) &&
        typeof item['field'] === 'string' &&
        typeof item['message'] === 'string' &&
        !first.has(item['field'])
      ) {
        first.set(item['field'], item['message']);
      }
    }
    // fromEntries defines own properties, so a field named "__proto__" stays harmless data.
    return Object.fromEntries(first);
  }

  private build(
    message: string,
    code: string | null = null,
    requestId: string | null = null,
    fieldErrors: Readonly<Record<string, string>> = {},
  ): ResolvedError {
    return { message, code, requestId, fieldErrors };
  }
}
