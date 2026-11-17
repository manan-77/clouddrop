import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { ActivityDialogComponent } from './activity-dialog.component';
import { type Dialog } from './explorer-dialog';
import { ShareDialogComponent } from './share-dialog.component';

/** The share and activity dialogs of the explorer, kept out of the page to keep it small. */
@Component({
  selector: 'cd-sharing-dialogs',
  imports: [ActivityDialogComponent, ShareDialogComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let open = dialog();
    @if (open && open.kind === 'share-folder') {
      <cd-share-dialog
        kind="folders"
        [resourceId]="open.folder.id"
        [resourceName]="open.folder.name"
        (dismissed)="dismissed.emit()"
      />
    } @else if (open && open.kind === 'share-file') {
      <cd-share-dialog
        kind="files"
        [resourceId]="open.file.id"
        [resourceName]="open.file.name"
        (dismissed)="dismissed.emit()"
      />
    } @else if (open && open.kind === 'activity-folder') {
      <cd-activity-dialog
        [resourceId]="open.folder.id"
        [resourceName]="open.folder.name"
        (dismissed)="dismissed.emit()"
      />
    } @else if (open && open.kind === 'activity-file') {
      <cd-activity-dialog
        [resourceId]="open.file.id"
        [resourceName]="open.file.name"
        (dismissed)="dismissed.emit()"
      />
    }
  `,
})
export class SharingDialogsComponent {
  readonly dialog = input<Dialog | null>(null);
  readonly dismissed = output<void>();
}
