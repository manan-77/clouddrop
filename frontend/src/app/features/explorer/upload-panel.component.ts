import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { type UploadItem, type UploadStatus } from '@core/uploads/upload-queue.service';
import { FileSizePipe } from '@shared/pipes/file-size.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';

const LABELS: Readonly<Record<UploadStatus, string>> = {
  queued: 'Waiting',
  requesting: 'Starting',
  uploading: 'Uploading',
  completing: 'Finishing',
  done: 'Uploaded',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

@Component({
  selector: 'cd-upload-panel',
  imports: [FileSizePipe, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <p class="cd-visually-hidden" aria-live="polite">{{ summary() }}</p>
    @if (items().length > 0) {
      <section class="panel" aria-labelledby="uploads-heading">
        <h2 id="uploads-heading">Uploads</h2>
        <ul class="list">
          @for (item of items(); track item.id) {
            <li class="row">
              <span class="name">{{ item.name }}</span>
              <span class="size">{{ item.size | fileSize }}</span>
              @if (item.status === 'uploading' || item.status === 'completing') {
                <progress
                  class="bar"
                  max="100"
                  [value]="item.progress"
                  [attr.aria-label]="'Upload progress for ' + item.name"
                ></progress>
              }
              <span class="state">{{ labels[item.status] }}</span>
              <span class="actions">
                @if (item.status === 'failed') {
                  <button
                    cd-button
                    variant="secondary"
                    type="button"
                    [attr.aria-label]="'Retry ' + item.name"
                    (click)="retryUpload.emit(item.id)"
                  >
                    Retry
                  </button>
                }
                @if (
                  item.status === 'done' || item.status === 'failed' || item.status === 'cancelled'
                ) {
                  <button
                    cd-button
                    variant="secondary"
                    type="button"
                    [attr.aria-label]="'Remove ' + item.name"
                    (click)="removeUpload.emit(item.id)"
                  >
                    Remove
                  </button>
                } @else {
                  <button
                    cd-button
                    variant="secondary"
                    type="button"
                    [attr.aria-label]="'Cancel upload of ' + item.name"
                    (click)="cancelUpload.emit(item.id)"
                  >
                    Cancel
                  </button>
                }
              </span>
              @if (item.error) {
                <p class="cd-form-error row-error" role="alert">{{ item.error }}</p>
              }
            </li>
          }
        </ul>
      </section>
    }
  `,
  styleUrl: './upload-panel.component.scss',
})
export class UploadPanelComponent {
  readonly items = input.required<readonly UploadItem[]>();
  readonly cancelUpload = output<string>();
  readonly retryUpload = output<string>();
  readonly removeUpload = output<string>();

  protected readonly labels = LABELS;
  /** One persistent live region instead of one per row. */
  protected readonly summary = computed(() => {
    const items = this.items();
    if (items.length === 0) {
      return '';
    }
    const done = items.filter((item) => item.status === 'done').length;
    const failed = items.filter((item) => item.status === 'failed').length;
    return `${done} of ${items.length} uploads finished` + (failed ? `, ${failed} failed` : '');
  });
}
