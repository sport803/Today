# Sports 803 Autopost

A Python 3.11+ GitHub Actions workflow that reads the Sports 803 Blogger RSS feed, posts new or updated entries to Facebook and X through Buffer, and regenerates a static **Today's Events** page at [sport803.github.io/Today](https://sport803.github.io/Today/).

The source publishes a usable RSS feed at `https://www.sport803.online/feeds/posts/default?alt=rss`. No JavaScript browser automation is necessary. Feed item titles, article links, and publication/update dates are parsed directly from RSS.

## How it works

- Runs every 15 minutes and can also be launched manually.
- Rebuilds `docs/index.html` from up to 100 current feed entries.
- Queues each new or updated feed item once per configured channel. On the first live run, it posts only the newest feed item and seeds older entries as already handled, avoiding a historical posting backlog. Delivery state is stored in `.autopost-state.json`; successful per-channel sends are persisted immediately so a partial failure does not unnecessarily duplicate the already-sent channel.
- Limits each run to 1 new event by default (`MAX_POSTS_PER_RUN`) and processes older pending entries first. This means at most 2 Buffer calls per scheduled run, or 192 calls in a day of 15-minute runs, below Buffer’s stated 250-call Free-plan daily limit.
- Facebook text is `title` + newline + the original article URL, preserving the URL that generates the link preview.
- X text is `title` + newline + `https://sport803.github.io/Today/`.
- Buffer requests use bounded exponential backoff and honor retry/rate-limit headers when present.
- Manual runs default to dry-run. Scheduled runs publish normally.

## Setup

1. Fork `sport803/Today` (or use this repository) and ensure the default branch is `main`.
2. In **Settings → Secrets and variables → Actions**, add these repository secrets:
   - `BUFFER_API_KEY` — API key from your Buffer developer settings.
   - `BUFFER_FACEBOOK_CHANNEL_ID` — Buffer channel ID for your Facebook profile/page.
   - `BUFFER_TWITTER_CHANNEL_ID` — Buffer channel ID for your X account. Buffer's API calls this service `twitter`.
3. Find channel IDs with the [Buffer API Explorer](https://developers.buffer.com/): first query `account { organizations { id name } }`, then use the resulting organization ID in:

   ```graphql
   query GetChannels {
     channels(input: { organizationId: "YOUR_ORGANIZATION_ID" }) {
       id
       name
       service
     }
   }
   ```

   Copy the `id` for each appropriate channel into the corresponding GitHub secret. Keep the API key private; never put it in the repository.
4. In **Settings → Pages**, select **GitHub Actions** as the build/deployment source. The workflow uploads the generated `docs/` directory using the official Pages deployment actions.
5. Open **Actions → Sports 803 autopost → Run workflow**. The manual run defaults to `dry_run=true`, so its logs show what would post without contacting Buffer. Uncheck dry-run to publish. Scheduled executions always use real posting and require all three secrets.
6. To check a particular article's Facebook preview tags, run locally:

   ```bash
   python -m pip install -r scripts/requirements.txt
   python scripts/check_open_graph.py 'https://www.sport803.online/2026/10/argentina-vs-benin-intl-friendlies-live.html'
   ```

   The checker validates `og:title`, `og:description`, `og:image`, and `og:url`. Facebook may cache preview data; use [Meta Sharing Debugger](https://developers.facebook.com/tools/debug/) to refresh that cache if needed.

## Local development

```bash
python -m pip install -r scripts/requirements.txt
python -m unittest discover -s tests -v
python scripts/autopost.py --dry-run
```

`--dry-run` (or `DRY_RUN=true`) refreshes the local `docs/index.html` and logs planned social messages without calling Buffer or changing delivery state. To publish locally, set the three Buffer environment variables securely in your shell. Never commit local credentials.

Set `MAX_POSTS_PER_RUN` to adjust the per-run backlog cap. `GITHUB_PAGES_URL` overrides the X destination if the Pages URL changes.

## Notes and troubleshooting

- GitHub Actions schedule times are best-effort; scheduled runs can be delayed by 5–15 minutes during busy periods.
- A feed item updated with a new timestamp is treated as new content and posted again. Unchanged URL/timestamp pairs are deduplicated independently for Facebook and X.
- Buffer authentication errors point to `BUFFER_API_KEY`; channel errors normally mean a missing, incorrect, or disconnected channel ID.
- Feed/network failures fail the workflow rather than silently overwriting the page with an empty listing.
- The state file must be committed by the workflow to preserve deduplication between runs. If you manually reset it, the current feed entries can be queued again.
- The website's public feed can include past fixtures/highlights as well as upcoming events; the published index mirrors current feed entries and does not independently infer match status.

## Repository layout

```text
.github/workflows/autopost.yml  Scheduled/manual workflow and Pages deployment
scripts/autopost.py             RSS parsing, deduplication, Buffer GraphQL client, HTML output
scripts/check_open_graph.py     Article preview-tag verification helper
scripts/requirements.txt        Python dependencies
tests/test_autopost.py          Feed parsing and output tests
docs/index.html                 Generated GitHub Pages page
```
