# Aletheia Setup Notes

## Setup Completed on September 23, 2025

### Configuration Changes Made

1. **Environment Setup**
   - Ran `./dev setup` to generate secure .env file
   - Added Anthropic API key for AI services

2. **Database Password Fix**
   - Updated database password to remove special characters that were causing authentication issues
   - Changed from password with `^` characters to alphanumeric password
   - Updated both DB_PASSWORD and N8N_ENCRYPTION_KEY in .env file

3. **Services Started Successfully**
   - All Docker services are running
   - Database initialized with 485 court documents
   - Demo users created and verified

### Access Points

- **Main Application**: http://localhost:8080
- **n8n Workflows**: http://localhost:8100 (no login required)
- **Lawyer Chat**: http://localhost:8080/chat
- **AI Portal**: http://localhost:8102
- **Court Processor**: http://localhost:8104

### Demo Credentials

**Demo User:**
- Email: demo@reichmanjorgensen.com
- Password: demo123

**Admin User:**
- Email: admin@reichmanjorgensen.com
- Password: admin123

### Important Notes

- The .env file contains sensitive credentials and is gitignored for security
- Docker Desktop must be running for services to work
- Minimum 8GB RAM recommended (16GB optimal)
- All required ports (8080, 8100, 8102, 8104, 8200, 8201) must be available

### Repository Updated

- Remote origin updated to: https://github.com/manesha63/Aletheia-v0.1