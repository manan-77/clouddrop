import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from './api-base';
import { type AuditEvent, type Page } from './models';

/** Transport only: the activity on the caller's own files and folders. */
@Injectable({ providedIn: 'root' })
export class AuditApi {
  private readonly http = inject(HttpClient);

  forResource(resourceId: string, page: number, pageSize: number): Observable<Page<AuditEvent>> {
    const params = new HttpParams()
      .set('resource_id', resourceId)
      .set('page', page)
      .set('page_size', pageSize);
    return this.http.get<Page<AuditEvent>>(`${API_BASE}/audit-events`, { params });
  }
}
