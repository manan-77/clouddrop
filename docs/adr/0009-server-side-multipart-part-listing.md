# 0009 - The server lists multipart parts instead of the browser sending ETags

## Context

A multipart upload normally has the browser read each part's `ETag` response header and send the list back to complete the upload. That needs the bucket's CORS rule to expose `ETag` (the root CLAUDE.md lists this as a baseline), and it makes the server trust a client-supplied part list.

## Decision

The server chooses the part layout (part size and count), keeps the S3 upload id in the database, and on `complete` calls `ListParts` itself, checks every part's number and size against the layout it chose, and assembles the object from what S3 reports. The browser only slices the file and PUTs each part to a presigned address.

## Consequences

- The browser never reads `ETag`, so `ExposeHeaders: ETag` is not required for multipart uploads (it remains harmless and may stay in the CORS rule). This is a deliberate deviation from the baseline line; the owner may restore the requirement if other features need it.
- The server never trusts a client part list; a missing part is `409 upload_incomplete` and wrong sizes fail the file.
- The IAM identity needs `s3:ListMultipartUploadParts` and `s3:AbortMultipartUpload`.
- `complete` holds the file row lock while S3 assembles the object, which can take a while for large files.
