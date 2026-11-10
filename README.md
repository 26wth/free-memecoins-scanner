# Free news-to-memecoin alerts

This project sends alerts only. It never connects a wallet, buys, or sells. It uses free RSS feeds, simple Python rules, DEX Screener, GoPlus, Telegram, and GitHub Actions. It does **not** use your ChatGPT Plus subscription or any paid AI or X API. The ranking is a basic word-based heuristic, not an AI model, and it cannot understand or verify stories like a person.

## Before you start

You need a free GitHub account and the Telegram bot you created with BotFather. Do not put your bot token into a file you upload, a message, an issue, or a screenshot. GitHub repository **Secrets** are the place to enter it. Create a **public** repository: the supplied workflows deliberately skip private repositories. They use a standard GitHub-hosted Linux runner, which GitHub currently provides free for public repositories. Do not enable larger runners or paid features. No card or upgrade is needed for this project.

## 1. Prepare your Telegram chat ID

On your Mac, open Terminal, go to this project folder, and run `python3 setup_telegram.py`. Paste your bot token when prompted (it will not show on screen), then press Return. Open the bot link printed in Terminal and send the exact setup code shown there. Then return to Terminal and press Return. The helper finds your private chat, saves the settings locally in a private .env file, and sends a test message. It also prints your chat ID for GitHub. If it cannot find your message, rerun the setup and send the new code shown in Terminal. Use your own private chat's ID. If Python is not installed, install Python from [python.org](https://www.python.org/downloads/) first.

## 2. Make a public GitHub repository

1. Sign in at [GitHub](https://github.com/) and create a new repository. Choose **Public**. Do not add a payment method or select a paid feature.
2. Upload the project files except the local .env file, preserving folders, especially `.github/workflows/` and `state/`. Hidden folders may be hard to select in Finder; use a Git client or upload the files through GitHub's file editor, preserving the paths. The workflow files must be on the default branch.
3. In the repository, open **Settings → Secrets and variables → Actions → New repository secret**. Add `TELEGRAM_BOT_TOKEN` with your bot token, then add `TELEGRAM_CHAT_ID` with the chat ID. Never commit these values. Restrict repository write access: anyone allowed to modify workflows may be able to use secrets.
4. Under **Settings → Actions → General → Workflow permissions**, allow **Read and write permissions** and save. The scanner needs this to save its public deduplication state. Branch protection or restricted Actions policies can block this.

## 3. Send the Telegram test first

On GitHub, open your repository's **Actions** tab, choose **Telegram test**, then **Run workflow**. Wait for the run to finish and check Telegram for the test message. If it fails, open the run to see the error, then check your secrets and that you sent a message to the correct bot. Do not share your token or a screenshot containing it. The scanner has passed isolated unit tests; the Telegram test has not yet been sent. The first real test requires your secrets.

## 4. Start scanning

After the Telegram test succeeds, go to **Settings → Secrets and variables → Actions → Variables**, add a repository variable named `SCANNER_ENABLED` with the value `true`. The **News scanner** workflow is then scheduled for every five minutes. You can also open it in Actions and choose **Run workflow**. It reads feeds for recent headlines, ranks stories using free rules, searches Solana pools and sends a message for a close word match. It continues trying an accepted headline until one hour after its publication, subject to scheduled runs and processing limits. The state file is saved back to your public repository to reduce repeats; the news titles, links, token addresses and event history in that file and Git history are public. Never put personal data or credentials in that file.

## What the alerts mean

- Strict matching requires **two distinctive headline words** in the coin name or symbol, plus minimum liquidity and volume. This reduces noise but can miss most genuine meme coins, nicknames and different spellings. A match is not proof of a connection. News and token names can be false or copied.
- Pool age is not necessarily token age. Market cap, liquidity and 24-hour volume can be missing, stale or manipulated. Missing market cap is shown as unknown. GoPlus checks only a few risk flags; missing checks are unknown and no result proves safety or sellability.
- The scanner uses selected English-language feeds and keyword rules. It can discover subjects beyond the examples but cannot monitor all breaking news or X. Search results and indexed pools can be incomplete. At most 12 active stories are searched per run; old or crowded stories may be missed. Thresholds and feed lists are in `scanner.py`.
- GitHub's scheduled runs may be delayed or dropped, and may be disabled after 60 days of repository inactivity. They run only from the default branch. Free service limits, network errors, failed pushes, manual edits, overlapping runs, or a shutdown after an alert but before state is saved can cause missed or duplicate alerts. Check Actions regularly. This is not guaranteed continuous monitoring.

Sources: [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [GitHub schedule limits](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [DEX Screener API](https://docs.dexscreener.com/api/reference), [GoPlus limits](https://docs.gopluslabs.io/reference/support), [Telegram Bot API](https://core.telegram.org/bots/api).
