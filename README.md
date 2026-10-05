# 🩸 BloodBridge

**A community-powered blood emergency network.**

BloodBridge is a Flask-based MVP for connecting verified emergency blood requests with eligible donors. It includes:

- Donor registration and dashboard
- Blood-group profile
- Community credit points for verified donation records
- Emergency blood requests
- Hospital/admin verification workflow
- Need-based priority levels: Critical, Urgent, Required
- Basic blood-group compatibility matching
- Community emergency support cases
- Admin dashboard
- Render deployment configuration

## Important safety note

This is a **prototype/MVP**, not a clinical blood-bank system. It must not be used to independently determine clinical priority, blood compatibility, donor eligibility, or transfusion decisions. In a real deployment, licensed blood banks/hospitals and qualified medical professionals must verify requests, donors, compatibility, testing, storage, transportation and allocation according to applicable laws and standards.

## Demo admin

- Email: `admin@bloodbridge.local`
- Password: `admin123`

Change/remove the demo credentials before public production use.

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000

## GitHub

```powershell
git init
git add .
git commit -m "Initial BloodBridge MVP"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/BloodBridge.git
git push -u origin main
```

## Render

Create a Render Web Service from the GitHub repo.

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Python: 3.13
- Add a strong `SECRET_KEY` environment variable.

For a production system, move from SQLite on an ephemeral filesystem to a managed PostgreSQL database and use proper authentication/password hashing, HTTPS-only secure cookies, audit logs, encrypted medical-document storage, role-based permissions, rate limiting and hospital/blood-bank integrations.
