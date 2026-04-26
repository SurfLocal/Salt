import * as Minio from 'minio';
import { URL } from 'url';

/**
 * S3-compatible storage client. Tier A points this at Cloudflare R2; the
 * `minio` SDK speaks S3 well enough for putObject/getObject/removeObject/
 * bucketExists, which is everything the API uses.
 *
 * Two ways to configure:
 *   - STORAGE_ENDPOINT (R2 / GCS / etc.) — full URL like https://xxx.r2.cloudflarestorage.com
 *   - Legacy MINIO_ENDPOINT + MINIO_PORT for local docker-compose dev
 *
 * Logical buckets (BUCKETS.SESSION_MEDIA etc.) are object-key prefixes inside
 * a single physical bucket (STORAGE_BUCKET). This keeps a single public URL
 * surface and lets us swap from r2.dev → media.surflocal.app by changing one
 * env var.
 */

interface ParsedEndpoint {
  endPoint: string;
  port: number;
  useSSL: boolean;
}

const parseEndpoint = (): ParsedEndpoint => {
  const endpointUrl = process.env.STORAGE_ENDPOINT;
  if (endpointUrl) {
    const u = new URL(endpointUrl);
    return {
      endPoint: u.hostname,
      port: u.port ? parseInt(u.port) : u.protocol === 'https:' ? 443 : 80,
      useSSL: u.protocol === 'https:',
    };
  }

  // Local dev fallback (docker-compose MinIO)
  return {
    endPoint: process.env.MINIO_ENDPOINT || 'localhost',
    port: parseInt(process.env.MINIO_PORT || '9000'),
    useSSL: process.env.MINIO_USE_SSL === 'true',
  };
};

const { endPoint, port, useSSL } = parseEndpoint();

export const minioClient = new Minio.Client({
  endPoint,
  port,
  useSSL,
  accessKey: process.env.STORAGE_ACCESS_KEY_ID || process.env.MINIO_ACCESS_KEY || '',
  secretKey: process.env.STORAGE_SECRET_ACCESS_KEY || process.env.MINIO_SECRET_KEY || '',
  region: process.env.STORAGE_REGION || process.env.MINIO_REGION || 'auto',
  pathStyle: true, // R2 + MinIO both want path-style URLs
});

// Physical bucket — one R2 bucket holds everything in Tier A.
// Local dev + Tier B can override per-logical-bucket via MINIO_BUCKET_*.
const PHYSICAL_BUCKET = process.env.STORAGE_BUCKET || process.env.MINIO_BUCKET || 'salt-media';

// Logical buckets are key prefixes. The route code stays unchanged: it still
// passes `BUCKETS.AVATARS` to uploadFile/getFileUrl; the helpers below map
// (logicalBucket, objectName) -> (PHYSICAL_BUCKET, `${logicalBucket}/${objectName}`).
export const BUCKETS = {
  SESSION_MEDIA: process.env.BUCKET_SESSION_MEDIA || 'session-media',
  AVATARS: process.env.BUCKET_AVATARS || 'avatars',
  BOARD_PHOTOS: process.env.BUCKET_BOARD_PHOTOS || 'board-photos',
};

const buildKey = (logicalBucket: string, objectName: string): string => {
  // Avoid double-slashing on bucket prefixes that already end in '/'
  const trimmed = logicalBucket.replace(/\/+$/, '');
  return `${trimmed}/${objectName}`;
};

export const ensureBucketsExist = async () => {
  try {
    const exists = await minioClient.bucketExists(PHYSICAL_BUCKET);
    if (!exists) {
      console.warn(
        `Storage bucket ${PHYSICAL_BUCKET} does not exist. ` +
          `Tier A: create it via Terraform (cloudflare_r2_bucket.media). ` +
          `Local dev: create it via the MinIO console.`,
      );
    } else {
      console.log(`Storage bucket ${PHYSICAL_BUCKET} is available`);
    }
  } catch (error) {
    console.error('Error checking storage bucket:', error);
    // Don't crash the API on first deploy if R2 isn't reachable yet — log + continue.
    if (process.env.NODE_ENV === 'production') {
      return;
    }
    throw error;
  }
};

export const uploadFile = async (
  logicalBucket: string,
  objectName: string,
  stream: Buffer | NodeJS.ReadableStream | any,
  size: number,
  metadata: Record<string, string>,
): Promise<string> => {
  const key = buildKey(logicalBucket, objectName);
  try {
    await minioClient.putObject(PHYSICAL_BUCKET, key, stream, size, metadata);
    return getFileUrl(logicalBucket, objectName);
  } catch (error) {
    console.error('Error uploading file to storage:', error);
    throw error;
  }
};

export const deleteFile = async (logicalBucket: string, objectName: string): Promise<void> => {
  const key = buildKey(logicalBucket, objectName);
  try {
    await minioClient.removeObject(PHYSICAL_BUCKET, key);
  } catch (error) {
    console.error('Error deleting file from storage:', error);
    throw error;
  }
};

/**
 * Returns the persistent public URL stored in DB rows.
 *
 * STORAGE_PUBLIC_BASE_URL is expected to point at a public R2 endpoint:
 *   https://pub-XXXXX.r2.dev          (Cloudflare-managed dev URL)
 *   https://media.surflocal.app       (custom domain, post-DNS-cutover)
 *
 * If unset (e.g. before public access is enabled), falls back to a
 * relative path so existing behavior in local/MinIO dev keeps working.
 */
export const getFileUrl = (logicalBucket: string, objectName: string): string => {
  const base = process.env.STORAGE_PUBLIC_BASE_URL || process.env.MINIO_EXTERNAL_URL || '/minio';
  const trimmedBase = base.replace(/\/+$/, '');
  return `${trimmedBase}/${buildKey(logicalBucket, objectName)}`;
};
