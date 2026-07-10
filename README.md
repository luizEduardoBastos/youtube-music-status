<h1 align="center">YouTube Music GitHub Profile</h1>

<p align="center">
  Displays the song you're currently listening to on YouTube Music — in real-time — on your GitHub profile.
</p>

<p align="center">
  <img src="https://firebasestorage.googleapis.com/v0/b/music-profile-aaae2.firebasestorage.app/o/listening-on-ytmusic.svg?alt=media&v=381" alt="Now Listening"/>
</p>

---

## 🙏 Based on

This is a personal fork of [iXenonN/YouTube-Music-Profile](https://github.com/iXenonN/YouTube-Music-Profile) by **iXenonN**, with the following changes:

- Credentials and sensitive values moved to a `.env` file
- All SVG update functions consolidated into a single generic `update_svg()` function
- New themes added (Theme2 and Theme3 Card)
- Unused variables and duplicate code removed
- `.gitignore` expanded to prevent accidental credential commits

---

## ✨ How it works

A Chrome extension detects when YouTube Music opens or closes and sends a `POST` request to a local Flask server. The server fetches your listening history via the YouTube Music API, generates an SVG with the song info and dominant thumbnail color, and uploads it to Firebase Storage. Your GitHub README embeds the public SVG URL, which GitHub Actions refreshes every 2 minutes to bypass cache.

---

## 🛠️ Installation

### 1. Clone and install dependencies

```bash
git clone https://github.com/luizEduardoBastos/youtube-music-profile.git
cd youtube-music-profile
pip install -r requirements.txt
```

### 2. Generate `browser.json` for YouTube Music API

- Open YouTube Music in your browser and log in
- Open DevTools (`Ctrl+Shift+I`) → Network tab → filter by `/browse`
- Right-click any matching POST request → Copy request headers
- In your terminal:

```bash
ytmusicapi browser
```

- Paste the headers, then press `Enter → Ctrl+Z → Enter`
- Move the generated `browser.json` to the project root

> **Tip:** If `ytmusicapi` is not recognized, try running from a Linux environment or add it to your system PATH:
> `C:\Users\{username}\AppData\Roaming\Python\Python312\Scripts\`

### 3. Set up Firebase

- Create a project at [firebase.google.com](https://firebase.google.com)
- Enable **Storage** in the project
- Go to **Project Settings → Service Accounts → Generate new private key**
- Save the downloaded file as `firebase-credentials.json` in the project root

### 4. Configure `.env`

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

```env
YTMUSIC_BROWSER=browser.json
FIREBASE_CREDENTIALS=firebase-credentials.json
FIREBASE_BUCKET=your-project.firebasestorage.app
BLOB_NAME=listening-on-ytmusic.svg
```

### 5. Install the Chrome extension

Install [YouTube Music Status Checker](https://chromewebstore.google.com/detail/youtube-music-status-chec/bimommhpekpddlbmaaljdkcgcfclpkfo) from the Chrome Web Store.

### 6. Add the SVG to your GitHub profile README

- Go to your Firebase Storage, click on `listening-on-ytmusic.svg` and copy the public URL
- Add to your profile's `README.md`:

```markdown
![Now Listening](your-firebase-url?v=1)
```

> The `?v=1` parameter is incremented by GitHub Actions to bypass GitHub's image cache.

### 7. Set up GitHub Actions (cache busting)

In your **profile repository** (`username/username`), create `.github/workflows/update-readme.yaml`:

```yaml
name: Update SVG Version

on:
  schedule:
    - cron: '*/2 * * * *'
  workflow_dispatch:

jobs:
  update-version:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Increment SVG version
        run: |
          current=$(grep -oP '(?<=v=)\d+' README.md)
          sed -i "s/v=$current/v=$((current + 1))/" README.md

      - name: Commit changes
        run: |
          git config user.email "your@email.com"
          git config user.name "your-username"
          git add README.md
          git commit -m "chore: bump SVG cache version"

      - name: Push
        uses: ad-m/github-push-action@v0.6.0
        with:
          github_token: ${{ secrets.YOUR_SECRET_NAME }}
          branch: main
```

Go to your profile repository **Settings → Secrets → Actions** and create a secret with your [Personal Access Token](https://github.com/settings/tokens) (scope: `repo`).

### 8. Run the server

```bash
python app.py
```

To start automatically on Windows login, create a `.bat` file and add it to Task Scheduler:

```bat
cd /d C:\path\to\youtube-music-profile
python app.py
```

---

## 🚧 Common issues

**`ModuleNotFoundError`** → Run `pip install -r requirements.txt`

**`FileNotFoundError: browser.json`** → Make sure `browser.json` is in the project root and the path in `.env` is correct

**`404 POST` from Firebase** → Check your `FIREBASE_BUCKET` value in `.env` — it should look like `your-project.firebasestorage.app`

**SVG not updating on GitHub** → Go to your profile repository → Actions → run `update-readme.yaml` manually, or try `Ctrl+F5`

---

## 💻 Built with

- Python 3.12
- JavaScript (Chrome Extension)
- Firebase Storage
- YouTube Music API — [ytmusicapi](https://github.com/sigma67/ytmusicapi) by sigma67

---

## 🛡️ License

MIT — see [LICENSE](LICENSE)