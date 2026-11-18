import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type ElementRef,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { defer, from } from 'rxjs';

import { ButtonComponent } from '@shared/ui/button/button.component';

/** Shows a freshly made link once, selected and ready to copy. The address is never kept elsewhere. */
@Component({
  selector: 'cd-link-address',
  imports: [ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <p>Copy this link now. It is not shown again.</p>
    <div class="row">
      <input
        #field
        class="cd-input"
        type="text"
        readonly
        aria-label="Link address"
        [value]="address()"
      />
      <button cd-button variant="secondary" type="button" (click)="copy()">Copy</button>
    </div>
    <p class="copied" role="status">{{ copied() }}</p>
  `,
  styles: `
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--cd-space-2);
    }
    .row input {
      flex: 1 1 14rem;
    }
    .copied {
      color: var(--cd-text-muted);
      min-height: 1.5em;
    }
  `,
})
export class LinkAddressComponent {
  readonly address = input.required<string>();

  protected readonly copied = signal('');
  private readonly field = viewChild.required<ElementRef<HTMLInputElement>>('field');
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);

  constructor() {
    // A keyboard user lands on the address, already selected.
    afterNextRender(() => {
      this.field().nativeElement.focus();
      this.field().nativeElement.select();
    });
  }

  protected copy(): void {
    const clipboard = this.document.defaultView?.navigator.clipboard;
    if (!clipboard) {
      this.copied.set('Select the address and copy it.');
      return;
    }
    // The clipboard API is promise-only, so it is wrapped at the boundary.
    defer(() => from(clipboard.writeText(this.address())))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.copied.set('Copied.'),
        error: () => this.copied.set('Could not copy. Select the address and copy it.'),
      });
  }
}
