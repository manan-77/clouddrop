import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from './api-base';
import { type FileSummary } from './models';

@Injectable({ providedIn: 'root' })
export class SummaryApi {
  private readonly http = inject(HttpClient);

  /** 404 `summary_not_found` when none has been written (or asked for) yet. */
  get(fileId: string): Observable<FileSummary> {
    return this.http.get<FileSummary>(`${API_BASE}/files/${encodeURIComponent(fileId)}/summary`);
  }

  /** Asks for a new one (needs write access). It is written in the background: the answer is the
   * pending summary, and the previous text is still in it. */
  request(fileId: string): Observable<FileSummary> {
    return this.http.post<FileSummary>(
      `${API_BASE}/files/${encodeURIComponent(fileId)}/summary`,
      null,
    );
  }
}
