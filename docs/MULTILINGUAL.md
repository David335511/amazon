# Multilingual AI Support

The AI assistant responds in the **user's selected language** — **English** and
**Simplified Chinese (zh-CN)** — while AI reasoning stays fully
language-independent.

## The core contract

- **AI reasoning remains language independent.** The retrieval, capability
  detection and analysis all run the same way regardless of language.
- **Prompts remain English internally.** The prompt the model sees is written in
  English (including the instruction about which language to reply in).
- **Final responses are generated in the selected language.** Only the output
  text the user sees is localized.
- **Charts, tables, recommendations, notifications, reports and emails** are
  localized too (deterministically, no LLM needed).
- **Switching language never restarts the conversation.** Future responses
  automatically use the new language — the same thread continues.

## How the answer is produced in the selected language

### LLM path (primary)
When an LLM provider is configured, `MultilingualManager.build_system_instruction`
appends an **English** instruction to the system prompt:

> Respond to the user in 简体中文. Keep every ASIN, SKU, product code, and numeric
> value exactly as-is. Do not translate codes or unit prices. Reason in English
> internally, but write the final answer only in 简体中文.

The model reasons in English but writes its final answer in the target language.
The assistant then localizes the structured labels (capability, confidence,
retrieved-context summaries) deterministically.

### Deterministic fallback (no LLM)
When no LLM is configured, `MultilingualManager.fallback_answer` builds the
answer in the selected language from localized templates, and all structured
labels are localized via the i18n translation service. Data (codes, ASINs,
numbers, unit prices) is preserved verbatim.

### Prose translation (optional)
If a response was generated in English and then needs localizing,
`MultilingualManager.translate_text` uses the LLM to translate free-form prose
(English prompt; codes/numbers kept verbatim). With no LLM it returns the text
unchanged — the deterministic path never corrupts data.

## What is and isn't translated

| Translated (user-facing) | NOT translated (stays English) |
|--------------------------|--------------------------------|
| Final answer text | Database fields |
| Capability display label | API field names |
| Confidence display label | Enum values (`capability`, `confidence`, `source`) |
| Retrieved-context source labels | Configuration |
| Chart titles, axes, series names | Code |
| Table headers + formatted cells | Logs |
| Recommendation action/detail | SQL |
| Notification title/body/severity | JSON keys |
| Report title/sections, email greeting/signature | ASINs, SKUs, codes, numbers |

The API field names, enum values and data values are always preserved — only
display text is localized. `AssistantResponse` gains `language`,
`capability_label` and `confidence_label` for the localized display text while
`capability` / `confidence` / `source` enum values stay English.

## Language resolution & switching

The assistant resolves the response language exactly like i18n:

```
?lang=/body language  >  lang cookie  >  Accept-Language  >  stored preference  >  default (en)
```

`POST /multilingual/language` changes the language and persists it to the
browser cookie, the database preference and the user profile — so **future
responses automatically use it, without restarting the conversation**.

## Language detection

`LanguageDetector` is a pure-stdlib, offline heuristic over Unicode ranges. It
counts CJK vs Latin letters and returns a detected language with confidence and
script (`cjk` / `latin` / `unknown`). It is a hint only — callers can always
override with an explicit language. Short ambiguous strings (e.g. an ASIN) are
treated as their dominant script.

## Structured content localizers (deterministic)

`MultilingualManager` provides `localize_table`, `localize_chart`,
`localize_recommendation`, `localize_notification`, `localize_report` and
`localize_email`. They:

- translate titles / headers / labels via translation keys (``t:module.key``);
- format numbers, currency and percentages with the target locale
  (`LocaleManager`);
- preserve entities (ASINs, codes) and data values verbatim.

Because they are pure functions of the translation files + locale formatters,
the same input + language always produces the same output — reproducible and
production-safe with no LLM runtime.

## API surface

| Endpoint | Purpose |
|----------|---------|
| `GET /multilingual/capabilities` | supported languages + behaviour |
| `GET /multilingual/languages` | available output languages |
| `GET /multilingual/current` | resolve the current output language |
| `POST /multilingual/language?language=zh-CN` | change language (persists) |
| `POST /multilingual/detect` | detect the language of a text |
| `POST /multilingual/translate` | translate free-form prose |
| `POST /multilingual/localize/response` | localize an assistant response |
| `POST /multilingual/localize/table` | localize a table |
| `POST /multilingual/localize/chart` | localize a chart |
| `POST /multilingual/localize/recommendation` | localize a recommendation |
| `POST /multilingual/localize/notification` | localize a notification |
| `POST /multilingual/localize/report` | localize a report |
| `POST /multilingual/localize/email` | localize an email |

The assistant itself is `POST /assistant/ask` with `?lang=zh-CN` (or the
`lang` cookie / `Accept-Language` header / body `language`).

## Quick start

```bash
# Ask in Simplified Chinese (language resolves from the query param)
curl -X POST ".../assistant/ask?lang=zh-CN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Why is B0TEST profitable?"}'

# Change the assistant's language for all future responses
curl -X POST ".../multilingual/language?language=zh-CN"

# Resolve the current language
curl ".../multilingual/current"

# Detect the language of incoming user text
curl -X POST ".../multilingual/detect" -H "Content-Type: application/json" \
  -d '{"text": "这个商品利润高吗？"}'

# Localize a table for zh-CN (headers translated, cells locale-formatted)
curl -X POST ".../multilingual/localize/table" -H "Content-Type: application/json" \
  -d '{"language":"zh-CN","title_key":"t:multilingual.labels.table",
       "columns":[{"key":"product","label":"t:multilingual.labels.product","format":"text"}],
       "rows":[{"product":"B0TEST"}]}'
```

## Adding a new language

1. Add a directory under `translations/<lang>/` with the same modules/keys
   (including `multilingual.json`) — the validator enforces parity.
2. Add the code to `MultilingualConfig.supported_languages` (and
   `I18nConfig.supported_languages`).

No application code changes are required.

## Production readiness

- Pure-stdlib detection and deterministic localization; optional LLM for prose.
- No new database tables (language persistence reuses i18n tables).
- Data (codes, ASINs, numbers, unit prices) is never altered by localization.
- `translation` module validated by the i18n validator (parity across languages).
- Works fully offline with no LLM configured (structured content still localizes).
