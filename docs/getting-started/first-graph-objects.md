---
title: "Creating Graph Objects"
slug: "first-graph-objects"
summary: "Create your first devices, locations, and relationships through the UI and API."
category: "Getting Started"
tags: [getting-started, objects, api, ui, relationships]
status: published
---

# Creating Graph Objects

Once the platform is running and the schema is loaded, you can start creating nodes and edges. This guide walks through creating a device, a location, and connecting them with a relationship using both the web UI and the REST API.

## Creating Objects in the UI

### Create a Location

Navigate to **Locations** in the sidebar. Click **Create**. Fill in the form:

- **Name:** `dc-east-01`
- **Location Type:** `site`
- **Status:** `active`
- **City:** `Ashburn`
- **State:** `VA`
- **Country:** `US`

Click **Save**. The location now exists as a node in the graph.

### Create a Device

Navigate to **Devices** in the sidebar. Click **Create**. Fill in the form:

- **Hostname:** `core-rtr-01.dc-east-01`
- **Status:** `active`
- **Role:** `router`
- **Management IP:** `10.0.1.1`

Click **Save**. The device is created as a node.

### Connect Them

Open the device detail page for `core-rtr-01.dc-east-01`. In the relationships panel, click **Add Relationship**. Select the relationship type `LOCATED_IN`, then search for and select the `dc-east-01` location. Optionally set the `rack_position` to `22` and `rack_face` to `front`. Click **Save**.

The device is now connected to the location via a `LOCATED_IN` edge. This relationship is visible on both the device detail page and the location detail page, and it appears immediately in the graph explorer.

## Creating Objects via the API

Every operation available in the UI is also available through the REST API. The base URL for all endpoints is `http://localhost:8000/api/v1`.

### Create a Location

```bash
curl -X POST http://localhost:8000/api/v1/locations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{
    "name": "dc-west-01",
    "location_type": "site",
    "status": "active",
    "city": "San Jose",
    "state": "CA",
    "country": "US"
  }'
```

The response includes the created node's `id`, all properties, and timestamps from the lifecycle mixin.

### Create a Device

```bash
curl -X POST http://localhost:8000/api/v1/devices \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{
    "hostname": "dist-sw-01.dc-west-01",
    "status": "active",
    "role": "switch",
    "management_ip": "10.1.1.1"
  }'
```

### Create the Relationship

To connect the device to the location with a `LOCATED_IN` edge:

```bash
curl -X POST http://localhost:8000/api/v1/relationships \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{
    "edge_type": "LOCATED_IN",
    "source_type": "Device",
    "source_id": "<device-id>",
    "target_type": "Location",
    "target_id": "<location-id>",
    "properties": {
      "rack_position": 15,
      "rack_face": "front"
    }
  }'
```

Replace `<device-id>` and `<location-id>` with the IDs returned from the creation responses.

### Query the Results

List all devices at a specific location using a relationship filter:

```bash
curl "http://localhost:8000/api/v1/devices?located_in.name=dc-west-01" \
  -H "Authorization: Bearer <your-token>"
```

This traverses the `LOCATED_IN` edge in the graph to filter devices by their location's name -- a query that would require a join in a relational system but is a native traversal here.

## What Happens in the Graph

Each object you create becomes a labeled node in Neo4j with properties matching the schema's attribute definitions. Each relationship becomes a typed, directed edge. The cardinality constraints defined in the edge schema (for example, `many_to_one` for `LOCATED_IN`) are enforced by the application layer at write time. If you try to assign a device to two locations simultaneously, the platform will reject the second assignment.

## Next Steps

- [Using the AI Assistant](using-the-ai-assistant.md) -- Ask the assistant about the objects you just created.
- [Your First Schema](first-schema.md) -- Define your own custom node types.
