#!/bin/bash
set -e

echo "🚀 Starting MailCleaner with Local AI..."

# Start Ollama server in the background
echo "📦 Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "⏳ Waiting for Ollama to be ready..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
        echo "✅ Ollama is ready!"
        break
    fi
    sleep 1
done

# Pull the model if not already present
echo "🔍 Checking for qwen2.5:3b model..."
if ! ollama list | grep -q "qwen2.5:3b"; then
    echo "📥 Downloading qwen2.5:3b model (first run only, ~2GB)..."
    ollama pull qwen2.5:3b
    echo "✅ Model downloaded!"
else
    echo "✅ Model already present!"
fi

# Start the Flask application
echo "🌐 Starting MailCleaner web app..."
exec python execution/run.py
