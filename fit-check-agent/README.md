# fit-check-agent

Native Messaging host for the Chrome Fit Check extension. Chrome starts this host as a one-shot local script, passes it product-page JSON, and the host:

1. Loads the selected local profile bundle (text + images).
2. Filters the extracted product-image URLs down to "originals" (no transform params).
3. Downloads those product images locally.
4. Cleans the noisy product text context via OpenRouter (with a deterministic fallback).
5. Builds the fit-check prompt and drives ChatGPT web to upload profile + product images and paste/submit the prompt.

No local REST server runs and no port is opened.

## Requirements

- macOS. ChatGPT web handoff uses `open`, `pbcopy`, `osascript`, and `sips`.
- Chrome, or a Chromium browser that supports Native Messaging.
- `uv` and Python 3.12 or newer.
- A working ChatGPT web login in the browser that opens `https://chatgpt.com/`.
- Image generation available in that ChatGPT account.
- Optional but recommended: `OPENROUTER_API_KEY` for LLM cleanup of noisy
  product text. If it is missing, the agent still sends a prompt using
  deterministic cleanup.

## Pipeline

```
extension → native host
         → load profile bundle (text + images from profiles/<name>/)
         → select_original_image_urls(structured_image_urls)    # drop /h_,w_,q_,.../ derivatives
         → fetch_product_images(...)                            # httpx, capped, into a temp dir
         → clean_product_context(...)                           # OpenRouter, retry, fallback
         → build_fit_check_prompt(...)
         → send_to_chatgpt(prompt, profile_images + product_images)
```

Downloads and any `sips`-converted clipboard copies live in `tempfile.TemporaryDirectory` contexts and are removed as soon as the run returns. See `pipeline.py` and `images.py`.

## Profile Bundles

Create one directory per profile under `profiles/`:

```text
fit-check-agent/profiles/
└── shrey/
    ├── measurements.md
    ├── preferences.txt
    ├── front.jpg
    └── side.jpg
```

The directory name is the profile name shown in the extension popup. Supported text files (`.txt`, `.md`, `.json`, `.yaml`, `.yml`) are added to the ChatGPT prompt. Supported image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.heic`) are uploaded to ChatGPT.

Recommended minimum profile:

```text
fit-check-agent/profiles/shrey/
├── measurements.md
├── front.jpg
└── side.jpg
```

Example `measurements.md`:

```markdown
# Measurements
Height: 180 cm
Chest: 100 cm
Waist: 84 cm
Hip: 98 cm
Shoulder: 46 cm
Sleeve: 63 cm

# Usual sizes
T-shirts: M
Shirts: M or L depending on shoulder width
Jeans: 32

# Fit preferences
Preferred fit: regular, not tight at chest or stomach
Avoid: very long T-shirts, oversized logos, scratchy fabric
Style preference: casual, clean, easy to pair with jeans and sneakers
```

Use measurement names that commonly appear in size charts: chest, waist, hip,
shoulder, sleeve, length, inseam, rise. The prompt compares overlapping names
from this file against the product size chart, so clearer labels produce better
size recommendations.

## Product Image Fetcher

The extension emits `structured_image_urls` — image URLs from JSON-LD, OpenGraph/Twitter meta, and (on Myntra) `window.__myx.pdpData.media.albums`. Many of those are derivative thumbnails/recommendations with embedded transforms, e.g. `…/h_1440,q_100,w_1080/…` or `…/f_webp,h_560,q_90,w_420/…`.

`select_original_image_urls` keeps only URLs whose path has no comma — those are the un-transformed originals. They get downloaded via `httpx` into a temp dir, capped by:

| Env var | Default | Meaning |
| --- | --- | --- |
| `FIT_CHECK_PRODUCT_IMAGE_MAX_COUNT` | `6` | Max URLs fetched per run. |
| `FIT_CHECK_PRODUCT_IMAGE_MAX_BYTES` | `8388608` (8 MiB) | Max per-image bytes. Larger responses are dropped. |
| `FIT_CHECK_REQUEST_TIMEOUT_SECONDS` | `20` | httpx timeout used for both cleanup and image fetches. |

The fetched files plus the profile images are passed as a single list to `send_to_chatgpt`. The model never has to dereference a URL.

## Product Context Cleanup

The extension also captures product text blocks, JSON-LD product data, metadata, size-related text, tooltip/help text, selected options, and variant/color text. The host calls OpenRouter with `anthropic/claude-haiku-4.5` (configurable) at `temperature=0` to compress this into Markdown under five fixed headings: `Product`, `Visual Details`, `Size And Fit`, `Tooltips Or Hidden Size Text`, `Missing Or Unclear`.

Image URLs are excluded from the cleaner input — the fetcher handles those separately, so cleanup stays text-only.

Retries follow exponential backoff with jitter, honoring `Retry-After` on 429/5xx, capped at `FIT_CHECK_CLEANER_MAX_ATTEMPTS` (default 5). On final failure the host falls back to a deterministic reduced dict instead of crashing. Set `FIT_CHECK_CLEAN_PRODUCT_CONTEXT=false` to skip the LLM call entirely; the deterministic fallback is then always used.

## Prompt

`prompt.py` builds the final fit-check prompt. Highlights:

- Image generation is the first instruction, not a buried section, so it actually fires.
- Hard rule: if ChatGPT cannot see the attached product images, it must emit the exact missing-image sentence and nothing else.
- Size recommendation handles three cases: a size already selected on the page, overlapping measurements (with a markdown comparison table), and the no-overlap fallback (chart + fit descriptor + tooltip notes).
- The verdict must cite at least one visual observation from the product images and one fact from the size chart / fit notes.
- Sections 1–6 always; section 7 ("Better alternative") only when verdict is `pass` or `conditional buy`.
- When zero product images were fetched, `build_fit_check_prompt` short-circuits to a one-line prompt instructing ChatGPT to emit only the missing-image sentence.

## Setup

```bash
cd ~/Projects/agent_playground
uv sync
cd fit-check-agent
cp .env.example .env
# optional: edit .env, or use ../.env, to set OPENROUTER_API_KEY and OPENROUTER_MODEL
```

The cleaner uses only `OPENROUTER_MODEL`; there is no separate cleaner model
setting.

Load `fit-check-extension/` in Chrome:

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click **Load unpacked** and select `fit-check-extension/`.
4. Copy the extension ID.

Install the native host manifest:

```bash
cd ~/Projects/agent_playground/fit-check-agent
./install-native-host.sh <chrome-extension-id>
```

For Chrome-compatible browsers with a different Native Messaging directory, set `CHROME_NATIVE_HOST_DIR` before running the installer.

Common macOS Native Messaging directories:

```bash
# Google Chrome default used by install-native-host.sh
$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts

# Brave example
CHROME_NATIVE_HOST_DIR="$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts" ./install-native-host.sh <extension-id>

# Microsoft Edge example
CHROME_NATIVE_HOST_DIR="$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts" ./install-native-host.sh <extension-id>
```

If Chrome gives the unpacked extension a new ID, rerun
`./install-native-host.sh <new-extension-id>`.

## Usage

1. Make sure you are logged into ChatGPT in your default browser.
2. Open a product page (Myntra is the best-supported PDP today; generic JSON-LD product pages also work).
3. Click the Fit Check extension.
4. Select a profile.
5. Click **Analyze Outfit**.

The browser must stay focused while ChatGPT opens and the host pastes/uploads the images and prompt. On first use, macOS may ask for Accessibility permission for whichever app it names, commonly Terminal, iTerm, Chrome, or the launcher.

The extension status line after a run reads, e.g.:

```
Sent 2 profile images and 6 product images (7 original / 48 candidate URLs). Context cleaned by LLM.
```

`original` = URLs that passed the transform-free filter, `candidate` = URLs the extension extracted in total.

## Tests

```bash
cd ~/Projects/agent_playground/fit-check-agent
uv run python -m unittest discover tests
```

Covers: profile loading, deterministic cleanup, prompt invariants, URL transform filter (with the real Myntra URL set as a fixture), and image fetch behavior (mocked transport, MIME filtering, size cap).

## Manual Checks

```bash
uv run fit-check list-profiles
uv run python -m shared.chatgpt_web --no-submit "hello from shared chatgpt utility"
```

The first command should print your profile directory names. The second command
should open ChatGPT and paste text without submitting it.

## Troubleshooting

**Native host unavailable**

- Rerun `./install-native-host.sh <extension-id>` using the exact ID shown on
  `chrome://extensions`.
- If using Brave, Edge, Arc, or another Chromium browser, set
  `CHROME_NATIVE_HOST_DIR` to that browser's Native Messaging host directory.
- Confirm `uv` is available from a non-interactive shell:
  `command -v uv`.

**No profiles found**

- Create at least one directory under `fit-check-agent/profiles/`.
- Put at least one supported image file in that directory.
- Run `uv run fit-check list-profiles` from `fit-check-agent/` to confirm the
  host can see it.

**0 product images**

- Myntra PDPs are best supported because the extension reads
  `window.__myx.pdpData.media.albums`.
- The image fetcher keeps original product URLs without sizing/transform path
  segments. If a site only exposes transformed thumbnails, the prompt will use
  the missing-image hard stop.
- Increase `FIT_CHECK_PRODUCT_IMAGE_MAX_COUNT` only if the page has more useful
  original images than the default.

**ChatGPT opens but does not paste or submit**

- Keep the ChatGPT browser window focused until the run finishes.
- Grant macOS Accessibility permission to whichever app macOS names during the
  prompt, commonly Terminal, iTerm, Chrome, or the launcher.
- Increase `CHATGPT_WAIT_SECONDS`, `CHATGPT_IMAGE_SETTLE_SECONDS`,
  `CHATGPT_FINAL_SETTLE_SECONDS`, or `CHATGPT_SUBMIT_ATTEMPTS` in
  `fit-check-agent/.env` if ChatGPT is slow to load or process images.

**Context used fallback cleanup**

- This is not fatal; the prompt was still built from deterministic cleanup.
- Set `OPENROUTER_API_KEY` in the root `.env` or `fit-check-agent/.env` to use
  LLM cleanup.
- Keep `OPENROUTER_MODEL` in env if you want to change the model. The agent does
  not use a separate cleaner-model setting.
