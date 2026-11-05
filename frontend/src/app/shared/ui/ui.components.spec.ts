import { TestBed } from '@angular/core/testing';

import { EmptyStateComponent } from './empty-state/empty-state.component';
import { ErrorStateComponent } from './error-state/error-state.component';
import { FieldErrorComponent } from './field-error/field-error.component';
import { SkeletonComponent } from './skeleton/skeleton.component';

const html = (fixture: { nativeElement: unknown }): HTMLElement =>
  fixture.nativeElement as HTMLElement;

describe('SkeletonComponent', () => {
  it.each([
    [4, 4],
    [0, 1],
    [999, 20],
    [Number.NaN, 3],
  ])('lines_%s_rendersClampedRows', async (lines, expected) => {
    const fixture = TestBed.createComponent(SkeletonComponent);
    fixture.componentRef.setInput('lines', lines);
    await fixture.whenStable();
    expect(html(fixture).querySelectorAll('.line').length).toBe(expected);
    expect(html(fixture).querySelector('[role="status"]')).not.toBeNull();
  });
});

describe('EmptyStateComponent', () => {
  it('render_titleAndOptionalDescription', async () => {
    const fixture = TestBed.createComponent(EmptyStateComponent);
    fixture.componentRef.setInput('title', 'Nothing here');
    await fixture.whenStable();
    expect(html(fixture).querySelector('h2')?.textContent).toBe('Nothing here');
    expect(html(fixture).querySelector('p')).toBeNull();
    fixture.componentRef.setInput('description', 'Add a file');
    await fixture.whenStable();
    expect(html(fixture).querySelector('p')?.textContent).toBe('Add a file');
  });
});

describe('ErrorStateComponent', () => {
  it('retryButton_click_emitsRetryAndAnnouncesAlert', async () => {
    const fixture = TestBed.createComponent(ErrorStateComponent);
    fixture.componentRef.setInput('message', 'Could not load');
    const retried = vi.fn();
    fixture.componentInstance.retry.subscribe(retried);
    await fixture.whenStable();
    expect(html(fixture).querySelector('[role="alert"]')?.textContent).toContain('Could not load');
    (html(fixture).querySelector('button') as HTMLButtonElement).click();
    expect(retried).toHaveBeenCalledTimes(1);
  });
});

describe('FieldErrorComponent', () => {
  it('message_changes_updatesTextInPersistentLiveRegionWithSingleId', async () => {
    const fixture = TestBed.createComponent(FieldErrorComponent);
    fixture.componentRef.setInput('fieldId', 'email-error');
    await fixture.whenStable();
    const region = html(fixture).querySelector('p') as HTMLElement;
    expect(region.getAttribute('aria-live')).toBe('polite');
    expect(region.id).toBe('email-error');
    expect(region.textContent?.trim()).toBe('');
    fixture.componentRef.setInput('message', 'Enter a valid email');
    await fixture.whenStable();
    expect(html(fixture).querySelector('p')).toBe(region);
    expect(region.textContent?.trim()).toBe('Enter a valid email');
    expect(html(fixture).querySelectorAll('#email-error').length).toBe(1);
  });
});
