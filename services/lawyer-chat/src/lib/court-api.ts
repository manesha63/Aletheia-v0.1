import { CourtDocument, SearchResponse, BulkJudgeResponse } from '@/types/court-documents';

class CourtAPIClient {
  private baseUrl: string;
  private clientUrl: string;

  constructor() {
    // Use server URL for SSR, client URL for browser
    this.baseUrl = process.env.COURT_API_BASE_URL || 'http://court-processor:8104';
    this.clientUrl = process.env.NEXT_PUBLIC_COURT_API_URL || 'http://localhost:8104';
    
    // Validate environment variables in production
    if (typeof window !== 'undefined' && 
        this.clientUrl === 'http://localhost:8104' && 
        window.location.hostname !== 'localhost') {
      console.error(
        'Court API URL not configured. Document selection will not work.',
        'Please rebuild the application with NEXT_PUBLIC_COURT_API_URL environment variable set.'
      );
    }
  }

  private getUrl(): string {
    // In browser, check if we're in production with localhost fallback
    if (typeof window !== 'undefined') {
      if (this.clientUrl === 'http://localhost:8104' && window.location.hostname !== 'localhost') {
        throw new Error(
          'Court API not configured. Please contact your administrator to enable document selection.'
        );
      }
      return this.clientUrl;
    }
    return this.baseUrl;
  }

  async searchDocuments(params: {
    judge?: string;
    type?: string;
    min_length?: number;
    limit?: number;
    offset?: number;
  }): Promise<SearchResponse> {
    const searchParams = new URLSearchParams();
    
    // Map parameters to Court Processor API format
    if (params.judge) searchParams.append('judge', params.judge);
    if (params.type) searchParams.append('type', params.type);
    if (params.min_length) searchParams.append('min_length', params.min_length.toString());
    searchParams.append('limit', (params.limit || 50).toString());
    searchParams.append('offset', (params.offset || 0).toString());

    const response = await fetch(`${this.getUrl()}/search?${searchParams}`);
    if (!response.ok) {
      throw new Error(`Search failed: ${response.statusText}`);
    }
    return response.json();
  }

  async getDocumentText(id: number): Promise<string> {
    const response = await fetch(`${this.getUrl()}/text/${id}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch document text: ${response.statusText}`);
    }
    return response.text();
  }

  async getDocument(id: number): Promise<CourtDocument> {
    const response = await fetch(`${this.getUrl()}/documents/${id}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch document: ${response.statusText}`);
    }
    return response.json();
  }

  async getBulkByJudge(judgeName: string, includeText = false): Promise<BulkJudgeResponse> {
    const url = `${this.getUrl()}/bulk/judge/${encodeURIComponent(judgeName)}?include_text=${includeText}`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Bulk fetch failed: ${response.statusText}`);
    }
    return response.json();
  }

  async listDocuments(limit = 20): Promise<CourtDocument[]> {
    const response = await fetch(`${this.getUrl()}/list?limit=${limit}`);
    if (!response.ok) {
      throw new Error(`List failed: ${response.statusText}`);
    }
    return response.json();
  }

  async getAvailableJudges(minDocs = 5): Promise<{
    judges: Array<{
      name: string;
      full_name: string;
      court: string;
      total_documents: number;
      substantial_documents: number;
    }>;
    total_judges: number;
  }> {
    const response = await fetch(`${this.getUrl()}/api/judges?min_docs=${minDocs}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch judges: ${response.statusText}`);
    }
    return response.json();
  }

  async getAvailableCourts(minDocs = 10): Promise<{
    courts: Array<{
      court_id: string;
      name: string;
      total_documents: number;
      substantial_documents: number;
      judge_count: number;
    }>;
    total_courts: number;
  }> {
    const response = await fetch(`${this.getUrl()}/api/courts?min_docs=${minDocs}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch courts: ${response.statusText}`);
    }
    return response.json();
  }

  async getDataSummary(): Promise<{
    total_documents: number;
    substantial_documents: number;
    unique_judges: number;
    unique_courts: number;
    top_judges: Array<{ name: string; documents: number }>;
    top_courts: Array<{ court_id: string; documents: number }>;
    data_quality: {
      substantial_ratio: number;
      very_long_ratio: number;
    };
  }> {
    const response = await fetch(`${this.getUrl()}/api/stats/summary`);
    if (!response.ok) {
      throw new Error(`Failed to fetch data summary: ${response.statusText}`);
    }
    return response.json();
  }

  async searchElasticsearch(params: {
    query: string;
    judge?: string;
    court?: string;
    document_type?: string;
    limit?: number;
    offset?: number;
  }): Promise<SearchResponse & { query: string }> {
    const searchParams = new URLSearchParams();

    // Required query parameter
    searchParams.append('query', params.query);

    // Optional filters
    if (params.judge) searchParams.append('judge', params.judge);
    if (params.court) searchParams.append('court', params.court);
    if (params.document_type) searchParams.append('document_type', params.document_type);
    searchParams.append('limit', (params.limit || 10).toString());
    searchParams.append('offset', (params.offset || 0).toString());

    const response = await fetch(`${this.getUrl()}/search/es?${searchParams}`);
    if (!response.ok) {
      throw new Error(`Elasticsearch search failed: ${response.statusText}`);
    }
    return response.json();
  }

  async searchAI(params: {
    query: string;
    profile?: 'basic' | 'professional' | 'advanced' | 'research' | 'litigation';
    legal_topics?: string[];
    courts?: string[];
    judges?: string[];
    dispositions?: string[];
    date_start?: string;
    date_end?: string;
    limit?: number;
    offset?: number;
  }): Promise<SearchResponse & {
    query: string;
    search_profile: string;
    ai_features_active: number;
    legal_filters_applied: number;
    aggregations?: any;
    features_used: string[];
  }> {
    const searchParams = new URLSearchParams();

    // Required query parameter
    searchParams.append('query', params.query);

    // Search profile
    if (params.profile) searchParams.append('profile', params.profile);

    // Legal filtering
    if (params.legal_topics?.length) {
      searchParams.append('legal_topics', params.legal_topics.join(','));
    }
    if (params.courts?.length) {
      searchParams.append('courts', params.courts.join(','));
    }
    if (params.judges?.length) {
      searchParams.append('judges', params.judges.join(','));
    }
    if (params.dispositions?.length) {
      searchParams.append('dispositions', params.dispositions.join(','));
    }

    // Date range
    if (params.date_start) searchParams.append('date_start', params.date_start);
    if (params.date_end) searchParams.append('date_end', params.date_end);

    // Pagination
    searchParams.append('limit', (params.limit || 10).toString());
    searchParams.append('offset', (params.offset || 0).toString());

    const response = await fetch(`${this.getUrl()}/search/ai?${searchParams}`);
    if (!response.ok) {
      throw new Error(`AI search failed: ${response.statusText}`);
    }
    return response.json();
  }

  async getSearchFeatures(): Promise<{
    available_features: Array<{
      name: string;
      description: string;
    }>;
    search_profiles: Record<string, {
      description: string;
      features: string[];
      use_cases: string[];
      performance: string;
    }>;
    dataset_info: {
      total_documents: number;
      has_embeddings: boolean;
      has_legal_topics: boolean;
      has_case_dispositions: boolean;
      courts_available: number;
      judges_available: number;
    };
  }> {
    const response = await fetch(`${this.getUrl()}/search/features`);
    if (!response.ok) {
      throw new Error(`Failed to fetch search features: ${response.statusText}`);
    }
    return response.json();
  }
}

export const courtAPI = new CourtAPIClient();