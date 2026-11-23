import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from './api-base';
import { type Page, type SearchHit } from './models';

@Injectable({ providedIn: 'root' })
export class SearchApi {
  private readonly http = inject(HttpClient);

  /** The words travel in the body, never the URL: they must not reach logs, history or referrers. */
  search(query: string, page: number, pageSize: number): Observable<Page<SearchHit>> {
    const params = new HttpParams().set('page', page).set('page_size', pageSize);
    return this.http.post<Page<SearchHit>>(`${API_BASE}/search`, { query }, { params });
  }
}
