import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';

import { STATUS_LABELS } from '@core/api/file-status';
import { type FileStatus } from '@core/api/models';
import { DownloadService } from '@core/download/download.service';
import { DialogComponent } from './dialog/dialog.component';
import { PagerComponent } from './pager/pager.component';
import { StatusBadgeComponent } from './status-badge/status-badge.component';

describe('PagerComponent', () => {
  const setup = async (page: number, total: number) => {
    const fixture = TestBed.createComponent(PagerComponent);
    fixture.componentRef.setInput('page', page);
    fixture.componentRef.setInput('pageSize', 20);
    fixture.componentRef.setInput('total', total);
    const changes: number[] = [];
    fixture.componentInstance.pageChange.subscribe((value) => changes.push(value));
    await fixture.whenStable();
    return { root: fixture.nativeElement as HTMLElement, changes };
  };

  it('singlePage_rendersNothing', async () => {
    const { root } = await setup(1, 20);
    expect(root.querySelector('nav')).toBeNull();
  });

  it('firstPage_disablesPreviousAndEmitsNext', async () => {
    const { root, changes } = await setup(1, 45);
    const [previous, next] = [...root.querySelectorAll('button')] as HTMLButtonElement[];
    expect(previous.disabled).toBe(true);
    next.click();
    expect(changes).toEqual([2]);
    expect(root.querySelector('span')?.textContent).toBe('Page 1 of 3');
  });

  it('lastPage_disablesNextAndEmitsPrevious', async () => {
    const { root, changes } = await setup(3, 45);
    const [previous, next] = [...root.querySelectorAll('button')] as HTMLButtonElement[];
    expect(next.disabled).toBe(true);
    previous.click();
    expect(changes).toEqual([2]);
  });
});

describe('StatusBadgeComponent', () => {
  it.each(Object.entries(STATUS_LABELS))('status_%s_showsReadableLabel', async (status, label) => {
    const fixture = TestBed.createComponent(StatusBadgeComponent);
    fixture.componentRef.setInput('status', status as FileStatus);
    await fixture.whenStable();
    expect((fixture.nativeElement as HTMLElement).textContent?.trim()).toBe(label);
  });
});

describe('DialogComponent', () => {
  it('open_marksTheDialogOpenAndLabelsItWithTheTitle', async () => {
    const fixture = TestBed.createComponent(DialogComponent);
    fixture.componentRef.setInput('heading', 'Delete file');
    await fixture.whenStable();
    const dialog = (fixture.nativeElement as HTMLElement).querySelector(
      'dialog',
    ) as HTMLDialogElement;
    expect(dialog.hasAttribute('open')).toBe(true);
    const labelId = dialog.getAttribute('aria-labelledby') ?? '';
    expect((fixture.nativeElement as HTMLElement).querySelector(`#${labelId}`)?.textContent).toBe(
      'Delete file',
    );
  });

  it('closeEvent_emitsDismissedButDestroyingDoesNot', async () => {
    const fixture = TestBed.createComponent(DialogComponent);
    fixture.componentRef.setInput('heading', 'Title');
    const dismissed = vi.fn();
    fixture.componentInstance.dismissed.subscribe(dismissed);
    await fixture.whenStable();
    (fixture.nativeElement as HTMLElement)
      .querySelector('dialog')
      ?.dispatchEvent(new Event('close'));
    expect(dismissed).toHaveBeenCalledTimes(1);
    fixture.destroy();
    expect(dismissed).toHaveBeenCalledTimes(1);
  });
});

describe('DownloadService', () => {
  it('start_createsAnAnchorClicksItAndRemovesIt', () => {
    const document = TestBed.inject(DOCUMENT);
    const clicked: string[] = [];
    const original = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      clicked.push(this.href + '|' + this.rel);
    };
    try {
      TestBed.inject(DownloadService).start('https://files.example/a?sig=1');
    } finally {
      HTMLAnchorElement.prototype.click = original;
    }
    expect(clicked).toEqual(['https://files.example/a?sig=1|noopener noreferrer']);
    expect(document.body.querySelector('a[href^="https://files.example"]')).toBeNull();
  });
});

describe('DialogComponent dismissal', () => {
  it.each([
    [true, false],
    [false, true],
  ])('dismissible_%s_cancelEventPrevented_%s', async (dismissible, prevented) => {
    const fixture = TestBed.createComponent(DialogComponent);
    fixture.componentRef.setInput('heading', 'Busy');
    fixture.componentRef.setInput('dismissible', dismissible);
    await fixture.whenStable();
    const cancel = new Event('cancel', { cancelable: true });
    (fixture.nativeElement as HTMLElement).querySelector('dialog')?.dispatchEvent(cancel);
    expect(cancel.defaultPrevented).toBe(prevented);
  });
});

describe('DownloadService safety', () => {
  it.each(['javascript:alert(1)', 'data:text/html,<b>x</b>', 'file:///etc/passwd'])(
    'start_%s_isRefused',
    (url) => {
      expect(() => TestBed.inject(DownloadService).start(url)).toThrow();
    },
  );
});
