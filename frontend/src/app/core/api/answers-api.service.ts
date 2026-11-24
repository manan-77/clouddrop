import { HttpClient, HttpErrorResponse, HttpEventType, type HttpEvent } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { concatWith, defer, EMPTY, from, mergeMap, type Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs';

import { API_BASE } from './api-base';
import { type AnswerEvent, type Citation } from './models';

/** The answer stream was cut off or was not what the server promised. */
export class AnswerStreamError extends Error {
  constructor() {
    super('The answer stream was not valid');
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

function isCitation(value: unknown): value is Citation {
  return (
    isRecord(value) &&
    typeof value['label'] === 'string' &&
    typeof value['file_id'] === 'string' &&
    typeof value['file_name'] === 'string' &&
    typeof value['chunk_id'] === 'string' &&
    (value['page'] === null || typeof value['page'] === 'number')
  );
}

/** Every field is checked: the shape of server data is not taken on trust. */
function parseEvent(json: string): AnswerEvent {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    throw new AnswerStreamError();
  }
  if (isRecord(data)) {
    if (data['type'] === 'token' && typeof data['text'] === 'string') {
      return { type: 'token', text: data['text'] };
    }
    const citations = data['citations'];
    if (
      data['type'] === 'done' &&
      Array.isArray(citations) &&
      citations.every(isCitation) &&
      typeof data['cut_off'] === 'boolean'
    ) {
      return { type: 'done', citations, cut_off: data['cut_off'] };
    }
    if (data['type'] === 'error' && typeof data['code'] === 'string') {
      return { type: 'error', code: data['code'] };
    }
  }
  throw new AnswerStreamError();
}

/**
 * The complete events in `text` after position `consumed` (a server-sent event ends at a blank
 * line). `text` is the whole body so far; whatever follows the last blank line is half an event
 * and is left for the next call.
 */
export function readEvents(
  text: string,
  consumed: number,
): { events: AnswerEvent[]; consumed: number } {
  const events: AnswerEvent[] = [];
  let position = consumed;
  for (let end = text.indexOf('\n\n', position); end !== -1; end = text.indexOf('\n\n', position)) {
    const frame = text.slice(position, end);
    position = end + 2;
    if (frame.startsWith('data: ')) {
      events.push(parseEvent(frame.slice('data: '.length)));
    }
  }
  return { events, consumed: position };
}

/** A refused request answers in JSON, but this request reads text: parse it back so the error
 * resolver sees the same envelope as for every other call. */
function withParsedBody(error: unknown): unknown {
  if (!(error instanceof HttpErrorResponse) || typeof error.error !== 'string') {
    return error;
  }
  try {
    return new HttpErrorResponse({
      error: JSON.parse(error.error),
      headers: error.headers,
      status: error.status,
      statusText: error.statusText,
      url: error.url ?? undefined,
    });
  } catch {
    return error;
  }
}

@Injectable({ providedIn: 'root' })
export class AnswersApi {
  private readonly http = inject(HttpClient);

  /**
   * Events as the answer is written. Unsubscribing cancels the request, which stops the model.
   * Read through the normal HTTP client (progress events carry the text so far), so signing in,
   * refreshing a token and error handling work exactly as for every other call. The question
   * travels in the body, never the URL.
   */
  ask(question: string): Observable<AnswerEvent> {
    return defer(() => {
      let consumed = 0;
      let finished = false;
      return this.http
        .post(
          `${API_BASE}/answers`,
          { question },
          {
            observe: 'events',
            responseType: 'text',
            reportProgress: true,
          },
        )
        .pipe(
          mergeMap((event: HttpEvent<string>) => {
            const text =
              event.type === HttpEventType.DownloadProgress
                ? event.partialText
                : event.type === HttpEventType.Response
                  ? event.body
                  : null;
            if (text == null) {
              return EMPTY;
            }
            const read = readEvents(text, consumed);
            consumed = read.consumed;
            finished ||= read.events.some((item) => item.type !== 'token');
            return from(read.events);
          }),
          // The server always ends an answer with `done` or `error`; anything else was cut off.
          concatWith(defer(() => (finished ? EMPTY : throwError(() => new AnswerStreamError())))),
          catchError((error: unknown) => throwError(() => withParsedBody(error))),
        );
    });
  }
}
