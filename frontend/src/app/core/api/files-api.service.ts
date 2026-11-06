import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from './api-base';
import { type DownloadResponse, type FileRead, type Page } from './models';

@Injectable({ providedIn: 'root' })
export class FilesApi {
  private readonly http = inject(HttpClient);

  list(folderId: string | null, page: number, pageSize: number): Observable<Page<FileRead>> {
    let params = new HttpParams().set('page', page).set('page_size', pageSize);
    if (folderId) {
      params = params.set('folder_id', folderId);
    }
    return this.http.get<Page<FileRead>>(`${API_BASE}/files`, { params });
  }

  rename(fileId: string, name: string): Observable<FileRead> {
    return this.http.patch<FileRead>(`${API_BASE}/files/${encodeURIComponent(fileId)}`, { name });
  }

  remove(fileId: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/files/${encodeURIComponent(fileId)}`);
  }

  download(fileId: string): Observable<DownloadResponse> {
    return this.http.get<DownloadResponse>(
      `${API_BASE}/files/${encodeURIComponent(fileId)}/download`,
    );
  }
}
