import { HttpTestingController } from '@angular/common/http/testing';
import { type ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { By } from '@angular/platform-browser';
import { BehaviorSubject } from 'rxjs';

import { type CallerRole, type FileRead, type FolderRead } from '@core/api/models';
import { MAX_PAGE_SIZE } from '@core/api/pagination';
import { provideAuthTesting } from '@core/auth/auth-testing';
import { UploadQueue } from '@core/uploads/upload-queue.service';
import { DropZoneDirective } from './drop-zone.directive';
import { ExplorerPage } from './explorer.page';
import { ExplorerStore } from './explorer.store';

const STAMP = '2026-01-02T10:00:00Z';
const folder = (id: string, name: string, role: CallerRole): FolderRead => ({
  id,
  parent_id: null,
  name,
  created_at: STAMP,
  updated_at: STAMP,
  role,
});
const file = (id: string, name: string, role: CallerRole): FileRead => ({
  id,
  folder_id: 'shared',
  name,
  content_type: 'application/pdf',
  size_bytes: 10,
  status: 'ready',
  created_at: STAMP,
  updated_at: STAMP,
  role,
});
const page = <T>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 50 });

describe('ExplorerPage sharing controls', () => {
  const setup = async (folderId: string | null, role: CallerRole) => {
    const params$ = new BehaviorSubject(convertToParamMap(folderId ? { folderId } : {}));
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: params$.value }, paramMap: params$ },
        },
      ],
    });
    const fixture: ComponentFixture<ExplorerPage> = TestBed.createComponent(ExplorerPage);
    const backend = TestBed.inject(HttpTestingController);
    await fixture.whenStable();
    if (folderId) {
      backend
        .expectOne(`/api/v1/folders/${folderId}/path`)
        .flush([folder(folderId, 'Shared', role)]);
    }
    backend.expectOne((r) => r.url === '/api/v1/folders').flush(page([folder('d1', 'Docs', role)]));
    backend.expectOne((r) => r.url === '/api/v1/files').flush(page([file('f1', 'a.pdf', role)]));
    await fixture.whenStable();
    await fixture.whenStable();
    return { fixture, backend, root: fixture.nativeElement as HTMLElement };
  };
  const buttons = (root: HTMLElement) =>
    [...root.querySelectorAll('.cd-toolbar button, .cd-toolbar label')].map((b) =>
      b.textContent?.trim(),
    );
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('root_offersUploadAndNewFolder', async () => {
    const { root, backend } = await setup(null, 'owner');
    expect(buttons(root)).toContain('New folder');
    expect(root.querySelector('cd-upload-button')).not.toBeNull();
    backend.verify();
  });

  it('inAFolderSharedAsViewOnly_uploadAndNewFolderAreHidden', async () => {
    const { root } = await setup('shared', 'viewer');
    expect(buttons(root)).not.toContain('New folder');
    expect(root.querySelector('cd-upload-button')).toBeNull();
  });

  it('inAFolderSharedAsEditor_uploadAndNewFolderAreOffered', async () => {
    const { root } = await setup('shared', 'editor');
    expect(buttons(root)).toContain('New folder');
    expect(root.querySelector('cd-upload-button')).not.toBeNull();
  });

  it('ownerShareButton_opensTheShareDialogForThatFolder', async () => {
    const { fixture, backend, root } = await setup(null, 'owner');
    (root.querySelector('[aria-label="Share folder Docs"]') as HTMLButtonElement).click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-share-dialog')).not.toBeNull();
    backend
      .expectOne(`/api/v1/folders/d1/permissions?page=1&page_size=${MAX_PAGE_SIZE}`)
      .flush(page([]));
  });

  it('ownerActivityButton_opensTheActivityDialogForThatFile', async () => {
    const { fixture, backend, root } = await setup(null, 'owner');
    (root.querySelector('[aria-label="Activity for a.pdf"]') as HTMLButtonElement).click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-activity-dialog')).not.toBeNull();
    backend
      .expectOne((r) => r.url === '/api/v1/audit-events' && r.params.get('resource_id') === 'f1')
      .flush(page([]));
  });

  it('viewer_seesNoShareActivityRenameOrDeleteControls', async () => {
    const { root } = await setup('shared', 'viewer');
    const labels = [...root.querySelectorAll('tbody button')].map((b) =>
      b.getAttribute('aria-label'),
    );
    // Reading is allowed, so the summary is too; nothing that changes or shares the file.
    expect(labels).toEqual(['Download a.pdf', 'Summary of a.pdf']);
  });

  it('whileAFolderIsStillLoading_noWriteControlsAreOffered', async () => {
    const params$ = new BehaviorSubject(convertToParamMap({ folderId: 'shared' }));
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: params$.value }, paramMap: params$ },
        },
      ],
    });
    const fixture = TestBed.createComponent(ExplorerPage);
    const backend = TestBed.inject(HttpTestingController);
    await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    // Nothing has been answered yet: the folder's role is unknown, so nothing is offered.
    expect(root.querySelector('cd-skeleton')).not.toBeNull();
    expect(root.querySelector('cd-upload-button')).toBeNull();
    expect(buttons(root)).not.toContain('New folder');
    backend
      .match(() => true)
      .forEach((r) => r.flush({ items: [], total: 0, page: 1, page_size: 50 }));
  });

  it('afterAFailedLoad_noWriteControlsAreOffered', async () => {
    const params$ = new BehaviorSubject(convertToParamMap({ folderId: 'shared' }));
    TestBed.configureTestingModule({
      providers: [
        ...provideAuthTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: params$.value }, paramMap: params$ },
        },
      ],
    });
    const fixture = TestBed.createComponent(ExplorerPage);
    const backend = TestBed.inject(HttpTestingController);
    await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    // The loads run together: the first failure cancels the others.
    const [first] = backend.match(() => true);
    first.flush({ error: { code: 'folder_not_found' } }, { status: 404, statusText: 'x' });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-upload-button')).toBeNull();
    expect(buttons(root)).not.toContain('New folder');
  });

  it('aReloadKeepsTheLastKnownWriteControlsOnScreen', async () => {
    const { fixture, backend, root } = await setup('shared', 'editor');
    expect(root.querySelector('cd-upload-button')).not.toBeNull();
    // Reload (as after creating a folder): the buttons stay mounted while the answer is pending.
    fixture.debugElement.injector.get(ExplorerStore).reload();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-skeleton')).not.toBeNull();
    expect(root.querySelector('cd-upload-button')).not.toBeNull();
    expect(buttons(root)).toContain('New folder');
    backend.expectOne('/api/v1/folders/shared/path').flush([folder('shared', 'Shared', 'editor')]);
    backend.expectOne((r) => r.url === '/api/v1/folders').flush(page([]));
    backend.expectOne((r) => r.url === '/api/v1/files').flush(page([]));
  });

  it('droppingFilesOnAViewOnlyFolder_queuesNothing', async () => {
    const { fixture, root } = await setup('shared', 'viewer');
    const queue = TestBed.inject(UploadQueue);
    const add = vi.spyOn(queue, 'add');
    const zone = fixture.debugElement.query(By.directive(DropZoneDirective));
    zone.triggerEventHandler('filesDropped', [new File(['x'], 'x.txt')]);
    expect(add).not.toHaveBeenCalled();
    expect(root.querySelector('cd-upload-button')).toBeNull();
  });

  it('droppingFilesOnAnEditableFolder_queuesThem', async () => {
    const { fixture } = await setup('shared', 'editor');
    const queue = TestBed.inject(UploadQueue);
    const add = vi.spyOn(queue, 'add').mockImplementation(() => undefined);
    const zone = fixture.debugElement.query(By.directive(DropZoneDirective));
    zone.triggerEventHandler('filesDropped', [new File(['x'], 'x.txt')]);
    expect(add).toHaveBeenCalledOnce();
  });

  it('anOpenDialogClosesWhenTheFolderChanges', async () => {
    const { fixture, backend, root } = await setup(null, 'owner');
    (root.querySelector('[aria-label="Share folder Docs"]') as HTMLButtonElement).click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-share-dialog')).not.toBeNull();
    backend
      .expectOne(`/api/v1/folders/d1/permissions?page=1&page_size=${MAX_PAGE_SIZE}`)
      .flush(page([]));
    const route = TestBed.inject(ActivatedRoute) as unknown as {
      paramMap: BehaviorSubject<ReturnType<typeof convertToParamMap>>;
    };
    route.paramMap.next(convertToParamMap({ folderId: 'other' }));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-share-dialog')).toBeNull();
    backend.match(() => true).forEach((r) => r.flush(page([])));
  });

  it('navigatingFromAnEditableFolderToAViewOnlyOne_offersNothingWhileItLoads', async () => {
    const { fixture, backend, root } = await setup('shared', 'editor');
    expect(root.querySelector('cd-upload-button')).not.toBeNull();
    const route = TestBed.inject(ActivatedRoute) as unknown as {
      paramMap: BehaviorSubject<ReturnType<typeof convertToParamMap>>;
    };
    route.paramMap.next(convertToParamMap({ folderId: 'other' }));
    await fixture.whenStable();
    fixture.detectChanges();
    // The second folder has not answered yet: the first folder's role must not carry over.
    expect(root.querySelector('cd-upload-button')).toBeNull();
    expect(buttons(root)).not.toContain('New folder');
    backend.expectOne('/api/v1/folders/other/path').flush([folder('other', 'Other', 'viewer')]);
    backend.expectOne((r) => r.url === '/api/v1/folders').flush(page([]));
    backend.expectOne((r) => r.url === '/api/v1/files').flush(page([]));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-upload-button')).toBeNull();
  });

  it('aFailedReloadForgetsTheAnswerSoRetryOffersNothingWhileItLoads', async () => {
    const { fixture, backend, root } = await setup('shared', 'editor');
    expect(root.querySelector('cd-upload-button')).not.toBeNull();
    const store = fixture.debugElement.injector.get(ExplorerStore);
    store.reload();
    await fixture.whenStable();
    const [first] = backend.match(() => true);
    first.flush({ error: { code: 'folder_not_found' } }, { status: 404, statusText: 'x' });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-upload-button')).toBeNull();
    // Retry: the stale answer must not bring the controls back while the retry is pending.
    store.reload();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(root.querySelector('cd-skeleton')).not.toBeNull();
    expect(root.querySelector('cd-upload-button')).toBeNull();
    expect(buttons(root)).not.toContain('New folder');
    backend.match(() => true).forEach((r) => !r.cancelled && r.flush(page([])));
  });
});
