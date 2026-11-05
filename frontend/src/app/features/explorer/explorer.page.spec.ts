import { HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';

import { ENVELOPE, provideAuthTesting } from '@core/auth/auth-testing';
import { type FileRead, type FileStatus, type FolderRead, type Page } from '@core/api/models';
import { DownloadService } from '@core/download/download.service';
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
    TestBed.configureTestingModule({
      providers: [...provideAuthTesting(), { provide: DownloadService, useValue: download }],
    });
    const fixture: ComponentFixture<ExplorerPage> = TestBed.createComponent(ExplorerPage);
    if (folderId) {
      fixture.componentRef.setInput('folderId', folderId);
    }
    const backend = TestBed.inject(HttpTestingController);
    const settle = async () => {
      await fixture.whenStable();
      await fixture.whenStable();
    };
    await settle();
    return { fixture, backend, settle, root: fixture.nativeElement as HTMLElement };
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
    click(root, '.cd-toolbar button');
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
    click(root, '.cd-toolbar button');
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
    click(root, '.cd-toolbar button');
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
});
