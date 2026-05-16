const HOST_NAME = "com.agent_playground.fit_check";

const profileSelect = document.getElementById("profileSelect");
const refreshProfilesButton = document.getElementById("refreshProfiles");
const sendButton = document.getElementById("sendButton");
const sendButtonLabel = document.getElementById("sendButtonLabel");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const progressEl = document.getElementById("progress");
const progressTextEl = document.getElementById("progressText");

const SEND_LABEL_IDLE = "Analyze Outfit";
const SEND_LABEL_BUSY = "Working...";

function setStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = kind;
}

function setProgress(message = "") {
  if (!message) {
    progressEl.hidden = true;
    progressTextEl.textContent = "";
    return;
  }
  progressTextEl.textContent = message;
  progressEl.hidden = false;
}

function setBusy(isBusy) {
  sendButton.disabled = isBusy;
  refreshProfilesButton.disabled = isBusy;
  profileSelect.disabled = isBusy;
  sendButton.classList.toggle("is-busy", isBusy);
  sendButtonLabel.textContent = isBusy ? SEND_LABEL_BUSY : SEND_LABEL_IDLE;
  if (!isBusy) {
    setProgress("");
  }
}

function sendNativeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      if (!response) {
        reject(new Error("Native host returned no response."));
        return;
      }
      resolve(response);
    });
  });
}

function option(value, text) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = text;
  return item;
}

async function loadProfiles() {
  setBusy(true);
  setStatus("Loading profiles...");
  setProgress("Connecting to local host...");
  summaryEl.hidden = true;

  try {
    const response = await sendNativeMessage({ action: "list_profiles" });
    if (!response.ok) {
      throw new Error(response.error || "Could not list profiles.");
    }

    profileSelect.replaceChildren();
    if (!response.profiles.length) {
      profileSelect.append(option("", "No profiles found"));
      sendButton.disabled = true;
      setProgress("");
      setStatus("Create a folder in fit-check-agent/profiles.", "error");
      return;
    }

    const { lastProfile = "" } = await chrome.storage.local.get("lastProfile");
    for (const profile of response.profiles) {
      profileSelect.append(option(profile, profile));
    }
    if (lastProfile && response.profiles.includes(lastProfile)) {
      profileSelect.value = lastProfile;
    }
    setStatus(`${response.profiles.length} profile${response.profiles.length === 1 ? "" : "s"} available.`);
  } catch (error) {
    profileSelect.replaceChildren(option("", "Native host unavailable"));
    sendButton.disabled = true;
    setProgress("");
    setStatus(error.message, "error");
  } finally {
    setProgress("");
    setBusy(false);
    if (!profileSelect.value) {
      sendButton.disabled = true;
    }
  }
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    throw new Error("No active tab found.");
  }
  return tab;
}

function extractProductContextFromPage() {
  function cleanText(value) {
    return String(value || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function resolvedUrl(rawUrl) {
    if (!rawUrl || typeof rawUrl !== "string") return "";
    if (rawUrl.startsWith("data:")) return "";
    if (rawUrl.includes("($")) return "";
    try {
      const url = new URL(rawUrl, location.href);
      if (url.protocol === "http:" && url.hostname.endsWith("myntassets.com")) {
        url.protocol = "https:";
      }
      return url.href;
    } catch {
      return "";
    }
  }

  function addResolvedUrl(values, rawUrl) {
    const href = resolvedUrl(rawUrl);
    if (!href) {
      return;
    }
    values.add(href);
  }

  function flattenJsonLd(value, output = []) {
    if (!value) return output;
    if (Array.isArray(value)) {
      for (const item of value) flattenJsonLd(item, output);
      return output;
    }
    if (typeof value !== "object") return output;
    output.push(value);
    if (Array.isArray(value["@graph"])) {
      flattenJsonLd(value["@graph"], output);
    }
    return output;
  }

  function isProductNode(node) {
    const type = node && node["@type"];
    if (Array.isArray(type)) {
      return type.map(String).some((item) => item.toLowerCase() === "product");
    }
    return String(type || "").toLowerCase() === "product";
  }

  function imageValuesFrom(value, output) {
    if (!value) return;
    if (typeof value === "string") {
      addResolvedUrl(output, value);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) imageValuesFrom(item, output);
      return;
    }
    if (typeof value === "object") {
      imageValuesFrom(value.url || value.contentUrl, output);
    }
  }

  function compactObject(value) {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      if (item === undefined || item === null || item === "") continue;
      if (Array.isArray(item) && !item.length) continue;
      output[key] = item;
    }
    return output;
  }

  function readMyntraPdpData() {
    return window.__myx?.pdpData || null;
  }

  function addMyntraProductImages(imageUrls) {
    const pdp = readMyntraPdpData();
    const albums = Array.isArray(pdp?.media?.albums) ? pdp.media.albums : [];
    for (const album of albums) {
      const images = Array.isArray(album?.images) ? album.images : [];
      for (const image of images) {
        addResolvedUrl(imageUrls, image?.imageURL);
        addResolvedUrl(imageUrls, image?.secureSrc);
        addResolvedUrl(imageUrls, image?.src);
      }
    }
  }

  function readMeasurementList(measurements) {
    if (!Array.isArray(measurements)) return [];
    const rows = [];
    for (const measurement of measurements) {
      rows.push(
        compactObject({
          type: cleanText(measurement?.type),
          name: cleanText(measurement?.name),
          value: cleanText(measurement?.value),
          min_value: cleanText(measurement?.minValue),
          max_value: cleanText(measurement?.maxValue),
          unit: cleanText(measurement?.unit),
          display_text: cleanText(measurement?.displayText),
        }),
      );
    }
    return rows.filter((row) => Object.keys(row).length);
  }

  function readAllSizesList(allSizesList) {
    if (!Array.isArray(allSizesList)) return [];
    const rows = [];
    for (const entry of allSizesList) {
      rows.push(
        compactObject({
          scale_code: cleanText(entry?.scaleCode),
          label: cleanText(entry?.size),
          prefix: cleanText(entry?.prefix),
          value: cleanText(entry?.sizeValue),
          order: Number.isFinite(Number(entry?.order)) ? Number(entry.order) : undefined,
        }),
      );
    }
    return rows.filter((row) => Object.keys(row).length);
  }

  function totalAvailableCount(size) {
    const sellers = Array.isArray(size?.sizeSellerData) ? size.sizeSellerData : [];
    let total = 0;
    let hasCount = false;
    for (const seller of sellers) {
      const count = Number(seller?.availableCount);
      if (Number.isFinite(count)) {
        total += count;
        hasCount = true;
      }
    }
    return hasCount ? total : undefined;
  }

  function readMyntraSizeChart() {
    const pdp = readMyntraPdpData();
    if (!pdp) return null;

    const sizes = Array.isArray(pdp.sizes) ? pdp.sizes : [];
    const rows = [];
    for (const size of sizes) {
      const measurements = readMeasurementList(size?.measurements);
      const allSizes = readAllSizesList(size?.allSizesList);
      const row = compactObject({
        label: cleanText(size?.label || size?.size || size?.sizeValue),
        available: typeof size?.available === "boolean" ? size.available : undefined,
        available_count: totalAvailableCount(size),
        sku_id: size?.skuId,
        style_id: size?.styleId,
        size_type: cleanText(size?.sizeType),
        all_sizes: allSizes,
        measurements,
      });
      if (Object.keys(row).length) {
        rows.push(row);
      }
    }

    const chart = pdp.sizechart || {};
    const imageUrl = resolvedUrl(chart.sizeChartUrl || chart.sizeRepresentationUrl);
    const result = compactObject({
      source: "window.__myx.pdpData",
      disclaimer: cleanText(pdp.sizeChartDisclaimerText),
      image_url: imageUrl,
      rows,
    });
    return Object.keys(result).length > 1 ? result : null;
  }

  function readDomSizeChart() {
    const tables = [];
    const tableSelectors = [
      '[class*="sizeChart" i] table',
      '[class*="sizechart" i] table',
      '[class*="size-chart" i] table',
      'table[class*="sizeChart" i]',
      'table[class*="sizechart" i]',
      'table[class*="size-chart" i]',
    ];
    for (const selector of tableSelectors) {
      for (const table of document.querySelectorAll(selector)) {
        const rows = [];
        for (const tableRow of table.querySelectorAll("tr")) {
          const cells = [...tableRow.querySelectorAll("th, td")]
            .map((cell) => cleanText(cell.innerText || cell.textContent))
            .filter(Boolean);
          if (cells.length) rows.push(cells);
        }
        if (rows.length) {
          tables.push({ rows });
        }
      }
    }

    const image = document.querySelector(
      '[class*="sizeChart" i] img, [class*="sizechart" i] img, [class*="size-chart" i] img',
    );
    const imageUrl = resolvedUrl(image?.currentSrc || image?.src || "");
    const result = compactObject({
      source: "dom",
      image_url: imageUrl,
      tables,
    });
    return Object.keys(result).length > 1 ? result : null;
  }

  function readSizeChart() {
    const stateChart = readMyntraSizeChart();
    const domChart = readDomSizeChart();
    if (stateChart && domChart?.tables?.length && !stateChart.rows?.length) {
      return {
        ...stateChart,
        dom_tables: domChart.tables,
      };
    }
    return stateChart || domChart;
  }

  function readJsonLdProducts(imageUrls) {
    const products = [];
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const parsed = JSON.parse(script.textContent || "null");
        for (const node of flattenJsonLd(parsed)) {
          if (isProductNode(node)) {
            products.push(node);
            imageValuesFrom(node.image, imageUrls);
          }
        }
      } catch {
        // Ignore malformed JSON-LD.
      }
    }
    return products;
  }

  function uniqueShortTexts(values) {
    const out = [];
    const seen = new Set();
    for (const value of values) {
      const text = cleanText(value);
      if (!text || seen.has(text)) continue;
      seen.add(text);
      out.push(text);
    }
    return out;
  }

  function metadata(imageUrls) {
    const data = {};
    for (const meta of document.querySelectorAll("meta[property], meta[name]")) {
      const key = meta.getAttribute("property") || meta.getAttribute("name");
      const content = cleanText(meta.getAttribute("content"));
      if (!key || !content) continue;
      const lower = key.toLowerCase();
      if (
        lower.startsWith("og:") ||
        lower.startsWith("twitter:") ||
        lower.startsWith("product:")
      ) {
        data[key] = content;
      }
      if (["og:image", "twitter:image", "twitter:image:src"].includes(lower)) {
        addResolvedUrl(imageUrls, content);
      }
    }
    for (const link of document.querySelectorAll('link[rel~="image_src"][href]')) {
      addResolvedUrl(imageUrls, link.getAttribute("href"));
    }
    return data;
  }

  function productTextBlocks() {
    const selectors = [
      '[itemprop="description"]',
      '[class*="pdp-productDescriptors" i]',
      '[class*="pdp-description" i]',
      '[class*="pdp-title" i]',
      '[class*="pdp-name" i]',
      '[class*="pdp-price" i]',
      '[class*="pdp-sizeFitDesc" i]',
      '[class*="index-sizeFitDesc" i]',
      '[class*="index-tableContainer" i]',
      '[class*="product-description" i]',
      '[class*="product-details" i]',
      '[class*="product-info" i]',
      '[class*="product-spec" i]',
      '[id*="product-description" i]',
      '[id*="product-details" i]',
      '[id*="product-spec" i]',
    ];
    const seen = new Set();
    const blocks = [];
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        const text = cleanText(element.innerText || element.textContent);
        if (text.length < 15 || seen.has(text)) continue;
        seen.add(text);
        blocks.push(text);
      }
    }
    return blocks;
  }

  function descriptionText(blocks) {
    if (blocks.length) {
      return blocks.join("\n\n");
    }

    const bodyLines = cleanText(document.body?.innerText || "")
      .split(/(?<=[.!?])\s+|\n+/)
      .map(cleanText)
      .filter((line) => {
        if (line.length < 25) return false;
        return /brand|product|size|fit|fabric|cotton|material|sleeve|neck|pattern|colour|color|shirt|t-shirt|tshirt|price|mrp|discount/i.test(line);
      });
    return uniqueShortTexts(bodyLines).join("\n");
  }

  function selectedText() {
    const values = [];
    for (const select of document.querySelectorAll("select")) {
      const selected = select.options[select.selectedIndex];
      if (selected) values.push(cleanText(`${select.name || select.id || "select"}: ${selected.text}`));
    }
    for (const input of document.querySelectorAll('input[type="radio"]:checked, input[type="checkbox"]:checked')) {
      const label = input.closest("label") || document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      values.push(cleanText(label?.innerText || input.value || input.name));
    }
    for (const element of document.querySelectorAll('[aria-pressed="true"], [aria-selected="true"], .selected')) {
      const text = cleanText(element.innerText || element.textContent);
      if (text && text.length <= 120) values.push(text);
    }
    return [...new Set(values.filter(Boolean))].join("\n");
  }

  function sizeTexts() {
    const values = [];
    const selectors = [
      '[class*="size" i]',
      '[id*="size" i]',
      '[data-testid*="size" i]',
      '[aria-label*="size" i]',
      '[title*="size" i]',
    ];

    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        const text = cleanText(element.innerText || element.textContent);
        if (text) values.push(text);
        for (const attr of ["aria-label", "title", "data-size", "data-testid", "data-id"]) {
          const attrValue = element.getAttribute?.(attr);
          if (attrValue) values.push(attrValue);
        }
      }
    }

    for (const button of document.querySelectorAll("button, [role='button'], li, span")) {
      const text = cleanText(button.innerText || button.textContent);
      if (!text) continue;
      const attrs = `${button.className || ""} ${button.id || ""} ${button.getAttribute?.("aria-label") || ""}`.toLowerCase();
      const parentAttrs = `${button.parentElement?.className || ""} ${button.parentElement?.id || ""}`.toLowerCase();
      if (/size|fit/.test(`${attrs} ${parentAttrs}`)) values.push(text);
    }

    return uniqueShortTexts(values);
  }

  function tooltipTexts() {
    const values = [];
    const tooltipAttrs = [
      "title",
      "aria-label",
      "data-tooltip",
      "data-tip",
      "data-tooltip-content",
      "data-content",
      "data-original-title",
    ];

    for (const element of document.querySelectorAll("*")) {
      for (const attr of tooltipAttrs) {
        const attrValue = element.getAttribute?.(attr);
        if (attrValue) values.push(attrValue);
      }
    }

    for (const element of document.querySelectorAll('[role="tooltip"], [class*="tooltip" i], [class*="toolTip" i], [class*="tip" i]')) {
      const text = cleanText(element.innerText || element.textContent);
      if (text) values.push(text);
    }

    return uniqueShortTexts(values);
  }

  function variantTexts() {
    const values = [];
    const selectors = [
      '[class*="color" i]',
      '[class*="colour" i]',
      '[class*="swatch" i]',
      '[class*="variant" i]',
      '[aria-label*="color" i]',
      '[aria-label*="colour" i]',
    ];

    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        const text = cleanText(element.innerText || element.textContent);
        if (text) values.push(text);
        for (const attr of ["aria-label", "title", "data-color", "data-colour", "data-testid"]) {
          const attrValue = element.getAttribute?.(attr);
          if (attrValue) values.push(attrValue);
        }
      }
    }

    return uniqueShortTexts(values);
  }

  function imageCandidates(imageUrls) {
    const scored = new Map();
    for (const img of document.images) {
      const src = img.currentSrc || img.src;
      if (!src) continue;
      let href;
      try {
        href = new URL(src, location.href).href;
      } catch {
        continue;
      }
      if (href.startsWith("data:")) continue;
      const width = img.naturalWidth || img.width || 0;
      const height = img.naturalHeight || img.height || 0;
      if (width < 80 || height < 80) continue;
      const attrs = `${img.alt || ""} ${img.className || ""} ${img.id || ""}`.toLowerCase();
      let score = width * height;
      if (/product|main|hero|gallery|image|pdp/.test(attrs)) score += 2_000_000;
      scored.set(href, Math.max(scored.get(href) || 0, score));
    }

    for (const [href] of [...scored.entries()].sort((a, b) => b[1] - a[1])) {
      imageUrls.add(href);
    }
    return [...imageUrls];
  }

  const imageUrls = new Set();
  const structuredProduct = readJsonLdProducts(imageUrls);
  addMyntraProductImages(imageUrls);
  const meta = metadata(imageUrls);
  const structuredImageUrls = [...imageUrls];
  const blocks = productTextBlocks();
  const sizeChart = readSizeChart();

  return {
    url: location.href,
    title: cleanText(document.title),
    captured_at: new Date().toISOString(),
    description_text: descriptionText(blocks),
    product_text_blocks: blocks,
    structured_product: structuredProduct,
    metadata: meta,
    selected_text: selectedText(),
    size_texts: sizeTexts(),
    size_chart: sizeChart,
    tooltip_texts: tooltipTexts(),
    variant_texts: variantTexts(),
    structured_image_urls: structuredImageUrls,
    image_candidates: imageCandidates(imageUrls),
  };
}

async function executeProductExtractor(tabId) {
  try {
    return await chrome.scripting.executeScript({
      target: { tabId },
      func: extractProductContextFromPage,
      world: "MAIN",
    });
  } catch (error) {
    return chrome.scripting.executeScript({
      target: { tabId },
      func: extractProductContextFromPage,
    });
  }
}

function renderSummary(product) {
  const title = product.title || "Untitled page";
  const imageCount = product.image_candidates?.length || 0;
  const sizeCount = product.size_texts?.length || 0;
  const sizeChartRows = product.size_chart?.rows?.length || 0;
  const sizeChartTables = product.size_chart?.tables?.length || product.size_chart?.dom_tables?.length || 0;
  const tooltipCount = product.tooltip_texts?.length || 0;
  const textLength = product.description_text?.length || 0;
  const chartSummary = sizeChartRows
    ? `${sizeChartRows} size-chart row${sizeChartRows === 1 ? "" : "s"}`
    : `${sizeChartTables} size-chart table${sizeChartTables === 1 ? "" : "s"}`;
  summaryEl.textContent = `${title}\n${imageCount} image candidate${imageCount === 1 ? "" : "s"} · ${sizeCount} size text${sizeCount === 1 ? "" : "s"} · ${chartSummary} · ${tooltipCount} tooltip text${tooltipCount === 1 ? "" : "s"} · ${textLength} chars`;
  summaryEl.hidden = false;
}

async function runFitCheck() {
  const profileName = profileSelect.value;
  if (!profileName) {
    setStatus("Select a profile first.", "error");
    return;
  }

  setBusy(true);
  setStatus("Extracting product page...");
  setProgress("Reading current product page...");
  try {
    const tab = await getActiveTab();
    const [injection] = await executeProductExtractor(tab.id);
    const product = injection?.result;
    if (!product) {
      throw new Error("Could not extract product context.");
    }

    renderSummary(product);
    await chrome.storage.local.set({ lastProfile: profileName });

    setStatus("Launching local fit-check host...");
    setProgress("Cleaning context and preparing ChatGPT...");
    const response = await sendNativeMessage({
      action: "fit_check",
      profile_name: profileName,
      product,
    });

    if (!response.ok) {
      throw new Error(response.error || "Fit check failed.");
    }
    setProgress("");
    const cleanupMessage = response.context_cleaned
      ? "Context cleaned by LLM."
      : `Context used fallback cleanup${response.context_cleaner_error ? `: ${response.context_cleaner_error}` : "."}`;
    const profileImages = response.profile_images || 0;
    const productFetched = response.product_images_fetched || 0;
    const productOriginals = response.product_image_urls || 0;
    const productCandidates = response.product_image_url_candidates || 0;
    setStatus(
      `Sent ${profileImages} profile image${profileImages === 1 ? "" : "s"} and ${productFetched} product image${productFetched === 1 ? "" : "s"} (${productOriginals} original / ${productCandidates} candidate URLs). ${cleanupMessage}`,
      response.context_cleaned && productFetched > 0 ? "success" : "error",
    );
  } catch (error) {
    setProgress("");
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
    if (!profileSelect.value) sendButton.disabled = true;
  }
}

refreshProfilesButton.addEventListener("click", loadProfiles);
sendButton.addEventListener("click", runFitCheck);
document.addEventListener("DOMContentLoaded", loadProfiles);
