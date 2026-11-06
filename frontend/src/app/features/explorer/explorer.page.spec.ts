import { HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { BehaviorSubject } from 'rxjs';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { type FileRead, type FileStatus, type FolderRead, type Page } from '@core/api/models';
import { DownloadService } from '@core/download/download.service';
import { UploadQueue } from '@core/uploads/upload-queue.service';
import { ExplorerPage } from './explorer.page';

const STAMP = '2026-01-02T10:00:00Z';
const folder = (id: string, name: string, parent: string | null = null): FolderRead => ({
  id,
  parent_id: parent,
  name,
  created_at: STAMP,
  updated_at: STAMP,
});
const file = (id: string, name: string, status: FileStatus = 'ready'): FileRead => ({
  id,
  folder_id: null,
  name,
  content_type: 'application/pdf',
  size_bytes: 1536,
  status,
  created_at: STAMP,
  updated_at: STAMP,
});
const page = <T>(items: T[], total = items.length, current = 1, size = 50): Page<T> => ({
  items,
  total,
  page: current,
  page_size: size,
});

const isList = (name: 'folders' | 'files') => (req: { url: string }) =>
  req.url === `/api/v1/${name}`;

describe('ExplorerPage', () => {
  const download = { start: vi.fn() };

  const setup = async (folderId?: string) => {
    const params$ = new BehaviorSubject(convertToParamMap(folderId ? { folderId } : {}));
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        { provide: DownloadService, useValue: download },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: params$.value }, paramMap: params$ },
        },
      ],
    });
    const fixture: ComponentFixture<ExplorerPage> = TestBed.createComponent(ExplorerPage);
    const backend = TestBed.inject(HttpTestingController);
    const settle = async () => {
      await fixture.whenStable();
      await fixture.whenStable();
    };
    await settle();
    return { fixture, backend, settle, params$, root: fixture.nativeElement as HTMLElement };
  };

  const loadRoot = (
    backend: HttpTestingController,
    folders: Page<FolderRead>,
    files: Page<FileRead>,
  ): { folders: TestRequest; files: TestRequest } => {
    const foldersRequest = backend.expectOne(isList('folders'));
    const filesRequest = backend.expectOne(isList('files'));
    foldersRequest.flush(folders);
    filesRequest.flush(files);
    return { folders: foldersRequest, files: filesRequest };
  };

  const click = (root: HTMLElement, selector: string): void =>
    (root.querySelector(selector) as HTMLElement).click();
  const text = (root: HTMLElement, selector: string): string =>
    root.querySelector(selector)?.textContent?.trim() ?? '';

  beforeEach(() => download.start.mockClear());
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('load_beforeResponses_showsASkeleton', async () => {
    const { root, backend } = await setup();
    expect(root.querySelector('cd-skeleton [role="status"]')).not.toBeNull();
    backend.match(() => true).forEach((r) => r.flush(page([])));
  });

  it('load_root_requestsFirstPagesWithoutAParentAndRendersRows', async () => {
    const { root, backend, settle } = await setup();
    const requests = loadRoot(
      backend,
      page([folder('f1', 'Reports')]),
      page([file('a', 'report.pdf')]),
    );
    expect(requests.folders.request.params.get('page')).toBe('1');
    expect(requests.folders.request.params.has('parent_id')).toBe(false);
    expect(requests.files.request.params.has('folder_id')).toBe(false);
    await settle();
    expect(text(root, 'cd-folder-table tbody tr td a')).toBe('Reports');
    expect(text(root, 'cd-file-table tbody tr td')).toBe('report.pdf');
    expect(root.querySelector('cd-file-table cd-status-badge')?.textContent?.trim()).toBe('Ready');
    expect(text(root, 'cd-file-table tbody tr td:nth-child(2)')).toBe('1.5 KB');
    expect(text(root, 'cd-file-table tbody tr td:nth-child(4)')).toMatch(
      /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/,
    );
  });

  it('load_folder_requestsPathAndScopesBothListsToTheFolder', async () => {
    const { root, backend, settle } = await setup('f2');
    const path = backend.expectOne('/api/v1/folders/f2/path');
    const folders = backend.expectOne(isList('folders'));
    const files = backend.expectOne(isList('files'));
    expect(folders.request.params.get('parent_id')).toBe('f2');
    expect(files.request.params.get('folder_id')).toBe('f2');
    path.flush([folder('f1', 'Work'), folder('f2', 'Reports', 'f1')]);
    folders.flush(page([]));
    files.flush(page([]));
    await settle();
    const crumbs = [...root.querySelectorAll('.cd-breadcrumbs li')].map((li) =>
      li.textContent?.trim(),
    );
    expect(crumbs).toEqual(['All files', 'Work', 'Reports']);
    expect(
      root.querySelector('.cd-breadcrumbs li:last-child [aria-current="page"]'),
    ).not.toBeNull();
  });

  it('load_nothingThere_showsTheEmptyState', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    expect(text(root, 'cd-empty-state h2')).toBe('This folder is empty');
  });

  it('load_serverError_showsMappedMessageAndRetryReloads', async () => {
    const { root, backend, settle } = await setup();
    backend
      .expectOne(isList('folders'))
      .flush(ENVELOPE('internal_error'), { status: 500, statusText: 'Server Error' });
    backend.match(isList('files'));
    await settle();
    expect(text(root, 'cd-error-state [role="alert"]')).toContain(
      'Something went wrong on our side',
    );
    click(root, 'cd-error-state button');
    await settle();
    loadRoot(backend, page([folder('f1', 'Reports')]), page([]));
    await settle();
    expect(root.querySelector('cd-folder-table')).not.toBeNull();
  });

  it('fileNames_areRenderedAsTextNeverAsHtml', async () => {
    const { root, backend, settle } = await setup();
    const hostile = '<img src=x onerror=alert(1)>.pdf';
    loadRoot(backend, page([]), page([file('a', hostile)]));
    await settle();
    expect(text(root, 'cd-file-table tbody tr td')).toBe(hostile);
    expect(root.querySelector('cd-file-table img')).toBeNull();
  });

  it('downloadButton_disabledUnlessTheStatusAllowsIt', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(
      backend,
      page([]),
      page([
        file('a', 'ok.pdf'),
        file('b', 'new.pdf', 'pending_upload'),
        file('c', 'bad.pdf', 'infected'),
      ]),
    );
    await settle();
    const disabled = [...root.querySelectorAll('cd-file-table button[aria-label^="Download"]')].map(
      (b) => (b as HTMLButtonElement).disabled,
    );
    expect(disabled).toEqual([false, true, true]);
  });

  it('download_click_asksForALinkAndStartsTheDownload', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([file('a', 'report.pdf')]));
    await settle();
    click(root, 'button[aria-label="Download report.pdf"]');
    backend
      .expectOne('/api/v1/files/a/download')
      .flush({ url: 'https://files.example/x', expires_in: 300 });
    expect(download.start).toHaveBeenCalledWith('https://files.example/x');
  });

  it('download_notReady_showsMappedNoticeAndStartsNothing', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([file('a', 'report.pdf')]));
    await settle();
    click(root, 'button[aria-label="Download report.pdf"]');
    backend
      .expectOne('/api/v1/files/a/download')
      .flush(ENVELOPE('file_not_ready'), { status: 409, statusText: 'Conflict' });
    await settle();
    expect(text(root, '[role="alert"]')).toBe('This file is not available yet.');
    expect(download.start).not.toHaveBeenCalled();
  });

  it('newFolder_emptyName_showsInlineErrorAndSendsNothing', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    click(root, '.cd-toolbar .cd-actions > button');
    await settle();
    (root.querySelector('cd-name-dialog form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    await settle();
    expect(text(root, '#name-dialog-error')).toBe('Name is required.');
    backend.expectNone('/api/v1/folders');
  });

  it('newFolder_valid_isBusyThenClosesAndReloads', async () => {
    const { root, backend, settle } = await setup('f1');
    backend.expectOne('/api/v1/folders/f1/path').flush([folder('f1', 'Work')]);
    backend.expectOne(isList('folders')).flush(page([]));
    backend.expectOne(isList('files')).flush(page([]));
    await settle();
    click(root, '.cd-toolbar .cd-actions > button');
    await settle();
    const input = root.querySelector('#name-dialog-input') as HTMLInputElement;
    input.value = '  Invoices  ';
    input.dispatchEvent(new Event('input'));
    (root.querySelector('cd-name-dialog form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    await settle();
    const submit = root.querySelector('cd-name-dialog button[type="submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    const create = backend.expectOne((r) => r.method === 'POST' && r.url === '/api/v1/folders');
    expect(create.request.body).toEqual({ name: 'Invoices', parent_id: 'f1' });
    create.flush(folder('f9', 'Invoices', 'f1'));
    await settle();
    backend.expectOne('/api/v1/folders/f1/path').flush([folder('f1', 'Work')]);
    backend.expectOne(isList('folders')).flush(page([folder('f9', 'Invoices', 'f1')]));
    backend.expectOne(isList('files')).flush(page([]));
    await settle();
    expect(root.querySelector('cd-name-dialog')).toBeNull();
    expect(text(root, 'cd-folder-table tbody tr td a')).toBe('Invoices');
  });

  it('newFolder_nameTaken_keepsTheDialogOpenWithTheMessageAndAllowsRetry', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    click(root, '.cd-toolbar .cd-actions > button');
    await settle();
    const input = root.querySelector('#name-dialog-input') as HTMLInputElement;
    input.value = 'Reports';
    input.dispatchEvent(new Event('input'));
    (root.querySelector('cd-name-dialog form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    backend
      .expectOne((r) => r.method === 'POST' && r.url === '/api/v1/folders')
      .flush(ENVELOPE('folder_name_taken'), { status: 409, statusText: 'Conflict' });
    await settle();
    expect(text(root, 'cd-name-dialog [role="alert"]')).toBe(
      'A folder with this name already exists here.',
    );
    const submit = root.querySelector('cd-name-dialog button[type="submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });

  it('renameFile_prefillsTheNameAndSendsAPatch', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([file('a', 'old.pdf')]));
    await settle();
    click(root, 'button[aria-label="Rename old.pdf"]');
    await settle();
    const input = root.querySelector('#name-dialog-input') as HTMLInputElement;
    expect(input.value).toBe('old.pdf');
    input.value = 'new.pdf';
    input.dispatchEvent(new Event('input'));
    (root.querySelector('cd-name-dialog form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    const patch = backend.expectOne((r) => r.method === 'PATCH' && r.url === '/api/v1/files/a');
    expect(patch.request.body).toEqual({ name: 'new.pdf' });
    patch.flush(file('a', 'new.pdf'));
    await settle();
    backend.match(() => true).forEach((r) => r.flush(page([])));
  });

  it('deleteFile_confirmed_deletesAndReloads_cancelledDoesNothing', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([file('a', 'old.pdf')]));
    await settle();
    click(root, 'button[aria-label="Delete old.pdf"]');
    await settle();
    expect(text(root, 'cd-confirm-dialog p')).toContain('old.pdf');
    click(root, 'cd-confirm-dialog button[data-variant="secondary"]');
    await settle();
    backend.expectNone((r) => r.method === 'DELETE');

    click(root, 'button[aria-label="Delete old.pdf"]');
    await settle();
    click(root, 'cd-confirm-dialog button[data-variant="danger"]');
    backend.expectOne((r) => r.method === 'DELETE' && r.url === '/api/v1/files/a').flush(null);
    await settle();
    loadRoot(backend, page([]), page([]));
    await settle();
    expect(root.querySelector('cd-confirm-dialog')).toBeNull();
    expect(text(root, 'cd-empty-state h2')).toBe('This folder is empty');
  });

  it('deleteFolder_notEmpty_showsMessageInTheDialog', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([folder('f1', 'Reports')]), page([]));
    await settle();
    click(root, 'button[aria-label="Delete folder Reports"]');
    await settle();
    click(root, 'cd-confirm-dialog button[data-variant="danger"]');
    backend
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/v1/folders/f1')
      .flush(ENVELOPE('folder_not_empty'), { status: 409, statusText: 'Conflict' });
    await settle();
    expect(text(root, 'cd-confirm-dialog [role="alert"]')).toContain('not empty');
  });

  it('pager_next_requestsTheNextPageOfThatListOnly', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([folder('f1', 'A')], 120, 1, 50), page([]));
    await settle();
    expect(text(root, 'nav[aria-label="Folders pagination"] span')).toBe('Page 1 of 3');
    click(root, 'nav[aria-label="Folders pagination"] button:last-child');
    await settle();
    const folders = backend.expectOne(isList('folders'));
    const files = backend.expectOne(isList('files'));
    expect(folders.request.params.get('page')).toBe('2');
    expect(files.request.params.get('page')).toBe('1');
    folders.flush(page([folder('f2', 'B')], 120, 2, 50));
    files.flush(page([]));
  });

  it('emptyPageAfterDeleting_stepsBackToTheLastPage', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([file('a', 'one.pdf')], 40, 1, 20));
    await settle();
    click(root, 'nav[aria-label="Files pagination"] button:last-child');
    await settle();
    backend.expectOne(isList('folders')).flush(page([]));
    backend.expectOne(isList('files')).flush(page([], 20, 2, 20));
    await settle();
    const folders = backend.expectOne(isList('folders'));
    const files = backend.expectOne(isList('files'));
    expect(files.request.params.get('page')).toBe('1');
    folders.flush(page([]));
    files.flush(page([file('a', 'one.pdf')], 20, 1, 20));
  });

  it('emptyPageThatIsAlreadyTheLastPossible_doesNotReloadForever', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([file('a', 'one.pdf')], 40, 1, 20));
    await settle();
    click(root, 'nav[aria-label="Files pagination"] button:last-child');
    await settle();
    backend.expectOne(isList('folders')).flush(page([]));
    backend.expectOne(isList('files')).flush(page([], 40, 2, 20));
    await settle();
    backend.expectNone(isList('files'));
    backend.expectNone(isList('folders'));
  });

  it('dialog_whileTheRequestRuns_cannotBeDismissedAndIsAfterwards', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    click(root, '.cd-toolbar .cd-actions > button');
    await settle();
    const input = root.querySelector('#name-dialog-input') as HTMLInputElement;
    input.value = 'Reports';
    input.dispatchEvent(new Event('input'));
    (root.querySelector('cd-name-dialog form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    await settle();
    const dialog = root.querySelector('cd-name-dialog dialog') as HTMLDialogElement;
    const whileBusy = new Event('cancel', { cancelable: true });
    dialog.dispatchEvent(whileBusy);
    expect(whileBusy.defaultPrevented).toBe(true);
    const cancelButton = root.querySelector('cd-name-dialog button[data-variant="secondary"]');
    expect((cancelButton as HTMLButtonElement).disabled).toBe(true);
    expect((root.querySelector('#name-dialog-input') as HTMLInputElement).readOnly).toBe(true);

    backend
      .expectOne((r) => r.method === 'POST' && r.url === '/api/v1/folders')
      .flush(ENVELOPE('folder_name_taken'), { status: 409, statusText: 'Conflict' });
    await settle();
    const afterwards = new Event('cancel', { cancelable: true });
    root.querySelector('cd-name-dialog dialog')?.dispatchEvent(afterwards);
    expect(afterwards.defaultPrevented).toBe(false);
  });

  it('editingTheName_clearsTheServerMessageInTheDialog', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    click(root, '.cd-toolbar .cd-actions > button');
    await settle();
    const input = root.querySelector('#name-dialog-input') as HTMLInputElement;
    input.value = 'Reports';
    input.dispatchEvent(new Event('input'));
    (root.querySelector('cd-name-dialog form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    backend
      .expectOne((r) => r.method === 'POST' && r.url === '/api/v1/folders')
      .flush(ENVELOPE('folder_name_taken'), { status: 409, statusText: 'Conflict' });
    await settle();
    expect(root.querySelector('cd-name-dialog [role="alert"]')).not.toBeNull();
    input.value = 'Reports 2';
    input.dispatchEvent(new Event('input'));
    await settle();
    expect(root.querySelector('cd-name-dialog [role="alert"]')).toBeNull();
  });

  it('download_doubleClick_sendsOneRequestAndShowsBusyUntilItFinishes', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([file('a', 'report.pdf')]));
    await settle();
    const button = root.querySelector(
      'button[aria-label="Download report.pdf"]',
    ) as HTMLButtonElement;
    button.click();
    button.click();
    await settle();
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.disabled).toBe(true);
    backend
      .expectOne('/api/v1/files/a/download')
      .flush({ url: 'https://files.example/x', expires_in: 300 });
    await settle();
    expect(download.start).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(false);
  });

  it('routeChange_closesAnOpenDialogAndLoadsTheNewFolder', async () => {
    const { root, backend, settle, params$ } = await setup('f1');
    backend.expectOne('/api/v1/folders/f1/path').flush([folder('f1', 'Work')]);
    backend.expectOne(isList('folders')).flush(page([folder('x', 'Old')]));
    backend.expectOne(isList('files')).flush(page([]));
    await settle();
    click(root, 'button[aria-label="Delete folder Old"]');
    await settle();
    expect(root.querySelector('cd-confirm-dialog')).not.toBeNull();

    params$.next(convertToParamMap({ folderId: 'f2' }));
    await settle();
    expect(root.querySelector('cd-confirm-dialog')).toBeNull();
    backend.expectOne('/api/v1/folders/f2/path').flush([folder('f2', 'Other')]);
    backend.expectOne(isList('folders')).flush(page([]));
    backend.expectOne(isList('files')).flush(page([]));
  });

  it('folderNotFound_errorStateOffersAWayBackToAllFiles', async () => {
    const { root, backend, settle } = await setup('gone');
    backend
      .expectOne('/api/v1/folders/gone/path')
      .flush(ENVELOPE('not_found'), { status: 404, statusText: 'Not Found' });
    backend.match(isList('folders'));
    backend.match(isList('files'));
    await settle();
    expect(text(root, 'cd-error-state [role="alert"] p')).toBe('We could not find that.');
    expect(root.querySelector('a[href="/"]')?.textContent).toContain('Go to all files');
  });

  it('notice_isAPersistentLiveRegionThatIsEmptyWhenThereIsNothingToSay', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    const region = root.querySelector('.cd-toolbar ~ p[role="alert"]') as HTMLElement;
    expect(region).not.toBeNull();
    expect(region.textContent?.trim()).toBe('');
  });

  const finishUpload = (backend: HttpTestingController, id: string): void => {
    backend
      .expectOne((r) => r.method === 'POST' && r.url === '/api/v1/files/uploads')
      .flush({
        file: { ...file(id, 'new.pdf'), status: 'pending_upload' },
        upload: { url: 'https://bucket.example/', fields: { key: 'k' }, expires_in: 900 },
      });
    backend
      .expectOne('https://bucket.example/')
      .flush(null, { status: 204, statusText: 'No Content' });
    backend
      .expectOne(`/api/v1/files/${id}/uploads/complete`)
      .flush(file(id, 'new.pdf', 'uploaded'));
  };

  it('uploadFinishedInThisFolder_refreshesTheListing', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    TestBed.inject(UploadQueue).add(
      [new File(['x'], 'new.pdf', { type: 'application/pdf' })],
      null,
    );
    finishUpload(backend, 'n1');
    await settle();
    loadRoot(backend, page([]), page([file('n1', 'new.pdf', 'uploaded')]));
    await settle();
    expect(text(root, 'cd-file-table tbody tr td')).toBe('new.pdf');
    expect(text(root, 'cd-upload-panel .state')).toBe('Uploaded');
  });

  it('uploadFinishedInAnotherFolder_doesNotRefreshThisListing', async () => {
    const { backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    TestBed.inject(UploadQueue).add(
      [new File(['x'], 'new.pdf', { type: 'application/pdf' })],
      'other',
    );
    finishUpload(backend, 'n2');
    await settle();
    backend.expectNone(isList('folders'));
    backend.expectNone(isList('files'));
  });

  it('toolbar_offersUploadAndNewFolder', async () => {
    const { root, backend, settle } = await setup();
    loadRoot(backend, page([]), page([]));
    await settle();
    const labels = [...root.querySelectorAll('.cd-toolbar button')].map((b) =>
      b.textContent?.trim(),
    );
    expect(labels).toEqual(['Upload files', 'New folder']);
  });
});
