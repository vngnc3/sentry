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

## Progress, I guess?
[ ] python-based daemon for the client. start simple with few information.
[ ] server
[ ] front end
