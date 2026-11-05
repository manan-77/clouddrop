import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ButtonComponent } from './button.component';

@Component({
  imports: [ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<button cd-button [busy]="busy" [disabled]="disabled" (click)="clicks = clicks + 1">
    Save
  </button>`,
})
class HostComponent {
  busy = false;
  disabled = false;
  clicks = 0;
}

describe('ButtonComponent', () => {
  const setup = async (patch: Partial<HostComponent>) => {
    const fixture = TestBed.createComponent(HostComponent);
    Object.assign(fixture.componentInstance, patch);
    fixture.changeDetectorRef.markForCheck();
    await fixture.whenStable();
    return fixture.nativeElement.querySelector('button') as HTMLButtonElement;
  };

  it('idle_isEnabledWithoutSpinner', async () => {
    const button = await setup({});
    expect(button.disabled).toBe(false);
    expect(button.getAttribute('aria-busy')).toBeNull();
    expect(button.querySelector('.spinner')).toBeNull();
  });

  it('busy_isDisabledShowsSpinnerAndAnnouncesBusy', async () => {
    const button = await setup({ busy: true });
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.querySelector('.spinner')).not.toBeNull();
  });

  it('disabled_isDisabledWithoutSpinner', async () => {
    const button = await setup({ disabled: true });
    expect(button.disabled).toBe(true);
    expect(button.querySelector('.spinner')).toBeNull();
  });
});
