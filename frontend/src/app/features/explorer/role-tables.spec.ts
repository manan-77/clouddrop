import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { type CallerRole, type FileRead, type FolderRead } from '@core/api/models';
import { FileTableComponent } from './file-table.component';
import { FolderTableComponent } from './folder-table.component';

const STAMP = '2026-01-02T10:00:00Z';
const folder = (role: CallerRole): FolderRead => ({
  id: 'd1',
  parent_id: null,
  name: 'Docs',
  created_at: STAMP,
  updated_at: STAMP,
  role,
});
const file = (role: CallerRole, status: FileRead['status'] = 'ready'): FileRead => ({
  id: 'f1',
  folder_id: null,
  name: 'a.pdf',
  content_type: 'application/pdf',
  size_bytes: 10,
  status,
  created_at: STAMP,
  updated_at: STAMP,
  role,
});

const labels = (root: HTMLElement) =>
  [...root.querySelectorAll('button')].map((b) => b.textContent?.trim());

describe('role-driven controls', () => {
  it.each([
    ['owner', ['Download', 'Rename', 'Share', 'Activity', 'Delete']],
    ['editor', ['Download', 'Rename']],
    ['viewer', ['Download']],
  ] as const)('fileTable_%s_offersOnly_%j', (role, expected) => {
    const fixture = TestBed.createComponent(FileTableComponent);
    fixture.componentRef.setInput('files', [file(role)]);
    fixture.detectChanges();
    expect(labels(fixture.nativeElement)).toEqual(expected);
  });

  it.each([
    ['owner', ['Rename', 'Share', 'Activity', 'Delete']],
    ['editor', ['Rename']],
    ['viewer', []],
  ] as const)('folderTable_%s_offersOnly_%j', (role, expected) => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(FolderTableComponent);
    fixture.componentRef.setInput('folders', [folder(role)]);
    fixture.detectChanges();
    expect(labels(fixture.nativeElement)).toEqual(expected);
  });

  it('fileTable_aFileThatIsNotReadyCannotBeShared', () => {
    const fixture = TestBed.createComponent(FileTableComponent);
    fixture.componentRef.setInput('files', [file('owner', 'processing')]);
    fixture.detectChanges();
    const share = fixture.nativeElement.querySelector(
      '[aria-label="Share a.pdf"]',
    ) as HTMLButtonElement;
    expect(share.disabled).toBe(true);
  });

  it('fileTable_ownerButtonsEmitTheFile', () => {
    const fixture = TestBed.createComponent(FileTableComponent);
    fixture.componentRef.setInput('files', [file('owner')]);
    fixture.detectChanges();
    const shared: FileRead[] = [];
    const active: FileRead[] = [];
    fixture.componentInstance.share.subscribe((f) => shared.push(f));
    fixture.componentInstance.activity.subscribe((f) => active.push(f));
    (
      fixture.nativeElement.querySelector('[aria-label="Share a.pdf"]') as HTMLButtonElement
    ).click();
    (
      fixture.nativeElement.querySelector('[aria-label="Activity for a.pdf"]') as HTMLButtonElement
    ).click();
    expect(shared).toHaveLength(1);
    expect(active).toHaveLength(1);
  });
});
