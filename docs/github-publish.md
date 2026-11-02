# Publishing SADA on GitHub

Repository name: `sada-voice-ai`  
Suggested description: `Arabic-English voice support agent using FastAPI, WebSockets, WebRTC VAD, faster-whisper and local LLMs.`

## Create the repository

1. Sign in to [GitHub's new repository page](https://github.com/new?name=sada-voice-ai).
2. Use the exact name `sada-voice-ai` under your GitHub account. Choose Public for a portfolio project.
3. Leave **Add a README**, **Add .gitignore**, and **Choose a license** blank because this project already contains a README and `.gitignore`. You can decide on a license separately.
4. Select **Create repository**.
5. Allow your connected GitHub integration to access the new repository so files can be published from ChatGPT, or push locally using the steps below.

## Push from your computer

Extract the ZIP and open a terminal in the `sada-voice-ai` folder. Set your own Git commit identity first using your normal GitHub setup, then run:

```bash
git init
git add .
git commit -m "Build bilingual voice support prototype"
git branch -M main
git remote add origin https://github.com/FaizanAKhan786/sada-voice-ai.git
git push -u origin main
```

If asked for credentials, use your GitHub authentication method (such as Git Credential Manager). Do not paste access tokens into source files or chat.

## After publishing

- Open the repo's **Actions** tab and check that CI passes.
- Add topics: `voice-ai`, `arabic-nlp`, `fastapi`, `whisper`, `ollama`, `websockets`, `speech-recognition`.
- Add a short live demo video if you run speech models successfully on your own hardware.
- Pin the repository to your GitHub profile and link it from your resume.
- Don't claim real-world voice quality, production call-center integrations or latency benchmarks until you have tested them.
