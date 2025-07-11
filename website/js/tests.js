/**
 * Tests Section Extension for Aletheia
 * Provides interface for running and viewing Haystack node tests
 * Adapted from data_compose for Aletheia integration
 */

(function() {
    'use strict';

    class TestsHandler {
        constructor(app) {
            this.app = app;
            this.initialized = false;
            this.testApiUrl = 'http://localhost:8000'; // Direct to Haystack service
            this.currentStream = null;
            this.elements = {};
            this.testResults = new Map();
            this.isRunning = false;
        }

        initialize() {
            if (this.initialized) return;
            
            console.log('[Tests] Initializing tests section...');
            this.bindElements();
            console.log('[Tests] Elements bound:', this.elements);
            this.attachEventListeners();
            this.loadTestInfo();
            this.initialized = true;
            console.log('[Tests] Tests section initialized');
        }

        bindElements() {
            this.elements = {
                runAllBtn: document.getElementById('test-run-all'),
                testList: document.getElementById('test-list'),
                testOutput: document.getElementById('test-output'),
                testSummary: document.getElementById('test-summary'),
                progressBar: document.getElementById('test-progress'),
                progressFill: document.getElementById('test-progress-fill'),
                statusText: document.getElementById('test-status')
            };
        }

        attachEventListeners() {
            if (this.elements.runAllBtn) {
                this.elements.runAllBtn.addEventListener('click', () => this.runAllTests());
            }
            
            // Event delegation for test list clicks
            if (this.elements.testList) {
                this.elements.testList.addEventListener('click', (e) => {
                    const runBtn = e.target.closest('.test-run-single');
                    if (runBtn) {
                        const testName = runBtn.getAttribute('data-test');
                        if (testName) {
                            this.runSingleTest(testName);
                        }
                    }
                });
            }
        }

        async loadTestInfo() {
            console.log('[Tests] Loading available operations...');
            try {
                // Define the available operations for Haystack RAG
                const operations = [
                    { name: 'health', description: 'Test Elasticsearch and API connectivity' },
                    { name: 'ingest', description: 'Test document ingestion into Elasticsearch' },
                    { name: 'search', description: 'Test document search (BM25, Vector, Hybrid)' }
                ];
                
                this.displayTestList(operations);
            } catch (error) {
                console.error('[Tests] Failed to load test info:', error);
                this.showError('Failed to load test information');
            }
        }

        displayTestList(operations) {
            if (!this.elements.testList) return;
            
            let html = '<div class="test-grid">';
            
            operations.forEach(op => {
                const testId = `test-${op.name}`;
                this.testResults.set(op.name, { status: 'pending' });
                
                html += `
                    <div class="test-card" id="${testId}">
                        <div class="test-header">
                            <h4>${this.formatTestName(op.name)}</h4>
                            <span class="test-status pending">
                                <i class="fas fa-circle"></i> Pending
                            </span>
                        </div>
                        <p class="test-description">${op.description}</p>
                        <button class="btn btn-sm btn-outline-primary test-run-single" 
                                data-test="${op.name}"
                                ${this.isRunning ? 'disabled' : ''}>
                            <i class="fas fa-play"></i> Run Test
                        </button>
                        <div class="test-details" id="${testId}-details" style="display: none;">
                            <pre class="test-detail-content"></pre>
                        </div>
                    </div>
                `;
            });
            
            html += '</div>';
            this.elements.testList.innerHTML = html;
        }

        formatTestName(name) {
            return name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ');
        }

        async runAllTests() {
            console.log('[Tests] Running all tests...');
            if (this.isRunning) return;
            
            this.isRunning = true;
            this.resetUI();
            this.updateProgress(0, 'Starting tests...');
            
            const tests = ['health', 'ingest', 'search'];
            let completed = 0;
            
            for (const testName of tests) {
                await this.runTest(testName);
                completed++;
                const progress = (completed / tests.length) * 100;
                this.updateProgress(progress, `${completed}/${tests.length} tests completed`);
            }
            
            this.displaySummary();
            this.isRunning = false;
            this.enableButtons();
        }

        async runSingleTest(testName) {
            if (this.isRunning) return;
            
            this.isRunning = true;
            this.updateTestStatus(testName, 'running');
            
            try {
                await this.runTest(testName);
            } finally {
                this.isRunning = false;
                this.enableButtons();
            }
        }

        async runTest(testName) {
            const startTime = Date.now();
            let result = { status: 'failed', error: null, details: null };
            
            try {
                switch (testName) {
                    case 'health':
                        result = await this.testHealth();
                        break;
                    case 'ingest':
                        result = await this.testIngest();
                        break;
                    case 'search':
                        result = await this.testSearch();
                        break;
                    default:
                        throw new Error(`Unknown test: ${testName}`);
                }
            } catch (error) {
                console.error(`[Tests] ${testName} failed:`, error);
                result = {
                    status: 'failed',
                    error: error.message,
                    details: { error: error.toString() }
                };
            }
            
            const duration = ((Date.now() - startTime) / 1000).toFixed(2);
            result.duration = duration;
            
            this.updateTestStatus(testName, result.status, result.error, result);
            
            // Log with appropriate type based on status and warnings
            let logType = result.status === 'passed' ? 'success' : 'error';
            let logMessage = `${result.status.toUpperCase()}: ${testName} (${duration}s)`;
            
            if (result.status === 'passed' && result.details && result.details.warnings) {
                logMessage += ' - with warnings';
                logType = 'warning';
            }
            
            this.logOutput(logMessage, logType);
        }

        async testHealth() {
            const response = await fetch(`${this.testApiUrl}/health`);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(`Health check failed: ${response.status}`);
            }
            
            if (data.status !== 'healthy') {
                throw new Error(`Service unhealthy: ${data.status}`);
            }
            
            return {
                status: 'passed',
                details: data
            };
        }

        async testIngest() {
            const testDoc = {
                content: `Test document for Aletheia RAG testing at ${new Date().toISOString()}`,
                metadata: {
                    title: 'Test Document',
                    source: 'Aletheia Tests',
                    test_id: `test-${Date.now()}`
                }
            };
            
            const response = await fetch(`${this.testApiUrl}/ingest`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify([testDoc])
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(`Ingest failed: ${response.status}`);
            }
            
            if (data.documents_processed !== 1) {
                throw new Error(`Expected 1 document processed, got ${data.documents_processed}`);
            }
            
            return {
                status: 'passed',
                details: data
            };
        }

        async testSearch() {
            // Test with correct parameters
            const queries = [
                { query: 'test document', type: 'BM25', search_type: 'bm25' },
                { query: 'Aletheia RAG', type: 'Vector', search_type: 'vector' },
                { query: 'testing', type: 'Hybrid', search_type: 'hybrid' }
            ];
            
            const results = [];
            let errors = [];
            let warnings = [];
            
            // First, test with old incorrect parameters to ensure they fail
            try {
                const oldParamsResponse = await fetch(`${this.testApiUrl}/search`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        query: 'test',
                        topK: 5,  // Wrong parameter name
                        use_hybrid: true  // Wrong parameter
                    })
                });
                
                const oldData = await oldParamsResponse.json();
                
                // The API is lenient and accepts wrong params, but we should warn
                if (oldParamsResponse.ok) {
                    warnings.push('API accepted old parameter format (topK, use_hybrid). Consider making API stricter.');
                }
            } catch (error) {
                // This is actually good - old params should fail
                results.push({
                    type: 'Parameter Validation',
                    status: 'Good - Old format rejected',
                    error: error.message
                });
            }
            
            // Now test with correct parameters
            for (const queryConfig of queries) {
                const { type, ...params } = queryConfig;
                try {
                    const response = await fetch(`${this.testApiUrl}/search`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            query: params.query,
                            top_k: 5,  // Correct parameter name
                            search_type: params.search_type  // Correct parameter
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (!response.ok) {
                        const errorDetail = data.detail || data.error || 'Unknown error';
                        throw new Error(`${type} search failed (${response.status}): ${errorDetail}`);
                    }
                    
                    // Validate response structure
                    if (data.search_type !== params.search_type) {
                        warnings.push(`${type}: Expected search_type '${params.search_type}', got '${data.search_type}'`);
                    }
                    
                    results.push({
                        type,
                        total_results: data.total_results || 0,
                        search_type: data.search_type,
                        query_used: data.query,
                        status: 'success'
                    });
                } catch (error) {
                    errors.push(`${type} search error: ${error.message}`);
                    results.push({
                        type,
                        status: 'failed',
                        error: error.message
                    });
                }
            }
            
            // Only fail if there are actual errors, not warnings
            const hasErrors = errors.length > 0 || results.some(r => r.status === 'failed');
            const hasWarnings = warnings.length > 0;
            
            return {
                status: hasErrors ? 'failed' : 'passed',
                error: errors.length > 0 ? errors.join('; ') : null,
                details: { 
                    searches: results,
                    parameter_format: 'Using correct format: top_k (not topK), search_type (not use_hybrid/use_vector/use_bm25)',
                    warnings: hasWarnings ? warnings : undefined,
                    errors: errors.length > 0 ? errors : undefined
                }
            };
        }

        updateTestStatus(testName, status, error = null, details = null) {
            const testCard = document.getElementById(`test-${testName}`);
            if (!testCard) {
                console.warn(`[Tests] Test card not found for: ${testName}`);
                return;
            }
            
            const statusElement = testCard.querySelector('.test-status');
            if (!statusElement) {
                console.warn(`[Tests] Status element not found for: ${testName}`);
                return;
            }
            
            const detailsElement = document.getElementById(`test-${testName}-details`);
            const detailContent = detailsElement?.querySelector('.test-detail-content');
            
            // Update status
            statusElement.className = `test-status ${status}`;
            switch (status) {
                case 'running':
                    statusElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running';
                    break;
                case 'passed':
                    statusElement.innerHTML = '<i class="fas fa-check-circle"></i> Passed';
                    break;
                case 'failed':
                    statusElement.innerHTML = '<i class="fas fa-times-circle"></i> Failed';
                    break;
                default:
                    statusElement.innerHTML = '<i class="fas fa-circle"></i> Pending';
            }
            
            // Store result
            this.testResults.set(testName, { status, error, details });
            
            // Show details if available
            if (details && detailsElement && detailContent) {
                let detailText = '';
                
                if (details.duration) {
                    detailText += `Duration: ${details.duration}s\n`;
                }
                
                if (error) {
                    detailText += `Error: ${error}\n`;
                }
                
                if (details.details) {
                    // Format details for better readability
                    if (details.details.parameter_format) {
                        detailText += `\nParameter Format:\n${details.details.parameter_format}\n`;
                    }
                    
                    if (details.details.warnings && details.details.warnings.length > 0) {
                        detailText += `\nWarnings:\n`;
                        details.details.warnings.forEach(warning => {
                            detailText += `⚠️  ${warning}\n`;
                        });
                    }
                    
                    if (details.details.searches) {
                        detailText += `\nSearch Results:\n`;
                        details.details.searches.forEach(search => {
                            detailText += `- ${search.type}: `;
                            if (search.status === 'success') {
                                detailText += `✅ ${search.total_results} results found (${search.search_type})\n`;
                            } else {
                                detailText += `❌ ${search.error || 'Failed'}\n`;
                            }
                        });
                    } else {
                        detailText += `\nDetails:\n${JSON.stringify(details.details, null, 2)}`;
                    }
                }
                
                detailContent.textContent = detailText;
                detailsElement.style.display = detailText ? 'block' : 'none';
                
                // Automatically expand details for failed tests
                if (status === 'failed') {
                    detailsElement.style.display = 'block';
                }
            }
        }

        updateProgress(percentage, statusText) {
            if (this.elements.progressFill) {
                this.elements.progressFill.style.width = `${percentage}%`;
            }
            if (this.elements.statusText) {
                this.elements.statusText.textContent = statusText;
            }
        }

        logOutput(message, type = 'info') {
            if (!this.elements.testOutput) return;
            
            const timestamp = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = `test-log-entry test-log-${type}`;
            
            // Add special formatting for parameter errors
            let formattedMessage = this.escapeHtml(message);
            if (message.includes('parameter') || message.includes('topK') || message.includes('use_hybrid')) {
                formattedMessage = formattedMessage
                    .replace(/topK/g, '<span style="color: #ff6b6b; font-weight: bold;">topK</span>')
                    .replace(/top_k/g, '<span style="color: #51cf66; font-weight: bold;">top_k</span>')
                    .replace(/use_hybrid/g, '<span style="color: #ff6b6b; font-weight: bold;">use_hybrid</span>')
                    .replace(/use_vector/g, '<span style="color: #ff6b6b; font-weight: bold;">use_vector</span>')
                    .replace(/use_bm25/g, '<span style="color: #ff6b6b; font-weight: bold;">use_bm25</span>')
                    .replace(/search_type/g, '<span style="color: #51cf66; font-weight: bold;">search_type</span>');
            }
            
            // Add icon for warning type
            let icon = '';
            if (type === 'warning') {
                icon = '<i class="fas fa-exclamation-triangle" style="color: #ffc107; margin-right: 5px;"></i>';
            }
            
            entry.innerHTML = `
                <span class="test-log-time">${timestamp}</span>
                <span class="test-log-message">${icon}${formattedMessage}</span>
            `;
            
            this.elements.testOutput.appendChild(entry);
            this.elements.testOutput.scrollTop = this.elements.testOutput.scrollHeight;
        }

        displaySummary() {
            if (!this.elements.testSummary) return;
            
            let passed = 0;
            let failed = 0;
            
            this.testResults.forEach(result => {
                if (result.status === 'passed') passed++;
                else if (result.status === 'failed') failed++;
            });
            
            const total = this.testResults.size;
            const passRate = total > 0 ? (passed / total) * 100 : 0;
            const statusClass = passRate === 100 ? 'success' : passRate >= 80 ? 'warning' : 'error';
            
            this.elements.testSummary.innerHTML = `
                <div class="test-summary-card ${statusClass}">
                    <h3>Test Summary</h3>
                    <div class="test-summary-stats">
                        <div class="stat">
                            <span class="stat-value">${total}</span>
                            <span class="stat-label">Total Tests</span>
                        </div>
                        <div class="stat">
                            <span class="stat-value">${passed}</span>
                            <span class="stat-label">Passed</span>
                        </div>
                        <div class="stat">
                            <span class="stat-value">${failed}</span>
                            <span class="stat-label">Failed</span>
                        </div>
                        <div class="stat">
                            <span class="stat-value">${passRate.toFixed(1)}%</span>
                            <span class="stat-label">Pass Rate</span>
                        </div>
                    </div>
                </div>
            `;
            
            this.elements.testSummary.style.display = 'block';
        }

        resetUI() {
            console.log('[Tests] Resetting UI...');
            
            // Clear output
            if (this.elements.testOutput) {
                this.elements.testOutput.innerHTML = '';
            }
            
            // Hide summary
            if (this.elements.testSummary) {
                this.elements.testSummary.style.display = 'none';
            }
            
            // Reset all test statuses
            this.testResults.forEach((result, testName) => {
                this.updateTestStatus(testName, 'pending');
            });
            
            // Disable buttons
            this.disableButtons();
        }

        disableButtons() {
            const buttons = document.querySelectorAll('.test-run-single, #test-run-all');
            buttons.forEach(btn => btn.disabled = true);
        }

        enableButtons() {
            const buttons = document.querySelectorAll('.test-run-single, #test-run-all');
            buttons.forEach(btn => btn.disabled = false);
        }

        showError(message) {
            this.logOutput(message, 'error');
            if (this.elements.statusText) {
                this.elements.statusText.textContent = 'Error: ' + message;
            }
        }

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        generateSectionHTML() {
            return `
                <div class="tests-container">
                    <header class="tests-header">
                        <h2>Haystack RAG Tests</h2>
                        <p>Test the Haystack service operations for document ingestion and retrieval</p>
                    </header>
                    
                    <div class="tests-controls">
                        <button id="test-run-all" class="btn btn-primary btn-large">
                            <i class="fas fa-play-circle"></i> Run All Tests
                        </button>
                        <div class="test-status-bar">
                            <div id="test-progress" class="test-progress-bar">
                                <div id="test-progress-fill" class="test-progress-fill"></div>
                            </div>
                            <span id="test-status" class="test-status-text">Ready to run tests</span>
                        </div>
                    </div>
                    
                    <div id="test-summary" class="test-summary" style="display: none;"></div>
                    
                    <section class="tests-section">
                        <h3>Available Tests</h3>
                        <div id="test-list" class="test-list">
                            <p class="loading">Loading tests...</p>
                        </div>
                    </section>
                    
                    <section class="tests-output-section">
                        <h3>Test Output</h3>
                        <div id="test-output" class="test-output"></div>
                    </section>
                </div>
            `;
        }
    }

    // Wait for app to be ready and register the section
    function initializeTests() {
        if (window.app && typeof window.app.addSection === 'function') {
            const handler = new TestsHandler(window.app);
            
            // Register with app
            window.app.addSection(
                'tests',
                'Tests',
                'fas fa-vial',
                handler.generateSectionHTML(),
                {
                    onShow: () => handler.initialize()
                }
            );
            
            // Make handler globally accessible for debugging
            window.testsHandler = handler;
            
            console.log('Tests section registered');
        } else {
            // Retry if app not ready
            setTimeout(initializeTests, 100);
        }
    }
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeTests);
    } else {
        initializeTests();
    }
})();