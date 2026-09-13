# Change Monitor Agent

A minimal AI-powered webpage change monitor:

**URL → fetch text → compare → OpenAI relevance check → Telegram alert**

## Stack

- Python
- GitHub Actions
- OpenAI Responses API
- Telegram Bot API

No server or database is required for the MVP.

## 1. Required GitHub secrets

Repository → Settings → Secrets and variables → Actions → Secrets:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## 2. Optional GitHub variables

Repository → Settings → Secrets and variables → Actions → Variables:

- `OPENAI_MODEL` = `gpt-5.6-luna`
- `TEST_NOTIFICATION` = `1` for the first Telegram connectivity test

After the test succeeds, change:

`TEST_NOTIFICATION = 0`

## 3. Configure targets

Edit `targets.json`.

Example:

```json
{
  "targets": [
    {
      "name": "Company Careers",
      "url": "https://example.com/careers",
      "enabled": true,
      "min_score": 6,
      "keywords": ["IT Support", "Linux", "VMware"],
      "context": "Notify only about relevant job opportunities."
    }
  ]
}
```

## 4. First run

GitHub → Actions → Change Monitor → Run workflow.

The first normal run creates a baseline snapshot.

Later runs compare the page to that baseline.

## 5. Schedule

The included workflow runs every 6 hours at minute 17.

GitHub Actions cron uses UTC.

## Notes

Some websites block ordinary HTTP fetches or render important content only with JavaScript. Those sites will need a browser-based adapter later (for example Playwright). The MVP intentionally avoids that complexity.
