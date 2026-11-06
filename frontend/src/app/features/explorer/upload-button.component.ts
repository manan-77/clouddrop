import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';

import { UploadQueue } from '@core/uploads/upload-queue.service';
import { ButtonComponent } from '@shared/ui/button/button.component';

/** Opens the system file picker and queues what was chosen into the folder being viewed. */
@Component({
  selector: 'cd-upload-button',
  imports: [ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <input
      #picker
      class="cd-visually-hidden"
      type="file"
      multiple
      tabindex="-1"
      aria-hidden="true"
      (change)="choose(picker)"
    />
    <button cd-button variant="secondary" type="button" (click)="picker.click()">
      Upload files
    </button>
  `,
})
export class UploadButtonComponent {
  readonly folderId = input<string | null>(null);
  private readonly queue = inject(UploadQueue);

  protected choose(picker: HTMLInputElement): void {
    this.queue.add(Array.from(picker.files ?? []), this.folderId());
    // Allows choosing the same file again later.
    picker.value = '';
  }
}
