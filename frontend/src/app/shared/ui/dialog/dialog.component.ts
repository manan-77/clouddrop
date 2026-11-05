import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type ElementRef,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';

let nextId = 0;

/**
 * Modal built on the native dialog element, which traps focus, closes on Escape and restores focus
 * to the opener. Create it when needed (inside an @if) and listen for `dismissed`.
 */
@Component({
  selector: 'cd-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <dialog #dialog class="dialog" [attr.aria-labelledby]="titleId" (close)="onClosed()">
      <h2 [id]="titleId">{{ title() }}</h2>
      <ng-content />
    </dialog>
  `,
  styleUrl: './dialog.component.scss',
})
export class DialogComponent {
  readonly title = input.required<string>();
  readonly dismissed = output<void>();

  protected readonly titleId = `cd-dialog-title-${nextId++}`;
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');
  private destroying = false;

  constructor() {
    afterNextRender(() => {
      const element = this.dialog().nativeElement;
      if (typeof element.showModal === 'function') {
        element.showModal();
      } else {
        element.setAttribute('open', '');
      }
    });
    inject(DestroyRef).onDestroy(() => {
      this.destroying = true;
      const element = this.dialog().nativeElement;
      if (typeof element.close === 'function' && element.open) {
        element.close();
      }
    });
  }

  protected onClosed(): void {
    if (!this.destroying) {
      this.dismissed.emit();
    }
  }
}
