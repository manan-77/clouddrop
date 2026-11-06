import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from './api-base';
import { type FolderRead, type Page } from './models';

/** Transport only. One typed client per resource. */
@Injectable({ providedIn: 'root' })
export class FoldersApi {
  private readonly http = inject(HttpClient);

  list(parentId: string | null, page: number, pageSize: number): Observable<Page<FolderRead>> {
    let params = new HttpParams().set('page', page).set('page_size', pageSize);
    if (parentId) {
      params = params.set('parent_id', parentId);
    }
    return this.http.get<Page<FolderRead>>(`${API_BASE}/folders`, { params });
  }

  path(folderId: string): Observable<FolderRead[]> {
    return this.http.get<FolderRead[]>(`${API_BASE}/folders/${encodeURIComponent(folderId)}/path`);
  }

  create(name: string, parentId: string | null): Observable<FolderRead> {
    return this.http.post<FolderRead>(`${API_BASE}/folders`, { name, parent_id: parentId });
  }

  rename(folderId: string, name: string): Observable<FolderRead> {
    return this.http.patch<FolderRead>(`${API_BASE}/folders/${encodeURIComponent(folderId)}`, {
      name,
    });
  }

  remove(folderId: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/folders/${encodeURIComponent(folderId)}`);
  }
}
