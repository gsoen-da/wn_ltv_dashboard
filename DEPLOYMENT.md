# Deployment Guide - Customer Segmentation & LTV Dashboard

## Option 1: Streamlit Cloud (Simplest, ~$7/month)

1. **Push code to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git push origin main
   ```

2. **Sign up at [streamlit.io/cloud](https://streamlit.io/cloud)**

3. **Deploy**
   - Click "New app"
   - Select your GitHub repo
   - Choose `dashboard.py` as main file
   - Click Deploy

4. **Make it private**
   - Share link only with team members
   - Or upgrade to paid tier for access controls

---

## Option 2: Docker on Internal Server (Full Control)

### Prerequisites
- Docker installed on server
- Server accessible to team (via VPN or internal network)
- Excel data files in `reports/` folder

### Build & Run

```bash
# Build image
docker build -t subscription-dashboard .

# Run container
docker run -d \
  -p 8501:8501 \
  -v /path/to/reports:/app/reports \
  --name dashboard \
  subscription-dashboard
```

Access at: `http://server-ip:8501`

### With Docker Compose (Recommended)

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  dashboard:
    build: .
    ports:
      - "8501:8501"
    volumes:
      - ./reports:/app/reports
      - ./data:/app/data
    environment:
      - STREAMLIT_SERVER_HEADLESS=true
    restart: unless-stopped
```

Then run:
```bash
docker-compose up -d
```

### Update Data Regularly
```bash
# Regenerate customer_segmentation.xlsx
docker exec dashboard python customer_segmentation.py

# Or mount the Excel file and update it externally
# then Streamlit auto-reloads
```

---

## Option 3: AWS/Azure/GCP (Scalable)

### AWS Lightsail (Easy)
1. Create Ubuntu instance
2. SSH in and install Docker
3. Follow Docker instructions above
4. Restrict security group to company IP ranges

### Azure Container Instances
```bash
az container create \
  --resource-group mygroup \
  --name dashboard \
  --image myregistry.azurecr.io/dashboard:latest \
  --ports 8501 \
  --environment-variables STREAMLIT_SERVER_HEADLESS=true
```

### GCP Cloud Run
- Push to Artifact Registry
- Deploy via Cloud Run
- Set IAM policies to restrict access

---

## Option 4: Simple Server (DIY)

Run on any company Linux server with Python:

```bash
# Install dependencies
pip install -r requirements.txt

# Run in background with nohup
nohup python -m streamlit run dashboard.py \
  --server.port=8501 \
  --server.address=0.0.0.0 &

# Or use systemd service (see below)
```

### Systemd Service (Optional)
Create `/etc/systemd/system/dashboard.service`:
```ini
[Unit]
Description=Subscription Dashboard
After=network.target

[Service]
Type=simple
User=dashboard
WorkingDirectory=/home/dashboard/app
ExecStart=/usr/bin/python3 -m streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable dashboard
sudo systemctl start dashboard
```

---

## Security Considerations

### Network Access
- **On Internal Network:** Firewall to company IPs only
- **Via VPN:** Accessible only when connected to company VPN
- **Basic Auth:** Add Streamlit password protection

### Data Protection
- Run on company infrastructure (not public cloud)
- Restrict to read-only for sensitive data
- Use HTTPS reverse proxy (nginx)

### Basic Auth with Nginx Reverse Proxy
```nginx
server {
    listen 443 ssl;
    server_name dashboard.company.internal;

    auth_basic "Restricted Area";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://localhost:8501;
        proxy_set_header Host $host;
    }
}
```

---

## Updating Data

### Option A: Manual
```bash
# SSH to server
ssh user@dashboard-server

# Regenerate report
python customer_segmentation.py

# Streamlit auto-reloads
```

### Option B: Scheduled (Cron)
```bash
# Add to crontab (weekly refresh)
0 2 * * 0 cd /home/dashboard/app && python customer_segmentation.py
```

### Option C: Git Auto-Deploy
- Push code changes to main branch
- Server polls GitHub and auto-deploys with webhook

---

## Recommendation for Your Organization

| Size | Recommendation | Cost | Effort |
|------|---|---|---|
| **Small (<10 users)** | Streamlit Cloud paid | $7/mo | Minimal |
| **Medium (10-50)** | Docker on AWS Lightsail | $5-10/mo | 1-2 hours |
| **Large (50+)** | Docker on internal server + Nginx | Free | 2-4 hours |
| **Very sensitive data** | On-premises Docker | Free | 2-4 hours |

---

## Questions?

- **Docker issues?** Check logs: `docker logs dashboard`
- **Can't access?** Check firewall, VPN, server IP
- **Data stale?** Regenerate with `python customer_segmentation.py`
