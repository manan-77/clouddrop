import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';

import { type FolderRead } from '@core/api/models';
import { DateTimePipe } from '@shared/pipes/date-time.pipe';
import { ButtonComponent } from '@shared/ui/button/button.component';

@Component({
  selector: 'cd-folder-table',
  imports: [RouterLink, DateTimePipe, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="cd-table-wrap">
      <table class="cd-table">
        <caption class="cd-visually-hidden">
          Folders
        </caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Modified</th>
            <th scope="col"><span class="cd-visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          @for (folder of folders(); track folder.id) {
            <tr>
              <td>
                <a [routerLink]="['/folders', folder.id]">{{ folder.name }}</a>
              </td>
              <td>{{ folder.updated_at | cdDateTime }}</td>
              <td class="cd-actions">
                <button
                  cd-button
                  variant="secondary"
                  type="button"
                  [attr.aria-label]="'Rename folder ' + folder.name"
                  (click)="rename.emit(folder)"
                >
                  Rename
                </button>
                <button
                  cd-button
                  variant="danger"
                  type="button"
                  [attr.aria-label]="'Delete folder ' + folder.name"
                  (click)="remove.emit(folder)"
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
export class FolderTableComponent {
  readonly folders = input.required<readonly FolderRead[]>();
  readonly rename = output<FolderRead>();
  readonly remove = output<FolderRead>();
}
