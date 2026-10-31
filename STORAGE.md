# Blob storage (S3 protocol)

Audio and other blobs go through `backend/app/storage.py` (boto3). The app code never cares which S3 server is behind it; only env vars change (see `.env.example`).

## Local: MinIO on a local folder
    docker compose up -d minio     # API :9000, console :9001 (sloka / sloka-secret-1)
The compose file bind-mounts `./blobdata` to `/data`, so the data lives in a local folder, but in MinIO's own on-disk layout, not as readable `.mp3`/`.json` files: e.g. `blobdata/sloka/<key>/xl.meta` (newer MinIO stores objects as a directory per key containing `xl.meta`, plus a part file for larger objects). `blobdata/` should be gitignored. The bucket is created on demand by `storage.get().ensure_bucket()`.

Image: compose defaults to `cgr.dev/chainguard/minio` (Docker Hub `minio/minio` and Quay were not pullable when this was set up). Override with `MINIO_IMAGE`. The image has no shell, so there is no container healthcheck; check `curl http://localhost:9000/minio/health/live`. Compose runs it as `LOCAL_UID:LOCAL_GID` (default 1000:1000) so `./blobdata` is owned by you; run `export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)` first if your ids differ.

## Switching to AWS S3 or Dokploy MinIO
Set in `.env` (examples in `.env.example`):
- AWS: `S3_ENDPOINT=` (empty), real `S3_BUCKET`, keys, `S3_REGION`, `S3_PATH_STYLE=false`.
- Dokploy MinIO: `S3_ENDPOINT=https://<host>`, keys, `S3_PATH_STYLE=true`.

## Backup
Stop writes (or accept a fuzzy copy) and copy the `blobdata/` folder (`rsync -a blobdata/ backup/`). Restore by copying back while MinIO is stopped. Postgres is separate (`pg_dump`).

## Bucket policy
Keep the bucket private. The app proxies audio via `get_stream` (with Range support), so browsers never need direct bucket access or presigned URLs.

## Errors
`storage.NotFound` (a `KeyError`), `storage.Unavailable` (connection/timeout; connect 3s, read 30s, 2 retries), `storage.BadRange` (caller returns 416).
