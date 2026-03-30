---
title: "Quick Start"
slug: "quick-start"
summary: "Get NetGraphy running locally in under five minutes with Docker Compose."
category: "Getting Started"
tags: [quick-start, installation, docker, setup]
status: published
---

# Quick Start

This guide gets a full NetGraphy development environment running on your machine. You will need Docker, Docker Compose, Python 3.11+, and Node.js 18+ installed.

## Clone the Repository

```bash
git clone https://github.com/netgraphy/netgraphy.git
cd netgraphy
```

## Start Infrastructure Services

Bring up Neo4j, Redis, NATS, and MinIO using Docker Compose:

```bash
docker compose -f infra/compose/docker-compose.yml up -d neo4j redis nats minio
```

Wait for Neo4j to become healthy. You can check with:

```bash
docker compose -f infra/compose/docker-compose.yml ps
```

Neo4j will be available at `http://localhost:7474` (browser) and `bolt://localhost:7687` (driver). The default credentials are `neo4j` / `netgraphy`.

## Install Python Dependencies

Create a virtual environment and install the backend dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Start the API Server

```bash
cd apps/api
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will load all YAML schemas from the `schemas/` directory on startup. You should see log messages indicating each node type and edge type being registered. The API documentation is available at `http://localhost:8000/docs`.

## Install Frontend Dependencies

In a separate terminal:

```bash
cd apps/web
npm install
```

## Start the Frontend

```bash
npm run dev
```

The frontend will be available at `http://localhost:3000`.

## Seed the Database

With the API server running, load the built-in seed data to populate the graph with example devices, locations, interfaces, and connections:

```bash
python -m scripts.seed
```

This creates a representative set of network infrastructure objects and relationships so you can immediately explore the UI, run queries, and test the API without manually entering data.

## Log In

Open `http://localhost:3000` in your browser. Log in with the default credentials:

- **Username:** `admin`
- **Password:** `admin`

You will see the dashboard with summary counts of objects in the graph. From here you can browse the schema-generated list views, open the graph explorer, run queries in the workbench, or open the AI assistant panel.

## Verify the Stack

Confirm everything is working:

- **API health:** `curl http://localhost:8000/health/live`
- **Neo4j browser:** `http://localhost:7474`
- **NATS monitoring:** `http://localhost:8222`
- **MinIO console:** `http://localhost:9001` (credentials: `netgraphy` / `netgraphysecret`)

## Full Docker Compose (Alternative)

If you prefer to run the entire stack in containers instead of running the API and frontend locally:

```bash
docker compose -f infra/compose/docker-compose.yml up -d
```

This builds and starts all services including the API server, web frontend, and Celery worker. Hot reload is supported via volume mounts for both the backend and frontend source directories.

## Next Steps

- [Your First Schema](first-schema.md) -- Define a new object type in YAML.
- [Creating Graph Objects](first-graph-objects.md) -- Add data through the UI and API.
- [Using the AI Assistant](using-the-ai-assistant.md) -- Query your network in natural language.
