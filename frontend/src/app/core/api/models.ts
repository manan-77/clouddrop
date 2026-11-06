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

export interface FolderRead {
  id: string;
  parent_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
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
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface DownloadResponse {
  url: string;
  expires_in: number;
}
