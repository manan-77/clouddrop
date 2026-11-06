import { Directive, output, signal } from '@angular/core';

/** Turns an element into a target for files dragged in from the desktop. */
@Directive({
  selector: '[cdDropZone]',
  host: {
    '[class.cd-dropzone--active]': 'active()',
    '(dragenter)': 'over($event)',
    '(dragover)': 'over($event)',
    '(dragleave)': 'active.set(false)',
    '(drop)': 'drop($event)',
  },
})
export class DropZoneDirective {
  readonly filesDropped = output<File[]>();
  protected readonly active = signal(false);

  protected over(event: DragEvent): void {
    if (this.hasFiles(event)) {
      event.preventDefault();
      this.active.set(true);
    }
  }

  protected drop(event: DragEvent): void {
    if (!this.hasFiles(event)) {
      return;
    }
    event.preventDefault();
    this.active.set(false);
    this.filesDropped.emit(Array.from(event.dataTransfer?.files ?? []));
  }

  private hasFiles(event: DragEvent): boolean {
    return event.dataTransfer?.types.includes('Files') ?? false;
  }
}
