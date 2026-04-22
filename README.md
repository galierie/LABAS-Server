# PULLING REPOSITORY

We could simply pull from the server repository. You might need to restart `fastapi` so that the service gets updated as well.
```bash
git pull
sudo systemctl restart fastapi
```

# Local Setup Notes

## Cloning the Server-side Repository Locally

The server-side code simply live in your user directory (ex. `/home/shiro/LABAS-Server`)
```bash 
git clone https://github.com/SHIROKAMIQQ/LABAS-Server.git
cd LABAS-Server
```

## Certificates and MOSIP Wireguard Setup
Put the certificates into your server folder, preferrably in `LABAS-Server/certs`. Rememeber to configure `config.toml` properly.

You would also need to install Wireguard and then paste the given wireguard configuration as a tunnel. You would need this VPN activated whenever you will be using MOSIP's KYC.

## .env Setup
You need to copy `.env.sample` into `.env`.
- Make sure `CONFIG_TOML` is the path of config.toml on your machine.
- Make sure `DATABASE_URL` is has the correct USER-PASSWORD pair in the URL.
```bash
cp .env.sample .env
``` 

## Installing Requirements

Create a virtual environment in `LABAS-Server` and then install the required packages there.
```bash
python3 -m venv venv
source venv/bin/activate
pip install requirements -r requirements.txt
```

## Running the server locally

Be sure to be using your `venv`. Then we could use uvicorn to run FastAPI locally.
```bash
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```
You may now access APIs at `http://127.0.0.1:8000`. For example, `http://127.0.0.1:8000/scan`.


# Server Setup Notes

## Cloning the Server-side Repository

The server-side code will primarily live on `/opt/LABAS-Server`.

We could simply clone the repository from GitHub
```bash
sudo git clone https://github.com/SHIROKAMIQQ/LABAS-Server.git
cd LABAS-Server
```

## Permissions

We want all our users to have permissions for `/opt/LABAS-Server`. So, we create a group containing all our users, and then give permissions. \
This allows us to quickly edit the source code via VSCode if needed. (We could still use `sudo nano` without these permissions though)
We also want a system user `fastapi` so that we won't run the service via root (for security purposes). \
```bash
sudo groupadd labas
sudo usermod -aG labas migz
# sudo usermod -aG for all other users

sudo useradd -r -s /bin/false fastapi
sudo usermod -aG labas fastapi

sudo chown -R :labas /opt/LABAS-Server
sudo chmod -R 775 /opt/LABAS-Server
```

Then, for each account, we want to let them use git without needing to sudo. Run this in each account:
```bash
git config --global --add safe.directory /opt/LABAS-Server
```

## Certificates and Virtual Environment packages

Put the certificates in `LABAS-Server/certs`
```bash
mkdir certs
scp -i ~/.ssh/labas-migz /home/shiro/projects/labas/server/certs/config.toml migz@165.245.190.93:/opt/LABAS-Server/certs
scp -i ~/.ssh/labas-migz /home/shiro/projects/labas/server/certs/keystore.p12 migz@165.245.190.93:
/opt/LABAS-Server/certs
scp -i ~/.ssh/labas-migz /home/shiro/projects/labas/server/certs/keystore-signed.p12 migz@165.245.
190.93:/opt/LABAS-Server/certs
scp -i ~/.ssh/labas-migz /home/shiro/projects/labas/server/certs/pdec_ida_partner.pem migz@165.245
.190.93:/opt/LABAS-Server/certs
```

Make that `certs/config.toml` and `kyc_auth.py` use the correct certification paths. 

Install the required python packages into a virtual environment
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## FastAPI and Uvicorn as a Service

`uvicorn` is a package that serves the FastAPI application. But, this process dies once we close our SSH Terminal. \
So, we want to keep this as a service, and run it upon boot.

Create the service's configuration file via `sudo nano /etc/systemd/system/fastapi.service`
```bash
[Unit]
Description=FastAPI Server
After=network.target

[Service]
User=fastapi
Group=labas
WorkingDirectory=/opt/LABAS-Server
ExecStart=/opt/LABAS-Server/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Then enable and start it:
```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable-fastapi
sudo systemctl start fastapi
sudo systemctl status fastapi
```

Some useful commands:
- `sudo systemctl stop fastapi` - stop the service
- `sudo systemctl restart fastapi` - for code changes
- `sudo systemctl daemon-reload` - for `fastapi.service` edits
- `journalctl -u fastapi -f` - check logs
- `sudo systemctl disable fastapi` - to disable start on boot 

## Wireguard Setup

Install wireguard:
```bash
sudo apt install wireguard -y
```

We will call the interface for MOSIP tunneling `wg0`. So, we will paste the contents of the given wireguard configuration file via `sudo nano /etc/wireguard/wg0.conf`. 

Then have strict permissions:
```bash
sudo chmod 600 /etc/wireguard/wg0.conf
``` 

Some usefule commands:
- `sudo wg-quick up wg0` - start VPN
- `sudo wg` - status check
- `ip a` - shows all network interfaces
- `sudo wg-quick down wg0` - turn off VPN