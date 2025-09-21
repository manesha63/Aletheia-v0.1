import {
  IExecuteFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
  NodeOperationError,
  IDataObject,
  NodeConnectionType,
  INodeInputConfiguration,
  INodeCredentialDescription,
} from 'n8n-workflow';

import { v4 as uuidv4 } from 'uuid';
import { Pool } from 'pg';
// Constants
const CHARS_PER_TOKEN = 4;

// Token estimation helper
function estimateTokenCount(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.length / CHARS_PER_TOKEN);
}

// Global resilience instances
let globalCircuitBreaker: CircuitBreaker | null = null;
let globalRateLimiter: RateLimiter | null = null;

// NEW CLEAN INTERFACES

// Input document from webhook
interface DocumentInput {
  id: string;
  type: 'opinion' | 'transcript';
  content: string;
  metadata: {
    parties?: string[];
    code?: string;
    court?: string;
    date?: string;
    [key: string]: any;
  };
}

// AI-generated tags with specialized format
interface AITag {
  type: 'status' | 'outcome' | 'legal_standard' | 'parties' | 'custom';
  value: string;
  confidence?: number;
  source_reference: string;
  raw_tag: string; // Original <**type:value**> format
}

// First-level summary with tags
interface TaggedSummary {
  id: string;
  document_id: string;
  batch_index: number;
  summary_text: string;
  ai_tags: AITag[];
  token_count: number;
  source_content: string;
}

// Group summary result
interface GroupSummary {
  group_key: string;
  group_type: string;
  summary: string;
  source_document_ids: string[];
  member_count: number;
  ai_tags: AITag[];
}

// Processing configuration (simplified)
interface ProcessingConfig {
  documentType: 'opinion' | 'transcript';
  batchId: string;
  resilience?: ResilienceConfig;
  prompts: {
    summaryPrompt: string;
    taggingPrompt: string;
    secondLevelPrompt: string;
  };
}

// Output format for processed documents
interface ProcessedDocument {
  original_document: DocumentInput;
  first_level_summaries: TaggedSummary[];
  grouped_analysis: {
    by_status?: GroupSummary[];
    by_parties?: GroupSummary[];
    by_code_outcome?: GroupSummary[];
  };
  metadata: {
    processing_time: number;
    total_summaries: number;
    total_groups: number;
    ai_tags_generated: number;
  };
}

// Document batch for initial processing (unused for now)
// interface DocumentBatch {
//   id: string;
//   content: string;
//   start_index: number;
//   end_index: number;
//   token_count: number;
// }

interface RetryConfig {
  maxRetries: number;
  initialDelay: number;
  maxDelay: number;
  backoffMultiplier: number;
  jitterFactor: number;
}

interface ResilienceConfig {
  retryEnabled: boolean;
  retryConfig: RetryConfig;
  requestTimeout: number;
  fallbackEnabled: boolean;
  rateLimit: number;
  circuitBreakerEnabled?: boolean;
  circuitBreakerThreshold?: number;
  circuitBreakerResetTimeout?: number;
}

interface CircuitBreakerConfig {
  failureThreshold: number;
  resetTimeout: number;
  halfOpenRequests: number;
}

// Circuit breaker state management
class CircuitBreaker {
  private failures = 0;
  private lastFailureTime = 0;
  private state: 'closed' | 'open' | 'half-open' = 'closed';
  private halfOpenAttempts = 0;
  private successfulHalfOpenRequests = 0;

  constructor(private config: CircuitBreakerConfig) {}

  async execute<T>(operation: () => Promise<T>): Promise<T> {
    // Check if circuit should transition from open to half-open
    if (this.state === 'open') {
      const timeSinceLastFailure = Date.now() - this.lastFailureTime;
      if (timeSinceLastFailure > this.config.resetTimeout) {
        console.log('[CircuitBreaker] Transitioning from OPEN to HALF-OPEN');
        this.state = 'half-open';
        this.halfOpenAttempts = 0;
        this.successfulHalfOpenRequests = 0;
      } else {
        throw new Error(`Circuit breaker is OPEN - BitNet server is unavailable. Will retry in ${Math.round((this.config.resetTimeout - timeSinceLastFailure) / 1000)} seconds`);
      }
    }

    // In half-open state, limit the number of test requests
    if (this.state === 'half-open' && this.halfOpenAttempts >= this.config.halfOpenRequests) {
      // Decide whether to close or re-open based on success rate
      if (this.successfulHalfOpenRequests >= Math.ceil(this.config.halfOpenRequests / 2)) {
        console.log('[CircuitBreaker] Closing circuit - server recovered');
        this.state = 'closed';
        this.failures = 0;
      } else {
        console.log('[CircuitBreaker] Re-opening circuit - server still failing');
        this.state = 'open';
        this.lastFailureTime = Date.now();
      }
    }

    try {
      const result = await operation();
      this.onSuccess();
      return result;
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }

  private onSuccess() {
    if (this.state === 'half-open') {
      this.successfulHalfOpenRequests++;
      this.halfOpenAttempts++;
      console.log(`[CircuitBreaker] Half-open success ${this.successfulHalfOpenRequests}/${this.halfOpenAttempts}`);
    } else if (this.state === 'closed') {
      // Reset failure count on success
      this.failures = 0;
    }
  }

  private onFailure() {
    this.failures++;
    this.lastFailureTime = Date.now();

    if (this.state === 'half-open') {
      this.halfOpenAttempts++;
      console.log(`[CircuitBreaker] Half-open failure ${this.halfOpenAttempts - this.successfulHalfOpenRequests}/${this.halfOpenAttempts}`);
    } else if (this.state === 'closed' && this.failures >= this.config.failureThreshold) {
      console.log(`[CircuitBreaker] Opening circuit after ${this.failures} consecutive failures`);
      this.state = 'open';
    }
  }

  getState(): string {
    return this.state;
  }
}

// Rate limiter with request queue
class RateLimiter {
  private queue: Array<{
    execute: () => Promise<any>;
    resolve: (value: any) => void;
    reject: (error: any) => void;
  }> = [];
  private processing = false;
  private lastRequestTime = 0;

  constructor(
    private requestsPerMinute: number
  ) {}

  async execute<T>(operation: () => Promise<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      this.queue.push({
        execute: operation,
        resolve,
        reject
      });

      if (!this.processing) {
        this.processQueue();
      }
    });
  }

  private async processQueue() {
    this.processing = true;

    while (this.queue.length > 0) {
      const request = this.queue.shift();
      if (!request) continue;

      // Calculate minimum interval between requests
      const minInterval = 60000 / this.requestsPerMinute;
      const timeSinceLastRequest = Date.now() - this.lastRequestTime;

      // Wait if necessary to maintain rate limit
      if (timeSinceLastRequest < minInterval) {
        const waitTime = minInterval - timeSinceLastRequest;
        console.log(`[RateLimiter] Waiting ${Math.round(waitTime)}ms to maintain rate limit`);
        await new Promise(resolve => setTimeout(resolve, waitTime));
      }

      try {
        const result = await request.execute();
        this.lastRequestTime = Date.now();
        request.resolve(result);
      } catch (error) {
        request.reject(error);
      }
    }

    this.processing = false;
  }

  getQueueLength(): number {
    return this.queue.length;
  }
}

export class CitationGen implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Citation Generator',
    name: 'citationGen',
    icon: 'file:citationGen.svg',
    group: ['transform'],
    version: 1,
    subtitle: '=Smart Legal Document Processing',
    description: 'Process legal opinions and transcripts with AI-powered summarization and Elasticsearch grouping',
    defaults: {
      name: 'Citation Generator',
    },
    // Define multiple input connections
    inputs: [
      NodeConnectionType.Main,
      {
        type: NodeConnectionType.AiLanguageModel,
        required: true,
        displayName: 'Language Model',
        maxConnections: 1,
      },
    ] as Array<NodeConnectionType | INodeInputConfiguration>,

    outputs: [NodeConnectionType.Main],

    credentials: [
      {
        name: 'postgres',
        required: false,
        displayOptions: {
          show: {
            databaseConfig: ['credentials'],
          },
        },
      },
    ] as INodeCredentialDescription[],

    properties: [
      // Document Type Selection
      {
        displayName: 'Document Type',
        name: 'documentType',
        type: 'options',
        options: [
          {
            name: 'Legal Opinion',
            value: 'opinion',
            description: 'Legal opinion documents for AI analysis and grouping',
          },
          {
            name: 'Legal Transcript',
            value: 'transcript',
            description: 'Legal transcript processing (coming soon)',
          },
        ],
        default: 'opinion',
        description: 'Type of legal document to process',
      },

      // Opinion Processing Configuration
      {
        displayName: 'Opinion Summary Prompt',
        name: 'opinionSummaryPrompt',
        type: 'string',
        default: 'Summarize this legal opinion section in 2-3 sentences with proper citations. Generate specialized tags in format <**type:value**> for legal status, outcomes, and standards.',
        displayOptions: {
          show: {
            documentType: ['opinion'],
          },
        },
        typeOptions: {
          rows: 4,
        },
        description: 'Prompt for initial opinion summarization with AI tagging',
      },
      {
        displayName: 'AI Tagging Prompt',
        name: 'taggingPrompt',
        type: 'string',
        default: 'Generate specialized tags for this legal content using format <**type:value**>:\\n- Status: <**status:granted**>, <**status:denied**>\\n- Outcomes: <**outcome:dismissed**>, <**outcome:remanded**>\\n- Standards: <**standard:summary_judgment**>\\n- Parties: <**party:plaintiff**>, <**party:defendant**>',
        displayOptions: {
          show: {
            documentType: ['opinion'],
          },
        },
        typeOptions: {
          rows: 4,
        },
        description: 'Prompt for generating specialized AI tags',
      },
      {
        displayName: 'Second Level Summary Prompt',
        name: 'secondLevelPrompt',
        type: 'string',
        default: 'Analyze and summarize this group of related legal content. Identify patterns and provide comprehensive analysis with source references.',
        displayOptions: {
          show: {
            documentType: ['opinion'],
          },
        },
        typeOptions: {
          rows: 3,
        },
        description: 'Prompt for second-level grouped summarization',
      },

      // Elasticsearch Configuration
      {
        displayName: 'Enable Elasticsearch Grouping',
        name: 'enableElasticsearch',
        type: 'boolean',
        default: true,
        displayOptions: {
          show: {
            documentType: ['opinion'],
          },
        },
        description: 'Use Elasticsearch for intelligent document grouping',
      },
      {
        displayName: 'Elasticsearch Host',
        name: 'elasticsearchHost',
        type: 'string',
        default: 'elasticsearch',
        displayOptions: {
          show: {
            documentType: ['opinion'],
            enableElasticsearch: [true],
          },
        },
        description: 'Elasticsearch server host',
      },
      {
        displayName: 'Elasticsearch Port',
        name: 'elasticsearchPort',
        type: 'number',
        default: 9200,
        displayOptions: {
          show: {
            documentType: ['opinion'],
            enableElasticsearch: [true],
          },
        },
        description: 'Elasticsearch server port',
      },
      {
        displayName: 'Elasticsearch Index',
        name: 'elasticsearchIndex',
        type: 'string',
        default: 'legal_summaries',
        displayOptions: {
          show: {
            documentType: ['opinion'],
            enableElasticsearch: [true],
          },
        },
        description: 'Elasticsearch index for storing summaries',
      },

      // Processing Configuration
      {
        displayName: 'Batch Size (tokens)',
        name: 'batchSize',
        type: 'number',
        default: 4000,
        description: 'Maximum tokens per processing batch',
        typeOptions: {
          minValue: 1000,
          maxValue: 16000,
          numberStepSize: 500,
        },
      },

      // Database Configuration (simplified)
      {
        displayName: 'Database Configuration',
        name: 'databaseConfig',
        type: 'options',
        options: [
          {
            name: 'Use Credentials',
            value: 'credentials',
            description: 'Use PostgreSQL credentials configured in n8n',
          },
          {
            name: 'Manual Configuration',
            value: 'manual',
            description: 'Manually configure database connection parameters',
          },
        ],
        default: 'credentials',
        description: 'How to connect to the database for storing results',
      },

      // Resilience Options (simplified)
      {
        displayName: 'Resilience Options',
        name: 'resilienceOptions',
        type: 'collection',
        placeholder: 'Add resilience option',
        default: {},
        description: 'Configure resilience patterns for AI model connectivity',
        options: [
          {
            displayName: 'Rate Limit (per minute)',
            name: 'rateLimit',
            type: 'number',
            default: 20,
            description: 'Maximum AI requests per minute',
          },
          {
            displayName: 'Enable Circuit Breaker',
            name: 'circuitBreakerEnabled',
            type: 'boolean',
            default: true,
            description: 'Protect against failing AI service',
          },
        ],
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const returnData: INodeExecutionData[] = [];

    // Initialize global resilience patterns
    await initializeResilience();

    // Create database pool
    let pool: Pool | null = null;

    try {
      pool = await createDatabasePool(this);
      await ensureDatabaseSchema(pool);

      // Process each item with clean routing
      for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
        try {
          const result = await processItem(this, itemIndex, pool);
          returnData.push(result);
        } catch (error) {
          throw new NodeOperationError(
            this.getNode(),
            `Failed to process item ${itemIndex}: ${error.message}`,
            { itemIndex }
          );
        }
      }

      return [returnData];

    } catch (error) {
      throw new NodeOperationError(
        this.getNode(),
        `Execution failed: ${error.message}`
      );
    } finally {
      if (pool) {
        await pool.end();
      }
    }
  }

  // Note: Methods moved to module-level functions for proper n8n integration

  // Note: Input validation moved to module-level function

  // Note: Processing methods moved to module-level functions

  // Note: Configuration helpers moved to module-level functions

  // Note: Database helpers moved to module-level functions

}

// MODULE-LEVEL FUNCTIONS FOR N8N INTEGRATION

async function initializeResilience(): Promise<void> {
  // Initialize global circuit breaker if not exists
  if (!globalCircuitBreaker) {
    globalCircuitBreaker = new CircuitBreaker({
      failureThreshold: 5,
      resetTimeout: 60000,
      halfOpenRequests: 3
    });
  }

  // Initialize global rate limiter if not exists
  if (!globalRateLimiter) {
    globalRateLimiter = new RateLimiter(20); // 20 requests per minute default
  }
}

async function createDatabasePool(executeFunctions: IExecuteFunctions): Promise<Pool> {
  const databaseConfig = executeFunctions.getNodeParameter('databaseConfig', 0) as string;

  if (databaseConfig === 'credentials') {
    const credentials = await executeFunctions.getCredentials('postgres');
    return new Pool({
      host: credentials.host as string,
      port: credentials.port as number,
      database: credentials.database as string,
      user: credentials.user as string,
      password: credentials.password as string,
      max: 10,
      idleTimeoutMillis: 60000
    });
  } else {
    // Manual configuration - simplified for now
    throw new Error('Manual database configuration not yet implemented in refactored version');
  }
}

async function ensureDatabaseSchema(pool: Pool): Promise<void> {
  const client = await pool.connect();
  try {
    // Simplified schema - just what we need for the new architecture
    await client.query(`
      CREATE TABLE IF NOT EXISTS legal_summaries (
        id SERIAL PRIMARY KEY,
        document_id VARCHAR(255) NOT NULL,
        batch_index INTEGER NOT NULL,
        summary_text TEXT NOT NULL,
        ai_tags JSONB DEFAULT '[]',
        token_count INTEGER DEFAULT 0,
        source_content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

    await client.query(`
      CREATE TABLE IF NOT EXISTS grouped_summaries (
        id SERIAL PRIMARY KEY,
        group_key VARCHAR(255) NOT NULL,
        group_type VARCHAR(100) NOT NULL,
        summary TEXT NOT NULL,
        source_document_ids JSONB DEFAULT '[]',
        member_count INTEGER DEFAULT 0,
        ai_tags JSONB DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);

  } finally {
    client.release();
  }
}

// CLEAN ROUTING METHOD
async function processItem(
  executeFunctions: IExecuteFunctions,
  itemIndex: number,
  pool: Pool
): Promise<INodeExecutionData> {
  const documentType = executeFunctions.getNodeParameter('documentType', itemIndex) as string;
  const inputData = executeFunctions.getInputData()[itemIndex];

  // Validate input
  const documentInput = validateInput(inputData);

  // Route by document type
  switch (documentType) {
    case 'opinion':
      return await processOpinion(executeFunctions, documentInput, itemIndex, pool);
    case 'transcript':
      return await processTranscript(executeFunctions, documentInput, itemIndex, pool);
    default:
      throw new Error(`Unsupported document type: ${documentType}`);
  }
}

// INPUT VALIDATION
function validateInput(inputData: INodeExecutionData): DocumentInput {
  const json = inputData.json;

  if (!json) {
    throw new Error('No input data provided');
  }

  const documentInput: DocumentInput = {
    id: json.id as string || uuidv4(),
    type: json.type as 'opinion' | 'transcript' || 'opinion',
    content: json.content as string || json.text as string || '',
    metadata: json.metadata as any || {}
  };

  if (!documentInput.content) {
    throw new Error('Document content is required');
  }

  if (!['opinion', 'transcript'].includes(documentInput.type)) {
    throw new Error(`Invalid document type: ${documentInput.type}`);
  }

  return documentInput;
}

// TRANSCRIPT PROCESSING (STUB)
async function processTranscript(
  executeFunctions: IExecuteFunctions,
  doc: DocumentInput,
  itemIndex: number,
  pool: Pool
): Promise<INodeExecutionData> {
  throw new Error('Transcript processing is not yet implemented. Please use document type "opinion".');
}

// OPINION PROCESSING - MAIN WORKFLOW
async function processOpinion(
  executeFunctions: IExecuteFunctions,
  doc: DocumentInput,
  itemIndex: number,
  pool: Pool
): Promise<INodeExecutionData> {
  const startTime = Date.now();

  console.log(`[CG] Processing opinion document: ${doc.id}`);

  // Phase 1: Generate initial summary batches with AI tagging
  const firstLevelSummaries = await generateInitialSummaries(executeFunctions, doc, itemIndex, pool);

  // Phase 2: Elasticsearch grouping (if enabled)
  let groupedAnalysis = {};
  const enableElasticsearch = executeFunctions.getNodeParameter('enableElasticsearch', itemIndex) as boolean;

  if (enableElasticsearch) {
    groupedAnalysis = await performElasticsearchGrouping(firstLevelSummaries, pool);
  }

  // Format final output
  const processedDocument = {
    original_document: doc,
    first_level_summaries: firstLevelSummaries,
    grouped_analysis: groupedAnalysis,
    metadata: {
      processing_time: Date.now() - startTime,
      total_summaries: firstLevelSummaries.length,
      total_groups: Object.keys(groupedAnalysis).length,
      ai_tags_generated: firstLevelSummaries.reduce((sum, s) => sum + s.ai_tags.length, 0)
    }
  };

  return {
    json: processedDocument as IDataObject,
    pairedItem: itemIndex
  };
}

// AI-POWERED INITIAL SUMMARIZATION
async function generateInitialSummaries(
  executeFunctions: IExecuteFunctions,
  doc: DocumentInput,
  itemIndex: number,
  pool: Pool
): Promise<TaggedSummary[]> {
  console.log(`[CG] Starting AI-powered summarization for document ${doc.id}`);

  // Get configuration parameters
  const summaryPrompt = executeFunctions.getNodeParameter('opinionSummaryPrompt', itemIndex) as string;
  const taggingPrompt = executeFunctions.getNodeParameter('taggingPrompt', itemIndex) as string;
  const batchSize = executeFunctions.getNodeParameter('batchSize', itemIndex) as number;

  // Get resilience options
  const resilienceOptions = executeFunctions.getNodeParameter('resilienceOptions', itemIndex) as any;
  const rateLimit = resilienceOptions?.rateLimit || 20;
  const circuitBreakerEnabled = resilienceOptions?.circuitBreakerEnabled !== false;

  // Initialize resilience patterns
  await initializeResilience();

  // Split document into batches
  const batches = chunkDocumentIntoBatches(doc.content, batchSize);
  const summaries: TaggedSummary[] = [];

  console.log(`[CG] Processing ${batches.length} batches for document ${doc.id}`);

  // Process each batch
  for (let i = 0; i < batches.length; i++) {
    const batch = batches[i];
    console.log(`[CG] Processing batch ${i + 1}/${batches.length} (${batch.length} chars)`);

    try {
      // Create combined prompt for summary and tagging
      const combinedPrompt = `${summaryPrompt}\n\nAdditional tagging instructions: ${taggingPrompt}`;

      // Generate summary with AI
      const summaryText = await generateAISummary(
        executeFunctions,
        batch,
        combinedPrompt,
        rateLimit,
        circuitBreakerEnabled
      );

      // Extract AI tags from the summary
      const aiTags = extractAITags(summaryText);

      // Store in database
      const client = await pool.connect();
      try {
        const result = await client.query(
          `INSERT INTO legal_summaries
           (document_id, batch_index, summary_text, ai_tags, token_count, source_content)
           VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,
          [
            doc.id,
            i,
            summaryText,
            JSON.stringify(aiTags),
            estimateTokenCount(summaryText),
            batch
          ]
        );

        const summaryId = result.rows[0].id;

        summaries.push({
          id: summaryId,
          document_id: doc.id,
          batch_index: i,
          summary_text: summaryText,
          ai_tags: aiTags,
          token_count: estimateTokenCount(summaryText),
          source_content: batch
        });

      } finally {
        client.release();
      }

    } catch (error) {
      console.error(`[CG] Failed to process batch ${i + 1}: ${error.message}`);

      // Create fallback summary
      const fallbackSummary = generateFallbackSummary(batch, i);
      summaries.push(fallbackSummary);
    }
  }

  console.log(`[CG] Completed summarization: ${summaries.length} summaries generated`);
  return summaries;
}

// Helper function to chunk document into manageable batches
function chunkDocumentIntoBatches(content: string, maxTokens: number): string[] {
  const maxChars = maxTokens * CHARS_PER_TOKEN;
  const chunks: string[] = [];

  // Split on paragraph boundaries first
  const paragraphs = content.split(/\n\s*\n/);
  let currentChunk = '';

  for (const paragraph of paragraphs) {
    if (currentChunk.length + paragraph.length + 2 <= maxChars) {
      currentChunk += (currentChunk ? '\n\n' : '') + paragraph;
    } else {
      if (currentChunk) {
        chunks.push(currentChunk.trim());
        currentChunk = '';
      }

      // If paragraph is too long, split by sentences
      if (paragraph.length > maxChars) {
        const sentences = paragraph.split(/(?<=[.!?])\s+/);
        for (const sentence of sentences) {
          if (currentChunk.length + sentence.length + 1 <= maxChars) {
            currentChunk += (currentChunk ? ' ' : '') + sentence;
          } else {
            if (currentChunk) {
              chunks.push(currentChunk.trim());
              currentChunk = sentence;
            } else {
              // Sentence too long, force split
              chunks.push(sentence.substring(0, maxChars));
              currentChunk = sentence.substring(maxChars);
            }
          }
        }
      } else {
        currentChunk = paragraph;
      }
    }
  }

  if (currentChunk.trim()) {
    chunks.push(currentChunk.trim());
  }

  return chunks.length > 0 ? chunks : [content.substring(0, maxChars)];
}

// AI summary generation with resilience
async function generateAISummary(
  executeFunctions: IExecuteFunctions,
  content: string,
  prompt: string,
  rateLimit: number,
  circuitBreakerEnabled: boolean
): Promise<string> {
  // Rate limiting
  if (globalRateLimiter) {
    await globalRateLimiter.execute(async () => Promise.resolve());
  }

  // Circuit breaker protection
  const operation = async () => {
    // Get the AI language model connection
    const languageModel = await executeFunctions.getInputConnectionData(
      NodeConnectionType.AiLanguageModel,
      0
    );

    if (!languageModel || typeof (languageModel as any).invoke !== 'function') {
      throw new NodeOperationError(
        executeFunctions.getNode(),
        'No AI language model connected. Please connect an AI model to the Language Model input.'
      );
    }

    // Build user content
    const userContent = `Legal document content to summarize:\n\n${content}`;

    let response;
    try {
      // Try custom node format first (BitNet style)
      response = await Promise.race([
        (languageModel as any).invoke({
          messages: [
            { role: 'system', content: prompt },
            { role: 'user', content: userContent }
          ],
          options: {
            temperature: 0.3,
            maxTokensToSample: 200,
          }
        }),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('AI request timeout after 60 seconds')), 60000)
        )
      ]);
    } catch (invokeError: any) {
      // Fallback to standard n8n format
      if (invokeError.message?.includes('toChatMessages') || invokeError.message?.includes('messages')) {
        console.log('[CG] Using standard n8n AI format');
        const combinedPrompt = `${prompt}\n\nHuman: ${userContent}\n\nAI:`;

        response = await Promise.race([
          (languageModel as any).invoke(combinedPrompt, {
            temperature: 0.3,
            estimatedTokens: estimateTokenCount(userContent) + 100,
            options: {
              temperature: 0.3,
              max_tokens: 200,
            }
          }),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error('AI request timeout after 60 seconds')), 60000)
          )
        ]);
      } else {
        throw invokeError;
      }
    }

    // Parse response based on format
    let summaryText = '';
    if (response?.text) {
      summaryText = response.text;
    } else if (response?.content) {
      summaryText = response.content;
    } else if (response?.response?.generations?.[0]?.[0]?.text) {
      summaryText = response.response.generations[0][0].text;
    } else if (typeof response === 'string') {
      summaryText = response;
    } else {
      throw new Error('Unexpected AI response format');
    }

    return summaryText.trim();
  };

  // Execute with circuit breaker if enabled
  if (circuitBreakerEnabled && globalCircuitBreaker) {
    return await globalCircuitBreaker.execute(operation);
  } else {
    return await operation();
  }
}

// Extract AI tags from summary text
function extractAITags(summaryText: string): AITag[] {
  const tags: AITag[] = [];

  // Regex to find tags in format <**type:value**>
  const tagRegex = /<\*\*([^:]+):([^*]+)\*\*>/g;
  let match;

  while ((match = tagRegex.exec(summaryText)) !== null) {
    const [fullMatch, type, value] = match;

    // Validate tag type
    const validTypes: Array<AITag['type']> = ['status', 'outcome', 'legal_standard', 'parties', 'custom'];
    const tagType = validTypes.includes(type as AITag['type']) ? type as AITag['type'] : 'custom';

    tags.push({
      type: tagType,
      value: value.trim(),
      confidence: 0.8, // Default confidence for extracted tags
      source_reference: `char_${match.index}`,
      raw_tag: fullMatch
    });
  }

  // If no tags found, create a default processing tag
  if (tags.length === 0) {
    tags.push({
      type: 'status',
      value: 'analyzed',
      confidence: 0.5,
      source_reference: 'auto_generated',
      raw_tag: '<**status:analyzed**>'
    });
  }

  return tags;
}

// Fallback summary generation
function generateFallbackSummary(content: string, batchIndex: number): TaggedSummary {
  // Simple extractive summarization - take first few sentences
  const sentences = content.split(/(?<=[.!?])\s+/);
  const summaryText = sentences.slice(0, 3).join(' ');

  return {
    id: uuidv4(),
    document_id: 'fallback',
    batch_index: batchIndex,
    summary_text: `[FALLBACK SUMMARY] ${summaryText}`,
    ai_tags: [{
      type: 'status',
      value: 'fallback_generated',
      confidence: 0.3,
      source_reference: 'fallback_system',
      raw_tag: '<**status:fallback_generated**>'
    }],
    token_count: estimateTokenCount(summaryText),
    source_content: content
  };
}

async function performElasticsearchGrouping(
  summaries: TaggedSummary[],
  pool: Pool
): Promise<any> {
  console.log(`[CG] Elasticsearch grouping placeholder for ${summaries.length} summaries`);

  // Return placeholder grouped analysis
  return {
    by_status: [],
    by_parties: [],
    by_code_outcome: []
  };
}