import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { provideAuthTesting } from '@core/auth/auth-testing';
import { FilesApi } from './files-api.service';

describe('FilesApi', () => {
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it.each([
    ['a folder', 'f1'],
    ['the top level', null],
  ])('move_to_%s_sendsFolderIdInAPatch', (_label, folderId) => {
    TestBed.configureTestingModule({ providers: provideAuthTesting() });
    TestBed.inject(FilesApi).move('a/b', folderId).subscribe();
    const req = TestBed.inject(HttpTestingController).expectOne('/api/v1/files/a%2Fb');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ folder_id: folderId });
  });
});
