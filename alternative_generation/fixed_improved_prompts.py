"""
改进的prompt模板 - 明确指定输出格式以简化后续重构
"""

def create_structured_frontend_prompt(instruction: str, tech_stack: str = "React", api_documentation: str = None) -> str:
    """Create frontend code generation prompt with structured output format"""
    
    api_doc_section = ""
    if api_documentation:
        api_doc_section = f"""
API DOCUMENTATION:
This is the API documentation that the frontend should interact with. Ensure all API calls match these specifications.
---
{api_documentation}
---
"""

    return f"""You are a professional frontend developer. Generate complete frontend code based on the following requirements:

Requirements: {instruction}
{api_doc_section}
REQUIREMENTS:
1. Generate complete frontend project with proper file structure
2. Include all necessary files: package.json, HTML, JSX components, CSS files
3. Use EXACTLY the format "// FILE: filepath" separators between files
4. NO explanations, NO markdown code blocks, NO extra text - only file contents
5. Each file content must be complete and runnable
6. Modern React patterns with hooks (useState, useEffect, useCallback)
7. Responsive design with mobile-first approach
8. Comprehensive error handling and loading states
9. Use functional components with proper prop validation
10. ALL API calls must use http://localhost:5001/api as the base URL
11. Configure API endpoints with proper /api prefix (e.g., /api/users, /api/products)
12. Implement proper form validation and user feedback
13. Add accessibility attributes (ARIA labels, semantic HTML)
14. Use modern CSS features (Flexbox, Grid, CSS variables)
15. Include TypeScript interfaces if using TypeScript
16. Add proper cleanup for useEffect hooks to prevent memory leaks
17. Implement debouncing for search/input fields where appropriate
18. Use consistent naming conventions and component structure
19. Include loading skeletons or spinners for better UX
20. Add proper HTTP status code handling in API calls
21. Ensure all interactive elements have proper focus states
22. ALL packages/libraries used in the code MUST be included in package.json dependencies with correct versions

IMPORTANT OUTPUT FORMAT:
Please output ONLY the code files in the following EXACT format. Each file must be separated by a comment line starting with "// FILE:" followed by the file path:

// FILE: package.json
{{
  "name": "project-frontend",
  "version": "1.0.0",
  ...
}}

// FILE: public/index.html
<!DOCTYPE html>
<html>
...
</html>

// FILE: src/index.js
import React from 'react';
...

// FILE: src/App.jsx
import React from 'react';
...

// FILE: src/components/ComponentName.jsx
import React from 'react';
...

// FILE: src/styles/App.css
/* Main styles */
...


OUTPUT FORMAT:
Start directly with the first file using "// FILE: filepath" format.
No introduction, no explanations, no markdown formatting.
Each file should be production-ready code.

Generate the complete project now:"""

def create_structured_backend_prompt(instruction: str, tech_stack: str = "Node.js", api_documentation: str = None) -> str:
    """Create backend code generation prompt with structured output format (no database)"""
    
    api_doc_section = ""
    if api_documentation:
        api_doc_section = f"""
API DOCUMENTATION:
This is the API documentation that the backend should implement. Ensure all API endpoints, request/response formats, and logic match these specifications.
---
{api_documentation}
---
"""

    return f"""Generate complete backend code following these exact specifications:

Requirements: {instruction}
Tech Stack: {tech_stack}
{api_doc_section}
CRITICAL: Use ONLY IN-MEMORY DATA STORAGE. No external databases, no persistent storage.

REQUIREMENTS:
1. Generate complete backend project with proper file structure
2. NO DATABASE DEPENDENCIES - use in-memory mock data only
3. Include: package.json, app.js, mock data, routes, controllers, middleware
4. Use EXACTLY the format "// FILE: filepath" separators between files
5. NO explanations, NO markdown code blocks, NO extra text - only file contents
6. Each file content must be complete and runnable
7. RESTful API design with full CRUD operations using mock data
8. Comprehensive error handling and input validation
9. CORS support for frontend integration
10. Use simple data structures like arrays and objects
11. NO mongoose, NO database connections, NO external data services
12. Server MUST run on port 5001
13. ALL API routes MUST be prefixed with '/api' (e.g., '/api/users', '/api/products')
14. Implement proper API versioning and route structure
15. Base URL structure: http://localhost:5001/api/{{'resource'}}
16. ALL packages/libraries used in the code MUST be included in package.json with correct versions
17. Include proper middleware for security, logging, and request parsing
18. Implement consistent API response format with proper HTTP status codes
19. Add request validation and sanitization
20. Include proper error handling middleware

IMPORTANT OUTPUT FORMAT:
Output ONLY the code files in this EXACT format. Each file must be separated by a comment line starting with "// FILE:" followed by the file path:

// FILE: package.json
{{
  "name": "project-backend",
  "version": "1.0.0",
  "description": "Backend API server with mock data",
  "main": "app.js",
  "scripts": {{
    "start": "node app.js",
    "dev": "nodemon app.js"
  }},
  "dependencies": {{
    "express": "^4.18.2",
    "cors": "^2.8.5",
    "dotenv": "^16.0.3",
    "body-parser": "^1.20.2",
    "helmet": "^6.0.1",
    "morgan": "^1.10.0"
  }},
  "devDependencies": {{
    "nodemon": "^2.0.20"
  }}
}}

// FILE: .env
PORT=5000
NODE_ENV=development

// FILE: app.js
const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const helmet = require('helmet');
const morgan = require('morgan');
require('dotenv').config();

const app = express();

// Middleware
app.use(helmet());
app.use(morgan('combined'));
app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({{ extended: true }}));

// Routes
// [Import and use your routes here]

// Error handling middleware
app.use((err, req, res, next) => {{
  console.error(err.stack);
  res.status(500).json({{ error: 'Something went wrong!' }});
}});

// 404 handler
app.use('*', (req, res) => {{
  res.status(404).json({{ error: 'Route not found' }});
}});

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {{
  console.log(`Server running on port ${{PORT}}`);
}});

// FILE: data/mockData.js
// In-memory mock data storage
let mockDataStore = {{
  // Define your mock data collections here
}};

// Helper functions for mock data operations
const mockDataHelpers = {{
  generateId: () => Date.now().toString(),
  findById: (collection, id) => collection.find(item => item.id === id),
  findByProperty: (collection, property, value) => collection.filter(item => item[property] === value),
  updateById: (collection, id, updates) => {{
    const index = collection.findIndex(item => item.id === id);
    if (index !== -1) {{
      collection[index] = {{ ...collection[index], ...updates }};
      return collection[index];
    }}
    return null;
  }},
  deleteById: (collection, id) => {{
    const index = collection.findIndex(item => item.id === id);
    if (index !== -1) {{
      return collection.splice(index, 1)[0];
    }}
    return null;
  }}
}};

module.exports = {{ mockDataStore, mockDataHelpers }};

// FILE: routes/[routeName].js
const express = require('express');
const router = express.Router();
const controller = require('../controllers/[controllerName]');

// Define your routes here with proper HTTP methods
// Example: router.get('/', controller.getAll);

module.exports = router;

// FILE: controllers/[controllerName].js
const {{ mockDataStore, mockDataHelpers }} = require('../data/mockData');

// Controller functions using mock data
const controller = {{
  getAll: (req, res) => {{
    try {{
      // Implementation using mockDataStore
      res.json({{ success: true, data: [] }});
    }} catch (error) {{
      res.status(500).json({{ success: false, error: error.message }});
    }}
  }},
  
  getById: (req, res) => {{
    try {{
      const {{ id }} = req.params;
      // Implementation using mockDataHelpers
      res.json({{ success: true, data: {{}} }});
    }} catch (error) {{
      res.status(404).json({{ success: false, error: 'Not found' }});
    }}
  }},
  
  create: (req, res) => {{
    try {{
      // Implementation for creating new records
      res.status(201).json({{ success: true, data: {{}} }});
    }} catch (error) {{
      res.status(400).json({{ success: false, error: error.message }});
    }}
  }},
  
  update: (req, res) => {{
    try {{
      // Implementation for updating records
      res.json({{ success: true, data: {{}} }});
    }} catch (error) {{
      res.status(400).json({{ success: false, error: error.message }});
    }}
  }},
  
  delete: (req, res) => {{
    try {{
      // Implementation for deleting records
      res.json({{ success: true, message: 'Deleted successfully' }});
    }} catch (error) {{
      res.status(400).json({{ success: false, error: error.message }});
    }}
  }}
}};

module.exports = controller;

// FILE: middleware/validation.js
// Input validation middleware
const validateInput = (schema) => {{
  return (req, res, next) => {{
    // Implement validation logic
    next();
  }};
}};

module.exports = {{ validateInput }};

OUTPUT FORMAT:
Start directly with the first file using "// FILE: filepath" format.
No introduction, no explanations, no markdown formatting.
Each file should be production-ready code.

Generate the complete project now:"""

def create_structured_database_prompt(instruction: str, db_type: str = "MongoDB") -> str:
    """Create database design prompt with structured output format"""
    return f"""You are a professional database architect. Design a complete database based on the following requirements:

Requirements: {instruction}

Database Type: {db_type}

IMPORTANT OUTPUT FORMAT:
Please output ONLY the database files in the following EXACT format. Each file must be separated by a comment line starting with "// FILE:" followed by the file path:

// FILE: database/init.js
// Database initialization script
const mongoose = require('mongoose');
...

// FILE: database/schemas.js
// Database schemas and models
const mongoose = require('mongoose');
...

// FILE: database/seeds.js
// Sample data for development
const ModelName = require('../models/ModelName');
...

// FILE: database/migrations.js
// Database migration scripts
...

REQUIREMENTS:
1. Generate complete database design with initialization scripts
2. Include schemas, seed data, and migration scripts
3. Use EXACTLY the format above with "// FILE: filepath" separators
4. NO explanations, NO markdown code blocks, NO extra text
5. Each file content should be complete and runnable
6. Proper indexing and relationships
7. Sample data for testing

Generate the complete database design now:"""

def create_structured_deployment_prompt(instruction: str, platform: str = "Docker") -> str:
    """Create deployment configuration prompt with structured output format"""
    return f"""You are a professional DevOps engineer. Generate complete deployment configuration based on the following project requirements:

Project Description: {instruction}

Deployment Platform: {platform}

IMPORTANT OUTPUT FORMAT:
Please output ONLY the configuration files in the following EXACT format. Each file must be separated by a comment line starting with "// FILE:" followed by the file path:

// FILE: Dockerfile.frontend
FROM node:18-alpine
...

// FILE: Dockerfile.backend
FROM node:18-alpine
...

// FILE: docker-compose.yml
version: '3.8'
services:
...

// FILE: .env.production
NODE_ENV=production
...

// FILE: nginx.conf
server {{
...
}}

REQUIREMENTS:
1. Generate complete deployment configuration
2. Include Dockerfiles, docker-compose, environment configs
3. Use EXACTLY the format above with "// FILE: filepath" separators
4. NO explanations, NO markdown code blocks, NO extra text
5. Each file content should be complete and deployable
6. Multi-stage builds for optimization
7. Environment-specific configurations

Generate the complete deployment configuration now:"""
