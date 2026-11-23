import { ChangeDetectionStrategy, Component } from '@angular/core';
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { DownloadService } from './download.service';
import { DOWNLOAD_START_FAILED, type FileDownloads, fileDownloads } from './file-downloads';

const LINK = { url: 'https://bucket.s3.amazonaws.com/x', expires_in: 300 };
const URL = '/api/v1/files/f1/download';

@Component({
  selector: 'cd-downloads-host',
  template: '',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class Host {
  readonly downloads = fileDownloads();
}

describe('fileDownloads', () => {
  const service = { start: vi.fn() };
  let backend: HttpTestingController;
  let downloads: FileDownloads;

  beforeEach(() => {
    service.start.mockReset();
    TestBed.configureTestingModule({
      providers: [...provideAuthTesting(), { provide: DownloadService, useValue: service }],
    });
    backend = TestBed.inject(HttpTestingController);
    downloads = TestBed.createComponent(Host).componentInstance.downloads;
  });
  afterEach(() => backend.verify());

  it('start_asksForALinkAndHandsItToTheBrowser_markingTheFileBusyMeanwhile', () => {
    downloads.start('f1');
    expect(downloads.busy()).toEqual(['f1']);
    backend.expectOne(URL).flush(LINK);
    expect(service.start).toHaveBeenCalledWith(LINK.url);
    expect(downloads.busy()).toEqual([]);
    expect(downloads.error()).toBeNull();
  });

  it('start_aSecondCallWhileTheFirstRuns_isIgnored', () => {
    downloads.start('f1');
    downloads.start('f1');
    expect(backend.match(URL)).toHaveLength(1);
  });

  it('start_twoDifferentFiles_runTogether', () => {
    downloads.start('f1');
    downloads.start('f2');
    expect(downloads.busy()).toEqual(['f1', 'f2']);
    backend.expectOne(URL).flush(LINK);
    backend.expectOne('/api/v1/files/f2/download').flush(LINK);
    expect(downloads.busy()).toEqual([]);
  });

  it('start_aRefusedRequest_showsTheServersReasonAndFreesTheButton', () => {
    downloads.start('f1');
    backend.expectOne(URL).flush(ENVELOPE('file_not_ready'), { status: 409, statusText: 'x' });
    expect(downloads.error()).toBe('This file is not available yet.');
    expect(downloads.busy()).toEqual([]);
    expect(service.start).not.toHaveBeenCalled();
  });

  it('start_aLinkTheBrowserRefuses_isAMessageNotSilence', () => {
    service.start.mockImplementationOnce(() => {
      throw new Error('Refusing to download from a non-http link');
    });
    downloads.start('f1');
    backend.expectOne(URL).flush({ url: 'javascript:alert(1)', expires_in: 300 });
    expect(downloads.error()).toBe(DOWNLOAD_START_FAILED);
    expect(downloads.busy()).toEqual([]);
  });

  it('start_clearsTheOldMessage_andClearErrorDoesToo', () => {
    downloads.start('f1');
    backend.expectOne(URL).flush(ENVELOPE('file_not_ready'), { status: 409, statusText: 'x' });
    downloads.start('f1');
    expect(downloads.error()).toBeNull();
    backend.expectOne(URL).flush(ENVELOPE('file_not_ready'), { status: 409, statusText: 'x' });
    downloads.clearError();
    expect(downloads.error()).toBeNull();
  });

  it('theRequestIsCancelledWhenTheComponentGoesAway', () => {
    const fixture = TestBed.createComponent(Host);
    fixture.componentInstance.downloads.start('f1');
    const request = backend.expectOne(URL);
    fixture.destroy();
    expect(request.cancelled).toBe(true);
  });
});
