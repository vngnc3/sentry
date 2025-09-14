# Mata Sentry
### DCC agnostic render monitoring dashboard
> Finding the middleground between full-blown render farm architecture and traditional group rendering.

## Preface
While a full-blown render farm solution provides render progress monitoring, often with additional node information,  
more traditional approach like group rendering within an team lacks this hybrid solution.  
Basically, we're looking for a tool that helps us monitor many render nodes in realtime without looking at them one at a time.  

Do keep in mind that I'm building this to be Mata Foundry's internal tool and not a product.

Few rule of thumb in the creation of this tool:  
- No installation needed for each client. A simple python install and dependencies should be sufficient.
- Render progress should be monitored by simply watching the filesystem on the render output directory.
- It should require as few user interaction as possible.

## Architecture
A single server running endpoints to receive data from each render nodes, store it as a JSON file for each node, while providing REST API to be fetched by the front end application. No database. No historical data stored. Everything is assumed to be ephemeral.  
Front end application will be built with web technologies, possibly with HTMX or any other framework we see fit.  

## Security Features
The system now includes authentication using a shared "magic string" secret:

### Server Setup
1. Copy `server/env.example` to `server/.env`
2. Set your `SENTRY_SECRET` value in the `.env` file
3. Optionally configure `SERVER_PORT` (defaults to 3000)

### Client Setup
1. Copy `client/sentry_secret.example` to `client/sentry_secret`
2. Set the `SERVER_HOST` and `SERVER_PORT` to match your server
3. Set the `SENTRY_SECRET` to match the server's secret

The client will automatically include the magic string in all POST requests, and the server will validate it before processing any data submissions.

### Updated Payload Format
The client now sends the following JSON payload:
```json
{
  "hostname": "render-node-01",
  "os": "macOS 15.6.1 arm64",
  "cpu": "cpu-name",
  "gpu": "gpu-name",
  "timestamp": "2025-09-08T02:21:00Z",
  "sentry_secret": "your-magic-string"
}
```

## Progress, I guess?
- [x] python-based daemon for the client. start simple with few information.
- [x] server
- [ ] front end
