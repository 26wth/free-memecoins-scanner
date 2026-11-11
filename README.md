# Free early memecoin alerts

This project sends alerts only. It never connects a wallet, buys, or sells. It uses free RSS feeds, simple Python rules, DEX Screener, GoPlus, Telegram, and GitHub Actions. It does **not** use your ChatGPT Plus subscription or any paid AI or X API. It looks for early trading momentum and adds narrative context where available.

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

On GitHub, open your repository's **Actions** tab, choose **Telegram test**, then **Run workflow**. Wait for the run to finish and check Telegram for the test message. If it fails, open the run to see the error, then check your secrets and that you sent a message to the correct bot. Do not share your token or a screenshot containing it. A Telegram test in a new repository requires your secrets.

## 4. Start scanning

Set the Actions repository variable `SCANNER_ENABLED` to `true`. The existing Telegram secrets and **News scanner** workflow run the scanner every five minutes, subject to GitHub's scheduling delays.

The tracker combines global, per-network, and launchpad market feeds into one ranking. The global feeds run every scan, and the tracker rotates individual feeds across all 19 configured networks within the free request budget. It has dedicated feeds for Pump.fun, PumpSwap, Raydium LaunchLab, Stonkfun, Pons, and Long.xyz. Other venues can appear in indexed network feeds. There is no verified dedicated Noxafun feed. Discovery can be partial when a provider rate-limits requests or has no data.

Candidates need 15–25 minutes of observations, at least $10,000 in reported pool liquidity, a pool at most 90 minutes old, and market cap or FDV at most $500,000. The bot looks for buy counts and volume building without a late price spike or a material drop in liquidity. It skips ambiguous same-name coins, limits sends to two per run and five per rolling day, and remembers an alerted network and contract for 30 days. Pool age can differ from token age.

Each alert includes the coin, possible headline or project description, all distinct project links returned by the available metadata, contract, market cap, liquidity, volume windows, network, launchpad when identified, and chart. Project-listed links are labeled. A coin can qualify without a narrative. There is no direct X feed or signed-in Axiom or Fomo access.

GoPlus holder and required contract fields must be present. Solana also requires a fresh linked-wallet summary from the free Bubbles service, which is separate from Bubblemaps. Supported EVM networks use stricter holder concentration checks when a wallet map is unavailable. Networks missing a usable holder and risk source are discovery-only. Checks can miss risks and do not prove liquidity is locked, a project is original, or a token can be sold later. The scanner does not estimate trade outcomes.

Sources: [GeckoTerminal](https://api.geckoterminal.com/docs/index.html), [DEX Screener](https://docs.dexscreener.com/api/reference), [GoPlus](https://docs.gopluslabs.io/reference/tokensecurityusingget_1), [Bubbles](https://bubblemaps.dev/api), [X pricing](https://docs.x.com/x-api/getting-started/pricing), and [GitHub schedule limits](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
