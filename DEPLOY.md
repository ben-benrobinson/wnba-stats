# EC2 Deployment

## Instance setup

1. Launch an **EC2 t3.micro** (Amazon Linux 2023 or Ubuntu 22.04), open port 80 (HTTP) and 22 (SSH) in the security group.

2. SSH in and install dependencies:

```bash
sudo dnf install -y git python3.11 python3.11-pip nginx   # Amazon Linux 2023
# or: sudo apt install -y git python3.11 python3.11-pip nginx  # Ubuntu
```

3. Clone the repo:

```bash
cd /home/ec2-user
git clone https://github.com/ben-benrobinson/wnba-stats.git
cd wnba-stats
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

4. Seed initial data:

```bash
python -m scripts.bootstrap
```

## Running with Gunicorn

```bash
# Test it works
gunicorn -b 0.0.0.0:8050 dashboard.app:server

# Run as a background service
sudo tee /etc/systemd/system/wnba.service > /dev/null <<EOF
[Unit]
Description=WNBA Stats Dashboard
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/wnba-stats
ExecStart=/home/ec2-user/wnba-stats/venv/bin/gunicorn -b 127.0.0.1:8050 -w 2 dashboard.app:server
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable wnba
sudo systemctl start wnba
```

## Nginx reverse proxy (port 80 → 8050)

```bash
sudo tee /etc/nginx/conf.d/wnba.conf > /dev/null <<EOF
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:8050;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

sudo systemctl enable nginx
sudo systemctl restart nginx
```

## Nightly cron job (2am ET)

```bash
crontab -e
# Add this line:
0 2 * * * cd /home/ec2-user/wnba-stats && /home/ec2-user/wnba-stats/venv/bin/python -m scripts.nightly >> /var/log/wnba-nightly.log 2>&1
```

## Updating the app

```bash
cd /home/ec2-user/wnba-stats
git pull
sudo systemctl restart wnba
```
