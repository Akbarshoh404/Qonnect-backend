# ⚡ Qonnect Backend API

Enterprise-grade dynamic QR code and file proxying REST API engine built with **Flask**, **SQLAlchemy**, **Segno**, and **Google Drive API v3**.

## 🚀 Features
- **Dynamic Link Engine**: Short-code resolution and real-time 302 redirection.
- **Google Drive Proxying**: Direct file retrieval without exposing private Google Drive URLs.
- **QR Code Customization**: High-precision vector SVG and PNG rendering with Segno.
- **Bulk Engine**: Batch creation, CSV processing, and on-the-fly streaming ZIP file generation.
- **Analytics & Geolocation**: MaxMind GeoLite2 IP resolution, device detection, and scan event logging.
- **Custom Domains**: Automated verification and multi-tenant domain routing.
- **Branded Inactive / 404 Pages**: Server-side branded HTML rendering for paused QR links.

## 🛠️ Tech Stack
- **Python 3.12**
- **Flask 3.0**
- **SQLAlchemy 2.0**
- **Segno** (QR Code engine)
- **Google API Client** (Drive v3, OAuth2)
- **Cryptography** (Fernet token encryption)
- **GeoIP2 & User-Agents**
- **Flask-Limiter**

## 🏃 Local Run
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
python run.py
```

Crafted with ❤️ by [Akbarshoh](https://akbarshoh-dev.uz)
