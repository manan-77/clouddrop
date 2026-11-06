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
 * to the opener. Create it when needed (inside an @if) and listen for `dismissed`. While
 * `dismissible` is false (a request is running) Escape is ignored.
 */
@Component({
  selector: 'cd-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <dialog
      #dialog
      class="dialog"
      [attr.aria-labelledby]="titleId"
      (cancel)="onCancel($event)"
      (close)="onClosed()"
    >
      <h2 [id]="titleId">{{ heading() }}</h2>
      <ng-content />
    </dialog>
  `,
  styleUrl: './dialog.component.scss',
})
export class DialogComponent {
  readonly heading = input.required<string>();
  readonly dismissible = input(true);
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

  protected onCancel(event: Event): void {
    if (!this.dismissible()) {
      event.preventDefault();
    }
  }

  protected onClosed(): void {
    if (!this.destroying) {
      this.dismissed.emit();
    }
  }
}
