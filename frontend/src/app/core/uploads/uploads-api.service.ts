import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from '@core/api/api-base';
import {
  type FileRead,
  type MultipartInitResponse,
  type PartUrlsResponse,
  type UploadInitRequest,
  type UploadInitResponse,
} from '@core/api/models';

/** The two API calls around a direct-to-storage upload. Transport only. */
@Injectable({ providedIn: 'root' })
export class UploadsApi {
  private readonly http = inject(HttpClient);

  init(body: UploadInitRequest): Observable<UploadInitResponse> {
    return this.http.post<UploadInitResponse>(`${API_BASE}/files/uploads`, body);
  }

  initMultipart(body: UploadInitRequest): Observable<MultipartInitResponse> {
    return this.http.post<MultipartInitResponse>(`${API_BASE}/files/uploads/multipart`, body);
  }

  /** A fresh signed address for each part, so a retry never reuses an expired one. */
  partUrls(fileId: string, partNumbers: readonly number[]): Observable<PartUrlsResponse> {
    return this.http.post<PartUrlsResponse>(
      `${API_BASE}/files/${encodeURIComponent(fileId)}/uploads/parts`,
      { part_numbers: partNumbers },
    );
  }

  /** Aborts an unfinished multipart upload and removes its row (best effort, safe to repeat). */
  abort(fileId: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/files/${encodeURIComponent(fileId)}/uploads`);
  }

  /** Soft-deletes the row an abandoned upload left behind (best effort, safe to repeat). */
  discard(fileId: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/files/${encodeURIComponent(fileId)}`);
  }

  complete(fileId: string): Observable<FileRead> {
    return this.http.post<FileRead>(
      `${API_BASE}/files/${encodeURIComponent(fileId)}/uploads/complete`,
      null,
    );
  }
}
