# LoVi – Log Viewer for Docker Stacks

![Status](https://img.shields.io/badge/status-beta-orange) ![License](https://img.shields.io/badge/license-MIT-blue)

> ⚠️ **Early Access** – LoVi is functional but still in active development. Expect rough edges. Feedback and contributions are very welcome!

> **LoVi** (Log Viewer) is a lightweight, self-hosted web application that centralizes and parses log files from containerized applications – for **any Docker container that writes logs**.

---

## 🎯 What is LoVi?

If you run multiple Docker containers – whether it's a media stack, home automation, reverse proxies or custom apps – you know the pain: log files are scattered across containers, formats differ, and finding a relevant warning or error is like searching for a needle in a haystack.

**LoVi solves that.** It aggregates log files from all your containers into one clean web interface, color-codes them by log level (ERROR, WARNING, INFO, DEBUG), and lets you filter, search and navigate with ease.

LoVi works with **any application that writes log files** – not just media tools. Thanks to its flexible profile system, you can teach it to parse virtually any log format.

---

## ✨ Features

- **📋 Centralized Log Dashboard** – All container logs in one place, live-reloadable
- **🎨 Color-coded Log Levels** – ERROR, WARNING, INFO, DEBUG instantly recognizable
- **🔍 Search & Filter** – Find specific events across all logs in seconds
- **📦 Profile System** – Parser profiles per application define how logs are interpreted
- **🌐 GitHub Profile Integration** – Download community-maintained profiles with one click
- **🤖 Auto-Detect** – LoVi automatically suggests the best matching profile for each log file
- **⚡ Auto-Assign** – Profiles get assigned automatically based on file name hints
- **🗂️ Recursive Log Scan** – Detects log files in subdirectories (e.g. `/logs/radarr/radarr.txt`)
- **👤 User Management** – Login system with admin and regular user roles
- **🌍 Multi-Language** – German & English UI
- **📊 Status Bar** – Storage usage and system health at a glance
- **🐳 Docker-native** – Runs as a container, no installation hassle

---

## 🏗️ Supported Applications (Builtin Profiles)

LoVi ships with ready-to-use parsing profiles for:

> 🧪 All profiles are untested – use with caution and feel free to report issues!

| Application | Category |
|---|---|
| 🧪 Radarr | Movies |
| 🧪 Sonarr | TV Series |
| 🧪 Lidarr | Music |
| 🧪 Readarr | Books |
| 🧪 Prowlarr | Indexer Manager |
| 🧪 Whisparr | Adult Content |
| 🧪 SABnzbd | Usenet Downloader |
| 🧪 Jellyfin | Media Server |
| 🧪 Nginx | Web Server / Reverse Proxy |
| 🧪 Traefik | Reverse Proxy |
| 🧪 Home Assistant | Home Automation |
| 🧪 Syslog | System Logs |
| 🧪 Python | Python App Standard Logging |

Additional community profiles are available via **GitHub integration**.

---

## 🚀 Quick Start

### 1. LoVi docker-compose

```yaml
services:
  lovi:
    image: lovi:latest
    container_name: lovi
    volumes:
      - /opt/docker/logs:/logs
    ports:
      - "8095:5000"
    restart: unless-stopped
```

### 2. Extend your existing app containers

Add a log volume to each container you want to monitor. Example for **Radarr**:

```yaml
services:
  radarr:
    volumes:
      - /opt/docker/config/radarr:/config          # already exists
      - /opt/docker/logs/radarr:/config/logs        # ADD THIS for LoVi
```

> Repeat this for each application (Sonarr, SABnzbd, Prowlarr, etc.)

### 3. Recreate containers

```bash
docker-compose up -d radarr sonarr prowlarr sabnzbd
docker-compose up -d lovi
```

### 4. Open LoVi

Visit `http://YOUR-SERVER-IP:8095` and follow the **Quick Start** guide in Settings.

---

## ⚙️ Settings Workflow

LoVi guides you step by step:

1. **Quick Start** – Overview & getting started
2. **GitHub** – Browse & install community profiles
3. **Profiles** – Manage your local profiles
4. **Assign** – Manually assign profiles to log files
5. **Auto-Detect** – Let LoVi suggest profiles automatically
6. **New Profile** – Create a custom profile for any application
7. **Log Files** – Manage which logs appear on the dashboard

---

## 🌐 Community Profiles

LoVi connects to **[zockerlusche/lovi-profiles](https://github.com/zockerlusche/lovi-profiles)** on GitHub.

Each profile contains:
- Log level keyword definitions (ERROR, WARN, INFO, DEBUG)
- Log path hints for auto-assignment
- Step-by-step setup instructions with docker-compose snippets
- Version compatibility notes

**Want to contribute?** Submit your own profile via Pull Request!

---

## 🛠️ Tech Stack

- **Backend:** Python / Flask
- **Database:** SQLite
- **Frontend:** HTML / CSS / JavaScript
- **Deployment:** Docker

---

## 📁 Log Directory Structure

LoVi scans `/logs` recursively, so this structure works out of the box:

```
/opt/docker/logs/
├── radarr/
│   └── radarr.txt
├── sonarr/
│   └── sonarr.txt
├── sabnzbd/
│   └── sabnzbd.log
├── prowlarr/
│   └── prowlarr.txt
└── qnap-backup.log
```

---

## 📸 Screenshots

*Coming soon*

---

## 📄 License

MIT License – use it, fork it, improve it.

---

## 🤝 Contributing

Pull requests are welcome! If you've built a profile for an application not yet supported, please share it via [lovi-profiles](https://github.com/zockerlusche/lovi-profiles).
