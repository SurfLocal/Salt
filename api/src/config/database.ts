import { Pool, PoolConfig } from 'pg';
import * as dns from 'dns';

// Force IPv4 first; harmless on dual-stack hosts (Cloud Run, local).
dns.setDefaultResultOrder('ipv4first');

/**
 * Tier A wires both pools from connection strings (Neon pooled hosts).
 * Tier B / production can keep using DATABASE_URL pointed at Cloud SQL.
 *
 * Legacy DATABASE_HOST/USER/PASSWORD/NAME are still honored as a fallback
 * so local docker-compose dev keeps working unchanged.
 */
const buildPoolConfig = (
  connectionString: string | undefined,
  fallbackDatabase: string,
  max: number,
): PoolConfig => {
  if (connectionString) {
    return {
      connectionString,
      max,
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 5_000,
    };
  }

  return {
    host: process.env.DATABASE_HOST || 'localhost',
    port: parseInt(process.env.DATABASE_PORT || '5432'),
    database: process.env.DATABASE_NAME || fallbackDatabase,
    user: process.env.DATABASE_USER || 'salt_app',
    password: process.env.DATABASE_PASSWORD,
    max,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
  };
};

const PRIMARY_MAX = parseInt(process.env.DATABASE_MAX_CONNECTIONS || '5');
const ANALYTICS_MAX = parseInt(process.env.ANALYTICS_DATABASE_MAX_CONNECTIONS || '3');

export const pool = new Pool(
  buildPoolConfig(process.env.DATABASE_URL, 'salt_app', PRIMARY_MAX),
);

// Tier A: Neon project has both salt_app and surf_analytics databases.
// If ANALYTICS_DATABASE_URL is unset (e.g. local dev with one DB), reuse the
// primary pool so analyticsQuery still resolves — callers can no-op gracefully.
const analyticsConnectionString =
  process.env.ANALYTICS_DATABASE_URL || process.env.DATABASE_URL;

export const analyticsPool = analyticsConnectionString
  ? new Pool(buildPoolConfig(analyticsConnectionString, 'surf_analytics', ANALYTICS_MAX))
  : new Pool(buildPoolConfig(undefined, 'surf_analytics', ANALYTICS_MAX));

pool.on('error', (err) => {
  console.error('Unexpected error on idle primary client', err);
  process.exit(-1);
});

analyticsPool.on('error', (err) => {
  console.error('Unexpected error on analytics pool idle client', err);
});

export const query = async (text: string, params?: any[]) => {
  const start = Date.now();
  try {
    const res = await pool.query(text, params);
    const duration = Date.now() - start;
    console.log('Executed query', { text, duration, rows: res.rowCount });
    return res;
  } catch (error) {
    console.error('Database query error:', error);
    throw error;
  }
};

export const analyticsQuery = async (text: string, params?: any[]) => {
  const start = Date.now();
  try {
    const res = await analyticsPool.query(text, params);
    const duration = Date.now() - start;
    console.log('Executed analytics query', { text, duration, rows: res.rowCount });
    return res;
  } catch (error) {
    console.error('Analytics database query error:', error);
    throw error;
  }
};

export const getClient = async () => {
  const client = await pool.connect();
  const query = client.query;
  const release = client.release;

  const timeout = setTimeout(() => {
    console.error('A client has been checked out for more than 5 seconds!');
  }, 5000);

  client.query = (...args: any[]) => {
    return query.apply(client, args as any);
  };

  client.release = () => {
    clearTimeout(timeout);
    client.query = query;
    client.release = release;
    return release.apply(client);
  };

  return client;
};
