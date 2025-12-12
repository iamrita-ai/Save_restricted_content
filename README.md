# SERENA – Telegram Recovery & Clone Bot

SERENA ek personal Telegram bot hai jo aapke Telegram account ke user-session se:

- Private & Public **channels / groups** se files, media, messages clone/extract kar sakta hai  
- Lost / second account ke important channels se content nikal kar aapko bhej sakta hai  
- Flood wait se bachne ke liye slow & safe way me kaam karta hai

> ⚠️ Use sirf apne hi accounts / channels ke liye karein. Kisi aur ka data bina permission ke access karna Telegram TOS ke khilaaf hai.

---

## Features

- User login:
  - Session String
  - Phone + OTP (force SMS + in-app code support)
  - QR Code Login (Telegram Desktop style)
- Clone media & text:
  - Photos, Videos, Documents, Stickers, GIFs, Audio, Voice, Video Notes, Text + Links
- Any chat support:
  - Agar aapka `/login` wala account kisi channel/group me member hai, bot user-session se us chat se content clone kar sakta hai  
  - Bot ko us channel/group me add/admin hone ki zaroorat nahi
- Batch mode:
  - `/batch` + message link + count
  - Clone directly **usi chat me** (DM ya Group jahan se command diya)
- Free/Premium system:
  - Free: 50 messages per batch
  - Premium/Owner: 1000 messages per batch
- Settings:
  - Set Chat ID (optional auto-forward)
  - Replace text: “Serena” → “Kumari”
  - Remove Words: custom list (Serena,Kumari,File,...) – text/caption se remove
- Romantic UI:
  - DM me pinned header: progress X/Y, status, source link, inline button “Contact Owner”
- Logs:
  - Har task/logs ek dedicated logs channel me jaate hain

---

## Commands

### General (DM & Groups)

- `/start` – Intro & welcome
- `/help` – Help menu
- `/status` – Account & plan status
- `/plan` – History & stats
- `/batch` – Batch clone mode (public & private links)
- `/cancel` – Ongoing task cancel (login/batch etc.)

### DM-only

- `/login` – Login menu (Session / Phone+OTP / QR)
- `/logout` – Session logout
- `/settings` – Premium settings (Set Chat ID, Rename, Remove Words)
- `/addpremium user_id days` – Owner: add premium
- `/remove user_id` – Owner: remove premium
- `/clear` – Owner: clear Mongo users data

---

## Environment Variables

Render ya local `.env` me:

- `API_ID` – Telegram API ID (https://my.telegram.org)
- `API_HASH` – Telegram API Hash
- `BOT_TOKEN` – Bot token from @BotFather
- `MONGO_URI` – MongoDB connection string
- `START_IMAGE_URL` – (optional) /start pe banner image URL

---

## Deployment (Render)

1. Git repo banaye, is `main.py` ko root me rakhein.
2. `requirements.txt`:

   ```txt
   pyrogram==2.0.106
   tgcrypto
   motor
   flask
   qrcode
   Pillow
