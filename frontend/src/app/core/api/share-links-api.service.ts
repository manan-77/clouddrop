import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from './api-base';
import {
  type DownloadResponse,
  type Page,
  type PublicLink,
  type ShareLink,
  type ShareLinkCreated,
} from './models';

/** Transport only: owner-side links for a file, and the public side that needs no sign-in. */
@Injectable({ providedIn: 'root' })
export class ShareLinksApi {
  private readonly http = inject(HttpClient);

  create(fileId: string, expiresInDays: number): Observable<ShareLinkCreated> {
    return this.http.post<ShareLinkCreated>(this.base(fileId), {
      expires_in_days: expiresInDays,
    });
  }

  list(fileId: string, page: number, pageSize: number): Observable<Page<ShareLink>> {
    const params = new HttpParams().set('page', page).set('page_size', pageSize);
    return this.http.get<Page<ShareLink>>(this.base(fileId), { params });
  }

  revoke(fileId: string, linkId: string): Observable<void> {
    return this.http.delete<void>(`${this.base(fileId)}/${encodeURIComponent(linkId)}`);
  }

  /** The token goes in the body, never the URL, so it stays out of access logs. */
  resolve(token: string): Observable<PublicLink> {
    return this.http.post<PublicLink>(`${API_BASE}/public/share-links/resolve`, { token });
  }

  download(token: string): Observable<DownloadResponse> {
    return this.http.post<DownloadResponse>(`${API_BASE}/public/share-links/download`, { token });
  }

  private base(fileId: string): string {
    return `${API_BASE}/files/${encodeURIComponent(fileId)}/share-links`;
  }
}
