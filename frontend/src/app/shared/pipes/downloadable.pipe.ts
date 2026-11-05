import { Pipe, type PipeTransform } from '@angular/core';

import { isDownloadable } from '@core/api/file-status';
import { type FileStatus } from '@core/api/models';

@Pipe({ name: 'downloadable' })
export class DownloadablePipe implements PipeTransform {
  transform(status: FileStatus): boolean {
    return isDownloadable(status);
  }
}
