import { Directive, output, signal } from '@angular/core';

/** Turns an element into a target for files dragged in from the desktop. */
@Directive({
  selector: '[cdDropZone]',
  host: {
    '[class.cd-dropzone--active]': 'active()',
    '(dragenter)': 'enter($event)',
    '(dragover)': 'over($event)',
    '(dragleave)': 'leave($event)',
    '(drop)': 'drop($event)',
  },
})
export class DropZoneDirective {
  readonly filesDropped = output<File[]>();
  protected readonly active = signal(false);
  // dragenter/dragleave also fire for child elements, so count them to avoid a flickering highlight.
  private depth = 0;

  protected enter(event: DragEvent): void {
    if (this.hasFiles(event)) {
      event.preventDefault();
      this.depth += 1;
      this.active.set(true);
    }
  }

  protected over(event: DragEvent): void {
    if (this.hasFiles(event)) {
      event.preventDefault();
    }
  }

  protected leave(event: DragEvent): void {
    if (this.hasFiles(event) && this.depth > 0) {
      this.depth -= 1;
      this.active.set(this.depth > 0);
    }
  }

  protected drop(event: DragEvent): void {
    if (!this.hasFiles(event)) {
      return;
    }
    event.preventDefault();
    this.depth = 0;
    this.active.set(false);
    this.filesDropped.emit(Array.from(event.dataTransfer?.files ?? []));
  }

  private hasFiles(event: DragEvent): boolean {
    return event.dataTransfer?.types.includes('Files') ?? false;
  }
}
