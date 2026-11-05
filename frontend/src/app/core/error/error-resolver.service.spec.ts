import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { GENERIC_MESSAGE, NETWORK_MESSAGE } from './error-messages';
import { ErrorResolver } from './error-resolver.service';

const envelope = (code: string, details: { field: string; message: string }[] = []) => ({
  error: { code, message: 'server wording <b>x</b>', request_id: 'req-1', details },
});

describe('ErrorResolver', () => {
  const resolver = () => TestBed.inject(ErrorResolver);

  it('resolve_knownCode_returnsMappedMessageAndRequestId', () => {
    const result = resolver().resolve(
      new HttpErrorResponse({ status: 409, error: envelope('folder_name_taken') }),
    );
    expect(result.message).toBe('A folder with this name already exists here.');
    expect(result.code).toBe('folder_name_taken');
    expect(result.requestId).toBe('req-1');
  });

  it('resolve_unknownCode_neverShowsServerWording', () => {
    const result = resolver().resolve(
      new HttpErrorResponse({ status: 400, error: envelope('brand_new_code') }),
    );
    expect(result.message).toBe(GENERIC_MESSAGE);
    expect(result.message).not.toContain('<b>');
  });

  it('resolve_validationDetails_returnsFirstMessagePerField', () => {
    const result = resolver().resolve(
      new HttpErrorResponse({
        status: 422,
        error: envelope('validation_error', [
          { field: 'password', message: 'too short' },
          { field: 'password', message: 'second message' },
          { field: 'email', message: 'invalid' },
        ]),
      }),
    );
    expect(result.fieldErrors).toEqual({ password: 'too short', email: 'invalid' });
  });

  it('resolve_statusZero_returnsNetworkMessage', () => {
    const result = resolver().resolve(new HttpErrorResponse({ status: 0 }));
    expect(result.message).toBe(NETWORK_MESSAGE);
  });

  it('resolve_serverErrorWithoutEnvelope_returnsFriendlyMessage', () => {
    const result = resolver().resolve(
      new HttpErrorResponse({ status: 502, error: '<html>Bad gateway</html>' }),
    );
    expect(result.message).toContain('trouble');
    expect(result.message).not.toContain('html');
  });

  it('resolve_rateLimited_returnsWaitMessage', () => {
    const result = resolver().resolve(new HttpErrorResponse({ status: 429, error: null }));
    expect(result.message).toContain('wait');
  });

  it('resolve_nonHttpError_returnsGenericMessage', () => {
    expect(resolver().resolve(new Error('boom')).message).toBe(GENERIC_MESSAGE);
    expect(resolver().resolve('weird').message).toBe(GENERIC_MESSAGE);
  });
});
