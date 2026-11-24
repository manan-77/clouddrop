import { type FileRead, type FolderRead } from '@core/api/models';

/** The dialog open on the explorer page, if any. */
export type Dialog =
  | { kind: 'create-folder' }
  | { kind: 'rename-folder'; folder: FolderRead }
  | { kind: 'rename-file'; file: FileRead }
  | { kind: 'move-file'; file: FileRead }
  | { kind: 'delete-folder'; folder: FolderRead }
  | { kind: 'delete-file'; file: FileRead }
  | { kind: 'share-folder'; folder: FolderRead }
  | { kind: 'share-file'; file: FileRead }
  | { kind: 'activity-folder'; folder: FolderRead }
  | { kind: 'activity-file'; file: FileRead }
  | { kind: 'summary-file'; file: FileRead };
