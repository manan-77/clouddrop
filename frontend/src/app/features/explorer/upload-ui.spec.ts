import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { UploadQueue, type UploadItem } from '@core/uploads/upload-queue.service';
import { DropZoneDirective } from './drop-zone.directive';
import { UploadButtonComponent } from './upload-button.component';
import { UploadPanelComponent } from './upload-panel.component';

const item = (patch: Partial<UploadItem>): UploadItem => ({
  id: 'u1',
  file: new File(['x'], 'a.pdf'),
  name: 'a.pdf',
  size: 1536,
  folderId: null,
  status: 'uploading',
  progress: 40,
  error: null,
  fileId: null,
  ...patch,
});

describe('UploadPanelComponent', () => {
  const setup = async (items: UploadItem[]) => {
    const fixture = TestBed.createComponent(UploadPanelComponent);
    fixture.componentRef.setInput('items', items);
    const events: string[] = [];
    fixture.componentInstance.cancelUpload.subscribe((id) => events.push(`cancel:${id}`));
    fixture.componentInstance.retryUpload.subscribe((id) => events.push(`retry:${id}`));
    fixture.componentInstance.removeUpload.subscribe((id) => events.push(`remove:${id}`));
    await fixture.whenStable();
    return { root: fixture.nativeElement as HTMLElement, events };
  };

  it('noItems_rendersNothing', async () => {
    const { root } = await setup([]);
    expect(root.querySelector('section')).toBeNull();
  });

  it('uploading_showsNameSizeAccessibleProgressAndCancel', async () => {
    const { root, events } = await setup([item({})]);
    expect(root.querySelector('.name')?.textContent).toBe('a.pdf');
    expect(root.querySelector('.size')?.textContent).toBe('1.5 KB');
    const bar = root.querySelector('progress') as HTMLProgressElement;
    expect(bar.value).toBe(40);
    expect(bar.getAttribute('aria-label')).toBe('Upload progress for a.pdf');
    expect(root.querySelector('.state')?.textContent).toBe('Uploading');
    (
      root.querySelector('button[aria-label="Cancel upload of a.pdf"]') as HTMLButtonElement
    ).click();
    expect(events).toEqual(['cancel:u1']);
  });

  it('failed_showsTheMessageAsAnAlertWithRetryAndRemove', async () => {
    const { root, events } = await setup([item({ status: 'failed', error: 'Nope', progress: 0 })]);
    expect(root.querySelector('[role="alert"]')?.textContent).toBe('Nope');
    expect(root.querySelector('progress')).toBeNull();
    (root.querySelector('button[aria-label="Retry a.pdf"]') as HTMLButtonElement).click();
    (root.querySelector('button[aria-label="Remove a.pdf"]') as HTMLButtonElement).click();
    expect(events).toEqual(['retry:u1', 'remove:u1']);
  });

  it('fileNames_areTextNeverHtml', async () => {
    const { root } = await setup([item({ name: '<img src=x onerror=alert(1)>.pdf' })]);
    expect(root.querySelector('.name')?.textContent).toBe('<img src=x onerror=alert(1)>.pdf');
    expect(root.querySelector('img')).toBeNull();
  });
});

describe('UploadButtonComponent', () => {
  it('choosingFiles_queuesThemIntoTheFolderAndResetsThePicker', async () => {
    const add = vi.fn();
    TestBed.configureTestingModule({ providers: [{ provide: UploadQueue, useValue: { add } }] });
    const fixture = TestBed.createComponent(UploadButtonComponent);
    fixture.componentRef.setInput('folderId', 'folder-9');
    await fixture.whenStable();
    const input = (fixture.nativeElement as HTMLElement).querySelector('input') as HTMLInputElement;
    const files = [new File(['a'], 'a.pdf'), new File(['b'], 'b.pdf')];
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    input.dispatchEvent(new Event('change'));
    expect(add).toHaveBeenCalledWith(files, 'folder-9');
    expect(input.value).toBe('');
  });

  it('button_click_opensThePicker', async () => {
    TestBed.configureTestingModule({
      providers: [{ provide: UploadQueue, useValue: { add: vi.fn() } }],
    });
    const fixture = TestBed.createComponent(UploadButtonComponent);
    await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    const clicked = vi.spyOn(root.querySelector('input') as HTMLInputElement, 'click');
    (root.querySelector('button') as HTMLButtonElement).click();
    expect(clicked).toHaveBeenCalled();
  });
});

@Component({
  imports: [DropZoneDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div cdDropZone (filesDropped)="dropped = $event">zone</div>`,
})
class DropHost {
  dropped: File[] = [];
}

describe('DropZoneDirective', () => {
  const drag = (type: string, types: string[], files: File[] = []): DragEvent => {
    const event = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
    Object.defineProperty(event, 'dataTransfer', { value: { types, files } });
    return event;
  };
  const setup = async () => {
    const fixture = TestBed.createComponent(DropHost);
    await fixture.whenStable();
    return {
      fixture,
      zone: (fixture.nativeElement as HTMLElement).querySelector('div') as HTMLElement,
    };
  };

  it('dragOverFiles_allowsTheDropAndHighlightsTheZone', async () => {
    const { fixture, zone } = await setup();
    const over = drag('dragover', ['Files']);
    zone.dispatchEvent(over);
    await fixture.whenStable();
    expect(over.defaultPrevented).toBe(true);
    expect(zone.classList.contains('cd-dropzone--active')).toBe(true);
    zone.dispatchEvent(drag('dragleave', ['Files']));
    await fixture.whenStable();
    expect(zone.classList.contains('cd-dropzone--active')).toBe(false);
  });

  it('dropFiles_emitsThemAndPreventsTheBrowserFromOpeningThem', async () => {
    const { fixture, zone } = await setup();
    const files = [new File(['a'], 'a.pdf')];
    const drop = drag('drop', ['Files'], files);
    zone.dispatchEvent(drop);
    expect(drop.defaultPrevented).toBe(true);
    expect(fixture.componentInstance.dropped).toEqual(files);
  });

  it('dragOfTextOrLinks_isIgnored', async () => {
    const { fixture, zone } = await setup();
    const over = drag('dragover', ['text/plain']);
    zone.dispatchEvent(over);
    const drop = drag('drop', ['text/plain']);
    zone.dispatchEvent(drop);
    expect(over.defaultPrevented).toBe(false);
    expect(drop.defaultPrevented).toBe(false);
    expect(fixture.componentInstance.dropped).toEqual([]);
  });
});
