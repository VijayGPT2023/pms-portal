# NPC PMS Portal - Deployment Guide for IT Department

## Table of Contents
1. [System Overview](#system-overview)
2. [Server Requirements](#server-requirements)
3. [Software Prerequisites](#software-prerequisites)
4. [Installation Steps](#installation-steps)
5. [Database Setup](#database-setup)
6. [Application Configuration](#application-configuration)
7. [Production Deployment](#production-deployment)
8. [Security Considerations](#security-considerations)
9. [Backup & Recovery](#backup--recovery)
10. [Monitoring & Maintenance](#monitoring--maintenance)
11. [Troubleshooting](#troubleshooting)

---

## 1. System Overview

### Technology Stack

| Component | Technology | Version |
|-----------|------------|---------|
| **Backend Framework** | Python FastAPI | 3.11+ |
| **Database** | PostgreSQL | 14+ |
| **Web Server** | Uvicorn (ASGI) | Latest |
| **Reverse Proxy** | Nginx (recommended) | 1.18+ |
| **OS** | Ubuntu Server (recommended) | 22.04 LTS |

### Application Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Load Balancer / Firewall                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (Reverse Proxy)                     │
│                    - SSL Termination                         │
│                    - Static File Serving                     │
│                    - Request Routing                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Uvicorn (ASGI Server)                     │
│                    - FastAPI Application                     │
│                    - Session Management                      │
│                    - Business Logic                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    PostgreSQL Database                       │
│                    - User Data                               │
│                    - Assignments, Revenue Shares             │
│                    - Audit Logs                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Server Requirements

### Minimum Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU** | 2 cores | 4 cores |
| **RAM** | 2 GB | 4-8 GB |
| **Storage** | 20 GB SSD | 50 GB SSD |
| **Network** | 100 Mbps | 1 Gbps |

### Operating System
- **Recommended:** Ubuntu Server 22.04 LTS
- **Alternatives:** CentOS 8+, Debian 11+, Windows Server 2019+

### Network Requirements
- Static IP address
- Open ports: 80 (HTTP), 443 (HTTPS), 22 (SSH for admin)
- Internal port: 5432 (PostgreSQL - internal only)

---

## 3. Software Prerequisites

### Ubuntu/Debian Installation

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Install PostgreSQL 14
sudo apt install -y postgresql postgresql-contrib

# Install Nginx
sudo apt install -y nginx

# Install additional tools
sudo apt install -y git curl htop ufw
```

### Windows Server Installation

1. Download and install Python 3.11 from https://python.org
2. Download and install PostgreSQL 14 from https://postgresql.org
3. Install IIS or use Nginx for Windows

---

## 4. Installation Steps

### Step 1: Create Application User

```bash
# Create dedicated user for the application
sudo useradd -m -s /bin/bash pmsapp
sudo passwd pmsapp

# Add to sudo group (optional, for initial setup)
sudo usermod -aG sudo pmsapp
```

### Step 2: Clone/Copy Application

```bash
# Switch to application user
sudo su - pmsapp

# Create application directory
mkdir -p /home/pmsapp/pms-portal
cd /home/pmsapp/pms-portal

# Option A: Clone from Git repository
git clone https://github.com/VijayGPT2023/pms-portal.git .

# Option B: Copy files from ZIP/transfer
# Upload files to /home/pmsapp/pms-portal/
```

### Step 3: Set Up Python Virtual Environment

```bash
# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

### Step 4: Verify Installation

```bash
# Check installed packages
pip list

# Expected packages:
# - fastapi
# - uvicorn
# - psycopg2-binary
# - python-multipart
# - jinja2
# - python-dotenv
# - openpyxl
```

---

## 5. Database Setup

### Create PostgreSQL Database and User

```bash
# Switch to postgres user
sudo -u postgres psql

# In PostgreSQL shell, run:
CREATE USER pms_user WITH PASSWORD 'YourSecurePassword123!';
CREATE DATABASE pms_db OWNER pms_user;
GRANT ALL PRIVILEGES ON DATABASE pms_db TO pms_user;

# Enable UUID extension (if needed)
\c pms_db
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

# Exit
\q
```

### Configure PostgreSQL for Application Access

```bash
# Edit PostgreSQL configuration
sudo nano /etc/postgresql/14/main/pg_hba.conf

# Add this line (for local connections):
local   pms_db    pms_user                          md5
host    pms_db    pms_user    127.0.0.1/32          md5

# Restart PostgreSQL
sudo systemctl restart postgresql
```

### Test Database Connection

```bash
psql -U pms_user -d pms_db -h localhost
# Enter password when prompted
# If successful, you'll see the psql prompt
\q
```

---

## 6. Application Configuration

### Create Environment File

```bash
cd /home/pmsapp/pms-portal
nano .env
```

### Environment Variables (.env file)

```env
# Database Configuration
DATABASE_URL=postgresql://pms_user:YourSecurePassword123!@localhost:5432/pms_db

# Application Security
SECRET_KEY=generate-a-64-character-random-string-here-use-openssl-rand-hex-32

# Application Settings
APP_ENV=production
DEBUG=false

# Session Configuration
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=lax
```

### Generate Secret Key

```bash
# Generate a secure random secret key
openssl rand -hex 32
# Copy the output and use it as SECRET_KEY
```

### Initialize Database Tables

```bash
# Activate virtual environment
source venv/bin/activate

# Run the application once to create tables
python -c "from app.database import init_db; init_db()"

# Or start the app briefly
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
sleep 5
kill %1
```

---

## 7. Production Deployment

### Option A: Systemd Service (Recommended for Linux)

#### Create Service File

```bash
sudo nano /etc/systemd/system/pms-portal.service
```

#### Service Configuration

```ini
[Unit]
Description=NPC PMS Portal FastAPI Application
After=network.target postgresql.service

[Service]
Type=simple
User=pmsapp
Group=pmsapp
WorkingDirectory=/home/pmsapp/pms-portal
Environment="PATH=/home/pmsapp/pms-portal/venv/bin"
EnvironmentFile=/home/pmsapp/pms-portal/.env
ExecStart=/home/pmsapp/pms-portal/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

#### Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable pms-portal

# Start the service
sudo systemctl start pms-portal

# Check status
sudo systemctl status pms-portal

# View logs
sudo journalctl -u pms-portal -f
```

### Option B: Nginx Reverse Proxy Configuration

#### Create Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/pms-portal
```

#### Nginx Configuration

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com www.your-domain.com;

    # SSL Configuration
    ssl_certificate /etc/ssl/certs/your-domain.crt;
    ssl_certificate_key /etc/ssl/private/your-domain.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Logging
    access_log /var/log/nginx/pms-portal.access.log;
    error_log /var/log/nginx/pms-portal.error.log;

    # Static files
    location /static/ {
        alias /home/pmsapp/pms-portal/app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Proxy to FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # File upload size limit
    client_max_body_size 10M;
}
```

#### Enable Nginx Configuration

```bash
# Create symbolic link
sudo ln -s /etc/nginx/sites-available/pms-portal /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### Option C: SSL Certificate (Let's Encrypt)

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# Auto-renewal is configured automatically
# Test renewal
sudo certbot renew --dry-run
```

---

## 8. Security Considerations

### Firewall Configuration (UFW)

```bash
# Enable UFW
sudo ufw enable

# Allow SSH
sudo ufw allow 22/tcp

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Deny PostgreSQL from external access
sudo ufw deny 5432/tcp

# Check status
sudo ufw status verbose
```

### PostgreSQL Security

```bash
# Edit postgresql.conf
sudo nano /etc/postgresql/14/main/postgresql.conf

# Set these values:
listen_addresses = 'localhost'  # Only local connections
password_encryption = scram-sha-256
```

### Application Security Checklist

- [ ] Change default admin password immediately after deployment
- [ ] Use strong DATABASE_URL password (min 16 characters, mixed case, numbers, symbols)
- [ ] Generate unique SECRET_KEY for each deployment
- [ ] Enable HTTPS with valid SSL certificate
- [ ] Configure firewall to restrict access
- [ ] Disable DEBUG mode in production
- [ ] Set up regular security updates

---

## 9. Backup & Recovery

### Database Backup Script

```bash
# Create backup script
sudo nano /home/pmsapp/scripts/backup_db.sh
```

```bash
#!/bin/bash
# Database Backup Script

# Configuration
BACKUP_DIR="/home/pmsapp/backups"
DB_NAME="pms_db"
DB_USER="pms_user"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create backup directory
mkdir -p $BACKUP_DIR

# Create backup
PGPASSWORD="YourSecurePassword123!" pg_dump -U $DB_USER -h localhost $DB_NAME | gzip > "$BACKUP_DIR/pms_backup_$DATE.sql.gz"

# Delete old backups
find $BACKUP_DIR -name "pms_backup_*.sql.gz" -mtime +$RETENTION_DAYS -delete

# Log
echo "Backup completed: pms_backup_$DATE.sql.gz"
```

```bash
# Make executable
chmod +x /home/pmsapp/scripts/backup_db.sh

# Add to crontab for daily backups at 2 AM
crontab -e
# Add line:
0 2 * * * /home/pmsapp/scripts/backup_db.sh >> /var/log/pms_backup.log 2>&1
```

### Restore Database

```bash
# Restore from backup
gunzip -c /home/pmsapp/backups/pms_backup_YYYYMMDD_HHMMSS.sql.gz | psql -U pms_user -d pms_db
```

---

## 10. Monitoring & Maintenance

### Application Logs

```bash
# View application logs
sudo journalctl -u pms-portal -f

# View last 100 lines
sudo journalctl -u pms-portal -n 100

# View Nginx access logs
sudo tail -f /var/log/nginx/pms-portal.access.log

# View Nginx error logs
sudo tail -f /var/log/nginx/pms-portal.error.log
```

### Health Check Endpoint

The application provides a health check at:
```
GET /health
```

### Monitoring Script

```bash
# Create monitoring script
sudo nano /home/pmsapp/scripts/monitor.sh
```

```bash
#!/bin/bash
# Simple monitoring script

# Check if application is running
if ! systemctl is-active --quiet pms-portal; then
    echo "PMS Portal is DOWN! Restarting..."
    sudo systemctl restart pms-portal
    # Send alert (configure email/SMS)
fi

# Check disk space
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "Warning: Disk usage is ${DISK_USAGE}%"
fi
```

### Update Application

```bash
# Stop service
sudo systemctl stop pms-portal

# Backup current version
cp -r /home/pmsapp/pms-portal /home/pmsapp/pms-portal-backup

# Pull updates (if using Git)
cd /home/pmsapp/pms-portal
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Run database migrations (if any)
# python -m alembic upgrade head

# Start service
sudo systemctl start pms-portal
```

---

## 11. Troubleshooting

### Common Issues

#### Application Won't Start

```bash
# Check service status
sudo systemctl status pms-portal

# Check logs
sudo journalctl -u pms-portal -n 50

# Common fixes:
# 1. Check .env file exists and has correct values
# 2. Verify database connection
# 3. Check file permissions
```

#### Database Connection Error

```bash
# Test database connection
psql -U pms_user -d pms_db -h localhost

# Check PostgreSQL status
sudo systemctl status postgresql

# Check PostgreSQL logs
sudo tail -f /var/log/postgresql/postgresql-14-main.log
```

#### Permission Errors

```bash
# Fix ownership
sudo chown -R pmsapp:pmsapp /home/pmsapp/pms-portal

# Fix permissions
chmod 755 /home/pmsapp/pms-portal
chmod 600 /home/pmsapp/pms-portal/.env
```

#### Port Already in Use

```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill process
sudo kill -9 <PID>
```

### Support Contacts

- **Application Issues:** [Developer Contact]
- **Infrastructure Issues:** [IT Support]
- **Database Issues:** [DBA Contact]

---

## Quick Reference Commands

```bash
# Start application
sudo systemctl start pms-portal

# Stop application
sudo systemctl stop pms-portal

# Restart application
sudo systemctl restart pms-portal

# View logs
sudo journalctl -u pms-portal -f

# Check status
sudo systemctl status pms-portal

# Backup database
/home/pmsapp/scripts/backup_db.sh

# Test Nginx config
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

---

## Document Information

- **Version:** 1.0
- **Last Updated:** January 2026
- **Author:** Development Team
- **Application Version:** PMS Portal v2.0
