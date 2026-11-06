import { type FileStatus } from './models';

const DOWNLOADABLE: ReadonlySet<FileStatus> = new Set([
  'uploaded',
  'scanning',
  'processing',
  'ready',
  'needs_ocr',
]);

/** Mirrors the server rule only to decide whether to offer the button; the server still decides. */
export const isDownloadable = (status: FileStatus): boolean => DOWNLOADABLE.has(status);

export const STATUS_LABELS: Readonly<Record<FileStatus, string>> = {
  pending_upload: 'Waiting for upload',
  uploaded: 'Uploaded',
  scanning: 'Scanning',
  processing: 'Processing',
  ready: 'Ready',
  failed: 'Failed',
  infected: 'Blocked as unsafe',
  needs_ocr: 'Needs text recognition',
};
