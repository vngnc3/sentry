// server.js
import { file } from "bun";
import path from "path";

const DATA_DIR = "./data";

// Ensure data directory exists
await Bun.write(path.join(DATA_DIR, ".gitkeep"), "");

const server = Bun.serve({
  port: 3000,
  async fetch(req) {
    const url = new URL(req.url);
    
    // Hello World endpoint for testing
    if (url.pathname === "/" && req.method === "GET") {
      return new Response("Hello World! Mata Sentry is running.", {
        headers: { "Content-Type": "text/plain" }
      });
    }
    
    // Health check endpoint
    if (url.pathname === "/health" && req.method === "GET") {
      return Response.json({ 
        status: "healthy", 
        timestamp: new Date().toISOString(),
        server: "mata-sentry"
      });
    }
    
    // Data submission endpoint for Python agents
    if (url.pathname === "/submit" && req.method === "POST") {
      try {
        const data = await req.json();
        
        // Validate required fields
        if (!data.hostname) {
          return Response.json(
            { error: "Missing required field: hostname" }, 
            { status: 400 }
          );
        }
        
        // Add server timestamp
        const nodeData = {
          ...data,
          server_received_at: new Date().toISOString()
        };
        
        // Save to individual JSON file per hostname
        const filename = `node_${data.hostname.replace(/[^a-zA-Z0-9-]/g, '_')}.json`;
        const filepath = path.join(DATA_DIR, filename);
        
        await Bun.write(filepath, JSON.stringify(nodeData, null, 2));
        
        console.log(`✅ Data received from ${data.hostname} at ${nodeData.server_received_at}`);
        
        return Response.json({ 
          status: "success", 
          message: "Data stored successfully",
          hostname: data.hostname,
          stored_at: nodeData.server_received_at
        });
        
      } catch (error) {
        console.error("❌ Error processing submission:", error);
        return Response.json(
          { error: "Invalid JSON or server error" }, 
          { status: 500 }
        );
      }
    }
    
    // List all nodes endpoint (useful for debugging)
    if (url.pathname === "/nodes" && req.method === "GET") {
      try {
        const files = await Array.fromAsync(
          new Bun.Glob("node_*.json").scan({ cwd: DATA_DIR })
        );
        
        const nodes = [];
        for (const filename of files) {
          const filepath = path.join(DATA_DIR, filename);
          const content = await file(filepath).text();
          const nodeData = JSON.parse(content);
          nodes.push({
            hostname: nodeData.hostname,
            last_seen: nodeData.server_received_at,
            file: filename
          });
        }
        
        return Response.json({ nodes, count: nodes.length });
        
      } catch (error) {
        console.error("❌ Error listing nodes:", error);
        return Response.json({ error: "Server error" }, { status: 500 });
      }
    }
    
    // 404 for unknown endpoints
    return new Response("Not Found", { status: 404 });
  },
});

console.log(`🚀 Mata Sentry running on http://localhost:${server.port}`);
console.log(`📁 Data stored in: ${DATA_DIR}/`);
console.log(`📡 Submit endpoint: POST http://localhost:${server.port}/submit`);
console.log(`🔍 Nodes list: GET http://localhost:${server.port}/nodes`);

