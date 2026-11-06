/** User-safe text for every API error code. Server wording is never shown directly. */
export const ERROR_MESSAGES: Readonly<Record<string, string>> = {
  invalid_credentials: 'Incorrect email or password.',
  invalid_session: 'Your session has expired. Please sign in again.',
  invalid_token: 'Your session has expired. Please sign in again.',
  unauthorized: 'Please sign in to continue.',
  forbidden: 'You do not have permission to do that.',
  rate_limited: 'Too many attempts. Please wait a moment and try again.',
  csrf_check_failed: 'Your session could not be verified. Please reload the page.',
  not_found: 'We could not find that.',
  workspace_not_found: 'We could not find your workspace.',
  folder_not_found: 'That folder no longer exists.',
  file_not_found: 'That file no longer exists.',
  conflict: 'That already exists.',
  folder_name_taken: 'A folder with this name already exists here.',
  folder_too_deep: 'Folders cannot be nested that deeply.',
  folder_not_empty: 'This folder is not empty. Move or delete its contents first.',
  invalid_name: 'That name is not allowed.',
  empty_update: 'There is nothing to change.',
  file_too_large: 'That file is too large to upload.',
  unsupported_file_type: 'This type of file is not supported.',
  quota_exceeded: 'You have run out of storage space.',
  upload_incomplete: 'The file has not finished uploading.',
  upload_size_mismatch: 'The uploaded file did not match the expected size. Please try again.',
  file_not_ready: 'This file is not available yet.',
  file_infected: 'This file was blocked because it may be unsafe.',
  validation_error: 'Please check the highlighted fields.',
  storage_not_configured: 'File storage is not set up yet.',
  storage_unavailable: 'File storage is temporarily unavailable. Please try again.',
  db_unavailable: 'The service is temporarily unavailable. Please try again.',
  service_unavailable: 'The service is temporarily unavailable. Please try again.',
  internal_error: 'Something went wrong on our side. Please try again.',
};

export const NETWORK_MESSAGE = 'Could not reach the server. Check your connection and try again.';
export const GENERIC_MESSAGE = 'Something went wrong. Please try again.';

export const STATUS_MESSAGES: Readonly<Record<number, string>> = {
  401: 'Please sign in to continue.',
  403: 'You do not have permission to do that.',
  404: 'We could not find that.',
  409: 'That already exists.',
  429: 'Too many requests. Please wait a moment and try again.',
};
