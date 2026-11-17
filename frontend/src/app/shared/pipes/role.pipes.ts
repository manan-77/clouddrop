import { Pipe, type PipeTransform } from '@angular/core';

import { type CallerRole } from '@core/api/models';
import { canManage, canWrite } from '@core/api/permissions';

@Pipe({ name: 'canWrite' })
export class CanWritePipe implements PipeTransform {
  transform(role: CallerRole): boolean {
    return canWrite(role);
  }
}

@Pipe({ name: 'canManage' })
export class CanManagePipe implements PipeTransform {
  transform(role: CallerRole): boolean {
    return canManage(role);
  }
}
