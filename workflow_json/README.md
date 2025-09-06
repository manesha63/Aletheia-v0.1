# Workflow Templates

This directory contains n8n workflow templates that can be manually imported.

## Why Manual Import?

The workflows have been moved to manual import to avoid issues with:
- Corrupted workflow JSON files
- Missing custom node dependencies
- Automatic activation failures

## How to Import Workflows

After starting the services with `./dev up`:

1. Access n8n at http://localhost:8100
2. Login with: velvetmoon222999@gmail.com / admin123
3. Create a new workflow manually or import from templates
4. Configure credentials as needed

## Available Templates

Currently no templates are provided. Workflows should be created fresh in the n8n UI.

## Creating a Basic Webhook Workflow

1. Add a Webhook node
2. Set the path to: `c188c31c-1c45-4118-9ece-5b6057ab5177`
3. Add any additional nodes as needed
4. Save and activate the workflow