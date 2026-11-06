import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { type FileRead } from '@core/api/models';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { DownloadablePipe } from '@shared/pipes/downloadable.pipe';
import { FileSizePipe } from '@shared/pipes/file-size.pipe';
import { IsInPipe } from '@shared/pipes/is-in.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { StatusBadgeComponent } from '@shared/ui/status-badge/status-badge.component';

@Component({
  selector: 'cd-file-table',
  imports: [
    DateTimePipe,
    DownloadablePipe,
    FileSizePipe,
    IsInPipe,
    ButtonComponent,
    StatusBadgeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="cd-table-wrap">
      <table class="cd-table">
        <caption class="cd-visually-hidden">
          Files
        </caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Size</th>
            <th scope="col">Status</th>
            <th scope="col">Modified</th>
            <th scope="col"><span class="cd-visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          @for (file of files(); track file.id) {
            <tr>
              <td>{{ file.name }}</td>
              <td>{{ file.size_bytes | fileSize }}</td>
              <td><cd-status-badge [status]="file.status" /></td>
              <td>{{ file.updated_at | cdDateTime }}</td>
              <td class="cd-actions">
                <button
                  cd-button
                  variant="secondary"
                  type="button"
                  [busy]="file.id | isIn: downloading()"
                  [disabled]="!(file.status | downloadable)"
                  [attr.aria-label]="'Download ' + file.name"
                  (click)="download.emit(file)"
                >
                  Download
                </button>
                <button
                  cd-button
                  variant="secondary"
                  type="button"
                  [attr.aria-label]="'Rename ' + file.name"
                  (click)="rename.emit(file)"
                >
                  Rename
                </button>
                <button
                  cd-button
                  variant="danger"
                  type="button"
                  [attr.aria-label]="'Delete ' + file.name"
                  (click)="remove.emit(file)"
                >
                  Delete
                </button>
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
})
export class FileTableComponent {
  readonly files = input.required<readonly FileRead[]>();
  readonly downloading = input<readonly string[]>([]);
  readonly download = output<FileRead>();
  readonly rename = output<FileRead>();
  readonly remove = output<FileRead>();
}
