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
