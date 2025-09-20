#!/bin/bash

echo "🚀 Starting Haystack Services for Judicial Access (Quick Start)"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Navigate to project root
cd "$SCRIPT_DIR/.."

# Verify we're in the correct directory
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Error: Not in the correct directory structure."
    echo "   Current directory: $(pwd)"
    echo "   Missing docker-compose.yml file."
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if main services are running
if ! docker-compose ps | grep -q "n8n.*Up"; then
    echo "⚠️  Main services are not running. Starting them first..."
    docker-compose up -d
    sleep 10
fi

# Start Haystack services using main compose file
echo "📦 Starting Haystack and Elasticsearch services..."
docker-compose up -d elasticsearch haystack-service unstructured-service

# Wait for services to be ready
echo "⏳ Waiting for services to start (this may take a while for first run)..."
sleep 30

# Run setup script inside the haystack container instead
echo "🔧 Setting up Elasticsearch index..."
docker-compose exec -T haystack-service python elasticsearch_setup.py || echo "⚠️ Index setup will run when service is ready"

# Check service health
echo "🏥 Checking service health..."
echo "Elasticsearch:" 
curl -s http://localhost:9200/_cluster/health | python3 -m json.tool 2>/dev/null || echo "  ⚠️  Elasticsearch not ready yet"
echo -e "\nHaystack Service:"
curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "  ⚠️  Haystack service not ready yet"

echo ""
echo "✅ Haystack services are starting!"
echo "🌐 n8n UI: http://localhost:8080/n8n/"
echo "🔍 Elasticsearch: http://localhost:9200"
echo "🤖 Haystack API: http://localhost:8000"
echo "📚 API docs: http://localhost:8000/docs"
echo ""
echo "💡 Services may still be initializing. Check logs with:"
echo "   docker-compose logs -f haystack-service"
echo ""
echo "💡 To stop all services: docker-compose down"