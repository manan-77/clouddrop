import { Pipe, type PipeTransform } from '@angular/core';

import { type AuditAction, type AuditEvent } from '@core/api/models';

const LABELS: Readonly<Record<AuditAction, string>> = {
  'file.uploaded': 'Uploaded',
  'file.downloaded': 'Downloaded',
  'file.deleted': 'Deleted',
  'folder.deleted': 'Deleted',
  'permission.granted': 'Shared',
  'permission.changed': 'Changed access',
  'permission.revoked': 'Removed access',
  'auth.login': 'Signed in',
};

/** Plain-language text for an audit event (the role, when there is one, in brackets). */
@Pipe({ name: 'auditLabel' })
export class AuditLabelPipe implements PipeTransform {
  transform(event: AuditEvent): string {
    const base = LABELS[event.action];
    return event.detail ? `${base} (${event.detail})` : base;
  }
}
