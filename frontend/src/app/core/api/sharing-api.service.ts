import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from './api-base';
import {
  type GrantRead,
  type GrantRole,
  type Page,
  type SharedItem,
  type ShareKind,
} from './models';

/** Transport only: who has access to a file or folder, and what has been shared with me. */
@Injectable({ providedIn: 'root' })
export class SharingApi {
  private readonly http = inject(HttpClient);

  list(kind: ShareKind, id: string, page: number, pageSize: number): Observable<Page<GrantRead>> {
    const params = new HttpParams().set('page', page).set('page_size', pageSize);
    return this.http.get<Page<GrantRead>>(this.base(kind, id), { params });
  }

  grant(kind: ShareKind, id: string, email: string, role: GrantRole): Observable<GrantRead> {
    return this.http.post<GrantRead>(this.base(kind, id), { email, role });
  }

  changeRole(
    kind: ShareKind,
    id: string,
    permissionId: string,
    role: GrantRole,
  ): Observable<GrantRead> {
    return this.http.patch<GrantRead>(
      `${this.base(kind, id)}/${encodeURIComponent(permissionId)}`,
      {
        role,
      },
    );
  }

  revoke(kind: ShareKind, id: string, permissionId: string): Observable<void> {
    return this.http.delete<void>(`${this.base(kind, id)}/${encodeURIComponent(permissionId)}`);
  }

  sharedWithMe(page: number, pageSize: number): Observable<Page<SharedItem>> {
    const params = new HttpParams().set('page', page).set('page_size', pageSize);
    return this.http.get<Page<SharedItem>>(`${API_BASE}/shared-with-me`, { params });
  }

  private base(kind: ShareKind, id: string): string {
    return `${API_BASE}/${kind}/${encodeURIComponent(id)}/permissions`;
  }
}
