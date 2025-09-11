#!/usr/bin/env node

import { Client, ClientConfig } from 'pg';

interface ConnectionTest {
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
  ssl?: boolean;
  connectionTimeoutMillis?: number;
}

interface NodeModule {
  paths?: string[];
}

/**
 * Safely add module path with fallback strategies
 */
function addModulePath(path: string): boolean {
  try {
    // Strategy 1: Try to modify require.paths
    const moduleSystem = require('module') as NodeModule;
    if (moduleSystem?.paths && Array.isArray(moduleSystem.paths)) {
      moduleSystem.paths.push(path);
      return true;
    }
    
    // Strategy 2: Use NODE_PATH environment variable
    const currentNodePath = process.env.NODE_PATH || '';
    const paths = currentNodePath.split(':').filter(Boolean);
    if (!paths.includes(path)) {
      paths.push(path);
      process.env.NODE_PATH = paths.join(':');
      require('module')._initPaths();
      return true;
    }
    
    return false;
  } catch (error) {
    console.warn(`Could not add module path ${path}:`, (error as Error).message);
    return false;
  }
}

/**
 * Test PostgreSQL connection with multiple fallback strategies
 */
async function testConnection(config: ConnectionTest): Promise<void> {
  // Try to add n8n's node_modules path with fallbacks
  const n8nPaths = [
    '/usr/local/lib/node_modules/n8n/node_modules',
    '/app/node_modules',
    '/home/node/.n8n/node_modules'
  ];
  
  for (const path of n8nPaths) {
    if (addModulePath(path)) {
      console.log(`Added module path: ${path}`);
      break;
    }
  }

  const clientConfig: ClientConfig = {
    host: config.host,
    port: config.port,
    database: config.database,
    user: config.user,
    password: config.password,
    ssl: config.ssl ?? false,
    connectionTimeoutMillis: config.connectionTimeoutMillis ?? 5000
  };

  let client: Client | null = null;
  
  try {
    client = new Client(clientConfig);
    await client.connect();
    
    // Test basic query
    const result = await client.query('SELECT current_user, version() as postgres_version');
    console.log('SUCCESS');
    console.log(`Connected as: ${result.rows[0].current_user}`);
    console.log(`PostgreSQL version: ${result.rows[0].postgres_version.split(' ')[0]}`);
    
  } catch (error) {
    const pgError = error as Error & { code?: string; detail?: string };
    console.error('FAILED');
    console.error(`Error: ${pgError.message}`);
    if (pgError.code) {
      console.error(`Code: ${pgError.code}`);
    }
    if (pgError.detail) {
      console.error(`Detail: ${pgError.detail}`);
    }
    process.exit(1);
    
  } finally {
    if (client) {
      try {
        await client.end();
      } catch (endError) {
        console.warn('Warning: Error closing connection:', (endError as Error).message);
      }
    }
  }
}

// Main execution
if (require.main === module) {
  // Parse command line arguments or environment variables
  const config: ConnectionTest = {
    host: process.env.DB_HOST || process.argv[2] || 'localhost',
    port: parseInt(process.env.DB_PORT || process.argv[3] || '5432', 10),
    database: process.env.DB_NAME || process.argv[4] || 'postgres',
    user: process.env.DB_USER || process.argv[5] || 'postgres',
    password: process.env.DB_PASSWORD || process.argv[6] || '',
    ssl: process.env.DB_SSL === 'true' || false,
    connectionTimeoutMillis: 5000
  };

  // Validate required fields
  if (!config.password) {
    console.error('ERROR: Database password is required');
    console.error('Usage: node test-connection.js <host> <port> <database> <user> <password>');
    console.error('Or set environment variables: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD');
    process.exit(1);
  }

  testConnection(config)
    .then(() => {
      console.log('Connection test completed successfully');
      process.exit(0);
    })
    .catch((error) => {
      console.error('Unexpected error:', error);
      process.exit(1);
    });
}

export { testConnection, ConnectionTest };