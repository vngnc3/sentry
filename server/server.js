// server.js
import { file } from "bun";
import path from "path";
import { networkInterfaces } from "os";

const DATA_DIR = "./data";

// Load environment variables
const SENTRY_SECRET = process.env.SENTRY_SECRET || "default-secret-change-me";
const SERVER_PORT = process.env.SERVER_PORT || 3000;

// Track hostname status for rolling display
const hostnameStatus = new Map();
const HOSTNAME_TIMEOUT = 5 * 60 * 1000; // 5 minutes timeout for inactive hostnames

// Ensure data directory exists
await Bun.write(path.join(DATA_DIR, ".gitkeep"), "");

// Function to get network IP addresses
function getNetworkIPs() {
  const interfaces = networkInterfaces();
  const ips = [];
  
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
      // Skip internal (loopback) and non-IPv4 addresses
      if (iface.family === 'IPv4' && !iface.internal) {
        ips.push(iface.address);
      }
    }
  }
  
  return ips;
}

// Function to update hostname status and redraw the display
function updateHostnameStatus(hostname, timestamp) {
  // Update the hostname status
  hostnameStatus.set(hostname, {
    lastUpdate: timestamp,
    status: 'online'
  });
  
  // Clean up inactive hostnames (older than timeout)
  const now = new Date();
  for (const [host, data] of hostnameStatus.entries()) {
    if (now - new Date(data.lastUpdate) > HOSTNAME_TIMEOUT) {
      hostnameStatus.delete(host);
    }
  }
  
  // Clear the console and redraw the status
  console.clear();
  
  // Redraw server info
  console.log(`🚀 Mata Sentry Server running on:`);
  console.log(`   Local:   http://localhost:${SERVER_PORT}`);
  const networkIPs = getNetworkIPs();
  if (networkIPs.length > 0) {
    networkIPs.forEach(ip => {
      console.log(`   Network: http://${ip}:${SERVER_PORT}`);
    });
  } else {
    console.log(`   Network: No network interfaces found`);
  }
  console.log(`📁 Data stored in: ${DATA_DIR}/`);
  console.log(`📡 Submit endpoint: POST http://localhost:${SERVER_PORT}/submit`);
  console.log(`🔍 Nodes list: GET http://localhost:${SERVER_PORT}/nodes`);
  console.log(''); // Empty line
  
  // Display active hostnames
  if (hostnameStatus.size > 0) {
    console.log('📊 Active Hostnames:');
    for (const [hostname, data] of hostnameStatus.entries()) {
      const timeAgo = Math.floor((now - new Date(data.lastUpdate)) / 1000);
      const statusIcon = data.status === 'online' ? '🟢' : '🔴';
      console.log(`   ${statusIcon} ${hostname} (${timeAgo}s ago)`);
    }
  } else {
    console.log('📊 No active hostnames');
  }
}

const server = Bun.serve({
  hostname: "0.0.0.0", // Allow access from other devices
  port: SERVER_PORT,
  async fetch(req) {
    const url = new URL(req.url);
    
    // Hello World endpoint for testing
    if (url.pathname === "/" && req.method === "GET") {
      return new Response("Hello World! Mata Sentry Server is running.", {
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
        
        // Validate magic string authentication
        if (!data.sentry_secret || data.sentry_secret !== SENTRY_SECRET) {
          return Response.json(
            { error: "Invalid or missing sentry_secret" }, 
            { status: 401 }
          );
        }
        
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
        
        // Update the rolling display instead of logging each submission
        updateHostnameStatus(data.hostname, nodeData.server_received_at);
        
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
    
    // List all nodes endpoint with full data
    if (url.pathname === "/nodes" && req.method === "GET") {
      try {
        const files = await Array.fromAsync(
          new Bun.Glob("node_*.json").scan({ cwd: DATA_DIR })
        );
        
        const nodes = [];
        const now = new Date();
        const twoMinutesAgo = new Date(now.getTime() - 2 * 60 * 1000); // 2 minutes ago
        
        for (const filename of files) {
          const filepath = path.join(DATA_DIR, filename);
          const content = await file(filepath).text();
          const nodeData = JSON.parse(content);
          
          // Check if node is online (timestamp within 2 minutes)
          let isOnline = false;
          if (nodeData.timestamp) {
            const timestampDate = new Date(nodeData.timestamp);
            isOnline = timestampDate > twoMinutesAgo;
          }
          
          // Add is_online field to the data and remove sensitive fields
          const { sentry_secret, ...nodeDataWithoutSecret } = nodeData;
          const nodeDataWithOnlineStatus = {
            ...nodeDataWithoutSecret,
            is_online: isOnline
          };
          
          // Include all the stored data for each node
          nodes.push({
            filename: filename,
            data: nodeDataWithOnlineStatus
          });
        }
        
        return Response.json({ 
          nodes, 
          count: nodes.length,
          retrieved_at: new Date().toISOString()
        });
        
      } catch (error) {
        console.error("❌ Error listing nodes:", error);
        return Response.json({ error: "Server error" }, { status: 500 });
      }
    }
    
    // 404 for unknown endpoints
    return new Response("Not Found", { status: 404 });
  },
});

// Initialize the display
updateHostnameStatus('server', new Date().toISOString());

// Set up periodic cleanup of inactive hostnames (every minute)
setInterval(() => {
  const now = new Date();
  let hasChanges = false;
  
  for (const [host, data] of hostnameStatus.entries()) {
    if (now - new Date(data.lastUpdate) > HOSTNAME_TIMEOUT) {
      hostnameStatus.delete(host);
      hasChanges = true;
    }
  }
  
  // Only redraw if there were changes
  if (hasChanges) {
    updateHostnameStatus('server', new Date().toISOString());
  }
}, 60000); // Run every minute