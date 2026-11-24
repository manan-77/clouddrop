// Wire types mirror the backend schemas exactly (snake_case included).

export interface UserRead {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export type FileStatus =
  | 'pending_upload'
  | 'uploaded'
  | 'scanning'
  | 'processing'
  | 'ready'
  | 'failed'
  | 'infected'
  | 'needs_ocr';

/** What the caller may do with an item. The server decides; the UI only reflects it. */
export type CallerRole = 'owner' | 'editor' | 'viewer';

export interface FolderRead {
  id: string;
  parent_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
  role: CallerRole;
}

export interface FileRead {
  id: string;
  folder_id: string | null;
  name: string;
  content_type: string;
  size_bytes: number;
  status: FileStatus;
  created_at: string;
  updated_at: string;
  role: CallerRole;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

/** One file that matched a search: its best passage, never the whole text. */
export interface SearchHit {
  file_id: string;
  file_name: string;
  chunk_id: string;
  page: number | null;
  snippet: string;
  score: number;
}

/** A source the server verified was really offered to the model for this answer. */
export interface Citation {
  label: string;
  file_id: string;
  file_name: string;
  chunk_id: string;
  page: number | null;
}

/** One event of an answer stream (docs/api.md, Answers). */
export type AnswerEvent =
  | { type: 'token'; text: string }
  | { type: 'done'; citations: Citation[]; cut_off: boolean }
  | { type: 'error'; code: string };

export interface DownloadResponse {
  url: string;
  expires_in: number;
}

export interface UploadInitRequest {
  name: string;
  content_type: string;
  size_bytes: number;
  folder_id: string | null;
}

export interface UploadInstructions {
  url: string;
  fields: Record<string, string>;
  expires_in: number;
}

export interface UploadInitResponse {
  file: FileRead;
  upload: UploadInstructions;
}

export interface MultipartInstructions {
  part_size_bytes: number;
  part_count: number;
  expires_in: number;
}

export interface MultipartInitResponse {
  file: FileRead;
  multipart: MultipartInstructions;
}

export interface PartUrlsResponse {
  parts: { part_number: number; url: string }[];
  expires_in: number;
}

export type GrantRole = 'viewer' | 'editor';
export type ShareKind = 'files' | 'folders';

export interface GrantRead {
  id: string;
  email: string;
  display_name: string;
  role: GrantRole;
  created_at: string;
}

export interface SharedItem {
  resource_type: 'file' | 'folder';
  id: string;
  name: string;
  role: GrantRole;
  owner_name: string;
  updated_at: string;
  size_bytes: number | null;
  content_type: string | null;
  status: FileStatus | null;
}

export type AuditAction =
  | 'file.uploaded'
  | 'file.downloaded'
  | 'file.deleted'
  | 'folder.deleted'
  | 'permission.granted'
  | 'permission.changed'
  | 'permission.revoked'
  | 'auth.login';

export interface AuditEvent {
  id: string;
  created_at: string;
  action: AuditAction;
  resource_type: 'file' | 'folder' | 'user';
  resource_id: string | null;
  actor_id: string | null;
  actor_name: string | null;
  target_user_id: string | null;
  detail: string | null;
  request_id: string | null;
}

export interface ShareLink {
  id: string;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
}

/** Only the response to creating a link carries the token, and only once. */
export interface ShareLinkCreated extends ShareLink {
  token: string;
}

export interface PublicLink {
  file_name: string;
  size_bytes: number;
  content_type: string;
  expires_at: string;
}
