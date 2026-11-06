import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { type Observable } from 'rxjs';

import { API_BASE } from '@core/api/api-base';
import { type FileRead, type UploadInitRequest, type UploadInitResponse } from '@core/api/models';

/** The two API calls around a direct-to-storage upload. Transport only. */
@Injectable({ providedIn: 'root' })
export class UploadsApi {
  private readonly http = inject(HttpClient);

  init(body: UploadInitRequest): Observable<UploadInitResponse> {
    return this.http.post<UploadInitResponse>(`${API_BASE}/files/uploads`, body);
  }

  complete(fileId: string): Observable<FileRead> {
    return this.http.post<FileRead>(
      `${API_BASE}/files/${encodeURIComponent(fileId)}/uploads/complete`,
      null,
    );
  }
}
