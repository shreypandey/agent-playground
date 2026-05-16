# fit-check-extension

Unpacked Chrome MV3 extension for Fit Check. The popup extracts a product page (text + image URLs), hands the payload to the local Native Messaging host (`com.agent_playground.fit_check`), and reports status when ChatGPT has been driven.

## What the popup does

1. **Profile list** — calls the native host's `list_profiles` action and renders a dropdown of folders under `fit-check-agent/profiles/`.
2. **Analyze Outfit** — runs a content script (`extractProductContextFromPage`) in the active tab to collect:
   - JSON-LD product nodes
   - OpenGraph / Twitter / `product:*` metadata
   - Myntra `window.__myx.pdpData` size chart, measurements, and album images
   - DOM size-chart tables/images, product text blocks, size/variant/tooltip text, selected options
   - Two image-URL lists: `structured_image_urls` (from JSON-LD / meta / Myntra album — no DOM dimensions) and `image_candidates` (DOM `<img>` scan with dimensions)
3. **Send to native host** — posts the payload as the `fit_check` action. The agent filters URLs, downloads the originals, cleans the text, builds the prompt, and drives ChatGPT.
4. **Status line** — shows e.g. `Sent 2 profile images and 6 product images (7 original / 48 candidate URLs). Context cleaned by LLM.`

A round spinner on the Analyze Outfit button is active for the entire run and turns off when the run finishes (success or error). A separate progress row underneath shows the current step.

## Setup

Before loading the extension:

1. Run `uv sync` at the workspace root.
2. Create at least one profile directory under `fit-check-agent/profiles/`.
3. Add profile measurements/preferences as text and at least one profile image.
4. Make sure you are logged into ChatGPT in the browser that will open
   `https://chatgpt.com/`.

Then load the extension:

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click **Load unpacked** and select this `fit-check-extension/` directory.
4. Copy the generated extension ID.
5. Install the native host manifest so Chrome can launch the local agent:

```bash
cd ../fit-check-agent
./install-native-host.sh <chrome-extension-id>
```

For Chrome-compatible browsers with a different Native Messaging directory, set `CHROME_NATIVE_HOST_DIR` before running the installer.

If the extension ID changes after reinstalling or loading from a different path,
rerun the installer with the new ID.

## Usage

1. Make sure you are logged into ChatGPT in your default browser.
2. Open a product page (Myntra PDPs are best supported; generic JSON-LD product pages also work).
3. Click the Fit Check toolbar icon.
4. Pick a profile from the dropdown.
5. Click **Analyze Outfit** and keep the browser window focused while the agent pastes images and the prompt into ChatGPT.

On first use, macOS may ask for Accessibility permission for whichever app it names, commonly Terminal, iTerm, Chrome, or the launcher.

## Troubleshooting

- **Native host unavailable**: reinstall the native host manifest with the exact
  extension ID shown in `chrome://extensions`.
- **No profiles found**: create a directory under `fit-check-agent/profiles/`
  and add a supported image file (`.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`).
- **0 product images**: try a Myntra PDP first. The agent only sends downloaded
  original product images to ChatGPT; pages that expose only transformed
  thumbnails may hit the missing-image hard stop.
- **ChatGPT opens but nothing submits**: keep the browser focused and grant
  macOS Accessibility permission to the app macOS names. If ChatGPT is slow,
  increase the `CHATGPT_*` wait settings in `fit-check-agent/.env`.
- **Context used fallback cleanup**: the run still proceeded. Add
  `OPENROUTER_API_KEY` to the root `.env` or `fit-check-agent/.env` for LLM
  cleanup.

More setup detail lives in [`../fit-check-agent/README.md`](../fit-check-agent/README.md).

## Files

- `manifest.json` — MV3 manifest, requests `activeTab`, `scripting`, `storage`, `nativeMessaging`.
- `popup.html` / `popup.css` / `popup.js` — popup UI, content-script injector, and native-host client.

## Reloading after edits

Open `chrome://extensions`, click the reload icon on the Fit Check Agent card.
